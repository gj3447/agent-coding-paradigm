#!/usr/bin/env python3
"""Kill frozen L/R seam semantic mutants against an independent oracle.

Anchor drift, compilation/loading failure, timeout, or execution exception is
``INVALID_MUTANT`` and is never credited as a kill.  The pristine baseline is
the root ``flrh_lr_seam.project_lr`` export, and each non-empty baseline command
is also driven through the real public ``flrh_reactive.step_r`` publication
chain before any mutant receives credit.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/flrh_lr_seam/seam.py"
CANONICAL_SOURCE = ROOT / "src/flrh_lr_seam/canonical.py"
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from check_lr_seam_ambient import _build_documents
from flrh_lr_seam import project_lr
from flrh_reactive import step_r
from lr_seam_fixtures import canonical_bytes
from lr_seam_oracle import project_expected


TIMEOUT_SECONDS = 10
FORBIDDEN_OUTPUT_KEYS = frozenset(
    {"effect_intent", "effect_intents", "authority", "approval", "capability",
     "frontier", "frontiers", "demand", "backpressure", "checkpoint", "receipt"}
)
ARGUMENT_KEYS = (
    "l_result", "rule_bundle", "r_profile", "binding_profile", "query_batch"
)


@dataclass(frozen=True)
class Edit:
    anchor: str
    replacement: str


@dataclass(frozen=True)
class Mutation:
    name: str
    axis: str
    probe: str
    edits: tuple[Edit, ...]


MUTATIONS = (
    Mutation("true_false_mapping", "TRUE_FALSE_mapping", "true-positive", (Edit(
        '            satisfied = state == "TRUE_ONLY"',
        '            satisfied = state == "FALSE_ONLY"',
    ),)),
    Mutation("both_mapping", "BOTH_mapping", "both-positive", (Edit(
        '        if state == "BOTH":', '        if False and state == "BOTH":',
    ),)),
    Mutation("neither_mapping", "NEITHER_mapping", "neither-positive", (Edit(
        '        elif state == "NEITHER":\n            satisfied = False',
        '        elif state == "NEITHER":\n            satisfied = True',
    ),)),
    Mutation("polarity_omission", "polarity_mapping", "false-negative", (Edit(
        '        elif literal["polarity"] == "positive":', '        elif True:',
    ),)),
    Mutation("support_omission", "support_evidence", "true-positive", (Edit(
        '        supports.update(selected)', '        supports.update(())',
    ),)),
    Mutation("positional_precondition_join", "precondition_join", "mixed-multi", (Edit(
        '        fact = facts.get(canonical_bytes(literal["atom"]))',
        '        fact = next(iter(facts.values()), None)',
    ),)),
    Mutation("skip_query_declaration", "query_declaration", "undeclared-query", (Edit(
        '            if canonical_bytes(literal["atom"]) not in query_atoms:',
        '            if False and canonical_bytes(literal["atom"]) not in query_atoms:',
    ),)),
    Mutation("skip_digest_bindings", "version_digest_binding", "binding-rejection", (
        Edit('    for key, expected in bindings:', '    for key, expected in ():'),
        Edit('    if item["query_batch_digest"] != expected_batch:',
             '    if False and item["query_batch_digest"] != expected_batch:'),
    )),
    Mutation("stale_materialization_identity", "materialization_identity", "true-positive", (Edit(
        '        "l_materialization_digest": l_result["next_materialization"]["materialization_digest"],\n'
        '        "query_batch_digest": query_batch["query_batch_digest"],',
        '        "l_materialization_digest": l_result["prior_materialization_digest"],\n'
        '        "query_batch_digest": query_batch["query_batch_digest"],',
    ),)),
    Mutation("overflow_drop", "overflow_drop", "delta-overflow", (Edit(
        '    if len(deltas) > r_profile["limits"]["max_deltas_per_command"]:\n'
        '        raise _Reject("LIMIT_EXCEEDED", "/command/deltas",\n'
        '                      {"limit": r_profile["limits"]["max_deltas_per_command"],\n'
        '                       "observed": len(deltas)})',
        '    if len(deltas) > r_profile["limits"]["max_deltas_per_command"]:\n'
        '        deltas = deltas[:r_profile["limits"]["max_deltas_per_command"]]',
    ),)),
    Mutation("output_order", "canonical_output_order", "mixed-multi", (Edit(
        '    deltas = _sorted_wires(deltas)', '    deltas = list(reversed(_sorted_wires(deltas)))',
    ),)),
    Mutation("emit_frontier_demand", "frontier_demand_exclusion", "true-positive", (Edit(
        '            "dataflow_version": binding["dataflow_version"], "deltas": deltas,',
        '            "dataflow_version": binding["dataflow_version"], "deltas": deltas,\n'
        '            "frontier": l_result["logical_time"], "demand": 1,',
    ),)),
    Mutation("inject_h_output", "H_output_exclusion", "true-positive", (Edit(
        '    result["projection_digest"] = projection_digest\n    return thaw(result)',
        '    result["projection_digest"] = projection_digest\n'
        '    result["effect_intents"] = []\n    return thaw(result)',
    ),)),
    Mutation("bypass_actual_step_r_publication", "public_step_r_chain", "true-positive", (Edit(
        '        "source_id": source_id, "logical_time": logical_time, "diff": 1,',
        '        "source_id": source_id, "logical_time": logical_time, "diff": -1,',
    ),)),
)


def _digest_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _forbidden(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in FORBIDDEN_OUTPUT_KEYS:
                return key
            found = _forbidden(item)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _forbidden(item)
            if found is not None:
                return found
    return None


def _project(document: Mapping[str, Any], projector=project_lr) -> dict[str, Any]:
    return projector(*(document[key] for key in ARGUMENT_KEYS))


def _publication(document: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any] | None:
    command = result.get("command")
    if command is None:
        return None
    profile = document["r_profile"]
    state = None
    commands = [command]
    commands.extend(
        {
            "kind": "RAdvanceFrontier", "schema_version": "flrh-r-command/1",
            "profile_digest": profile["profile_digest"],
            "dataflow_version": profile["dataflow_version"],
            "source_id": source_id, "low_watermark": result["logical_time"] + 1,
        }
        for source_id in profile["source_ids"]
    )
    commands.append(
        {
            "kind": "RGrantDemand", "schema_version": "flrh-r-command/1",
            "profile_digest": profile["profile_digest"],
            "dataflow_version": profile["dataflow_version"], "batches": 1,
        }
    )
    final = None
    for command in commands:
        transition = step_r(state, profile, command)
        if transition.get("kind") != "RTransition":
            raise AssertionError(
                f"public step_r rejected LR command chain: {transition.get('code')} {transition.get('path')}"
            )
        state = transition["next_state"]
        final = transition
    assert final is not None
    published = final["published_batches"]
    if len(published) != 1:
        raise AssertionError("public step_r did not publish exactly one LR batch")
    batch = published[0]
    if batch["effect_proposals"] != sorted(
        [query["proposal"] for query in document["query_batch"]["queries"]], key=canonical_bytes
    ):
        raise AssertionError("public step_r proposal publication differs from LR query")
    if batch["eligibility_verdicts"] != result["verdicts"]:
        raise AssertionError("public step_r verdict publication differs from LR projection")
    return batch


def _extra_documents(base: dict[str, tuple[dict[str, Any], str]]):
    from lr_seam_fixtures import (
        materialize_binding_profile, materialize_proposal, materialize_query,
        materialize_query_batch, materialize_r_profile, materialize_requirement,
    )
    first = copy.deepcopy(base["true-positive"][0])
    l_result = first["l_result"]
    bundle = first["rule_bundle"]
    r_profile = first["r_profile"]
    binding = first["binding_profile"]
    facts = {item["atom"]["subject"]: item["atom"]
             for item in l_result["next_materialization"]["fact_states"]}

    proposal = materialize_proposal("mixed-multi", ["pre:multi:false", "pre:multi:true"])
    mixed_query = materialize_query(proposal, [
        materialize_requirement("pre:multi:true", facts["true_only"]),
        materialize_requirement("pre:multi:false", facts["false_only"]),
    ])
    mixed_batch = materialize_query_batch(
        binding_profile=binding, l_result=l_result, rule_bundle=bundle,
        r_profile=r_profile, queries=[mixed_query],
    )
    base["mixed-multi"] = ({**first, "query_batch": mixed_batch}, "success")

    undeclared_atom = {"predicate": "not_declared", "subject": "outside"}
    undeclared_proposal = materialize_proposal("undeclared", ["pre:undeclared"])
    undeclared_query = materialize_query(
        undeclared_proposal,
        [materialize_requirement("pre:undeclared", undeclared_atom)],
    )
    undeclared_batch = materialize_query_batch(
        binding_profile=binding, l_result=l_result, rule_bundle=bundle,
        r_profile=r_profile, queries=[undeclared_query],
    )
    base["undeclared-query"] = ({**first, "query_batch": undeclared_batch}, "rejection")

    overflow_r = materialize_r_profile(max_deltas_per_command=2)
    overflow_binding = materialize_binding_profile()
    overflow_queries = []
    for index, subject in enumerate(("true_only", "false_only")):
        pid = f"pre:overflow:{index}"
        overflow_queries.append(materialize_query(
            materialize_proposal(f"overflow-{index}", [pid]),
            [materialize_requirement(pid, facts[subject])],
        ))
    overflow_batch = materialize_query_batch(
        binding_profile=overflow_binding, l_result=l_result, rule_bundle=bundle,
        r_profile=overflow_r, queries=overflow_queries,
    )
    base["delta-overflow"] = ({
        **first, "r_profile": overflow_r, "binding_profile": overflow_binding,
        "query_batch": overflow_batch,
    }, "rejection")


def _load_mutant(source: str):
    for name in ("flrh_lr_seam", "flrh_lr_seam.canonical", "flrh_lr_seam.seam"):
        sys.modules.pop(name, None)
    package = types.ModuleType("flrh_lr_seam")
    package.__path__ = [str(SOURCE.parent)]
    package.__package__ = "flrh_lr_seam"
    sys.modules["flrh_lr_seam"] = package
    spec = importlib.util.spec_from_file_location("flrh_lr_seam.canonical", CANONICAL_SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load canonical module")
    canonical = importlib.util.module_from_spec(spec)
    sys.modules["flrh_lr_seam.canonical"] = canonical
    spec.loader.exec_module(canonical)
    seam = types.ModuleType("flrh_lr_seam.seam")
    seam.__file__ = str(SOURCE)
    seam.__package__ = "flrh_lr_seam"
    sys.modules["flrh_lr_seam.seam"] = seam
    exec(compile(source, str(SOURCE), "exec"), seam.__dict__)
    package.project_lr = seam.project_lr
    package.__all__ = ["project_lr"]
    return package.project_lr


def _worker() -> int:
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    projector = _load_mutant(request["source"])
    result = _project(request["document"], projector)
    sys.stdout.buffer.write(canonical_bytes(result) + b"\n")
    return 0


def _mutate(pristine: str, mutation: Mutation) -> str:
    source = pristine
    for edit in mutation.edits:
        count = source.count(edit.anchor)
        if count != 1:
            raise ValueError(f"anchor count {count} for {mutation.name}")
        source = source.replace(edit.anchor, edit.replacement, 1)
    compile(source, str(SOURCE), "exec")
    return source


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--worker":
        return _worker()

    documents = {label: (document, expected)
                 for label, document, expected in _build_documents()}
    _extra_documents(documents)
    baselines: dict[str, dict[str, Any]] = {}
    oracle_comparisons = publication_chains = 0
    for label, (document, expected_kind) in documents.items():
        result = _project(document)
        baselines[label] = result
        if expected_kind == "success":
            expected = project_expected(*(document[key] for key in ARGUMENT_KEYS))
            if result != expected:
                raise AssertionError(f"pristine public baseline disagrees with oracle: {label}")
            oracle_comparisons += 1
            if result["command"] is not None:
                _publication(document, result)
                publication_chains += 1
        elif result.get("kind") != "LRProjectionRejection":
            raise AssertionError(f"pristine rejection probe accepted: {label}")

    pristine = SOURCE.read_text(encoding="utf-8")
    receipts = []
    killed = survived = invalid = 0
    for mutation in MUTATIONS:
        try:
            mutant_source = _mutate(pristine, mutation)
        except (ValueError, SyntaxError) as error:
            receipts.append({"name": mutation.name, "axis": mutation.axis,
                             "status": "INVALID_MUTANT", "reason": str(error)})
            invalid += 1
            continue
        document = documents[mutation.probe][0]
        request = canonical_bytes({"source": mutant_source, "document": document})
        try:
            completed = subprocess.run(
                [sys.executable, "-B", str(Path(__file__).resolve()), "--worker"],
                cwd=ROOT, input=request, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            receipts.append({"name": mutation.name, "axis": mutation.axis,
                             "status": "INVALID_MUTANT", "reason": "timeout"})
            invalid += 1
            continue
        if completed.returncode != 0:
            receipts.append({"name": mutation.name, "axis": mutation.axis,
                             "status": "INVALID_MUTANT", "reason": "worker_failure"})
            invalid += 1
            continue
        try:
            mutant_result = json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            receipts.append({"name": mutation.name, "axis": mutation.axis,
                             "status": "INVALID_MUTANT", "reason": "invalid_worker_json"})
            invalid += 1
            continue
        forbidden = _forbidden(mutant_result)
        if forbidden is not None or mutant_result != baselines[mutation.probe]:
            status, reason = "KILLED", "forbidden_output" if forbidden else "oracle_difference"
            killed += 1
        else:
            status, reason = "SURVIVED", "matched_pristine_public_baseline"
            survived += 1
        receipts.append({"name": mutation.name, "axis": mutation.axis,
                         "status": status, "reason": reason})

    report = {
        "kind": "LRSemanticMutationReport",
        "schema_version": "lr-seam-semantic-mutation-report/1",
        "source_digest": _digest_file(SOURCE),
        "oracle_digest": _digest_file(ROOT / "scripts/lr_seam_oracle.py"),
        "axis_count": len({mutation.axis for mutation in MUTATIONS}),
        "mutant_count": len(MUTATIONS), "killed": killed, "survived": survived,
        "invalid": invalid, "oracle_comparisons": oracle_comparisons,
        "public_step_r_publication_chains": publication_chains,
        "receipts": receipts,
    }
    sys.stdout.buffer.write(canonical_bytes(report) + b"\n")
    return 0 if killed == len(MUTATIONS) and not survived and not invalid else 1


if __name__ == "__main__":
    raise SystemExit(main())
