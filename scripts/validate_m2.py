#!/usr/bin/env python3
"""Non-normative conformance runner for the bounded M2 stratified-L slice."""

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

from flrh_logic import solve_l  # noqa: E402
from flrh_logic.canonical import (  # noqa: E402
    CanonicalizationError,
    canonical_bytes as logic_canonical_bytes,
    canonical_digest as logic_canonical_digest,
)
from m1_guard import AttemptedMutation, write_tracking_copy  # noqa: E402
from m2_fixtures import (  # noqa: E402
    canonical_bytes as fixture_canonical_bytes,
    digest as fixture_digest,
    load_cases,
    materialize_case,
    materialize_delta_input,
    materialize_rule_bundle,
    materialize_sequence_step,
)
from m2_oracle import expected_success  # noqa: E402


M0_SPEC = importlib.util.spec_from_file_location(
    "m2_independent_m0_oracle", ROOT / "scripts/validate_m0.py"
)
if M0_SPEC is None or M0_SPEC.loader is None:
    raise RuntimeError("cannot load independent M0 canonical oracle")
M0 = importlib.util.module_from_spec(M0_SPEC)
M0_SPEC.loader.exec_module(M0)

PROTOCOL_URI = (
    "https://github.com/gj3447/agent-coding-paradigm/"
    "spec/schema/protocol.v1.schema.json"
)
M2_URI = (
    "https://github.com/gj3447/agent-coding-paradigm/"
    "spec/schema/m2-logic.v1.schema.json"
)
SCHEMA_PATHS = (
    "spec/schema/m2-logic.v1.schema.json",
    "spec/schema/m2-logic-contract.v1.schema.json",
    "spec/schema/m2-fixtures.v1.schema.json",
    "spec/schema/m2-manifest.v1.schema.json",
)
REQUIRED_INHERITED_DEPENDENCIES = (
    "spec/schema/protocol.v1.schema.json",
    "spec/canonicalization.v1.json",
    "spec/logic-semantics.v0.json",
    "spec/schema/m1-kernel.v1.schema.json",
)
REQUIRED_FIXTURE_DEPENDENCIES = (
    "fixtures/m1/golden/observe-with-effect.transition.json",
)
MEASURED_STATUS = "MEASURED_REFERENCE_CONFORMANCE"
ALLOWED_IMPLEMENTATION_IMPORTS = {
    "__future__",
    "dataclasses",
    "hashlib",
    "json",
    "re",
    "typing",
    "unicodedata",
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
FORBIDDEN_OUTPUT_KINDS = {
    "ActionReceipt",
    "EffectIntent",
    "EligibilityVerdict",
    "StableProposalBatch",
}
FORBIDDEN_OUTPUT_FIELDS = {
    "approval_digest",
    "approval_required",
    "assessed_risk",
    "authority_digest",
    "batch_id",
    "capability",
    "effect_intent",
    "eligibility_verdict",
    "frontier",
    "idempotency_key",
    "receipt",
    "stable_proposal_batch",
}


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
        {"$ref": ref}, registry=registry, format_checker=FormatChecker()
    )
    errors = sorted(
        validator.iter_errors(instance),
        key=lambda error: tuple(str(part) for part in error.path),
    )
    if errors:
        error = errors[0]
        location = "/" + "/".join(str(part) for part in error.absolute_path)
        raise AssertionError(f"schema rejection at {location}: {error.message}")


def _raw_wire_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=False
    ).encode("utf-8")


def _walk(value: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield key, child
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _check_no_r_h_authority(value: Mapping[str, Any]) -> None:
    def scan(item: Any) -> None:
        if isinstance(item, list):
            for child in item:
                scan(child)
            return
        if not isinstance(item, dict):
            return
        item_kind = item.get("kind")
        for key, child in item.items():
            # Atoms/FactDelta tuples and caller provenance are contract-declared
            # opaque application data.  Authority-shaped names in those zones
            # are inert and must not be misclassified as kernel authority.
            if key in {"atom", "tuple"}:
                continue
            if key == "provenance_delta" and item_kind == "LBaseSupport":
                continue
            require(key not in FORBIDDEN_OUTPUT_FIELDS, f"M2 emitted R/H-owned field {key}")
            if key == "kind" and isinstance(child, str):
                require(
                    child not in FORBIDDEN_OUTPUT_KINDS,
                    f"M2 emitted R/H-owned kind {child}",
                )
            scan(child)

    scan(value)


def _expected_rejection(
    case: Mapping[str, Any], bundle: Mapping[str, Any], logical_time: int
) -> dict[str, Any]:
    return {
        "kind": "LRejection",
        "schema_version": "flrh-l-result/1",
        "contract_version": "flrh-l-kernel/1",
        "code": case["expected_code"],
        "path": case["expected_path"],
        "logical_time": logical_time,
        "rule_bundle_digest": (
            bundle.get("rule_bundle_digest")
            if case["expected_rule_bundle_digest"] == "supplied"
            else None
        ),
        "context": copy.deepcopy(case["expected_context"]),
    }


def _semantic_projection(result: Mapping[str, Any]) -> dict[str, Any]:
    projected = copy.deepcopy(dict(result))
    projected.pop("fixpoint_digest", None)
    if "stats" in projected:
        projected["stats"] = {
            "evaluation_mode": projected["stats"]["evaluation_mode"]
        }
    return projected


def _independent_fixpoint_digest(result: Mapping[str, Any]) -> str:
    projection = copy.deepcopy(dict(result))
    projection.pop("fixpoint_digest", None)
    return M0.canonical_digest(
        {
            "kind": "M2FixpointPreimage",
            "contract_version": "flrh-l-kernel/1",
            "fixpoint_result_without_fixpoint_digest": projection,
        }
    )


def _validate_nested_fact_deltas(result: Mapping[str, Any], registry: Registry) -> int:
    checked = 0
    for wrapper in result.get("derived_fact_deltas", []):
        _validate_ref(wrapper, M2_URI + "#/$defs/LFactDeltaInput", registry)
        _validate_ref(wrapper["delta"], PROTOCOL_URI + "#/$defs/FactDelta", registry)
        checked += 1
    return checked


def _run_with_write_detection(
    prior: Mapping[str, Any] | None,
    bundle: Mapping[str, Any],
    deltas: list[Mapping[str, Any]],
    logical_time: int,
    expected: Mapping[str, Any],
    label: str,
) -> None:
    attempts: list[object] = []
    document = {
        "prior_materialization": copy.deepcopy(prior),
        "rule_bundle": copy.deepcopy(bundle),
        "fact_delta_inputs": copy.deepcopy(deltas),
        "logical_time": logical_time,
    }
    guarded = write_tracking_copy(document, attempts)
    before = _raw_wire_bytes(guarded)
    try:
        actual = solve_l(
            guarded["prior_materialization"],
            guarded["rule_bundle"],
            guarded["fact_delta_inputs"],
            guarded["logical_time"],
        )
    except AttemptedMutation as error:
        raise AssertionError(f"{label}: attempted caller-input mutation") from error
    require(not attempts, f"{label}: attempted caller-input mutation: {attempts}")
    require(before == _raw_wire_bytes(guarded), f"{label}: caller-input bytes changed")
    require(
        M0.canonical_bytes(actual) == M0.canonical_bytes(expected),
        f"{label}: guarded result changed",
    )


def validate_schemas_and_manifest(*, require_measured: bool = True) -> dict[str, int]:
    registry = _registry()
    for path in SCHEMA_PATHS:
        Draft202012Validator.check_schema(load_json(path))
    bindings = (
        ("spec/m2-logic-contract.v1.json", "spec/schema/m2-logic-contract.v1.schema.json"),
        ("spec/m2-manifest.v1.json", "spec/schema/m2-manifest.v1.schema.json"),
        ("fixtures/m2/cases.json", "spec/schema/m2-fixtures.v1.schema.json"),
    )
    for artifact_path, schema_path in bindings:
        Draft202012Validator(
            load_json(schema_path), registry=registry, format_checker=FormatChecker()
        ).validate(load_json(artifact_path))

    manifest = load_json("spec/m2-manifest.v1.json")
    contract = load_json("spec/m2-logic-contract.v1.json")
    require(manifest["status"] == contract["status"], "M2 manifest/contract status drift")
    if require_measured:
        require(
            manifest["status"] == MEASURED_STATUS,
            f"M2 aggregate cannot report measured conformance at status {manifest['status']}",
        )
    observed = tuple(
        dependency["artifact"] for dependency in manifest["inherited_normative_dependencies"]
    )
    require(
        observed == REQUIRED_INHERITED_DEPENDENCIES,
        f"M2 inherited dependency set/order drift: {observed}",
    )
    observed_fixtures = tuple(
        dependency["artifact"] for dependency in manifest["inherited_fixture_dependencies"]
    )
    require(
        observed_fixtures == REQUIRED_FIXTURE_DEPENDENCIES,
        f"M2 inherited fixture dependency set/order drift: {observed_fixtures}",
    )
    dependencies = (
        manifest["inherited_normative_dependencies"]
        + manifest["inherited_fixture_dependencies"]
    )
    for dependency in dependencies:
        target = ROOT / dependency["artifact"]
        require(target.is_file(), f"M2 inherited dependency missing: {dependency['artifact']}")
        actual = "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest()
        require(
            actual == dependency["sha256"],
            f"M2 inherited dependency digest drift: {dependency['artifact']}: {actual}",
        )
    declared = (
        manifest["normative_contracts"]
        + [item["artifact"] for item in dependencies]
        + manifest["self_validating_schemas"]
        + [manifest["conformance_fixture"]]
        + manifest["golden_outputs"]
        + manifest["reference_implementation"]
        + manifest["non_normative_tools"]
    )
    missing = [path for path in declared if not (ROOT / path).is_file()]
    require(not missing, f"M2 manifest references missing files: {missing}")
    return {
        "m2_schemas": len(SCHEMA_PATHS),
        "m2_bindings": len(bindings),
        "m2_inherited_dependencies": len(dependencies),
    }


def validate_static_authority_surface() -> dict[str, int]:
    manifest = load_json("spec/m2-manifest.v1.json")
    declared = set(manifest["reference_implementation"])
    observed = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "src/flrh_logic").rglob("*.py")
    }
    require(
        observed == declared,
        f"M2 implementation manifest drift: observed={sorted(observed)} declared={sorted(declared)}",
    )
    imports: set[str] = set()
    relative_modules: set[str] = set()
    dynamic_calls: list[str] = []
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
        imports <= ALLOWED_IMPLEMENTATION_IMPORTS,
        f"M2 implementation import allowlist drift: {sorted(imports)}",
    )
    require(
        not imports & FORBIDDEN_IMPLEMENTATION_IMPORTS,
        f"M2 forbidden implementation imports: {sorted(imports & FORBIDDEN_IMPLEMENTATION_IMPORTS)}",
    )
    require(
        relative_modules <= {"canonical", "logic"},
        f"M2 unmanifested relative modules: {sorted(relative_modules)}",
    )
    require(not dynamic_calls, f"M2 forbidden dynamic calls: {dynamic_calls}")

    import flrh_logic

    require(flrh_logic.__all__ == ["solve_l"], "M2 public root API drift")
    return {
        "m2_implementation_files": len(declared),
        "m2_static_imports": len(imports),
        "m2_dynamic_authority_calls": 0,
        "m2_public_root_exports": len(flrh_logic.__all__),
    }


def validate_canonical_oracle() -> dict[str, int]:
    corpus = load_cases()
    values = [
        corpus["atoms"]["a"],
        {"z": [3, 2, 1], "a": {"한글": "값"}},
        materialize_rule_bundle(corpus, "two_supports"),
    ]
    for index, value in enumerate(values):
        require(
            logic_canonical_bytes(value) == fixture_canonical_bytes(value),
            f"M2 canonical bytes disagree with independent oracle at case {index}",
        )
        require(
            logic_canonical_digest(value) == fixture_digest(value),
            f"M2 canonical digest disagrees with independent oracle at case {index}",
        )
    rejected = [
        {"float": 1.5},
        {"non_nfc": "e\u0301"},
        {"e\u0301": "non_nfc_object_key"},
        {"surrogate": "\ud800"},
        {"too_large": 2**63},
        (1, 2),
    ]
    for index, value in enumerate(rejected):
        implementation_rejected = False
        oracle_rejected = False
        try:
            logic_canonical_bytes(value)
        except CanonicalizationError:
            implementation_rejected = True
        try:
            fixture_canonical_bytes(value)
        except ValueError:
            oracle_rejected = True
        require(
            implementation_rejected and oracle_rejected,
            f"M2 canonical rejection disagreement at case {index}",
        )
    unicode_bundle = materialize_rule_bundle(corpus, "empty")
    unicode_atom = {"predicate": "probe", "한글": "값"}
    unicode_bundle["query_atoms"] = [unicode_atom]
    unicode_bundle["rule_bundle_digest"] = fixture_digest(
        {
            "kind": "M2RuleBundlePreimage",
            "contract_version": "flrh-l-kernel/1",
            "profile_id": "flrh-l-ground-stratified/1",
            "rule_set_version": unicode_bundle["rule_set_version"],
            "dataflow_version": unicode_bundle["dataflow_version"],
            "canonicalization_version": "flrh-cjson/1",
            "limits": unicode_bundle["limits"],
            "ordered_query_atoms": [unicode_atom],
            "ordered_rules": [],
        }
    )
    unicode_result = solve_l(None, unicode_bundle, [], 0)
    require(unicode_result["kind"] == "LFixpointResult", "M2 rejected NFC Unicode atom key")
    require(
        unicode_result["next_materialization"]["fact_states"][0]["atom"] == unicode_atom,
        "M2 changed Unicode atom key",
    )
    return {
        "m2_canonical_equal": len(values),
        "m2_canonical_reject": len(rejected),
        "m2_unicode_application_key_cases": 1,
    }


def validate_deterministic_rejection_boundaries() -> dict[str, int]:
    """Exercise fixed input ceilings and normalized malformed-input precedence."""

    corpus = load_cases()
    registry = _registry()
    empty_bundle = materialize_rule_bundle(corpus, "empty")
    delta = materialize_delta_input(corpus, "a_positive", 1)
    boundary = solve_l(None, empty_bundle, [delta] * 10_000, 1)
    require(boundary["kind"] == "LFixpointResult", "10,000 inputs must be admitted")
    require(len(boundary["input_delta_digests"]) == 1, "duplicate boundary did not collapse")
    require(
        len(boundary["next_materialization"]["base_supports"]) == 1,
        "duplicate boundary produced multiplicity",
    )
    over = solve_l(None, empty_bundle, [delta] * 10_001, 1)
    require(
        over
        == {
            "kind": "LRejection",
            "schema_version": "flrh-l-result/1",
            "contract_version": "flrh-l-kernel/1",
            "code": "MALFORMED_FACT_DELTA_INPUT",
            "path": "/fact_delta_inputs",
            "logical_time": 1,
            "rule_bundle_digest": empty_bundle["rule_bundle_digest"],
            "context": {"limit": 10_000, "observed": 10_001},
        },
        "10,001-input rejection does not bind the declared ceiling",
    )
    _validate_ref(over, M2_URI + "#/$defs/LRejection", registry)
    preempted = solve_l(
        {"kind": "malformed-prior-must-not-be-parsed"},
        empty_bundle,
        [delta] * 10_001,
        1,
    )
    require(
        M0.canonical_bytes(preempted) == M0.canonical_bytes(over),
        "input ceiling did not precede prior parsing/evaluation",
    )

    pairs: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []
    bundle = materialize_rule_bundle(corpus, "one_firing_exact")
    bad_kind = copy.deepcopy(bundle["rules"][0])
    bad_kind["kind"] = "NotLRule"
    bad_stratum = copy.deepcopy(bundle["rules"][0])
    bad_stratum["stratum"] = "not-an-integer"
    left = copy.deepcopy(bundle)
    right = copy.deepcopy(bundle)
    left["rules"] = [bad_kind, bad_stratum]
    right["rules"] = [bad_stratum, bad_kind]
    pairs.append(("malformed-rule-order", solve_l(None, left, [], 1), solve_l(None, right, [], 1)))

    bad_rule_float = copy.deepcopy(bundle["rules"][0])
    bad_rule_float["head"]["atom"]["invalid"] = 1.0
    bad_rule_nfc = copy.deepcopy(bundle["rules"][0])
    bad_rule_nfc["head"]["atom"]["invalid"] = "e\u0301"
    left = copy.deepcopy(bundle)
    right = copy.deepcopy(bundle)
    left["rules"] = [bad_rule_float, bad_rule_nfc]
    right["rules"] = [bad_rule_nfc, bad_rule_float]
    pairs.append(
        (
            "canonical-invalid-rule-order",
            solve_l(None, left, [], 1),
            solve_l(None, right, [], 1),
        )
    )

    def invalid_literal(value: Any) -> dict[str, Any]:
        literal = copy.deepcopy(bundle["rules"][0]["required_body"][0])
        literal["atom"] = {"x": value}
        return literal

    invalid_float = invalid_literal(1.0)
    invalid_surrogate = invalid_literal("\ud800")
    invalid_nfc = invalid_literal("e\u0301")
    cross_level_results = []
    for first_body in (
        [invalid_float, invalid_surrogate],
        [invalid_surrogate, invalid_float],
    ):
        rule_a = copy.deepcopy(bundle["rules"][0])
        rule_a["required_body"] = copy.deepcopy(first_body)
        rule_b = copy.deepcopy(bundle["rules"][0])
        rule_b["required_body"] = [copy.deepcopy(invalid_nfc)]
        changed = copy.deepcopy(bundle)
        changed["rules"] = [rule_a, rule_b]
        cross_level_results.append(solve_l(None, changed, [], 1))
    pairs.append(
        (
            "cross-level-rule-body-order",
            cross_level_results[0],
            cross_level_results[1],
        )
    )

    bad_literal_kind = copy.deepcopy(bundle["rules"][0]["required_body"][0])
    bad_literal_kind["kind"] = "NotLLiteral"
    bad_literal_polarity = copy.deepcopy(bundle["rules"][0]["required_body"][0])
    bad_literal_polarity["polarity"] = "not-a-polarity"
    left = copy.deepcopy(bundle)
    right = copy.deepcopy(bundle)
    left["rules"][0]["required_body"] = [bad_literal_kind, bad_literal_polarity]
    right["rules"][0]["required_body"] = [bad_literal_polarity, bad_literal_kind]
    pairs.append(("malformed-body-order", solve_l(None, left, [], 1), solve_l(None, right, [], 1)))

    left = materialize_rule_bundle(corpus, "empty")
    right = materialize_rule_bundle(corpus, "empty")
    left["query_atoms"] = [{"a": 1.0, "b": 2.0}]
    right["query_atoms"] = [{"b": 2.0, "a": 1.0}]
    pairs.append(("mapping-insertion-order", solve_l(None, left, [], 1), solve_l(None, right, [], 1)))

    bad_input_float = materialize_delta_input(corpus, "a_positive", 1)
    bad_input_float["delta"]["tuple"]["invalid"] = 1.0
    bad_input_nfc = materialize_delta_input(corpus, "a_positive", 1)
    bad_input_nfc["delta"]["tuple"]["invalid"] = "e\u0301"
    pairs.append(
        (
            "canonical-invalid-input-order",
            solve_l(None, empty_bundle, [bad_input_float, bad_input_nfc], 1),
            solve_l(None, empty_bundle, [bad_input_nfc, bad_input_float], 1),
        )
    )

    prior = boundary["next_materialization"]
    bad_support_kind = copy.deepcopy(prior["base_supports"][0])
    bad_support_kind["kind"] = "NotLBaseSupport"
    bad_support_id = copy.deepcopy(prior["base_supports"][0])
    bad_support_id["derivation_id"] = "not a valid id"
    left_prior = copy.deepcopy(prior)
    right_prior = copy.deepcopy(prior)
    left_prior["base_supports"] = [bad_support_kind, bad_support_id]
    right_prior["base_supports"] = [bad_support_id, bad_support_kind]
    pairs.append(
        (
            "malformed-support-order",
            solve_l(left_prior, empty_bundle, [], 2),
            solve_l(right_prior, empty_bundle, [], 2),
        )
    )

    derived_case = next(
        item
        for item in corpus["success_cases"]
        if item["id"] == "two-supports-and-downstream"
    )
    derived_bundle, derived_deltas = materialize_case(corpus, derived_case)
    derived_prior = solve_l(None, derived_bundle, derived_deltas, 1)[
        "next_materialization"
    ]
    left_prior = copy.deepcopy(derived_prior)
    right_prior = copy.deepcopy(derived_prior)
    left_prior["derived_supports"][0]["premise_literal_keys"] = [1.0, "e\u0301"]
    right_prior["derived_supports"][0]["premise_literal_keys"] = ["e\u0301", 1.0]
    pairs.append(
        (
            "malformed-nested-support-order",
            solve_l(left_prior, derived_bundle, [], 2),
            solve_l(right_prior, derived_bundle, [], 2),
        )
    )
    for label, left_result, right_result in pairs:
        require(left_result["kind"] == "LRejection", f"{label}: left did not reject")
        require(right_result["kind"] == "LRejection", f"{label}: right did not reject")
        require(
            M0.canonical_bytes(left_result) == M0.canonical_bytes(right_result),
            f"{label}: typed rejection depends on caller order",
        )
        _validate_ref(left_result, M2_URI + "#/$defs/LRejection", registry)

    invalid_key_bundle = materialize_rule_bundle(corpus, "empty")
    invalid_key_bundle["query_atoms"] = [{"e\u0301": "opaque"}]
    invalid_key_result = solve_l(None, invalid_key_bundle, [], 1)
    require(
        invalid_key_result["code"] == "CANONICALIZATION_VIOLATION"
        and invalid_key_result["path"] == "/rule_bundle/query_atoms/0"
        and invalid_key_result["context"] == {"invariant": "NON_NFC_OBJECT_KEY"},
        "non-NFC object key did not produce a closed canonical rejection",
    )
    M0.canonical_bytes(invalid_key_result)
    _validate_ref(invalid_key_result, M2_URI + "#/$defs/LRejection", registry)
    return {
        "m2_input_ceiling_boundary_checks": 3,
        "m2_rejection_order_pairs": len(pairs),
        "m2_canonical_typed_rejection_checks": 1,
    }


def _check_success(
    prior: Mapping[str, Any] | None,
    bundle: Mapping[str, Any],
    deltas: list[Mapping[str, Any]],
    logical_time: int,
    result: Mapping[str, Any],
    registry: Registry,
    label: str,
) -> int:
    _validate_ref(result, M2_URI + "#/$defs/LFixpointResult", registry)
    require(result["kind"] == "LFixpointResult", f"{label}: expected success")
    oracle = expected_success(prior, bundle, deltas, logical_time)
    require(
        M0.canonical_bytes(_semantic_projection(result))
        == M0.canonical_bytes(_semantic_projection(oracle)),
        f"{label}: semantic result differs from independent clean oracle",
    )
    require(
        result["fixpoint_digest"] == _independent_fixpoint_digest(result),
        f"{label}: fixpoint digest is not independently reproducible",
    )
    require(
        result["input_delta_digests"]
        == sorted(result["input_delta_digests"], key=M0.canonical_bytes),
        f"{label}: input digest order",
    )
    materialization = result["next_materialization"]
    for field in (
        "base_supports",
        "derived_supports",
        "fact_states",
        "conflicts",
        "stratum_digests",
    ):
        require(
            materialization[field] == sorted(materialization[field], key=M0.canonical_bytes),
            f"{label}: materialization {field} order",
        )
    require(
        result["derived_fact_deltas"]
        == sorted(result["derived_fact_deltas"], key=M0.canonical_bytes),
        f"{label}: derived delta order",
    )
    require(
        materialization["materialization_digest"]
        == M0.canonical_digest(
            {
                "kind": "M2MaterializationPreimage",
                "contract_version": "flrh-l-kernel/1",
                "materialization_without_materialization_digest": {
                    key: copy.deepcopy(value)
                    for key, value in materialization.items()
                    if key != "materialization_digest"
                },
            }
        ),
        f"{label}: materialization digest",
    )
    _check_no_r_h_authority(result)
    _run_with_write_detection(prior, bundle, deltas, logical_time, result, label)
    return _validate_nested_fact_deltas(result, registry)


def validate_cases() -> dict[str, int]:
    registry = _registry()
    corpus = load_cases()
    delta_checks = 0
    for case in corpus["success_cases"]:
        bundle, deltas = materialize_case(corpus, case)
        _validate_ref(bundle, M2_URI + "#/$defs/LRuleBundle", registry)
        for delta in deltas:
            _validate_ref(delta, M2_URI + "#/$defs/LFactDeltaInput", registry)
            _validate_ref(delta["delta"], PROTOCOL_URI + "#/$defs/FactDelta", registry)
        document = {
            "prior_materialization": None,
            "rule_bundle": bundle,
            "fact_delta_inputs": deltas,
            "logical_time": 1,
        }
        before = copy.deepcopy(document)
        before_bytes = _raw_wire_bytes(document)
        result = solve_l(None, bundle, deltas, 1)
        require(document == before, f"{case['id']}: input mutated")
        require(_raw_wire_bytes(document) == before_bytes, f"{case['id']}: input bytes changed")
        delta_checks += _check_success(None, bundle, deltas, 1, result, registry, case["id"])
    for case in corpus["rejection_cases"]:
        bundle, deltas = materialize_case(corpus, case)
        before = copy.deepcopy((bundle, deltas))
        before_bytes = _raw_wire_bytes((bundle, deltas))
        result = solve_l(None, bundle, deltas, 1)
        require((bundle, deltas) == before, f"{case['id']}: rejection mutated input")
        require(
            _raw_wire_bytes((bundle, deltas)) == before_bytes,
            f"{case['id']}: rejection input bytes changed",
        )
        _validate_ref(result, M2_URI + "#/$defs/LRejection", registry)
        expected = _expected_rejection(case, bundle, 1)
        require(
            M0.canonical_bytes(result) == M0.canonical_bytes(expected),
            f"{case['id']}: full rejection differs from independent fixture oracle",
        )
        _check_no_r_h_authority(result)
        _run_with_write_detection(None, bundle, deltas, 1, result, case["id"])
    for pair in corpus["equivalence_pairs"]:
        bundle, deltas = materialize_case(corpus, pair)
        changed_bundle, changed_deltas = materialize_case(
            corpus,
            pair,
            reverse_rules=pair["reverse_rules"],
            reverse_deltas=pair["reverse_deltas"],
        )
        left = solve_l(None, bundle, deltas, 1)
        right = solve_l(None, changed_bundle, changed_deltas, 1)
        require(
            M0.canonical_bytes(left) == M0.canonical_bytes(right),
            f"M2 equivalence pair differs: {pair['id']}",
        )
    return {
        "m2_success_cases": len(corpus["success_cases"]),
        "m2_rejection_cases": len(corpus["rejection_cases"]),
        "m2_equivalence_pairs": len(corpus["equivalence_pairs"]),
        "m2_nested_fact_delta_checks": delta_checks,
    }


def validate_sequences() -> dict[str, int]:
    registry = _registry()
    corpus = load_cases()
    steps = 0
    delta_checks = 0
    for sequence in corpus["sequences"]:
        prior = None
        oracle_prior = None
        saw_terminal_rejection = False
        for index in range(len(sequence["steps"])):
            logical_time = index + 1
            bundle, deltas = materialize_sequence_step(
                corpus, sequence, index, logical_time
            )
            result = solve_l(prior, bundle, deltas, logical_time)
            if result["kind"] == "LRejection":
                require(index == len(sequence["steps"]) - 1, f"{sequence['id']}: early reject")
                descriptor = sequence.get("expected_terminal_rejection")
                require(descriptor is not None, f"{sequence['id']}: undeclared rejection")
                expected = _expected_rejection(descriptor, bundle, logical_time)
                require(
                    M0.canonical_bytes(result) == M0.canonical_bytes(expected),
                    f"{sequence['id']}: full terminal rejection differs from fixture oracle",
                )
                _validate_ref(result, M2_URI + "#/$defs/LRejection", registry)
                _check_no_r_h_authority(result)
                _run_with_write_detection(
                    prior,
                    bundle,
                    deltas,
                    logical_time,
                    result,
                    f"{sequence['id']}:{index}:terminal-rejection",
                )
                saw_terminal_rejection = True
                steps += 1
                continue
            delta_checks += _check_success(
                prior,
                bundle,
                deltas,
                logical_time,
                result,
                registry,
                f"{sequence['id']}:{index}",
            )
            oracle_result = expected_success(
                oracle_prior, bundle, deltas, logical_time
            )
            require(
                M0.canonical_bytes(_semantic_projection(result))
                == M0.canonical_bytes(_semantic_projection(oracle_result)),
                f"{sequence['id']}:{index}: implementation != independent full recomputation",
            )
            prior = result["next_materialization"]
            oracle_prior = oracle_result["next_materialization"]
            steps += 1
        require(
            saw_terminal_rejection
            == (sequence.get("expected_terminal_rejection") is not None),
            f"{sequence['id']}: terminal rejection declaration/result mismatch",
        )
    return {
        "m2_sequences": len(corpus["sequences"]),
        "m2_sequence_steps": steps,
        "m2_sequence_derived_delta_checks": delta_checks,
    }


def _golden_cases() -> tuple[tuple[str, str, str], ...]:
    return (
        (
            "two-support-retain-then-remove",
            "fixtures/m2/golden/two-support-retraction.fixpoint.json",
            "LFixpointResult",
        ),
        (
            "negative-cycle",
            "fixtures/m2/golden/negative-cycle.rejection.json",
            "LRejection",
        ),
    )


def validate_result_goldens() -> dict[str, int]:
    registry = _registry()
    corpus = load_cases()
    for fixture_id, relative, kind in _golden_cases():
        raw = (ROOT / relative).read_bytes()
        require(raw.endswith(b"\n") and raw.count(b"\n") == 1, f"{fixture_id}: one-line golden")
        body = raw[:-1]
        parsed = json.loads(body.decode("utf-8"))
        require(parsed["kind"] == kind, f"{fixture_id}: golden kind drift")
        require(M0.canonical_bytes(parsed) == body, f"{fixture_id}: golden not canonical")
        _validate_ref(parsed, M2_URI + f"#/$defs/{kind}", registry)
        if kind == "LRejection":
            case = next(item for item in corpus["rejection_cases"] if item["id"] == fixture_id)
            bundle, deltas = materialize_case(corpus, case)
            expected = _expected_rejection(case, bundle, 1)
            actual = solve_l(None, bundle, deltas, 1)
        else:
            sequence = next(item for item in corpus["sequences"] if item["id"] == fixture_id)
            prior = None
            oracle_prior = None
            # Freeze the first-retraction boundary: one of two independent
            # supports is removed while the downstream closure remains true.
            for index in range(2):
                bundle, deltas = materialize_sequence_step(corpus, sequence, index, index + 1)
                actual = solve_l(prior, bundle, deltas, index + 1)
                expected = expected_success(oracle_prior, bundle, deltas, index + 1)
                require(actual["kind"] == "LFixpointResult", f"{fixture_id}: sequence rejected")
                prior = actual["next_materialization"]
                oracle_prior = expected["next_materialization"]
        require(M0.canonical_bytes(actual) == body, f"{fixture_id}: implementation/golden drift")
        require(
            M0.canonical_bytes(_semantic_projection(expected))
            == M0.canonical_bytes(_semantic_projection(parsed)),
            f"{fixture_id}: independent semantic oracle/golden drift",
        )
        require(logic_canonical_bytes(actual) == body, f"{fixture_id}: serializer/golden drift")
    return {"m2_exact_result_goldens": len(_golden_cases())}


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


def _spawn(
    command: list[str], cwd: Path, environment: Mapping[str, str], stdin: bytes = b""
) -> bytes:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=dict(environment),
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise AssertionError(f"M2 clean child timed out: {command}") from error
    require(
        completed.returncode == 0,
        f"M2 clean child failed ({completed.returncode}): {completed.stderr!r}",
    )
    require(completed.stderr == b"", f"M2 clean child wrote stderr: {completed.stderr!r}")
    require(
        completed.stdout.endswith(b"\n") and completed.stdout.count(b"\n") == 1,
        "M2 clean child emitted multiple results",
    )
    return completed.stdout


def _parse_canonical_stdout(raw: bytes, label: str) -> Any:
    body = raw[:-1]
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AssertionError(f"{label}: invalid JSON output") from error
    require(M0.canonical_bytes(parsed) == body, f"{label}: stdout not independently canonical")
    return parsed


def validate_clean_process_replay() -> dict[str, int]:
    corpus = load_cases()
    cases = [case for group in ("success_cases", "rejection_cases") for case in corpus[group]]
    comparisons = 0
    with tempfile.TemporaryDirectory(prefix="flrh-m2-a-") as directory_a, tempfile.TemporaryDirectory(
        prefix="flrh-m2-b-"
    ) as directory_b:
        root_a = Path(directory_a)
        root_b = Path(directory_b)
        home_a = root_a / "home"
        home_b = root_b / "home"
        home_a.mkdir()
        home_b.mkdir()
        env_a = _clean_env(home_a, seed="13", timezone="UTC", poison="m2-a")
        env_b = _clean_env(home_b, seed="89", timezone="Pacific/Honolulu", poison="m2-b")
        runner = str(ROOT / "scripts/run_m2_replay.py")
        for case in cases:
            bundle, deltas = materialize_case(corpus, case)
            document = {
                "prior_materialization": None,
                "rule_bundle": bundle,
                "fact_delta_inputs": deltas,
                "logical_time": 1,
            }
            payload = M0.canonical_bytes(document)
            left = _spawn([sys.executable, "-B", runner], root_a, env_a, payload)
            right = _spawn([sys.executable, "-B", runner], root_b, env_b, payload)
            require(left == right, f"M2 clean-process byte mismatch: {case['id']}")
            parsed = _parse_canonical_stdout(left, case["id"])
            if case in corpus["success_cases"]:
                expected = expected_success(None, bundle, deltas, 1)
                require(
                    M0.canonical_bytes(_semantic_projection(parsed))
                    == M0.canonical_bytes(_semantic_projection(expected)),
                    f"{case['id']}: child differs from independent oracle",
                )
            else:
                expected = _expected_rejection(case, bundle, 1)
                require(
                    M0.canonical_bytes(parsed) == M0.canonical_bytes(expected),
                    f"{case['id']}: child rejection differs from oracle",
                )
            comparisons += 1
        for sequence in corpus["sequences"]:
            prior_left = None
            prior_right = None
            oracle_prior = None
            for index in range(len(sequence["steps"])):
                bundle, deltas = materialize_sequence_step(corpus, sequence, index, index + 1)
                left_doc = {
                    "prior_materialization": prior_left,
                    "rule_bundle": bundle,
                    "fact_delta_inputs": deltas,
                    "logical_time": index + 1,
                }
                right_doc = copy.deepcopy(left_doc)
                right_doc["prior_materialization"] = prior_right
                left = _spawn(
                    [sys.executable, "-B", runner], root_a, env_a, M0.canonical_bytes(left_doc)
                )
                right = _spawn(
                    [sys.executable, "-B", runner], root_b, env_b, M0.canonical_bytes(right_doc)
                )
                require(left == right, f"M2 sequence child mismatch: {sequence['id']}:{index}")
                left_result = _parse_canonical_stdout(left, f"{sequence['id']}:{index}:a")
                right_result = _parse_canonical_stdout(right, f"{sequence['id']}:{index}:b")
                require(left_result == right_result, f"{sequence['id']}:{index}: parsed mismatch")
                if left_result["kind"] == "LFixpointResult":
                    expected = expected_success(oracle_prior, bundle, deltas, index + 1)
                    require(
                        M0.canonical_bytes(_semantic_projection(left_result))
                        == M0.canonical_bytes(_semantic_projection(expected)),
                        f"{sequence['id']}:{index}: child sequence oracle mismatch",
                    )
                    prior_left = left_result["next_materialization"]
                    prior_right = right_result["next_materialization"]
                    oracle_prior = expected["next_materialization"]
                else:
                    descriptor = sequence.get("expected_terminal_rejection")
                    require(
                        descriptor is not None and index == len(sequence["steps"]) - 1,
                        f"{sequence['id']}:{index}: undeclared child rejection",
                    )
                    expected = _expected_rejection(descriptor, bundle, index + 1)
                    require(
                        M0.canonical_bytes(left_result) == M0.canonical_bytes(expected),
                        f"{sequence['id']}:{index}: full child rejection oracle mismatch",
                    )
                comparisons += 1
    return {
        "m2_clean_process_comparisons": comparisons,
        "m2_clean_process_runs": comparisons * 2,
        "m2_byte_mismatches": 0,
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
        "audit_guard_self_tests": 3,
        "explicit_guard_self_tests": 8,
        "guard_self_tests": 11,
        "import_attempts": 0,
        "import_metadata_checks": 10,
        "kernel_path_executions": 4,
        "kernel_path_successes": 3,
        "kernel_path_rejections": 1,
        "kernel_path_ambient_attempts": 0,
        "kernel_path_input_mutation_attempts": 0,
        "kernel_ambient_attempts": 0,
        "kernel_input_mutation_attempts": 0,
        "mutants_detected": 13,
    }
    checker = str(ROOT / "scripts/check_m2_ambient.py")
    with tempfile.TemporaryDirectory(prefix="flrh-m2-guard-a-") as directory_a, tempfile.TemporaryDirectory(
        prefix="flrh-m2-guard-b-"
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
            _clean_env(home_a, seed="29", timezone="UTC", poison="m2-guard-a"),
        )
        right = _spawn(
            [sys.executable, "-B", checker],
            root_b,
            _clean_env(home_b, seed="73", timezone="Asia/Seoul", poison="m2-guard-b"),
        )
    require(left == right, "M2 ambient report differs across processes")
    left_report = _parse_canonical_stdout(left, "m2-ambient-a")
    right_report = _parse_canonical_stdout(right, "m2-ambient-b")
    require(left_report == expected and right_report == expected, "M2 ambient report drift")
    return {
        "m2_ambient_guard_processes": 2,
        "m2_ambient_guard_categories": len(expected["ambient_categories"]),
        "m2_guard_self_tests": expected["guard_self_tests"],
        "m2_import_metadata_checks": expected["import_metadata_checks"],
        "m2_control_mutants_detected": expected["mutants_detected"],
        "m2_kernel_ambient_attempts": 0,
        "m2_kernel_path_executions": expected["kernel_path_executions"],
        "m2_kernel_path_successes": expected["kernel_path_successes"],
        "m2_kernel_path_rejections": expected["kernel_path_rejections"],
        "m2_kernel_path_ambient_attempts": expected[
            "kernel_path_ambient_attempts"
        ],
        "m2_kernel_path_input_mutation_attempts": expected[
            "kernel_path_input_mutation_attempts"
        ],
    }


def validate_m2(*, require_measured: bool = True) -> dict[str, int]:
    summary: dict[str, int] = {}
    checks = (
        lambda: validate_schemas_and_manifest(require_measured=require_measured),
        validate_static_authority_surface,
        validate_canonical_oracle,
        validate_deterministic_rejection_boundaries,
        validate_result_goldens,
        validate_cases,
        validate_sequences,
        validate_clean_process_replay,
        validate_ambient_authority,
    )
    for check in checks:
        summary.update(check())
    return summary


def show_digests() -> dict[str, Any]:
    corpus = load_cases()
    successes = {}
    for case in corpus["success_cases"]:
        bundle, deltas = materialize_case(corpus, case)
        result = solve_l(None, bundle, deltas, 1)
        successes[case["id"]] = result.get("fixpoint_digest")
    sequences = {}
    for sequence in corpus["sequences"]:
        prior = None
        values = []
        for index in range(len(sequence["steps"])):
            bundle, deltas = materialize_sequence_step(corpus, sequence, index, index + 1)
            result = solve_l(prior, bundle, deltas, index + 1)
            values.append(result.get("fixpoint_digest"))
            if result["kind"] == "LFixpointResult":
                prior = result["next_materialization"]
        sequences[sequence["id"]] = values
    return {"success": successes, "sequences": sequences}


def main() -> int:
    if "--show-digests" in sys.argv:
        print(json.dumps(show_digests(), indent=2, sort_keys=True))
        return 0
    summary = validate_m2()
    print("M2 PASS " + json.dumps(summary, sort_keys=True, separators=(",", ":")))
    print(
        "BOUNDARY measured: "
        f"{summary['m2_success_cases']} success, "
        f"{summary['m2_rejection_cases']} rejection, "
        f"{summary['m2_sequences']} sequences/"
        f"{summary['m2_sequence_steps']} steps, "
        f"{summary['m2_clean_process_runs']} clean runs/"
        f"{summary['m2_clean_process_comparisons']} comparisons, "
        f"{summary['m2_guard_self_tests']} guard self-tests, "
        f"{summary['m2_control_mutants_detected']} mutants"
    )
    print("BOUNDARY not established: general Datalog/negation, R/H, durability, engine, efficacy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
