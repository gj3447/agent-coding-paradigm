#!/usr/bin/env python3
"""Independent source-bound verifier for one bounded M4C replay.

The verifier never trusts a stored stage output as the input to the next stage.
It rebuilds the frozen input profile and replays every public F/L/LR/R/H API.
The durable database report remains a detached, read-only consistency receipt;
it is not an authenticated statement about a real external destination.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable

from jsonschema import Draft202012Validator, FormatChecker

from flrh_authority import project_h_intent
from flrh_kernel import step_f
from flrh_kernel.canonical import CanonicalizationError, canonical_digest
from flrh_logic import solve_l
from flrh_lr_seam import project_lr
from flrh_reactive import step_r
from m4c_fixtures import (
    M4C_CONTRACT,
    build_l_inputs,
    build_low_risk_h_command,
    build_lr_inputs,
    build_receipt_binding,
    build_receipt_evidence,
    fresh,
    load_m1_expected_transition,
    load_m1_input,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = M4C_CONTRACT
FSM_PATH = ROOT / "spec/run-fsm.v1.json"
PROTOCOL_PATH = ROOT / "spec/schema/protocol.v1.schema.json"
TRACE_IDS = (
    "start",
    "accept-event",
    "stabilize-epoch",
    "authorize-low-risk",
    "dispatch-after-commit",
    "begin-reconciliation",
    "receipt-confirmed",
)
EVIDENCE_KEYS = {
    "kind", "schema_version", "contract_version", "replay_mode", "status",
    "outer_fsm_stop_state", "trace_claim", "outer_reducer_executed",
    "trace_source", "prior_materialization", "adapter_profile",
    "accepted_event", "f_transition", "rule_bundle", "l_input_deltas",
    "l_result", "binding_profile", "query_batch", "lr_projection",
    "r_profile", "r_apply_transition", "r_equal_frontier_transitions",
    "r_passed_frontier_transitions", "r_publish_transition",
    "r_published_batch", "h_command", "h_projection", "receipt_binding",
    "action_receipt", "m4b_verification", "durable_run_status",
    "adapter_counts", "recovery", "trace", "evidence_digest",
}


def _load_fsm() -> Dict[str, Any]:
    return json.loads(FSM_PATH.read_text(encoding="utf-8"))


def _fsm_index() -> tuple[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    fsm = _load_fsm()
    machine = next(row for row in fsm["machines"] if row["id"] == "control")
    return fsm, {row["id"]: row for row in machine["transitions"]}


_FSM, _FSM_TRANSITIONS = _fsm_index()
TRACE = [
    {
        "from": _FSM_TRANSITIONS[transition_id]["from"],
        "event": _FSM_TRANSITIONS[transition_id]["event"],
        "to": _FSM_TRANSITIONS[transition_id]["to"],
    }
    for transition_id in TRACE_IDS
]


class _Mismatch(Exception):
    def __init__(self, path: str, expected: Any = None, actual: Any = None) -> None:
        super().__init__(path)
        self.path = path or "/"
        self.expected = expected
        self.actual = actual


def _failure(path: str, expected: Any = None, actual: Any = None) -> Dict[str, Any]:
    context: Dict[str, Any] = {}
    if isinstance(expected, (str, int, bool)):
        context["expected"] = expected
    if isinstance(actual, (str, int, bool)):
        context["actual"] = actual
    return {
        "kind": "M4CVerificationFailure",
        "schema_version": "flrh-m4c-verification/1",
        "contract_version": CONTRACT,
        "code": "INTEGRATION_BINDING_MISMATCH",
        "path": path or "/",
        "context": context,
    }


def _child(path: str, token: Any) -> str:
    encoded = str(token).replace("~", "~0").replace("/", "~1")
    return f"{path}/{encoded}" if path else f"/{encoded}"


def _same(expected: Any, actual: Any, path: str) -> None:
    if type(expected) is not type(actual):
        raise _Mismatch(path)
    if isinstance(expected, dict):
        expected_keys = set(expected)
        actual_keys = set(actual)
        missing = sorted(expected_keys - actual_keys)
        if missing:
            raise _Mismatch(_child(path, missing[0]))
        extra = sorted(actual_keys - expected_keys)
        if extra:
            raise _Mismatch(_child(path, extra[0]))
        for key in sorted(expected):
            _same(expected[key], actual[key], _child(path, key))
        return
    if isinstance(expected, list):
        for index, item in enumerate(expected):
            if index >= len(actual):
                raise _Mismatch(_child(path, index))
            _same(item, actual[index], _child(path, index))
        if len(actual) > len(expected):
            raise _Mismatch(_child(path, len(expected)))
        return
    if expected != actual:
        raise _Mismatch(path, expected, actual)


def _exact_object(value: Any, keys: Iterable[str], path: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise _Mismatch(path)
    required = set(keys)
    missing = sorted(required - set(value))
    if missing:
        raise _Mismatch(_child(path, missing[0]))
    extra = sorted(set(value) - required)
    if extra:
        raise _Mismatch(_child(path, extra[0]))
    return value


def _stage(value: Any, kind: str, path: str) -> Dict[str, Any]:
    if not isinstance(value, dict) or value.get("kind") != kind:
        raise _Mismatch(path)
    return value


def _advance_frontiers(
    state: Dict[str, Any], profile: Dict[str, Any], low_watermark: int
) -> tuple[Dict[str, Any], list[Dict[str, Any]]]:
    transitions = []
    for source_id in profile["source_ids"]:
        command = {
            "kind": "RAdvanceFrontier",
            "schema_version": "flrh-r-command/1",
            "profile_digest": profile["profile_digest"],
            "dataflow_version": profile["dataflow_version"],
            "source_id": source_id,
            "low_watermark": low_watermark,
        }
        transition = _stage(step_r(state, profile, command), "RTransition", "/r_profile")
        transitions.append(transition)
        state = transition["next_state"]
    return state, transitions


def _m4b_report(value: Any, path: str, run_id: str, counts: tuple[int, int, int]) -> Dict[str, Any]:
    report = _exact_object(
        value,
        {"kind", "run_id", "valid", "errors", "intent_count", "receipt_count", "pending_count"},
        path,
    )
    expected = {
        "kind": "M4BVerificationReport",
        "run_id": run_id,
        "valid": True,
        "errors": [],
        "intent_count": counts[0],
        "receipt_count": counts[1],
        "pending_count": counts[2],
    }
    _same(expected, report, path)
    return report


def _validate_receipt(
    receipt: Any,
    intent: Dict[str, Any],
    binding: Dict[str, Any],
    projection_digest: str,
    mode: str,
) -> None:
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    schema = {
        "$schema": protocol["$schema"],
        "$defs": protocol["$defs"],
        "$ref": "#/$defs/ActionReceipt",
    }
    receipt = _exact_object(
        receipt,
        protocol["$defs"]["ActionReceipt"]["required"],
        "/action_receipt",
    )
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(receipt),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        error = errors[0]
        path = "/action_receipt"
        for token in error.absolute_path:
            path = _child(path, token)
        raise _Mismatch(path)
    for field in (
        "intent_id", "action_digest", "cause_id", "correlation_id", "capability",
        "authority_digest", "destination_digest", "goal_id", "obligation_id",
        "adapter_version", "assessed_risk", "approval_required", "approval_digest",
        "idempotency_key",
    ):
        _same(intent[field], receipt[field], f"/action_receipt/{field}")
    for field in ("command_digest", "input_root_digest", "platform_digest"):
        _same(binding[field], receipt[field], f"/action_receipt/{field}")
    _same(f"attempt:{intent['intent_id']}:1", receipt["attempt_id"], "/action_receipt/attempt_id")
    expected_observation = build_receipt_evidence({"projection_digest": projection_digest})(
        intent, receipt["attempt_id"], "confirmed_success"
    )
    _same(expected_observation["output_digests"], receipt["output_digests"], "/action_receipt/output_digests")
    _same(expected_observation["trace_ref"], receipt["trace_ref"], "/action_receipt/trace_ref")
    _same("confirmed_success", receipt["outcome"], "/action_receipt/outcome")
    expected_recorded_at = "1970-01-01T00:01:51Z" if mode == "crash_after_external_success" else "1970-01-01T00:01:40Z"
    _same(expected_recorded_at, receipt["recorded_at"], "/action_receipt/recorded_at")


def _expected_trace(
    evidence: Dict[str, Any],
    accepted_event: Dict[str, Any],
    l_result: Dict[str, Any],
    frontier_passed: list[Dict[str, Any]],
    h_projection: Dict[str, Any],
    binding: Dict[str, Any],
    receipt: Dict[str, Any],
    post_commit_report: Dict[str, Any],
    final_report: Dict[str, Any],
) -> list[Dict[str, Any]]:
    fsm, transitions = _fsm_index()
    machine = next(row for row in fsm["machines"] if row["id"] == "control")
    if machine["initial"] != "INIT":
        raise _Mismatch("/trace_source/machine_id")
    last_frontier = frontier_passed[-1]
    frontier_state = last_frontier["next_state"]
    logical_time = accepted_event["logical_time"]
    source_frontiers = frontier_state["source_frontiers"]
    frontier_guard = (
        frontier_state["global_low_watermark"] > logical_time
        and len(source_frontiers) == len(evidence["r_profile"]["source_ids"])
        and all(row["low_watermark"] > logical_time for row in source_frontiers)
        and len(frontier_state["ready_batches"]) == 1
    )
    if not frontier_guard:
        raise _Mismatch("/r_passed_frontier_transitions")
    intent_guard = (
        post_commit_report["valid"] is True
        and post_commit_report["errors"] == []
        and post_commit_report["intent_count"] == 1
        and post_commit_report["receipt_count"] == 0
        and post_commit_report["pending_count"] == 1
    )
    if not intent_guard:
        raise _Mismatch("/m4b_verification")
    materialization = l_result["next_materialization"]
    control_event = h_projection["control_event"]
    intent = h_projection["intent"]
    evidence_rows = {
        "start": {
            "workflow_digest": canonical_digest({
                "kind": "M4CWorkflowEvidencePreimage",
                "contract_version": CONTRACT,
                "workflow": accepted_event["versions"]["workflow"],
            }),
            "version_envelope_digest": canonical_digest({
                "kind": "M4CVersionEnvelopeEvidencePreimage",
                "contract_version": CONTRACT,
                "versions": fresh(accepted_event["versions"]),
            }),
        },
        "accept-event": {
            "accepted_event_digest": canonical_digest(accepted_event),
            "cursor": {
                "kind": "M4CBoundedFixtureCursor",
                "event_id": accepted_event["event_id"],
                "idempotency_key": accepted_event["idempotency_key"],
                "logical_time": logical_time,
            },
        },
        "stabilize-epoch": {
            "state_digest": frontier_state["state_digest"],
            "support_digest": canonical_digest({
                "kind": "M4CSupportEvidencePreimage",
                "contract_version": CONTRACT,
                "base_supports": fresh(materialization["base_supports"]),
                "derived_supports": fresh(materialization["derived_supports"]),
            }),
            "frontier_receipt": {
                "kind": "M4CFrontierReceipt",
                "logical_time": logical_time,
                "global_low_watermark": frontier_state["global_low_watermark"],
                "source_frontiers": fresh(source_frontiers),
                "transition_digest": last_frontier["transition_digest"],
                "ready_batch_digest": frontier_state["ready_batches"][0]["published_batch_digest"],
            },
        },
        "authorize-low-risk": {
            "policy_verdict": control_event["payload"]["policy_verdict"],
            "capability_digest": control_event["payload"]["capability_digest"],
        },
        "dispatch-after-commit": {
            "atomic_intent_checkpoint_outbox_receipt": {
                "kind": "M4CAtomicIntentCommitWitness",
                "intent_digest": canonical_digest(intent),
                "receipt_binding_digest": canonical_digest(binding),
                "post_commit_verification": fresh(post_commit_report),
            },
        },
        "begin-reconciliation": {
            "attempt_id": receipt["attempt_id"],
            "idempotency_key": receipt["idempotency_key"],
            "response_hash": canonical_digest({
                "kind": "M4CObservedAdapterResponsePreimage",
                "contract_version": CONTRACT,
                "outcome": receipt["outcome"],
                "output_digests": fresh(receipt["output_digests"]),
                "trace_ref": receipt["trace_ref"],
            }),
        },
        "receipt-confirmed": {
            "independent_action_receipt": {
                "receipt": fresh(receipt),
                "receipt_digest": canonical_digest(receipt),
                "verification": fresh(final_report),
            },
        },
    }
    bindings = {
        "authorize-low-risk": "PUBLIC_CONTROL_EVENT",
        "receipt-confirmed": "INDEPENDENT_READ_ONLY_VERIFIER",
    }
    rows = []
    for transition_id in TRACE_IDS:
        transition = transitions[transition_id]
        required = set(transition["evidence_required"])
        if set(evidence_rows[transition_id]) != required:
            raise _Mismatch("/trace")
        authority_rows = fsm["event_authority"][transition["event"]]
        if len(authority_rows) != 1:
            raise _Mismatch("/trace")
        guard_name = transition.get("guard")
        guard = None
        if guard_name:
            reads = {name: True for name in fsm["guards"][guard_name]["reads"]}
            guard = {"name": guard_name, "reads": reads, "result": True}
        rows.append({
            "transition_id": transition_id,
            "from": transition["from"],
            "event": transition["event"],
            "to": transition["to"],
            "authority": {
                **authority_rows[0],
                "binding": bindings.get(transition_id, "SOURCE_REQUIREMENT_ONLY"),
            },
            "guard": guard,
            "evidence": evidence_rows[transition_id],
        })
    if control_event["type"] != rows[3]["event"]:
        raise _Mismatch("/h_projection/control_event/type")
    if control_event["actor_role"] != rows[3]["authority"]["actor_role"]:
        raise _Mismatch("/h_projection/control_event/actor_role")
    if control_event["capability"] != rows[3]["authority"]["capability"]:
        raise _Mismatch("/h_projection/control_event/capability")
    if h_projection["next_control_state"] != "COMMIT_INTENT":
        raise _Mismatch("/h_projection/next_control_state")
    return rows


def _verify(evidence: Any) -> Dict[str, Any]:
    envelope = _exact_object(evidence, EVIDENCE_KEYS, "")
    fixed = {
        "kind": "M4CReplayEvidence",
        "schema_version": "flrh-m4c-replay/1",
        "contract_version": CONTRACT,
        "status": "SLICE_CONFORMED",
        "outer_fsm_stop_state": "HONOR_PENDING_INTERRUPT",
        "trace_claim": "FSM_CONFORMANCE_PROJECTION_ONLY",
        "outer_reducer_executed": False,
        "prior_materialization": None,
        "adapter_profile": "FakeAdapter",
        "durable_run_status": "active",
    }
    for field, expected in fixed.items():
        _same(expected, envelope[field], f"/{field}")
    mode = envelope["replay_mode"]
    if mode not in ("happy", "crash_after_external_success"):
        raise _Mismatch("/replay_mode")

    expected_trace_source = {
        "path": "spec/run-fsm.v1.json",
        "sha256": "sha256:" + hashlib.sha256(FSM_PATH.read_bytes()).hexdigest(),
        "schema_version": _FSM["schema_version"],
        "authority": _FSM["authority"],
        "machine_id": "control",
    }
    _same(expected_trace_source, envelope["trace_source"], "/trace_source")

    snapshot, accepted_event = load_m1_input()
    _same(accepted_event, envelope["accepted_event"], "/accepted_event")
    f_transition = _stage(step_f(snapshot, accepted_event), "FTransition", "/f_transition")
    _same(load_m1_expected_transition(), f_transition, "/f_transition")
    _same(f_transition, envelope["f_transition"], "/f_transition")

    rule_bundle, l_input_deltas, _proposal, _requirements, _frontiers = build_l_inputs(f_transition)
    _same(rule_bundle, envelope["rule_bundle"], "/rule_bundle")
    _same(l_input_deltas, envelope["l_input_deltas"], "/l_input_deltas")
    l_result = _stage(
        solve_l(None, rule_bundle, l_input_deltas, accepted_event["logical_time"]),
        "LFixpointResult",
        "/l_result",
    )
    _same(l_result, envelope["l_result"], "/l_result")

    rule_bundle_again, r_profile, binding_profile, query_batch = build_lr_inputs(f_transition, l_result)
    _same(rule_bundle, rule_bundle_again, "/rule_bundle")
    _same(r_profile, envelope["r_profile"], "/r_profile")
    _same(binding_profile, envelope["binding_profile"], "/binding_profile")
    _same(query_batch, envelope["query_batch"], "/query_batch")
    lr_projection = _stage(
        project_lr(l_result, rule_bundle, r_profile, binding_profile, query_batch),
        "LRProjectionResult",
        "/lr_projection",
    )
    _same(lr_projection, envelope["lr_projection"], "/lr_projection")

    r_apply = _stage(step_r(None, r_profile, lr_projection["command"]), "RTransition", "/r_apply_transition")
    _same(r_apply, envelope["r_apply_transition"], "/r_apply_transition")
    r_state = r_apply["next_state"]
    r_state, frontier_equal = _advance_frontiers(r_state, r_profile, 1)
    if r_state["ready_batches"]:
        raise _Mismatch("/r_equal_frontier_transitions")
    _same(frontier_equal, envelope["r_equal_frontier_transitions"], "/r_equal_frontier_transitions")
    r_state, frontier_passed = _advance_frontiers(r_state, r_profile, 2)
    if len(r_state["ready_batches"]) != 1:
        raise _Mismatch("/r_passed_frontier_transitions")
    _same(frontier_passed, envelope["r_passed_frontier_transitions"], "/r_passed_frontier_transitions")
    demand = {
        "kind": "RGrantDemand",
        "schema_version": "flrh-r-command/1",
        "profile_digest": r_profile["profile_digest"],
        "dataflow_version": r_profile["dataflow_version"],
        "batches": 1,
    }
    r_publish = _stage(step_r(r_state, r_profile, demand), "RTransition", "/r_publish_transition")
    _same(r_publish, envelope["r_publish_transition"], "/r_publish_transition")
    if len(r_publish["published_batches"]) != 1:
        raise _Mismatch("/r_published_batch")
    published = r_publish["published_batches"][0]
    _same(published, envelope["r_published_batch"], "/r_published_batch")

    h_command = build_low_risk_h_command(published, r_profile["profile_digest"])
    _same(h_command, envelope["h_command"], "/h_command")
    h_projection = _stage(project_h_intent(h_command), "HProjection", "/h_projection")
    _same(h_projection, envelope["h_projection"], "/h_projection")
    binding = build_receipt_binding(accepted_event, h_command)
    _same(binding, envelope["receipt_binding"], "/receipt_binding")

    intent = h_projection["intent"]
    receipt = envelope["action_receipt"]
    _validate_receipt(
        receipt,
        intent,
        binding,
        h_projection["projection_digest"],
        mode,
    )
    run_id = intent["correlation_id"]
    final_report = _m4b_report(envelope["m4b_verification"], "/m4b_verification", run_id, (1, 1, 0))

    happy_counts = {"apply_count": 1, "query_count": 0, "mutation_count": 1}
    crash_counts = {"apply_count": 1, "query_count": 1, "mutation_count": 1}
    recovery = envelope["recovery"]
    if mode == "happy":
        _same(None, recovery, "/recovery")
        _same(happy_counts, envelope["adapter_counts"], "/adapter_counts")
        post_commit_report = envelope["trace"][4]["evidence"]["atomic_intent_checkpoint_outbox_receipt"]["post_commit_verification"]
        _m4b_report(post_commit_report, "/trace/4/evidence/atomic_intent_checkpoint_outbox_receipt/post_commit_verification", run_id, (1, 0, 1))
    else:
        expected_recovery_keys = {
            "crash_point", "process_model", "worker_exit_code", "worker_payload_digest",
            "mutation_count_at_crash", "pre_recovery_verification", "reopen_epoch",
            "reconciliation_result",
        }
        recovery = _exact_object(recovery, expected_recovery_keys, "/recovery")
        fixed_recovery = {
            "crash_point": "after_external_success",
            "process_model": "subprocess_os_exit_reopen",
            "worker_exit_code": 86,
            "mutation_count_at_crash": 1,
            "reopen_epoch": 111,
            "reconciliation_result": "confirmed_success",
        }
        for field, expected in fixed_recovery.items():
            _same(expected, recovery[field], f"/recovery/{field}")
        checkpoint = {
            "kind": "M4CCheckpoint",
            "stage": "authority_projected",
            "projection_digest": h_projection["projection_digest"],
        }
        worker_envelope = {
            "kind": "M4CCrashWorkerEnvelope",
            "schema_version": "flrh-m4c-crash-worker/1",
            "h_command": fresh(h_command),
            "receipt_binding": fresh(binding),
            "checkpoint": checkpoint,
        }
        _same(canonical_digest(worker_envelope), recovery["worker_payload_digest"], "/recovery/worker_payload_digest")
        post_commit_report = _m4b_report(
            recovery["pre_recovery_verification"],
            "/recovery/pre_recovery_verification",
            run_id,
            (1, 0, 1),
        )
        _same(crash_counts, envelope["adapter_counts"], "/adapter_counts")

    expected_trace = _expected_trace(
        envelope,
        accepted_event,
        l_result,
        frontier_passed,
        h_projection,
        binding,
        receipt,
        post_commit_report,
        final_report,
    )
    _same(expected_trace, envelope["trace"], "/trace")

    body = copy.deepcopy(envelope)
    supplied_digest = body.pop("evidence_digest")
    expected_digest = canonical_digest({
        "kind": "M4CReplayEvidencePreimage",
        "contract_version": CONTRACT,
        "evidence": body,
    })
    _same(expected_digest, supplied_digest, "/evidence_digest")

    stage_digests = {
        "f_transition": f_transition["transition_digest"],
        "l_fixpoint": l_result["fixpoint_digest"],
        "lr_projection": lr_projection["projection_digest"],
        "r_published_batch": published["published_batch_digest"],
        "h_projection": h_projection["projection_digest"],
        "action_receipt": canonical_digest(receipt),
        "replay_evidence": expected_digest,
    }
    result = {
        "kind": "M4CVerificationReceipt",
        "schema_version": "flrh-m4c-verification/1",
        "contract_version": CONTRACT,
        "status": "SLICE_CONFORMED",
        "outer_fsm_stop_state": "HONOR_PENDING_INTERRUPT",
        "stage_digests": stage_digests,
        "checks": [
            "public_f_reexecution",
            "public_l_reexecution",
            "public_lr_reexecution",
            "public_r_reexecution",
            "public_h_reexecution",
            "exact_action_receipt_schema_and_binding",
            "detached_durable_consistency_receipt",
            "source_bound_fsm_evidence_projection",
            "real_subprocess_crash_recovery_when_selected",
        ],
    }
    result["verification_digest"] = canonical_digest({
        "kind": "M4CVerificationPreimage",
        "contract_version": CONTRACT,
        "receipt": copy.deepcopy(result),
    })
    return result


def verify_m4c_evidence(evidence: Any) -> Dict[str, Any]:
    try:
        return _verify(evidence)
    except _Mismatch as error:
        return _failure(error.path, error.expected, error.actual)
    except CanonicalizationError as error:
        return _failure(error.path)
    except (KeyError, IndexError, TypeError, ValueError, StopIteration):
        return _failure("/")


__all__ = ["TRACE", "TRACE_IDS", "verify_m4c_evidence"]
