#!/usr/bin/env python3
"""Non-normative conformance runner for the normative FLR-H M0 contracts.

The JSON contracts, truth tables, and state machines are normative. This Python
program is deliberately small and replaceable; passing it is checker-relative
M0 conformance evidence, not a global consistency proof, runtime result, or
comparative-efficacy result.
"""

from __future__ import annotations

import hashlib
import json
import sys
import unicodedata
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1
SET_LIKE_PATHS_BY_KIND = {
    "EffectProposal": {"/preconditions"},
    "EligibilityVerdict": {"/support_derivation_ids"},
    "StableProposalBatch": {"/proposal_ids", "/eligibility_verdict_ids"},
    "EffectIntent": {"/preconditions"},
    "GraphEnvelope": {"/provenance_refs"},
    "GraphDelta": {"/causal_parent_delta_ids"},
    "ActionReceipt": {"/output_digests"},
}


def load_json(relative: str) -> Any:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _pointer_child(path: str, key: str) -> str:
    escaped = key.replace("~", "~0").replace("/", "~1")
    return f"{path}/{escaped}"


def _canonical_value(value: Any, path: str, set_like_paths: set[str]) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        require(INT64_MIN <= value <= INT64_MAX, "integer is outside signed int64")
        return value
    if isinstance(value, float):
        raise AssertionError("floating-point values are outside flrh-cjson/1")
    if isinstance(value, str):
        require(unicodedata.normalize("NFC", value) == value, "string is not Unicode NFC")
        return value
    if isinstance(value, list):
        items = [_canonical_value(item, f"{path}/{index}", set_like_paths) for index, item in enumerate(value)]
        if path in set_like_paths:
            encoded = [
                json.dumps(item, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
                for item in items
            ]
            require(len(encoded) == len(set(encoded)), f"duplicate set-like element at {path}")
            return [item for _, item in sorted(zip(encoded, items), key=lambda pair: pair[0])]
        return items
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            require(isinstance(key, str), "object key is not a string")
            require(key.isascii(), "normative object key is not ASCII")
            require(unicodedata.normalize("NFC", key) == key, "object key is not Unicode NFC")
            require(key not in normalized, "duplicate object key after normalization")
            normalized[key] = _canonical_value(item, _pointer_child(path, key), set_like_paths)
        return {key: normalized[key] for key in sorted(normalized)}
    raise AssertionError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_bytes(value: Any) -> bytes:
    root_kind = value.get("kind") if isinstance(value, dict) else None
    set_like_paths = SET_LIKE_PATHS_BY_KIND.get(root_kind, set())
    normalized = _canonical_value(value, "", set_like_paths)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def _error_messages(error: Any) -> Iterable[str]:
    yield error.message
    for child in error.context:
        yield from _error_messages(child)


def validate_schemas_and_fixtures() -> dict[str, int]:
    manifest = load_json("spec/m0-manifest.v1.json")
    schema_paths = manifest["self_validating_schemas"]
    schemas = {path: load_json(path) for path in schema_paths}
    for path, schema in schemas.items():
        Draft202012Validator.check_schema(schema)
        require(schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema", f"{path}: wrong draft")

    checker = FormatChecker()
    for binding in manifest["schema_bindings"] + manifest["fixture_schema_bindings"]:
        validator = Draft202012Validator(schemas[binding["schema"]], format_checker=checker)
        errors = list(validator.iter_errors(load_json(binding["artifact"])))
        require(not errors, f"{binding['artifact']} invalid: {errors[0].message if errors else ''}")

    protocol_path = "spec/schema/protocol.v1.schema.json"
    protocol_schema = schemas[protocol_path]
    protocol = Draft202012Validator(protocol_schema, format_checker=checker)
    claim_doc = load_json("spec/claims.v1.json")
    claim_ids = [claim["id"] for claim in claim_doc["claims"]]
    require(len(claim_ids) == len(set(claim_ids)), "claim ledger contains duplicate ids")
    engine_decision = load_json("spec/engine-decision.v1.json")
    promotion_gates = engine_decision["promotion_gates"]
    expected_gate_ids = {
        "two-consumers-three-cycles",
        "deterministic-incremental-equivalence",
        "operational-durability-requirement",
        "m0-m5-mechanics-and-crash",
        "preregistered-operational-limits",
        "policy-outside-core",
        "separate-modules-comparator",
    }
    require({gate["id"] for gate in promotion_gates} == expected_gate_ids, "engine promotion gate set drift")
    require(all(gate["status"] in {"OPEN", "BLOCKED"} for gate in promotion_gates), "unearned engine gate verdict")
    require(all(not gate["evidence"] for gate in promotion_gates), "engine gate evidence is not yet admissible at M0")
    for gate_id in {"preregistered-operational-limits", "separate-modules-comparator"}:
        gate = next(item for item in promotion_gates if item["id"] == gate_id)
        require(gate["status"] == "BLOCKED" and gate["prerequisites"], f"{gate_id} lacks a blocking prerequisite")

    valid_cases = load_json("fixtures/m0/valid/protocol-objects.json")["cases"]
    for case in valid_cases:
        errors = list(protocol.iter_errors(case["instance"]))
        require(not errors, f"valid fixture {case['id']} rejected: {errors[0].message if errors else ''}")
    valid_by_kind = {case["instance"]["kind"]: case["instance"] for case in valid_cases}
    intent = valid_by_kind["EffectIntent"]
    receipt = valid_by_kind["ActionReceipt"]
    receipt_binding_fields = {
        "intent_id", "action_digest", "cause_id", "correlation_id", "capability", "authority_digest",
        "destination_digest", "goal_id", "obligation_id", "adapter_version", "assessed_risk",
        "approval_required", "approval_digest", "idempotency_key",
    }
    require(
        all(receipt[field] == intent[field] for field in receipt_binding_fields),
        "ActionReceipt does not preserve the committed EffectIntent authority/approval identity",
    )

    invalid_cases = load_json("fixtures/m0/invalid/protocol-mutations.json")["cases"]
    for case in invalid_cases:
        kind = case["instance"].get("kind")
        require(kind in protocol_schema["$defs"], f"invalid fixture {case['id']} has unknown kind {kind!r}")
        branch_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": f"#/$defs/{kind}",
            "$defs": protocol_schema["$defs"],
        }
        errors = list(Draft202012Validator(branch_schema, format_checker=checker).iter_errors(case["instance"]))
        require(errors, f"invalid fixture {case['id']} was accepted")
        require(len(errors) == 1, f"invalid fixture {case['id']} mutates more than one top-level invariant: {len(errors)} errors")
        messages = "\n".join(message for error in errors for message in _error_messages(error))
        require(
            case["expected_keyword"] in messages,
            f"invalid fixture {case['id']} failed for an unexpected reason; wanted {case['expected_keyword']!r}",
        )

    return {"schemas": len(schema_paths), "valid_protocol": len(valid_cases), "invalid_protocol": len(invalid_cases)}


def evidence_state(positive: int, negative: int) -> str:
    require(positive >= 0 and negative >= 0, "support counts must be non-negative")
    if positive and negative:
        return "BOTH"
    if positive:
        return "TRUE_ONLY"
    if negative:
        return "FALSE_ONLY"
    return "NEITHER"


def validate_logic() -> dict[str, int]:
    semantics = load_json("spec/logic-semantics.v0.json")
    fixtures = load_json("fixtures/m0/logic/cases.json")

    semantic_truth = {
        (item["positive_support_present"], item["negative_support_present"]): item["state"]
        for item in semantics["truth_states"]
    }
    require(len(semantic_truth) == 4, "truth table does not cover four evidence states")
    for case in fixtures["truth_state_cases"]:
        actual = evidence_state(case["positive"], case["negative"])
        require(actual == case["expected"], f"truth-state fixture mismatch: {case}")
        key = (bool(case["positive"]), bool(case["negative"]))
        require(semantic_truth[key] == actual, f"normative truth table mismatch: {case}")

    semantic_default = {
        item["state"]: item["succeeds"] for item in semantics["default_negation"]["truth_table"]
    }
    require(set(semantic_default) == {"NEITHER", "TRUE_ONLY", "FALSE_ONLY", "BOTH"}, "default-negation table incomplete")
    for case in fixtures["default_negation_cases"]:
        require(semantic_default[case["state"]] is case["expected"], f"default-negation mismatch: {case}")

    for case in fixtures["retraction_cases"]:
        supports: dict[str, str] = {}
        for support in case["initial_supports"]:
            identity = support["derivation_id"]
            polarity = support["polarity"]
            require(polarity in {"positive", "negative"}, f"bad polarity in {case['id']}")
            require(identity not in supports, f"duplicate derivation identity in {case['id']}")
            supports[identity] = polarity
        for identity in case["remove"]:
            require(identity in supports, f"unknown retraction target {identity} in {case['id']}")
            del supports[identity]
        actual = evidence_state(
            sum(value == "positive" for value in supports.values()),
            sum(value == "negative" for value in supports.values()),
        )
        require(actual == case["expected_state"], f"retraction state mismatch in {case['id']}")
        require(sorted(supports) == case["expected_remaining"], f"retraction identity mismatch in {case['id']}")

    for case in fixtures["retraction_conflict_cases"]:
        supports: dict[str, str] = {}
        actual = "OK"
        for support in case["initial_supports"]:
            identity = support["derivation_id"]
            polarity = support["polarity"]
            if identity in supports and supports[identity] != polarity:
                actual = "DERIVATION_IDENTITY_CONFLICT"
                break
            supports[identity] = polarity
        if actual == "OK":
            for identity in case["remove"]:
                if identity not in supports:
                    actual = "UNKNOWN_DERIVATION"
                    break
                del supports[identity]
        require(actual == case["expected"], f"retraction conflict mismatch in {case['id']}: {actual}")

    for case in fixtures["derivation_identity_cases"]:
        if case["left_id"] != case["right_id"]:
            actual = "DISTINCT"
        elif case["left_digest"] == case["right_digest"]:
            actual = "IDEMPOTENT_DUPLICATE"
        else:
            actual = "DERIVATION_IDENTITY_CONFLICT"
        require(actual == case["expected"], f"derivation identity mismatch in {case['id']}: {actual}")

    for case in fixtures["effect_identity_cases"]:
        if case["left_key"] != case["right_key"]:
            actual = "DISTINCT"
        elif case["left_digest"] == case["right_digest"]:
            actual = "IDEMPOTENT_DUPLICATE"
        else:
            actual = "IDEMPOTENCY_CONFLICT"
        require(actual == case["expected"], f"effect identity mismatch in {case['id']}: {actual}")

    for case in fixtures["stratification_cases"]:
        valid = all(
            edge["polarity"] != "negative" or edge["from_stratum"] > edge["to_stratum"]
            for edge in case["dependencies"]
        )
        actual = "ACCEPT" if valid else "OUTSIDE_V0_NEGATIVE_RECURSION"
        require(actual == case["expected"], f"stratification mismatch in {case['id']}")

    for case in fixtures["frontier_cases"]:
        require((case["low_watermark"] > case["epoch"]) is case["publish"], f"frontier mismatch: {case}")

    return {
        "truth": len(fixtures["truth_state_cases"]),
        "default_negation": len(fixtures["default_negation_cases"]),
        "retraction": len(fixtures["retraction_cases"]),
        "retraction_conflicts": len(fixtures["retraction_conflict_cases"]),
        "derivation_identity": len(fixtures["derivation_identity_cases"]),
        "effect_identity": len(fixtures["effect_identity_cases"]),
        "stratification": len(fixtures["stratification_cases"]),
        "frontier": len(fixtures["frontier_cases"]),
    }


def validate_canonicalization() -> dict[str, int]:
    profile = load_json("spec/canonicalization.v1.json")
    require(profile["algorithm"] == "flrh-cjson" and profile["algorithm_version"] == "1", "wrong canonical profile")
    declared = {kind: set(paths) for kind, paths in profile["set_like_paths_by_kind"].items()}
    require(declared == SET_LIKE_PATHS_BY_KIND, "canonical set-like path map drift")
    cases = load_json("fixtures/m0/canonical/cases.json")
    for case in cases["equal_pairs"]:
        left = canonical_digest(case["left"])
        right = canonical_digest(case["right"])
        require(left == right, f"canonical equivalent pair differs: {case['id']}")
        require(left == case["expected_digest"], f"canonical golden digest drift: {case['id']} got {left}")
    for case in cases["different_pairs"]:
        require(canonical_digest(case["left"]) != canonical_digest(case["right"]), f"canonical mutation collapsed: {case['id']}")
    for case in cases["reject_cases"]:
        try:
            canonical_bytes(case["input"])
        except AssertionError as error:
            require(case["expected"] in str(error), f"canonical rejection reason drift: {case['id']}: {error}")
        else:
            raise AssertionError(f"canonical reject fixture accepted: {case['id']}")
    return {
        "canonical_equal": len(cases["equal_pairs"]),
        "canonical_different": len(cases["different_pairs"]),
        "canonical_reject": len(cases["reject_cases"]),
    }


def _run_trace(
    spec: dict[str, Any], machine: dict[str, Any], case: dict[str, Any]
) -> tuple[set[str], set[str], bool, set[str], set[str], set[str]]:
    selected: set[str] = set()
    false_guards: set[str] = set()
    invalid_exercised = False
    reached: set[str] = {machine["initial"]}
    interrupts_exercised: set[str] = set()
    deferred_interrupts_exercised: set[str] = set()
    state = machine["initial"]
    policy = machine["invalid_event_policy"]
    event_validator = Draft202012Validator(spec["event_schema"])
    interrupts = {item["event"]: item for item in spec["global_interrupts"]}
    final_states = {item["id"] for item in machine["states"] if item["kind"] == "final"}
    for index, step in enumerate(case["steps"]):
        event = step["event"]
        event_errors = list(event_validator.iter_errors(event))
        schema_valid = not event_errors
        event_type = event.get("type")
        authority = (event.get("actor_role"), event.get("capability"))
        allowed = {
            (item["actor_role"], item["capability"])
            for item in spec["event_authority"].get(event_type, [])
        }
        authority_valid = authority in allowed
        if not schema_valid or not authority_valid:
            invalid_exercised = True
            effects = [policy["effect"]]
            require(state == step["expected_state"], f"{case['id']} step {index}: rejected event changed state")
            require(effects == step["expected_effects"], f"{case['id']} step {index}: effects {effects} != {step['expected_effects']}")
            continue

        if event_type in interrupts and state not in final_states:
            interrupt = interrupts[event_type]
            interrupts_exercised.add(event_type)
            if state in interrupt["deferred_in_states"]:
                deferred_interrupts_exercised.add(event_type)
                effects = [interrupt["deferred_effect"]]
            else:
                state = interrupt["to"]
                reached.add(state)
                effects = ["PersistControlTransition"]
            require(state == step["expected_state"], f"{case['id']} step {index}: state {state} != {step['expected_state']}")
            require(effects == step["expected_effects"], f"{case['id']} step {index}: effects {effects} != {step['expected_effects']}")
            continue

        choices = [
            transition
            for transition in machine["transitions"]
            if transition["from"] == state and transition["event"] == event_type
        ]
        choices.sort(key=lambda transition: transition.get("priority", 0))
        for transition in choices:
            guard = transition.get("guard")
            if guard and step["guard_results"].get(guard) is False:
                false_guards.add(guard)
        enabled = [
            transition
            for transition in choices
            if not transition.get("guard") or step["guard_results"].get(transition["guard"]) is True
        ]
        if enabled:
            transition = enabled[0]
            selected.add(transition["id"])
            state = transition["to"]
            effects = transition.get("effects", [])
            reached.add(state)
        else:
            invalid_exercised = invalid_exercised or not choices
            mode = policy["guard_false"] if choices else policy["mode"]
            effects = [policy["effect"]] if mode == "reject-and-audit" else []
        require(state == step["expected_state"], f"{case['id']} step {index}: state {state} != {step['expected_state']}")
        require(effects == step["expected_effects"], f"{case['id']} step {index}: effects {effects} != {step['expected_effects']}")
    return selected, false_guards, invalid_exercised, reached, interrupts_exercised, deferred_interrupts_exercised


def validate_fsm() -> dict[str, int]:
    spec = load_json("spec/run-fsm.v1.json")
    traces = load_json("spec/run-fsm-traces.v1.json")
    require(spec["schema_version"] == "flrh-run-fsm/v1", "wrong FSM schema version")
    require(spec["authority"] == "sole-authoritative-outer-control-fsm", "FSM authority is not singular")
    Draft202012Validator.check_schema(spec["event_schema"])
    require(len(spec["machines"]) == 1, "M0 expects one generic control machine")
    machine = spec["machines"][0]
    states = {state["id"]: state["kind"] for state in machine["states"]}
    require(len(states) == len(machine["states"]), "duplicate FSM states")
    require(machine["initial"] in states, "unknown FSM initial state")
    terminal = {state for state, kind in states.items() if kind == "final"}
    categories = {
        state["outcome_category"]
        for state in machine["states"]
        if state["kind"] == "final"
    }
    required_categories = {
        "success", "permanent_failure", "retry_exhausted", "budget_exhausted", "timeout",
        "canceled", "pathology", "saturated", "unknown_external_outcome",
    }
    require(categories == required_categories, "FSM terminal categories drift")
    require(set(machine["events"]) == set(spec["event_authority"]), "event authority matrix is incomplete")
    for event, authorities in spec["event_authority"].items():
        pairs = [(item["actor_role"], item["capability"]) for item in authorities]
        require(pairs and len(pairs) == len(set(pairs)), f"bad authority set for {event}")
        require(all("model" not in actor and "untrusted" not in actor for actor, _ in pairs), f"untrusted authority for {event}")
    transition_ids = {transition["id"] for transition in machine["transitions"]}
    require(len(transition_ids) == len(machine["transitions"]), "duplicate FSM transition ids")
    graph: dict[str, set[str]] = defaultdict(set)
    for transition in machine["transitions"]:
        require(transition["from"] in states and transition["to"] in states, f"bad FSM transition {transition['id']}")
        require(transition["from"] not in terminal, f"terminal state has outgoing transition: {transition['from']}")
        require(transition["event"] in machine["events"], f"undeclared event in {transition['id']}")
        require(all(effect in spec["effects"] for effect in transition.get("effects", [])), f"unknown effect in {transition['id']}")
        if "guard" in transition:
            require(transition["guard"] in spec["guards"], f"unknown guard in {transition['id']}")
        graph[transition["from"]].add(transition["to"])

    reachable = {machine["initial"]}
    queue = deque(reachable)
    while queue:
        for target in graph.get(queue.popleft(), set()):
            if target not in reachable:
                reachable.add(target)
                queue.append(target)
    require(reachable == set(states), f"unreachable FSM states: {sorted(set(states) - reachable)}")
    incoming_success = [transition for transition in machine["transitions"] if transition["to"] == "SUCCEEDED"]
    require(
        len(incoming_success) == 1
        and incoming_success[0]["from"] == "VERIFY_COMPLETION"
        and incoming_success[0].get("guard") == "completion_closed"
        and {"independent_closure_receipt", "empty_unknown_effect_ledger"} <= set(incoming_success[0]["evidence_required"]),
        "SUCCEEDED is not isolated behind independent completion verification",
    )
    require(
        set(spec["guards"]["completion_closed"]["reads"]) == {"independent_receipt_closed", "no_unknown_effects"},
        "completion guard omits independent closure or unknown-effect exclusion",
    )
    incoming_execute = [transition for transition in machine["transitions"] if transition["to"] == "EXECUTE"]
    require(
        incoming_execute
        and all(item["from"] == "COMMIT_INTENT" and item.get("guard") == "intent_durable" for item in incoming_execute),
        "EXECUTE is reachable without committed intent",
    )
    require(states.get("EFFECT_OUTCOME_UNKNOWN") == "final", "unknown effect outcome is not a typed terminal")
    require(
        any(item["event"] == "ABANDON" and item["to"] == "EFFECT_OUTCOME_UNKNOWN" for item in machine["transitions"]),
        "abandoned unknown outcome does not terminate as unknown",
    )
    confirmed = [item for item in machine["transitions"] if item["event"] in {"EFFECT_RESULT_CONFIRMED", "HUMAN_RECEIPT_CONFIRMED"}]
    require(confirmed and all(item["to"] == "HONOR_PENDING_INTERRUPT" for item in confirmed), "confirmed effect bypasses interrupt reconciliation")
    resume = [item for item in machine["transitions"] if item["from"] == "HONOR_PENDING_INTERRUPT" and item["event"] == "NO_PENDING_INTERRUPT"]
    require(len(resume) == 1 and resume[0]["to"] == "INGEST", "confirmed receipt does not re-enter INGEST")

    interrupts = {item["event"]: item for item in spec["global_interrupts"]}
    require(set(interrupts) == {"CANCEL", "TIMEOUT", "BUDGET_EXHAUSTED"}, "global interrupts are incomplete")
    critical = {"COMMIT_INTENT", "EXECUTE", "RECONCILE", "HUMAN_RECONCILIATION", "HONOR_PENDING_INTERRUPT"}
    for interrupt in interrupts.values():
        require(set(interrupt["deferred_in_states"]) == critical, f"{interrupt['event']}: critical-state deferral drift")
        require(states.get(interrupt["to"]) == "final", f"{interrupt['event']}: safe interrupt is not terminal")
        for source in set(states) - terminal - critical:
            graph[source].add(interrupt["to"])

    selected: set[str] = set()
    false_guards: set[str] = set()
    invalid = False
    reached: set[str] = set()
    interrupts_exercised: set[str] = set()
    deferred_interrupts_exercised: set[str] = set()
    for case in traces["cases"]:
        require(case["machine"] == machine["id"], f"unknown trace machine in {case['id']}")
        case_selected, case_false, case_invalid, case_reached, case_interrupts, case_deferred = _run_trace(spec, machine, case)
        selected.update(case_selected)
        false_guards.update(case_false)
        invalid = invalid or case_invalid
        reached.update(case_reached)
        interrupts_exercised.update(case_interrupts)
        deferred_interrupts_exercised.update(case_deferred)
    require(selected == transition_ids, f"uncovered FSM transitions: {sorted(transition_ids - selected)}")
    require(false_guards == set(spec["guards"]), f"guards without false branch: {sorted(set(spec['guards']) - false_guards)}")
    require(invalid, "invalid-event policy was not exercised")
    require(terminal <= reached, f"terminal paths not exercised: {sorted(terminal - reached)}")
    require(interrupts_exercised == set(interrupts), "global interrupt event not exercised")
    require(deferred_interrupts_exercised == set(interrupts), "deferred interrupt event not exercised")
    return {
        "fsm_transitions": len(transition_ids),
        "fsm_traces": len(traces["cases"]),
        "fsm_terminals": len(terminal),
        "fsm_interrupts": len(interrupts),
    }


def validate_loop() -> dict[str, int]:
    spec = load_json("spec/loop-contract.v1.json")
    fsm = load_json("spec/run-fsm.v1.json")
    require(spec["schema_version"] == "loop-contract/v1", "wrong loop schema version")
    require(spec["tier"] == "L_RT", "M0 loop must declare L_RT")
    require("commander_dispatch" not in spec, "generic FLR-H loop must not import SYMPOSIUM commander dispatch")
    binding = spec["control_fsm_binding"]
    require(binding["artifact"] == "spec/run-fsm.v1.json", "loop profile binds an unexpected FSM")
    fsm_bytes = (ROOT / binding["artifact"]).read_bytes()
    require(binding["file_sha256"] == "sha256:" + hashlib.sha256(fsm_bytes).hexdigest(), "loop/FSM digest binding drift")
    require(binding["authority"] == fsm["authority"], "loop/FSM authority drift")
    machine = next((item for item in fsm["machines"] if item["id"] == binding["machine_id"]), None)
    require(machine is not None, "loop profile binds an unknown machine")
    states = {item["id"] for item in machine["states"]}
    terminal_categories = {item["outcome_category"] for item in machine["states"] if item["kind"] == "final"}
    require(set(binding["required_terminal_categories"]) == terminal_categories, "loop/FSM terminal-category drift")
    safety_ids = {item["id"] for item in fsm["safety_properties"]}
    require(set(binding["required_safety_properties"]) <= safety_ids, "loop/FSM safety-property drift")
    transitions = machine["transitions"]

    high_risk = {name: value for name, value in spec["action_types"].items() if value["effect_class"] == "high_risk_external"}
    require(high_risk, "no high-risk effect path is declared")
    for name, action in high_risk.items():
        require(action["approval_required"] is True, f"{name}: approval is not mandatory")
        roles = {
            action["approval_state"], action["authorization_state"], action["execution_state"],
            action["reconciliation_state"], action["unknown_outcome_state"], action["post_reconciliation_state"],
            action["abandon_terminal"], action["confirmed_resume_state"],
        }
        require(roles <= states, f"{name}: effect path names an unknown state")
        require(any(item["from"] == action["approval_state"] and item["event"] == "APPROVAL_GRANTED" and item["to"] == action["authorization_state"] for item in transitions), f"{name}: missing approval path")
        require(any(item["from"] == action["authorization_state"] and item["event"] == "INTENT_COMMITTED" and item["to"] == action["execution_state"] for item in transitions), f"{name}: missing intent-before-execute path")
        require(any(item["from"] == action["execution_state"] and item["event"] == "ATTEMPT_RECORDED" and item["to"] == action["reconciliation_state"] for item in transitions), f"{name}: execution bypasses reconciliation")
        require(any(item["from"] == action["reconciliation_state"] and item["event"] == "OUTCOME_UNKNOWN" and item["to"] == action["unknown_outcome_state"] for item in transitions), f"{name}: missing unknown-outcome route")
        require(any(item["from"] == action["unknown_outcome_state"] and item["event"] == "ABANDON" and item["to"] == action["abandon_terminal"] for item in transitions), f"{name}: unresolved outcome can escape its terminal")
        require(any(item["from"] == action["post_reconciliation_state"] and item["event"] == "NO_PENDING_INTERRUPT" and item["to"] == action["confirmed_resume_state"] for item in transitions), f"{name}: confirmed receipt does not re-enter ingestion")

    critical = set(spec["effects"]["effect_critical_states"])
    require(critical == set(binding["required_effect_critical_states"]), "declared effect-critical states drift from FSM binding")
    require(spec["effects"]["persist_intent_before_execution"] is True, "effect intent is not durable before execution")
    require(spec["effects"]["atomic_with_checkpoint_and_outbox"] is True, "intent/checkpoint/outbox boundary is not atomic")
    require(spec["effects"]["delivery_semantics"] != "exactly-once", "unsupported exactly-once claim")

    for key in (
        "max_steps", "max_tool_calls", "max_retries_per_transition", "max_wall_seconds",
        "max_suspended_seconds", "max_tokens", "max_cost", "max_recursion_depth", "max_parallelism",
    ):
        value = spec["budgets"][key]
        require(isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0, f"invalid hard budget {key}")
    require(spec["budgets"]["aggregate_descendants"] is True, "descendant budgets are not aggregated")
    require("pending interrupts" in spec["checkpoint"]["persisted_fields"], "checkpoint omits pending interrupts")
    require(spec["approval"]["one_time"] is True, "approval is not one-time")
    require(spec["no_progress"]["outcome_state"] in states, "no-progress does not reach a typed terminal")
    require("independent" in spec["verification"]["evaluator_independence"], "verifier independence is not explicit")
    require(all(item.get("guard") == "completion_closed" for item in transitions if item["to"] == "SUCCEEDED"), "loop binding admits unverified success")
    return {"loop_bound_states": len(states), "loop_bound_transitions": len(transitions), "effect_critical_states": len(critical)}


def validate_manifest() -> dict[str, int]:
    manifest = load_json("spec/m0-manifest.v1.json")
    path_groups = (
        manifest["normative_contracts"]
        + manifest["self_validating_schemas"]
        + manifest["conformance_fixtures"]
        + manifest["non_normative_tools"]
    )
    missing = [path for path in path_groups if not (ROOT / path).is_file()]
    require(not missing, f"M0 manifest references missing files: {missing}")
    bound = {item["artifact"]: item["schema"] for item in manifest["schema_bindings"]}
    for artifact in manifest["normative_contracts"]:
        require(artifact.endswith(".schema.json") or artifact in bound, f"normative artifact lacks schema binding: {artifact}")
    require(set(bound.values()) <= set(manifest["self_validating_schemas"]), "normative binding names an unvalidated schema")
    fixture_bound = {item["artifact"]: item["schema"] for item in manifest["fixture_schema_bindings"]}
    require(set(fixture_bound) <= set(manifest["conformance_fixtures"]), "fixture binding names an undeclared fixture")
    require(set(fixture_bound.values()) <= set(manifest["self_validating_schemas"]), "fixture binding names an unvalidated schema")
    require(manifest["status"] == "MEASURED_CHECKER_CONFORMANCE", "M0 status overclaims checker evidence")
    require("runtime" in manifest["completion_boundary"] and "not" in manifest["completion_boundary"].lower(), "M0 boundary does not reject runtime overclaim")
    return {
        "manifest_contracts": len(manifest["normative_contracts"]),
        "manifest_schemas": len(manifest["self_validating_schemas"]),
        "manifest_fixtures": len(manifest["conformance_fixtures"]),
        "manifest_tools": len(manifest["non_normative_tools"]),
    }


def validate_all() -> dict[str, int]:
    summary: dict[str, int] = {}
    for check in (
        validate_schemas_and_fixtures,
        validate_logic,
        validate_canonicalization,
        validate_fsm,
        validate_loop,
        validate_manifest,
    ):
        summary.update(check())
    return summary


def main(argv: list[str]) -> int:
    if argv == ["--show-canonical-digests"]:
        cases = load_json("fixtures/m0/canonical/cases.json")
        for case in cases["equal_pairs"]:
            print(f"{case['id']} {canonical_digest(case['left'])}")
        return 0
    if argv:
        print("usage: validate_m0.py [--show-canonical-digests]", file=sys.stderr)
        return 2
    try:
        summary = validate_all()
    except (AssertionError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"M0 FAIL: {error}", file=sys.stderr)
        return 1
    print("M0 PASS " + json.dumps(summary, sort_keys=True, separators=(",", ":")))
    print("BOUNDARY pinned-checker conformance only; global consistency, runtime, recovery, efficacy, originality, and Lakatos progress remain unjudged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
