#!/usr/bin/env python3
"""Nonrecursive aggregate gate for the proposed M4C-IL integration profile."""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from flrh_kernel.canonical import canonical_bytes, canonical_digest
from m4cil_fixtures import M4CIL_CONTRACT, load_chain_inputs
from m4cil_verifier import verify_m4cil_evidence
from run_m4cil_replay import run_incremental_reference_chain


STATUS = "PROPOSED_PENDING_MEASUREMENT"
PURPOSE = (
    "Bind one live public F to two-prefix persistent incremental L to LR to R to "
    "M4A to M4B reference path, including real checkpoint reuse and crash "
    "reconciliation, without asserting outer-run completion."
)
NON_CLAIMS = (
    "outer FSM SUCCEEDED or full run completion",
    "general persistent incremental runtime",
    "filesystem or database persistence for L checkpoints",
    "reduced total runtime or performance superiority",
    "multi-event or multi-effect scheduling",
    "durable R state",
    "real destination safety or exactly-once delivery",
    "integrated production runtime",
    "engine promotion",
    "comparative efficacy or Lakatos progress",
)
CONTRACT_COMPLETION_BOUNDARY = (
    "PROPOSED only; a bounded two-prefix M2-IL checkpoint-reuse path feeds its "
    "exact M2-compatible fixpoint into the existing LR to R to H to durable "
    "crash/reconcile reference path. It ends at HONOR_PENDING_INTERRUPT with "
    "SLICE_CONFORMED and makes no performance, persistence, production, engine, "
    "efficacy, scientific-progress, or outer-completion claim."
)
MANIFEST_COMPLETION_BOUNDARY = (
    "Candidate evidence only. No outer completion, total-runtime performance, "
    "persistent L storage, real destination, production, engine, comparative "
    "efficacy, or Lakatos progress claim."
)
OWNED_CLOSURE = (
    "docs/M4CIL_INTEGRATED_INCREMENTAL_SLICE.md",
    "fixtures/m4cil/cases.json",
    "scripts/check_m4cil_sensitivity.py",
    "scripts/m4cil_fixtures.py",
    "scripts/m4cil_verifier.py",
    "scripts/run_m4cil_replay.py",
    "scripts/validate_m4cil.py",
    "spec/m4cil-integration-contract.v1.json",
    "spec/m4cil-manifest.v1.json",
    "spec/schema/m4cil-fixtures.v1.schema.json",
    "spec/schema/m4cil-integration-contract.v1.schema.json",
    "spec/schema/m4cil-manifest.v1.schema.json",
    "tests/test_m4cil_candidate_gate.py",
    "tests/test_m4cil_integration.py",
)
LOCAL_SCHEMAS = (
    "spec/schema/m4cil-integration-contract.v1.schema.json",
    "spec/schema/m4cil-fixtures.v1.schema.json",
    "spec/schema/m4cil-manifest.v1.schema.json",
)
SCHEMA_BINDINGS = (
    (
        "spec/m4cil-integration-contract.v1.json",
        "spec/schema/m4cil-integration-contract.v1.schema.json",
    ),
    (
        "spec/m4cil-manifest.v1.json",
        "spec/schema/m4cil-manifest.v1.schema.json",
    ),
    (
        "fixtures/m4cil/cases.json",
        "spec/schema/m4cil-fixtures.v1.schema.json",
    ),
)
REGISTRY_SCHEMAS = (
    "spec/schema/protocol.v1.schema.json",
    "spec/schema/m2il-incremental.v1.schema.json",
    "spec/schema/m4cil-integration-contract.v1.schema.json",
)
COMMITTED_NONREGRESSION = (
    ("scripts/validate_m4c.py", ("--allow-proposed",)),
    ("scripts/validate_m2il.py", ("--inherited",)),
    ("scripts/validate_lr_seam.py", ()),
)


def load(relative: str) -> Any:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def run(relative: str, *args: str) -> str:
    completed = subprocess.run(
        [sys.executable, str(ROOT / relative), *args],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if completed.returncode:
        raise AssertionError(
            f"{relative} failed: {completed.stderr or completed.stdout}"
        )
    return completed.stdout.strip()


def _registry() -> Registry:
    registry = Registry()
    for relative in REGISTRY_SCHEMAS:
        schema = load(relative)
        registry = registry.with_resource(
            schema["$id"],
            Resource.from_contents(schema, default_specification=DRAFT202012),
        )
    return registry


def _validate(value: Any, schema: Any, registry: Registry, label: str) -> None:
    errors = sorted(
        Draft202012Validator(schema, registry=registry).iter_errors(value),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        error = errors[0]
        path = "/" + "/".join(map(str, error.absolute_path))
        raise AssertionError(f"{label} schema rejection at {path}: {error.message}")


def _validate_def(
    value: Any, schema_id: str, definition: str, registry: Registry, label: str
) -> None:
    _validate(
        value,
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": f"{schema_id}#/$defs/{definition}",
        },
        registry,
        label,
    )


def _m4c_owned(manifest: dict[str, Any]) -> list[str]:
    return [
        *manifest["normative_contracts"],
        *manifest["schemas"],
        manifest["fixture"],
        *manifest["reference_implementation"],
        *manifest["tools"],
        *manifest["documentation"],
    ]


def _discover_owned() -> set[str]:
    paths: set[str] = set()
    for pattern in (
        "spec/m4cil-*.json",
        "spec/schema/m4cil-*.json",
        "fixtures/m4cil/**/*",
        "scripts/m4cil_*.py",
        "scripts/check_m4cil_*.py",
    ):
        paths.update(
            path.relative_to(ROOT).as_posix()
            for path in ROOT.glob(pattern)
            if path.is_file()
        )
    paths.update(
        {
            "scripts/run_m4cil_replay.py",
            "scripts/validate_m4cil.py",
            "tests/test_m4cil_candidate_gate.py",
            "tests/test_m4cil_integration.py",
            "docs/M4CIL_INTEGRATED_INCREMENTAL_SLICE.md",
        }
    )
    return paths


def _git_entries() -> list[tuple[str, str]]:
    raw = subprocess.check_output(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=ROOT,
    ).decode("utf-8")
    return [(item[:2], item[3:]) for item in raw.split("\0") if item]


def _head_paths() -> set[str]:
    raw = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", "-z", "HEAD"], cwd=ROOT
    ).decode("utf-8")
    return set(filter(None, raw.split("\0")))


def classify_closure(
    entries: Iterable[tuple[str, str]], head_paths: set[str]
) -> str:
    rows = list(entries)
    expected = set(OWNED_CLOSURE)
    if not rows and expected <= head_paths:
        return "committed-clean"
    if (
        len(rows) == len(OWNED_CLOSURE)
        and {path for _status, path in rows} == expected
        and {status for status, _path in rows} in ({"??"}, {"A "})
        and not (expected & head_paths)
    ):
        return "precommit-added-only"
    raise AssertionError(
        "M4C-IL git closure drift: "
        + json.dumps(
            {
                "entries": sorted(rows),
                "head_owned": sorted(expected & head_paths),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def _assert_closure_classifier() -> None:
    owned = set(OWNED_CLOSURE)
    if classify_closure((("??", path) for path in owned), set()) != "precommit-added-only":
        raise AssertionError("M4C-IL precommit closure classifier drift")
    if classify_closure((), owned) != "committed-clean":
        raise AssertionError("M4C-IL committed closure classifier drift")
    try:
        classify_closure(((" M", OWNED_CLOSURE[0]),), owned)
    except AssertionError:
        pass
    else:
        raise AssertionError("M4C-IL mixed git state accepted")


def _clean_process_replays() -> tuple[dict[str, bytes], list[str]]:
    rows: dict[str, list[bytes]] = {
        "happy": [],
        "crash_after_external_success": [],
    }
    descriptors: list[str] = []
    profiles = (
        ("clean-a", "1", "UTC"),
        ("clean-b", "777", "Pacific/Honolulu"),
    )
    with tempfile.TemporaryDirectory(prefix="flrh-m4cil-clean-") as raw:
        base = Path(raw)
        for name, hash_seed, timezone in profiles:
            cwd = base / name
            cwd.mkdir()
            env = {
                **os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONHASHSEED": hash_seed,
                "TZ": timezone,
                "TMPDIR": str(cwd),
            }
            for mode in rows:
                completed = subprocess.run(
                    [sys.executable, str(ROOT / "scripts/run_m4cil_replay.py")],
                    cwd=cwd,
                    env=env,
                    input=canonical_bytes({"mode": mode}) + b"\n",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                descriptor = f"{mode}:{name}"
                if completed.returncode or completed.stderr:
                    raise AssertionError(
                        f"M4C-IL clean process {descriptor}: "
                        + completed.stderr.decode("utf-8", "replace")
                    )
                rows[mode].append(completed.stdout)
                descriptors.append(descriptor)
    for mode, outputs in rows.items():
        if len(outputs) != 2 or outputs[0] != outputs[1]:
            raise AssertionError(f"M4C-IL clean-process mismatch: {mode}")
    return {mode: outputs[0] for mode, outputs in rows.items()}, descriptors


def _assert_semantic_boundaries(
    contract: dict[str, Any], cases: dict[str, Any], docs: str
) -> None:
    if contract["purpose"] != PURPOSE:
        raise AssertionError("M4C-IL purpose boundary drift")
    if contract["non_claims"] != list(NON_CLAIMS):
        raise AssertionError("M4C-IL contract non-claim boundary drift")
    if cases["non_claims"] != list(NON_CLAIMS):
        raise AssertionError("M4C-IL fixture non-claim boundary drift")
    if contract["completion_boundary"] != CONTRACT_COMPLETION_BOUNDARY:
        raise AssertionError("M4C-IL contract completion boundary drift")
    if len(contract["pipeline"]) != 7:
        raise AssertionError("M4C-IL pipeline cardinality drift")
    lineage = contract["incremental_lineage"]
    if (
        lineage["bootstrap_prior_checkpoint"] is not None
        or lineage["bootstrap_logical_time"] != 1
        or lineage["reuse_logical_time"] != 2
        or lineage["reuse_input_deltas"] != []
        or lineage["minimum_candidate_cache_hits"] != 1
        or lineage["maximum_reuse_candidate_body_evaluations"] != 0
        or lineage["public_m2_solve_calls_per_incremental_step"] != 2
        or lineage["public_m2_calls_excluded_from_candidate_counters"] is not True
        or lineage["lr_input"] != "reuse_logic_step.fixpoint_result"
    ):
        raise AssertionError("M4C-IL incremental-lineage boundary drift")
    fsm = contract["fsm_projection"]
    if (
        fsm["stop_state"] != "HONOR_PENDING_INTERRUPT"
        or fsm["terminal_claim"] != "SLICE_CONFORMED"
        or fsm["trace_claim"] != "FSM_CONFORMANCE_PROJECTION_ONLY"
        or fsm["outer_reducer_executed"] is not False
    ):
        raise AssertionError("M4C-IL FSM boundary drift")
    if cases["expected"]["minimum_candidate_cache_hits"] != 1:
        raise AssertionError("M4C-IL fixture reuse boundary drift")
    markers = (
        "PROPOSED_PENDING_MEASUREMENT",
        "step_incremental_l",
        "candidate_cache_hits",
        "executed_candidate_body_evaluations",
        "public M2",
        "project_lr",
        "HONOR_PENDING_INTERRUPT",
        "SLICE_CONFORMED",
        "FSM_CONFORMANCE_PROJECTION_ONLY",
        "outer_reducer_executed=false",
        "FakeAdapter",
        "os._exit(86)",
        "detached",
        "no performance",
        "no persistent L storage",
        "no production",
        "no engine",
        "no Lakatos progress",
    )
    for marker in markers:
        if marker not in docs:
            raise AssertionError(f"M4C-IL documentation boundary drift: {marker}")


def _validate_emitted_wires(
    registry: Registry, happy: dict[str, Any], crash: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    m4cil_id = load("spec/schema/m4cil-integration-contract.v1.schema.json")["$id"]
    m2il_id = load("spec/schema/m2il-incremental.v1.schema.json")["$id"]
    protocol_id = load("spec/schema/protocol.v1.schema.json")["$id"]
    verifications: dict[str, Any] = {}
    for label, evidence in (("happy", happy), ("crash", crash)):
        _validate_def(evidence, m4cil_id, "ReplayEvidence", registry, label)
        _validate_def(
            evidence["bootstrap_logic_step"],
            m2il_id,
            "LPersistentLStep",
            registry,
            f"{label}.bootstrap_logic_step",
        )
        _validate_def(
            evidence["reuse_logic_step"],
            m2il_id,
            "LPersistentLStep",
            registry,
            f"{label}.reuse_logic_step",
        )
        _validate_def(
            evidence["durable_checkpoint"]["logic_checkpoint"],
            m2il_id,
            "Checkpoint",
            registry,
            f"{label}.logic_checkpoint",
        )
        _validate_def(
            evidence["accepted_event"],
            protocol_id,
            "AcceptedEvent",
            registry,
            f"{label}.accepted_event",
        )
        _validate_def(
            evidence["action_receipt"],
            protocol_id,
            "ActionReceipt",
            registry,
            f"{label}.action_receipt",
        )
        verification = verify_m4cil_evidence(evidence)
        _validate_def(
            verification,
            m4cil_id,
            "VerificationReceipt",
            registry,
            f"{label}.verification",
        )
        verifications[label] = verification
        canonical_bytes(evidence)
        canonical_bytes(verification)

    bad_inputs = load_chain_inputs()
    bad_inputs["rule_bundle"]["rule_bundle_digest"] = "sha256:" + "0" * 64
    rejection = run_incremental_reference_chain(False, chain_inputs=bad_inputs)
    _validate_def(rejection, m4cil_id, "ReplayRejection", registry, "rejection")
    canonical_bytes(rejection)

    forged = copy.deepcopy(happy)
    forged["reuse_logic_step"]["reuse_receipt"]["candidate_cache_hits"] += 1
    forged.pop("evidence_digest")
    forged["evidence_digest"] = canonical_digest(
        {
            "kind": "M4CILEvidencePreimage",
            "contract_version": M4CIL_CONTRACT,
            **copy.deepcopy(forged),
        }
    )
    failure = verify_m4cil_evidence(forged)
    _validate_def(
        failure, m4cil_id, "VerificationFailure", registry, "verification_failure"
    )
    canonical_bytes(failure)
    return verifications, rejection, failure


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-proposed", action="store_true")
    args = parser.parse_args()
    if not args.allow_proposed:
        raise SystemExit(
            "M4C-IL is PROPOSED_PENDING_MEASUREMENT; pass --allow-proposed "
            "for candidate validation"
        )

    manifest = load("spec/m4cil-manifest.v1.json")
    contract = load("spec/m4cil-integration-contract.v1.json")
    cases = load("fixtures/m4cil/cases.json")
    if {manifest["status"], contract["status"], cases["status"]} != {STATUS}:
        raise AssertionError("M4C-IL status drift")
    if manifest["completion_boundary"] != MANIFEST_COMPLETION_BOUNDARY:
        raise AssertionError("M4C-IL manifest completion boundary drift")
    if tuple(manifest["owned_closure"]) != OWNED_CLOSURE:
        raise AssertionError("M4C-IL exact owned closure drift")
    if set(OWNED_CLOSURE) != _discover_owned():
        raise AssertionError(
            "M4C-IL filesystem closure drift: "
            + json.dumps(
                {
                    "missing": sorted(set(OWNED_CLOSURE) - _discover_owned()),
                    "extra": sorted(_discover_owned() - set(OWNED_CLOSURE)),
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    for relative in OWNED_CLOSURE:
        if not (ROOT / relative).is_file():
            raise AssertionError(f"M4C-IL owned artifact missing: {relative}")
    for relative in OWNED_CLOSURE:
        if relative.endswith(".py"):
            ast.parse((ROOT / relative).read_text(encoding="utf-8"), filename=relative)

    m4c_manifest = load("spec/m4c-manifest.v1.json")
    m2il_manifest = load("spec/m2il-manifest.v1.json")
    expected_inherited = [*_m4c_owned(m4c_manifest), *m2il_manifest["owned_closure"]]
    pins = manifest["inherited_sha256_pins"]
    if len(expected_inherited) != 36 or len(set(expected_inherited)) != 36:
        raise AssertionError("M4C-IL expected inherited closure is not exact 36")
    if [row.get("artifact") for row in pins] != expected_inherited:
        raise AssertionError("M4C-IL inherited dependency order drift")
    if len(pins) != len({row["artifact"] for row in pins}):
        raise AssertionError("M4C-IL inherited dependency duplicate")
    for row in pins:
        path = ROOT / row["artifact"]
        if not path.is_file():
            raise AssertionError(f"M4C-IL inherited artifact missing: {row['artifact']}")
        observed = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        if observed != row["sha256"]:
            raise AssertionError(f"M4C-IL inherited artifact drift: {row['artifact']}")

    _assert_closure_classifier()
    closure_mode = classify_closure(_git_entries(), _head_paths())

    registry = _registry()
    for relative in LOCAL_SCHEMAS:
        Draft202012Validator.check_schema(load(relative))
    for artifact, schema in SCHEMA_BINDINGS:
        _validate(load(artifact), load(schema), registry, artifact)
    hostile_contract = copy.deepcopy(contract)
    hostile_contract["non_claims"] = [f"evil-{index}" for index in range(10)]
    if Draft202012Validator(
        load("spec/schema/m4cil-integration-contract.v1.schema.json"),
        registry=registry,
    ).is_valid(hostile_contract):
        raise AssertionError("M4C-IL contract schema accepted non-claim substitution")
    hostile_manifest = copy.deepcopy(manifest)
    hostile_manifest["completion_boundary"] = (
        "PRODUCTION READY ENGINE LAKATOS PROGRESS"
    )
    if Draft202012Validator(
        load("spec/schema/m4cil-manifest.v1.schema.json"), registry=registry
    ).is_valid(hostile_manifest):
        raise AssertionError("M4C-IL manifest schema accepted claim-boundary drift")
    malformed = {
        "kind": "M4CILReplayEvidence",
        "schema_version": None,
        "evil": True,
    }
    m4cil_id = load("spec/schema/m4cil-integration-contract.v1.schema.json")["$id"]
    if Draft202012Validator(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": f"{m4cil_id}#/$defs/ReplayEvidence",
        },
        registry=registry,
    ).is_valid(malformed):
        raise AssertionError("M4C-IL closed wire schema accepted malformed evidence")

    docs = (ROOT / "docs/M4CIL_INTEGRATED_INCREMENTAL_SLICE.md").read_text(
        encoding="utf-8"
    )
    _assert_semantic_boundaries(contract, cases, docs)

    happy = run_incremental_reference_chain(False)
    crash = run_incremental_reference_chain(True)
    verifications, _rejection, _failure = _validate_emitted_wires(
        registry, happy, crash
    )
    expected = cases["expected"]
    if (
        happy["status"] != expected["status"]
        or happy["outer_fsm_stop_state"] != expected["outer_fsm_stop_state"]
        or happy["durable_run_status"] != expected["durable_run_status"]
        or happy["reuse_logic_step"]["reuse_receipt"]["candidate_cache_hits"]
        < expected["minimum_candidate_cache_hits"]
        or happy["reuse_logic_step"]["reuse_receipt"][
            "executed_candidate_body_evaluations"
        ]
        != expected["executed_candidate_body_evaluations"]
        or happy["m4b_verification"]["intent_count"] != expected["intent_count"]
        or happy["m4b_verification"]["receipt_count"] != expected["receipt_count"]
        or happy["m4b_verification"]["pending_count"] != expected["pending_count"]
        or crash["recovery"]["worker_exit_code"] != expected["crash_worker_exit_code"]
    ):
        raise AssertionError("M4C-IL replay fixture expectation drift")

    clean_outputs, clean_descriptors = _clean_process_replays()
    if clean_outputs != {
        "happy": canonical_bytes(happy) + b"\n",
        "crash_after_external_success": canonical_bytes(crash) + b"\n",
    }:
        raise AssertionError("M4C-IL in-process/clean-process replay mismatch")

    run("tests/test_m4cil_integration.py")
    sensitivity = json.loads(run("scripts/check_m4cil_sensitivity.py"))
    detected_ids = [row["case"] for row in sensitivity["detected"]]
    if (
        detected_ids != cases["sensitivity_cases"]
        or sensitivity["sensitivity_cases_detected"] != 16
        or sensitivity["escaped"] != 0
    ):
        raise AssertionError("M4C-IL sensitivity report drift")

    if closure_mode == "precommit-added-only":
        inherited_gate_state = "DEFERRED_UNTIL_COMMITTED_CLEAN"
    else:
        for relative, command_args in COMMITTED_NONREGRESSION:
            run(relative, *command_args)
        inherited_gate_state = "PASS"

    report = {
        "kind": "M4CILValidationReport",
        "status": STATUS,
        "manifest_owned_paths": len(OWNED_CLOSURE),
        "inherited_dependencies": len(pins),
        "public_pipeline_stages": len(contract["pipeline"]),
        "success_paths": len(cases["replay_modes"]),
        "crash_recovery_paths": 1,
        "sensitivity_cases": sensitivity["sensitivity_cases_detected"],
        "clean_processes": len(clean_descriptors),
        "clean_process_descriptors": clean_descriptors,
        "verification_checks": len(verifications["happy"]["checks"]),
        "unit_test_gate": 1,
        "closure_mode": closure_mode,
        "inherited_gate_state": inherited_gate_state,
    }
    print(json.dumps(report, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
