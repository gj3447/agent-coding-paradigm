#!/usr/bin/env python3
"""Non-normative conformance runner for the bounded M1 pure-F slice."""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from flrh_kernel import step_f  # noqa: E402
from flrh_kernel.canonical import (  # noqa: E402
    CanonicalizationError,
    canonical_bytes as kernel_canonical_bytes,
    canonical_digest as kernel_canonical_digest,
)
from m1_fixtures import (  # noqa: E402
    find_case,
    materialize_case,
    materialize_replay_sequence,
)
from m1_guard import AttemptedMutation, write_tracking_copy  # noqa: E402


M0_SPEC = importlib.util.spec_from_file_location("m1_independent_m0_oracle", ROOT / "scripts/validate_m0.py")
if M0_SPEC is None or M0_SPEC.loader is None:
    raise RuntimeError("cannot load independent M0 canonical oracle")
M0 = importlib.util.module_from_spec(M0_SPEC)
M0_SPEC.loader.exec_module(M0)

PROTOCOL_URI = "https://github.com/gj3447/agent-coding-paradigm/spec/schema/protocol.v1.schema.json"
M1_URI = "https://github.com/gj3447/agent-coding-paradigm/spec/schema/m1-kernel.v1.schema.json"
SCHEMA_PATHS = (
    "spec/schema/m1-kernel.v1.schema.json",
    "spec/schema/m1-kernel-contract.v1.schema.json",
    "spec/schema/m1-fixtures.v1.schema.json",
    "spec/schema/m1-manifest.v1.schema.json",
)
FORBIDDEN_H_FIELDS = {
    "intent_id",
    "batch_id",
    "capability",
    "authority_digest",
    "assessed_risk",
    "adapter_version",
    "idempotency_key",
}
FORBIDDEN_IMPLEMENTATION_IMPORTS = {
    "anthropic",
    "asyncio",
    "ctypes",
    "datetime",
    "http",
    "httpx",
    "importlib",
    "io",
    "langchain",
    "litellm",
    "openai",
    "os",
    "pathlib",
    "random",
    "requests",
    "secrets",
    "socket",
    "subprocess",
    "time",
    "urllib",
    "uuid",
}
FORBIDDEN_DYNAMIC_CALLS = {"__import__", "compile", "eval", "exec", "open"}
ALLOWED_IMPLEMENTATION_IMPORTS = {
    "__future__",
    "dataclasses",
    "hashlib",
    "json",
    "re",
    "typing",
    "unicodedata",
}
MEASURED_STATUS = "MEASURED_REFERENCE_CONFORMANCE"
REQUIRED_INHERITED_DEPENDENCIES = (
    "spec/schema/protocol.v1.schema.json",
    "spec/canonicalization.v1.json",
)


def load_json(relative: str) -> Any:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _registry() -> Registry:
    resources = []
    for path in ("spec/schema/protocol.v1.schema.json",) + SCHEMA_PATHS:
        schema = load_json(path)
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def _validate_ref(instance: Any, ref: str, registry: Registry) -> None:
    validator = Draft202012Validator(
        {"$ref": ref},
        registry=registry,
        format_checker=FormatChecker(),
    )
    errors = sorted(validator.iter_errors(instance), key=lambda error: tuple(str(part) for part in error.path))
    if errors:
        error = errors[0]
        location = "/" + "/".join(str(part) for part in error.absolute_path)
        raise AssertionError(f"schema rejection at {location}: {error.message}")


def _validate_manifest_closure(manifest: Mapping[str, Any], contract: Mapping[str, Any]) -> None:
    require(manifest["status"] == contract["status"], "M1 manifest/contract status drift")
    require(
        manifest["status"] == MEASURED_STATUS,
        f"M1 aggregate cannot report measured conformance at status {manifest['status']}",
    )
    observed_dependencies = tuple(
        dependency["artifact"] for dependency in manifest["inherited_normative_dependencies"]
    )
    require(
        observed_dependencies == REQUIRED_INHERITED_DEPENDENCIES,
        "M1 inherited dependency set/order drift: "
        f"observed={observed_dependencies} required={REQUIRED_INHERITED_DEPENDENCIES}",
    )


def _independent_transition_digest(result: Mapping[str, Any]) -> str:
    projection = {
        "kind": "FTransitionDigestProjection",
        "contract_version": result["contract_version"],
        "event_id": result["event_id"],
        "prior_snapshot_digest": result["prior_snapshot_digest"],
        "next_snapshot_digest": M0.canonical_digest(result["next_snapshot"]),
        "ordered_fact_delta_digests": [M0.canonical_digest(item) for item in result["fact_deltas"]],
        "ordered_effect_proposal_digests": [
            M0.canonical_digest(item) for item in result["effect_proposals"]
        ],
    }
    return M0.canonical_digest(projection)


def _independent_expected_rejection(
    document: Mapping[str, Any], case: Mapping[str, Any]
) -> dict[str, Any]:
    event = document.get("accepted_event")
    snapshot = document.get("snapshot")
    event_id = event.get("event_id") if isinstance(event, dict) else None
    if not isinstance(event_id, str):
        event_id = None
    snapshot_revision = snapshot.get("revision") if isinstance(snapshot, dict) else None
    if (
        not isinstance(snapshot_revision, int)
        or isinstance(snapshot_revision, bool)
        or not 0 <= snapshot_revision <= 2**63 - 1
    ):
        snapshot_revision = None
    return {
        "kind": "FRejection",
        "schema_version": "flrh-f-result/1",
        "contract_version": "flrh-f-kernel/1",
        "code": case["expected_code"],
        "path": case["expected_path"],
        "event_id": event_id,
        "snapshot_revision": snapshot_revision,
        "context": copy.deepcopy(case["expected_context"]),
    }


def _independent_value_digest(domain: str, value: Mapping[str, Any]) -> str:
    return M0.canonical_digest(
        {
            "kind": "M1ValueDigestPreimage",
            "contract_version": "flrh-f-kernel/1",
            "domain": domain,
            "value": dict(value),
        }
    )


def _independent_digest_id(prefix: str, domain: str, value: Mapping[str, Any]) -> str:
    digest = M0.canonical_digest(
        {
            "kind": "M1IdentityPreimage",
            "contract_version": "flrh-f-kernel/1",
            "domain": domain,
            "value": dict(value),
        }
    )
    return f"{prefix}:{digest.removeprefix('sha256:')}"


def _independent_expected_transition(document: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = document["snapshot"]
    event = document["accepted_event"]
    payload = event["payload"]
    versions = event["versions"]
    observation_digest = _independent_value_digest("observation", payload["observation"])
    fact_value = {
        "kind": "FactDelta",
        "tuple": {
            "predicate": "observation_recorded",
            "subject": snapshot["aggregate_id"],
            "object_digest": observation_digest,
        },
        "logical_time": event["logical_time"],
        "diff": 1,
        "causation_id": event["event_id"],
        "provenance_delta": {
            "source_event_id": event["event_id"],
            "observation_digest": observation_digest,
        },
        "rule_set_version": versions["rule_set"],
        "dataflow_version": versions["dataflow"],
    }
    fact_delta = dict(fact_value)
    fact_delta["derivation_id"] = _independent_digest_id(
        "derivation", "observation-fact-value", fact_value
    )
    fact_deltas = sorted([fact_delta], key=M0.canonical_bytes)

    effect_proposals = []
    request = payload["effect_request"]
    if request is not None:
        action_digest = _independent_value_digest("effect-action", request["action"])
        destination_digest = _independent_value_digest("effect-destination", request["destination"])
        proposal_value = {
            "kind": "EffectProposal",
            "effect_type": request["effect_type"],
            "action_digest": action_digest,
            "cause_id": event["event_id"],
            "correlation_id": event["correlation_id"],
            "destination_digest": destination_digest,
            "goal_id": request["goal_id"],
            "obligation_id": request["obligation_id"],
            "declared_risk_hint": request["declared_risk_hint"],
            "preconditions": sorted(request["preconditions"], key=M0.canonical_bytes),
            "versions": dict(versions),
        }
        proposal = dict(proposal_value)
        proposal["proposal_id"] = _independent_digest_id(
            "proposal", "effect-proposal-value", proposal_value
        )
        proposal["proposal_dedup_key"] = _independent_digest_id(
            "proposal-dedup", "proposal-dedup-value", proposal_value
        )
        effect_proposals = sorted([proposal], key=M0.canonical_bytes)

    next_snapshot = {
        "kind": "FStateSnapshot",
        "schema_version": "flrh-f-snapshot/1",
        "aggregate_id": snapshot["aggregate_id"],
        "revision": snapshot["revision"] + 1,
        "phase": "closed" if payload["mark_complete"] else snapshot["phase"],
        "observation_count": snapshot["observation_count"] + 1,
        "last_logical_time": event["logical_time"],
        "last_event_id": event["event_id"],
        "last_observation_digest": observation_digest,
        "versions": dict(snapshot["versions"]),
    }
    result = {
        "kind": "FTransition",
        "schema_version": "flrh-f-result/1",
        "contract_version": "flrh-f-kernel/1",
        "event_id": event["event_id"],
        "prior_snapshot_digest": M0.canonical_digest(snapshot),
        "next_snapshot": next_snapshot,
        "fact_deltas": fact_deltas,
        "effect_proposals": effect_proposals,
    }
    result["transition_digest"] = _independent_transition_digest(result)
    return result


def _raw_wire_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=False,
    ).encode("utf-8")


def _run_with_write_detection(
    document: Mapping[str, Any], expected_result: Mapping[str, Any], label: str
) -> None:
    attempts: list[str] = []
    guarded = write_tracking_copy(document, attempts)
    before = _raw_wire_bytes(guarded)
    try:
        result = step_f(guarded["snapshot"], guarded["accepted_event"])
    except AttemptedMutation as error:
        raise AssertionError(f"{label}: attempted caller-input mutation: {attempts}") from error
    after = _raw_wire_bytes(guarded)
    require(not attempts, f"{label}: attempted caller-input mutation: {attempts}")
    require(before == after, f"{label}: caller-input bytes changed")
    require(
        M0.canonical_bytes(result) == M0.canonical_bytes(expected_result),
        f"{label}: write-detecting input changed result",
    )


def _walk(value: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield key, item
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def _at_pointer(value: Any, pointer: str) -> Any:
    current = value
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        current = current[int(token)] if isinstance(current, list) else current[token]
    return current


def _check_no_h_authority(result: Mapping[str, Any]) -> None:
    require(result["kind"] != "EffectIntent", "F returned an EffectIntent")
    for key, value in _walk(result.get("effect_proposals", [])):
        require(key not in FORBIDDEN_H_FIELDS, f"F proposal contains H-owned field {key}")
        require(not key.startswith("approval"), f"F proposal contains approval field {key}")
        if isinstance(value, str):
            require(value not in {"EffectIntent", "ActionReceipt"}, f"F proposal contains H-owned kind {value}")


def _check_success(
    document: Mapping[str, Any],
    case: Mapping[str, Any],
    result: Mapping[str, Any],
    registry: Registry,
    *,
    check_golden: bool,
) -> None:
    event = document["accepted_event"]
    _validate_ref(result, M1_URI + "#/$defs/FTransition", registry)
    require(result["kind"] == "FTransition", f"{case['id']}: expected transition")
    expected = _independent_expected_transition(document)
    require(
        M0.canonical_bytes(result) == M0.canonical_bytes(expected),
        f"{case['id']}: full transition differs from independent semantic oracle",
    )
    require(result["event_id"] == event["event_id"], f"{case['id']}: event binding")
    require(
        result["prior_snapshot_digest"] == M0.canonical_digest(document["snapshot"]),
        f"{case['id']}: prior snapshot binding",
    )
    require(
        result["transition_digest"] == _independent_transition_digest(result),
        f"{case['id']}: transition digest is not independently reproducible",
    )
    if check_golden:
        require(
            result["transition_digest"] == case["expected_transition_digest"],
            f"{case['id']}: transition golden drift: {result['transition_digest']}",
        )
    require(result["next_snapshot"]["revision"] == case["expected_next_revision"], f"{case['id']}: revision")
    require(result["next_snapshot"]["phase"] == case["expected_next_phase"], f"{case['id']}: phase")
    require(len(result["fact_deltas"]) == case["expected_fact_delta_count"], f"{case['id']}: delta count")
    require(
        len(result["effect_proposals"]) == case["expected_effect_proposal_count"],
        f"{case['id']}: proposal count",
    )
    require(
        result["fact_deltas"] == sorted(result["fact_deltas"], key=M0.canonical_bytes),
        f"{case['id']}: FactDelta ordering",
    )
    require(
        result["effect_proposals"] == sorted(result["effect_proposals"], key=M0.canonical_bytes),
        f"{case['id']}: EffectProposal ordering",
    )
    for delta in result["fact_deltas"]:
        _validate_ref(delta, PROTOCOL_URI + "#/$defs/FactDelta", registry)
        require(delta["logical_time"] == event["logical_time"], f"{case['id']}: delta logical time")
        require(delta["causation_id"] == event["event_id"], f"{case['id']}: delta cause")
        require(delta["rule_set_version"] == event["versions"]["rule_set"], f"{case['id']}: rule version")
        require(delta["dataflow_version"] == event["versions"]["dataflow"], f"{case['id']}: dataflow version")
    request = event["payload"]["effect_request"]
    for proposal in result["effect_proposals"]:
        _validate_ref(proposal, PROTOCOL_URI + "#/$defs/EffectProposal", registry)
        require(request is not None, f"{case['id']}: proposal without explicit request")
        require(proposal["cause_id"] == event["event_id"], f"{case['id']}: proposal cause")
        require(proposal["correlation_id"] == event["correlation_id"], f"{case['id']}: proposal correlation")
        require(proposal["versions"] == event["versions"], f"{case['id']}: proposal versions")
        require(
            proposal["action_digest"] == _independent_value_digest("effect-action", request["action"]),
            f"{case['id']}: action binding",
        )
        require(
            proposal["destination_digest"]
            == _independent_value_digest("effect-destination", request["destination"]),
            f"{case['id']}: destination binding",
        )
        require(
            proposal["preconditions"] == sorted(proposal["preconditions"], key=M0.canonical_bytes),
            f"{case['id']}: precondition ordering",
        )
    _check_no_h_authority(result)


def validate_schemas_and_manifest() -> dict[str, int]:
    registry = _registry()
    for path in SCHEMA_PATHS:
        Draft202012Validator.check_schema(load_json(path))
    bindings = (
        ("spec/m1-kernel-contract.v1.json", "spec/schema/m1-kernel-contract.v1.schema.json"),
        ("spec/m1-manifest.v1.json", "spec/schema/m1-manifest.v1.schema.json"),
        ("fixtures/m1/cases.json", "spec/schema/m1-fixtures.v1.schema.json"),
    )
    for artifact_path, schema_path in bindings:
        schema = load_json(schema_path)
        Draft202012Validator(schema, registry=registry, format_checker=FormatChecker()).validate(
            load_json(artifact_path)
        )
    manifest = load_json("spec/m1-manifest.v1.json")
    contract = load_json("spec/m1-kernel-contract.v1.json")
    _validate_manifest_closure(manifest, contract)
    for dependency in manifest["inherited_normative_dependencies"]:
        target = ROOT / dependency["artifact"]
        require(target.is_file(), f"M1 inherited dependency missing: {dependency['artifact']}")
        actual = "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest()
        require(
            actual == dependency["sha256"],
            f"M1 inherited dependency digest drift: {dependency['artifact']}: {actual}",
        )
    declared = (
        manifest["normative_contracts"]
        + [item["artifact"] for item in manifest["inherited_normative_dependencies"]]
        + manifest["self_validating_schemas"]
        + [manifest["conformance_fixture"]]
        + manifest["golden_outputs"]
        + manifest["reference_implementation"]
        + manifest["non_normative_tools"]
    )
    missing = [path for path in declared if not (ROOT / path).is_file()]
    require(not missing, f"M1 manifest references missing files: {missing}")
    corpus = load_json("fixtures/m1/cases.json")
    for input_id, document in corpus["base_inputs"].items():
        try:
            _validate_ref(document, M1_URI + "#/$defs/M1Input", registry)
        except AssertionError as error:
            raise AssertionError(f"base input {input_id}: {error}") from error
    return {
        "m1_schemas": len(SCHEMA_PATHS),
        "m1_bindings": len(bindings),
        "m1_inherited_dependencies": len(manifest["inherited_normative_dependencies"]),
        "m1_base_inputs": len(corpus["base_inputs"]),
    }


def validate_static_authority_surface() -> dict[str, int]:
    manifest = load_json("spec/m1-manifest.v1.json")
    declared = set(manifest["reference_implementation"])
    observed = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "src/flrh_kernel").rglob("*.py")
    }
    require(observed == declared, f"implementation manifest drift: observed={sorted(observed)} declared={sorted(declared)}")
    imports: set[str] = set()
    dynamic_calls: list[str] = []
    relative_modules: set[str] = set()
    for relative in sorted(declared):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    imports.add(node.module.split(".", 1)[0])
                elif node.level == 1 and node.module:
                    relative_modules.add(node.module.split(".", 1)[0])
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in FORBIDDEN_DYNAMIC_CALLS:
                    dynamic_calls.append(f"{relative}:{node.lineno}:{node.func.id}")
    require(
        imports == ALLOWED_IMPLEMENTATION_IMPORTS,
        "implementation import allowlist drift: "
        f"observed={sorted(imports)} allowed={sorted(ALLOWED_IMPLEMENTATION_IMPORTS)}",
    )
    require(not imports & FORBIDDEN_IMPLEMENTATION_IMPORTS, f"forbidden implementation imports: {sorted(imports & FORBIDDEN_IMPLEMENTATION_IMPORTS)}")
    require(relative_modules <= {"canonical", "kernel"}, f"unmanifested relative modules: {sorted(relative_modules)}")
    require(not dynamic_calls, f"forbidden dynamic calls: {dynamic_calls}")
    for forbidden_path in ("engine", "ports", "adapters", "registry", "runtime", "persistence", "scheduler"):
        require(not (ROOT / "src/flrh_kernel" / forbidden_path).exists(), f"premature M1 abstraction: {forbidden_path}")
    return {
        "m1_manifested_implementation_files": len(declared),
        "m1_static_import_roots": len(imports),
        "m1_forbidden_static_surfaces": 0,
    }


def validate_canonical_oracle() -> dict[str, int]:
    cases = load_json("fixtures/m0/canonical/cases.json")
    for case in cases["equal_pairs"]:
        for side in ("left", "right"):
            require(
                kernel_canonical_bytes(case[side]) == M0.canonical_bytes(case[side]),
                f"canonical bytes disagree with independent oracle: {case['id']} {side}",
            )
        require(kernel_canonical_digest(case["left"]) == case["expected_digest"], f"golden digest drift: {case['id']}")
    for case in cases["different_pairs"]:
        require(
            kernel_canonical_digest(case["left"]) != kernel_canonical_digest(case["right"]),
            f"canonical mutation collapsed: {case['id']}",
        )
    for case in cases["reject_cases"]:
        kernel_rejected = False
        oracle_rejected = False
        try:
            kernel_canonical_bytes(case["input"])
        except CanonicalizationError:
            kernel_rejected = True
        try:
            M0.canonical_bytes(case["input"])
        except AssertionError:
            oracle_rejected = True
        require(kernel_rejected and oracle_rejected, f"canonical reject disagreement: {case['id']}")
    tuple_value = (1, 2)
    kernel_tuple_rejected = False
    oracle_tuple_rejected = False
    try:
        kernel_canonical_bytes(tuple_value)
    except CanonicalizationError:
        kernel_tuple_rejected = True
    try:
        M0.canonical_bytes(tuple_value)
    except AssertionError:
        oracle_tuple_rejected = True
    require(kernel_tuple_rejected and oracle_tuple_rejected, "tuple JSON-boundary disagreement")
    return {
        "m1_canonical_equal": len(cases["equal_pairs"]),
        "m1_canonical_different": len(cases["different_pairs"]),
        "m1_canonical_reject": len(cases["reject_cases"]),
        "m1_non_json_array_reject": 1,
    }


def validate_result_goldens() -> dict[str, int]:
    registry = _registry()
    corpus = load_json("fixtures/m1/cases.json")
    goldens = (
        (
            "observe-with-effect",
            "fixtures/m1/golden/observe-with-effect.transition.json",
            "FTransition",
        ),
        (
            "invalid-calendar-timestamp",
            "fixtures/m1/golden/invalid-calendar-timestamp.rejection.json",
            "FRejection",
        ),
    )
    for case_id, relative, expected_kind in goldens:
        raw = (ROOT / relative).read_bytes()
        require(raw.endswith(b"\n") and raw.count(b"\n") == 1, f"{case_id}: golden must be one line")
        body = raw[:-1]
        parsed = json.loads(body.decode("utf-8"))
        require(parsed["kind"] == expected_kind, f"{case_id}: golden kind drift")
        require(M0.canonical_bytes(parsed) == body, f"{case_id}: golden bytes are not canonical")
        document = materialize_case(corpus, find_case(corpus, case_id))
        actual = step_f(document["snapshot"], document["accepted_event"])
        if expected_kind == "FTransition":
            independently_expected = _independent_expected_transition(document)
        else:
            case = find_case(corpus, case_id)
            independently_expected = _independent_expected_rejection(document, case)
        require(
            M0.canonical_bytes(independently_expected) == body,
            f"{case_id}: semantic oracle differs from frozen golden bytes",
        )
        _validate_ref(actual, M1_URI + f"#/$defs/{expected_kind}", registry)
        require(M0.canonical_bytes(actual) == body, f"{case_id}: M0 oracle differs from frozen golden bytes")
        require(kernel_canonical_bytes(actual) == body, f"{case_id}: kernel serializer differs from golden bytes")
    return {"m1_exact_result_goldens": len(goldens)}


def validate_cases(*, check_goldens: bool = True) -> dict[str, int]:
    registry = _registry()
    corpus = load_json("fixtures/m1/cases.json")
    for case in corpus["success_cases"]:
        document = materialize_case(corpus, case)
        _validate_ref(document, M1_URI + "#/$defs/M1Input", registry)
        before = copy.deepcopy(document)
        before_bytes = _raw_wire_bytes(document)
        result = step_f(document["snapshot"], document["accepted_event"])
        require(document == before, f"{case['id']}: input mutated")
        require(_raw_wire_bytes(document) == before_bytes, f"{case['id']}: input bytes/order mutated")
        _check_success(document, case, result, registry, check_golden=check_goldens)
        _run_with_write_detection(document, result, case["id"])
    for case in corpus["rejection_cases"]:
        document = materialize_case(corpus, case)
        before = copy.deepcopy(document)
        before_bytes = _raw_wire_bytes(document)
        result = step_f(document["snapshot"], document["accepted_event"])
        require(document == before, f"{case['id']}: rejection mutated input")
        require(_raw_wire_bytes(document) == before_bytes, f"{case['id']}: rejection bytes/order mutated")
        _validate_ref(result, M1_URI + "#/$defs/FRejection", registry)
        require(result["kind"] == "FRejection", f"{case['id']}: expected rejection")
        independently_expected = _independent_expected_rejection(document, case)
        require(
            M0.canonical_bytes(result) == M0.canonical_bytes(independently_expected),
            f"{case['id']}: full rejection differs from independent fixture oracle",
        )
        M0.canonical_bytes(result)
        require("traceback" not in json.dumps(result).lower(), f"{case['id']}: traceback leaked")
        _run_with_write_detection(document, result, case["id"])
    for pair in corpus["equivalence_pairs"]:
        left_case = find_case(corpus, pair["left_case_id"])
        right_case = find_case(corpus, pair["right_case_id"])
        left_doc = materialize_case(corpus, left_case)
        right_doc = materialize_case(corpus, right_case)
        left = step_f(left_doc["snapshot"], left_doc["accepted_event"])
        right = step_f(right_doc["snapshot"], right_doc["accepted_event"])
        require(M0.canonical_bytes(left) == M0.canonical_bytes(right), f"equivalence pair differs: {pair}")
    for mutation in corpus["sensitivity_mutations"]:
        base_case = {"input_ref": mutation["input_ref"], "mutations": []}
        base_document = materialize_case(corpus, base_case)
        changed_document = materialize_case(corpus, mutation)
        base = step_f(base_document["snapshot"], base_document["accepted_event"])
        changed = step_f(changed_document["snapshot"], changed_document["accepted_event"])
        if mutation["expected_relation"] == "different_transition":
            require(base["kind"] == changed["kind"] == "FTransition", f"{mutation['id']}: not transitions")
            require(M0.canonical_bytes(base) != M0.canonical_bytes(changed), f"{mutation['id']}: insensitive kernel")
            for path in mutation.get("identity_paths", []):
                require(
                    _at_pointer(base, path) != _at_pointer(changed, path),
                    f"{mutation['id']}: identity collision at {path}",
                )
        else:
            require(changed["kind"] == "FRejection", f"{mutation['id']}: expected typed rejection")
    tuple_document = copy.deepcopy(corpus["base_inputs"]["observe-no-effect"])
    tuple_document["accepted_event"]["payload"]["observation"]["ordered_steps"] = ("capture", "verify")
    tuple_result = step_f(tuple_document["snapshot"], tuple_document["accepted_event"])
    require(tuple_result["kind"] == "FRejection", "nested tuple escaped typed rejection boundary")
    require(tuple_result["code"] == "CANONICALIZATION_VIOLATION", "nested tuple rejection code")
    require(
        tuple_result["path"] == "/accepted_event/payload/observation/ordered_steps",
        "nested tuple rejection path",
    )
    return {
        "m1_success_cases": len(corpus["success_cases"]),
        "m1_success_input_schema_checks": len(corpus["success_cases"]),
        "m1_rejection_cases": len(corpus["rejection_cases"]),
        "m1_equivalence_pairs": len(corpus["equivalence_pairs"]),
        "m1_sensitivity_mutations": len(corpus["sensitivity_mutations"]),
        "m1_non_json_boundary_rejections": 1,
    }


def validate_alias_boundaries() -> dict[str, int]:
    corpus = load_json("fixtures/m1/cases.json")

    success = copy.deepcopy(corpus["base_inputs"]["observe-with-effect"])
    shared_steps = ["capture", "verify"]
    success["accepted_event"]["payload"]["observation"]["alias_a"] = shared_steps
    success["accepted_event"]["payload"]["observation"]["alias_b"] = shared_steps
    shared_versions = success["snapshot"]["versions"]
    success["accepted_event"]["versions"] = shared_versions
    success_result = step_f(success["snapshot"], success["accepted_event"])
    require(success_result["kind"] == "FTransition", "success alias fixture rejected")
    _run_with_write_detection(success, success_result, "success-alias")

    rejection = copy.deepcopy(corpus["base_inputs"]["observe-with-effect"])
    shared_payload = {"canary": ["a", "b"]}
    rejection["accepted_event"]["payload"]["effect_request"]["action"]["alias"] = shared_payload
    rejection["accepted_event"]["payload"]["effect_request"]["destination"]["alias"] = shared_payload
    rejection["accepted_event"]["versions"]["workflow"] = "flrh-workflow/9"
    rejection_result = step_f(rejection["snapshot"], rejection["accepted_event"])
    require(rejection_result["kind"] == "FRejection", "late-rejection alias fixture did not reject")
    _run_with_write_detection(rejection, rejection_result, "rejection-alias")
    return {"m1_alias_boundary_cases": 2, "m1_input_mutation_attempts": 0}


def validate_replay_sequences(*, check_goldens: bool = True) -> dict[str, int]:
    corpus = load_json("fixtures/m1/cases.json")
    step_count = 0
    for sequence in corpus["replay_sequences"]:
        snapshot, events = materialize_replay_sequence(corpus, sequence)
        digests = []
        for event in events:
            document = {"snapshot": snapshot, "accepted_event": event}
            result = step_f(snapshot, event)
            require(result["kind"] == "FTransition", f"{sequence['id']}: replay rejected")
            expected = _independent_expected_transition(document)
            require(
                M0.canonical_bytes(result) == M0.canonical_bytes(expected),
                f"{sequence['id']}: replay step differs from independent oracle",
            )
            _run_with_write_detection(document, result, f"{sequence['id']}:replay-step-{step_count}")
            require(result["transition_digest"] == _independent_transition_digest(result), f"{sequence['id']}: digest")
            digests.append(result["transition_digest"])
            snapshot = result["next_snapshot"]
            step_count += 1
        if check_goldens:
            require(digests == sequence["expected_transition_digests"], f"{sequence['id']}: replay golden drift {digests}")
        require(snapshot["revision"] == sequence["expected_final_revision"], f"{sequence['id']}: final revision")
    return {"m1_replay_sequences": len(corpus["replay_sequences"]), "m1_replay_steps": step_count}


def _clean_env(home: Path, *, seed: str, timezone: str, poison: str) -> dict[str, str]:
    environment = {
        "HOME": str(home),
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": os.defpath,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": seed,
        "TZ": timezone,
        "FLRH_AMBIENT_POISON": poison,
    }
    if "SystemRoot" in os.environ:
        environment["SystemRoot"] = os.environ["SystemRoot"]
    return environment


def _spawn(command: list[str], cwd: Path, environment: Mapping[str, str]) -> bytes:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise AssertionError(f"clean child timed out: {command}") from error
    require(completed.returncode == 0, f"clean replay failed ({completed.returncode}): {completed.stderr!r}")
    require(completed.stderr == b"", f"clean replay wrote stderr: {completed.stderr!r}")
    require(completed.stdout.endswith(b"\n") and completed.stdout.count(b"\n") == 1, "replay emitted multiple results")
    return completed.stdout


def _parse_canonical_stdout(raw: bytes, label: str) -> Any:
    require(raw.endswith(b"\n") and raw.count(b"\n") == 1, f"{label}: expected one output line")
    body = raw[:-1]
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AssertionError(f"{label}: invalid JSON output") from error
    require(M0.canonical_bytes(parsed) == body, f"{label}: stdout is not independent canonical bytes")
    return parsed


def validate_clean_process_replay() -> dict[str, int]:
    corpus = load_json("fixtures/m1/cases.json")
    registry = _registry()
    cases = [case for group in ("success_cases", "rejection_cases") for case in corpus[group]]
    sequence_ids = [sequence["id"] for sequence in corpus["replay_sequences"]]
    comparisons = 0
    with tempfile.TemporaryDirectory(prefix="flrh-m1-a-") as directory_a, tempfile.TemporaryDirectory(
        prefix="flrh-m1-b-"
    ) as directory_b:
        root_a = Path(directory_a)
        root_b = Path(directory_b)
        home_a = root_a / "home"
        home_b = root_b / "home"
        home_a.mkdir()
        home_b.mkdir()
        env_a = _clean_env(home_a, seed="11", timezone="UTC", poison="profile-a")
        env_b = _clean_env(home_b, seed="97", timezone="Pacific/Honolulu", poison="profile-b")
        runner = str(ROOT / "scripts/run_m1_replay.py")
        for case in cases:
            case_id = case["id"]
            left = _spawn([sys.executable, "-B", runner, "--case", case_id], root_a, env_a)
            right = _spawn(
                [sys.executable, "-B", runner, "--case", case_id, "--reverse-objects"], root_b, env_b
            )
            require(left == right, f"clean-process byte mismatch: {case_id}")
            left_result = _parse_canonical_stdout(left, f"{case_id}:process-a")
            right_result = _parse_canonical_stdout(right, f"{case_id}:process-b")
            expected_document = materialize_case(corpus, case)
            if case in corpus["success_cases"]:
                expected = _independent_expected_transition(expected_document)
                _validate_ref(left_result, M1_URI + "#/$defs/FTransition", registry)
            else:
                expected = _independent_expected_rejection(expected_document, case)
                _validate_ref(left_result, M1_URI + "#/$defs/FRejection", registry)
            require(
                M0.canonical_bytes(left_result) == M0.canonical_bytes(expected),
                f"{case_id}: spawned output differs from independent expectation",
            )
            require(
                M0.canonical_bytes(right_result) == M0.canonical_bytes(expected),
                f"{case_id}: reversed-object output differs from expectation",
            )
            comparisons += 1
        for sequence_id in sequence_ids:
            left = _spawn([sys.executable, "-B", runner, "--sequence", sequence_id], root_a, env_a)
            right = _spawn(
                [sys.executable, "-B", runner, "--sequence", sequence_id, "--reverse-objects"],
                root_b,
                env_b,
            )
            require(left == right, f"clean-process sequence mismatch: {sequence_id}")
            left_result = _parse_canonical_stdout(left, f"{sequence_id}:process-a")
            right_result = _parse_canonical_stdout(right, f"{sequence_id}:process-b")
            sequence = next(item for item in corpus["replay_sequences"] if item["id"] == sequence_id)
            snapshot, events = materialize_replay_sequence(corpus, sequence)
            expected_transitions = []
            for event in events:
                transition = _independent_expected_transition(
                    {"snapshot": snapshot, "accepted_event": event}
                )
                expected_transitions.append(transition)
                snapshot = transition["next_snapshot"]
            expected = {
                "kind": "M1ReplayResult",
                "sequence_id": sequence_id,
                "transitions": expected_transitions,
                "final_snapshot": snapshot,
            }
            require(
                M0.canonical_bytes(left_result) == M0.canonical_bytes(expected),
                f"{sequence_id}: spawned sequence differs from independent oracle",
            )
            require(
                M0.canonical_bytes(right_result) == M0.canonical_bytes(expected),
                f"{sequence_id}: reversed sequence differs from independent oracle",
            )
            comparisons += 1
    return {
        "m1_clean_process_comparisons": comparisons,
        "m1_clean_process_runs": comparisons * 2,
        "m1_byte_mismatches": 0,
    }


def validate_ambient_authority() -> dict[str, int]:
    expected = {
        "ambient_categories": [
            "clock",
            "randomness",
            "uuid",
            "environment",
            "filesystem",
            "network",
            "subprocess",
            "model_or_tool",
        ],
        "explicit_guard_self_tests": 8,
        "audit_guard_self_tests": 3,
        "guard_self_tests": 11,
        "import_metadata_checks": 10,
        "import_attempts": 0,
        "kernel_ambient_attempts": 0,
        "kernel_input_mutation_attempts": 0,
        "mutants_detected": 8,
    }
    checker = str(ROOT / "scripts/check_m1_ambient.py")
    with tempfile.TemporaryDirectory(prefix="flrh-m1-guard-a-") as directory_a, tempfile.TemporaryDirectory(
        prefix="flrh-m1-guard-b-"
    ) as directory_b:
        root_a = Path(directory_a)
        root_b = Path(directory_b)
        home_a = root_a / "home"
        home_b = root_b / "home"
        home_a.mkdir()
        home_b.mkdir()
        left = _spawn(
            [sys.executable, "-B", checker],
            root_a,
            _clean_env(home_a, seed="23", timezone="UTC", poison="guard-a"),
        )
        right = _spawn(
            [sys.executable, "-B", checker],
            root_b,
            _clean_env(home_b, seed="71", timezone="Asia/Seoul", poison="guard-b"),
        )
    require(left == right, "ambient guard report differs across fresh processes")
    left_report = _parse_canonical_stdout(left, "ambient-guard-a")
    right_report = _parse_canonical_stdout(right, "ambient-guard-b")
    require(left_report == expected and right_report == expected, "ambient guard admission report drift")
    return {
        "m1_ambient_guard_processes": 2,
        "m1_ambient_guard_categories": len(expected["ambient_categories"]),
        "m1_explicit_guard_self_tests": expected["explicit_guard_self_tests"],
        "m1_audit_guard_self_tests": expected["audit_guard_self_tests"],
        "m1_guard_self_tests": expected["guard_self_tests"],
        "m1_import_metadata_checks": expected["import_metadata_checks"],
        "m1_control_mutants_detected": expected["mutants_detected"],
        "m1_kernel_ambient_attempts": 0,
    }


def show_digests() -> dict[str, Any]:
    corpus = load_json("fixtures/m1/cases.json")
    success = {}
    for case in corpus["success_cases"]:
        document = materialize_case(corpus, case)
        result = step_f(document["snapshot"], document["accepted_event"])
        success[case["id"]] = result["transition_digest"]
    replay = {}
    for sequence in corpus["replay_sequences"]:
        snapshot, events = materialize_replay_sequence(corpus, sequence)
        digests = []
        for event in events:
            result = step_f(snapshot, event)
            digests.append(result["transition_digest"])
            snapshot = result["next_snapshot"]
        replay[sequence["id"]] = digests
    return {"success": success, "replay": replay}


def validate_all() -> dict[str, int]:
    summary: dict[str, int] = {}
    for check in (
        validate_schemas_and_manifest,
        validate_static_authority_surface,
        validate_canonical_oracle,
        validate_result_goldens,
        validate_cases,
        validate_alias_boundaries,
        validate_replay_sequences,
        validate_clean_process_replay,
        validate_ambient_authority,
    ):
        summary.update(check())
    return summary


def main(argv: list[str]) -> int:
    if argv == ["--show-digests"]:
        print(json.dumps(show_digests(), ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    if argv:
        print("usage: validate_m1.py [--show-digests]", file=sys.stderr)
        return 2
    try:
        summary = validate_all()
    except (AssertionError, CanonicalizationError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"M1 FAIL: {error}", file=sys.stderr)
        return 1
    print("M1 PASS " + json.dumps(summary, sort_keys=True, separators=(",", ":")))
    print(
        "BOUNDARY measured Python reference-F mechanics and frozen corpus only; universal purity, "
        "L/R/H integration, production readiness, comparative efficacy, and Lakatos progress remain unjudged"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
