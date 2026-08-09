#!/usr/bin/env python3
"""Execute one deterministic public F-L-LR-R-H-durable M4C reference chain."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import hashlib
from pathlib import Path
from typing import Any, Dict


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from flrh_authority import project_h_intent
from flrh_harness import CrashInjected, DurableHarness, FakeAdapter, verify_run
from flrh_kernel import step_f
from flrh_kernel.canonical import canonical_bytes, canonical_digest
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

FSM_PATH = ROOT / "spec/run-fsm.v1.json"
FSM_SHA256 = "sha256:" + hashlib.sha256(FSM_PATH.read_bytes()).hexdigest()
TRACE_IDS = (
    "start",
    "accept-event",
    "stabilize-epoch",
    "authorize-low-risk",
    "dispatch-after-commit",
    "begin-reconciliation",
    "receipt-confirmed",
)


def _require_kind(value: Dict[str, Any], expected: str) -> Dict[str, Any]:
    if value.get("kind") != expected:
        raise RuntimeError("M4C public stage rejected: " + json.dumps(value, sort_keys=True))
    return value


def _advance_frontiers(state, profile, low_watermark):
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
        transition = _require_kind(step_r(state, profile, command), "RTransition")
        transitions.append(transition)
        state = transition["next_state"]
    return state, transitions


def _counts(adapter_path: Path) -> Dict[str, int]:
    return FakeAdapter.inspect(adapter_path)


def _build_trace(
    accepted_event: Dict[str, Any],
    l_result: Dict[str, Any],
    r_profile: Dict[str, Any],
    frontier_passed: list[Dict[str, Any]],
    h_projection: Dict[str, Any],
    receipt_binding: Dict[str, Any],
    action_receipt: Dict[str, Any],
    post_commit_verification: Dict[str, Any],
    final_verification: Dict[str, Any],
) -> list[Dict[str, Any]]:
    fsm = json.loads(FSM_PATH.read_text(encoding="utf-8"))
    machine = next(row for row in fsm["machines"] if row["id"] == "control")
    transitions = {row["id"]: row for row in machine["transitions"]}
    last_frontier = frontier_passed[-1]
    frontier_state = last_frontier["next_state"]
    materialization = l_result["next_materialization"]
    control_event = h_projection["control_event"]
    intent = h_projection["intent"]
    evidence_rows = {
        "start": {
            "workflow_digest": canonical_digest({
                "kind": "M4CWorkflowEvidencePreimage",
                "contract_version": M4C_CONTRACT,
                "workflow": accepted_event["versions"]["workflow"],
            }),
            "version_envelope_digest": canonical_digest({
                "kind": "M4CVersionEnvelopeEvidencePreimage",
                "contract_version": M4C_CONTRACT,
                "versions": fresh(accepted_event["versions"]),
            }),
        },
        "accept-event": {
            "accepted_event_digest": canonical_digest(accepted_event),
            "cursor": {
                "kind": "M4CBoundedFixtureCursor",
                "event_id": accepted_event["event_id"],
                "idempotency_key": accepted_event["idempotency_key"],
                "logical_time": accepted_event["logical_time"],
            },
        },
        "stabilize-epoch": {
            "state_digest": frontier_state["state_digest"],
            "support_digest": canonical_digest({
                "kind": "M4CSupportEvidencePreimage",
                "contract_version": M4C_CONTRACT,
                "base_supports": fresh(materialization["base_supports"]),
                "derived_supports": fresh(materialization["derived_supports"]),
            }),
            "frontier_receipt": {
                "kind": "M4CFrontierReceipt",
                "logical_time": accepted_event["logical_time"],
                "global_low_watermark": frontier_state["global_low_watermark"],
                "source_frontiers": fresh(frontier_state["source_frontiers"]),
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
                "receipt_binding_digest": canonical_digest(receipt_binding),
                "post_commit_verification": fresh(post_commit_verification),
            },
        },
        "begin-reconciliation": {
            "attempt_id": action_receipt["attempt_id"],
            "idempotency_key": action_receipt["idempotency_key"],
            "response_hash": canonical_digest({
                "kind": "M4CObservedAdapterResponsePreimage",
                "contract_version": M4C_CONTRACT,
                "outcome": action_receipt["outcome"],
                "output_digests": fresh(action_receipt["output_digests"]),
                "trace_ref": action_receipt["trace_ref"],
            }),
        },
        "receipt-confirmed": {
            "independent_action_receipt": {
                "receipt": fresh(action_receipt),
                "receipt_digest": canonical_digest(action_receipt),
                "verification": fresh(final_verification),
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
        authority = fsm["event_authority"][transition["event"]][0]
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
                **authority,
                "binding": bindings.get(transition_id, "SOURCE_REQUIREMENT_ONLY"),
            },
            "guard": guard,
            "evidence": evidence_rows[transition_id],
        })
    return rows


def _run_crash_worker(database: Path, adapter_path: Path, payload: Dict[str, Any]) -> int:
    expected_keys = {"kind", "schema_version", "h_command", "receipt_binding", "checkpoint"}
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise ValueError("invalid M4C crash worker envelope")
    if payload["kind"] != "M4CCrashWorkerEnvelope" or payload["schema_version"] != "flrh-m4c-crash-worker/1":
        raise ValueError("unsupported M4C crash worker envelope")
    h_projection = _require_kind(project_h_intent(payload["h_command"]), "HProjection")
    intent = h_projection["intent"]
    adapter = FakeAdapter(durable_path=adapter_path)
    harness = DurableHarness(
        database,
        adapter,
        now=lambda: 100,
        receipt_evidence=build_receipt_evidence(h_projection),
    )
    run_id = intent["correlation_id"]
    harness.create_run(run_id, payload["checkpoint"], max_pending=1, max_attempts=3)
    token = harness.acquire_lease(run_id, "runner:m4c:crash", ttl_seconds=10)
    if not harness.commit_intent(token, intent, receipt_binding=payload["receipt_binding"]):
        raise RuntimeError("M4C crash worker did not commit its fresh intent")
    try:
        harness.dispatch_next(token, crash_point="after_external_success")
    except CrashInjected:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(86)
    return 2


def run_reference_chain(crash_after_external_success: bool = False) -> Dict[str, Any]:
    snapshot, accepted_event = load_m1_input()
    f_transition = _require_kind(step_f(snapshot, accepted_event), "FTransition")
    if canonical_bytes(f_transition) != canonical_bytes(load_m1_expected_transition()):
        raise RuntimeError("live M1 output drifted from the frozen golden")

    rule_bundle, l_input_deltas, _proposal, _requirements, _frontiers = build_l_inputs(
        f_transition
    )
    l_result = _require_kind(
        solve_l(None, rule_bundle, l_input_deltas, accepted_event["logical_time"]),
        "LFixpointResult",
    )
    rule_bundle_again, r_profile, binding_profile, query_batch = build_lr_inputs(
        f_transition, l_result
    )
    if canonical_bytes(rule_bundle) != canonical_bytes(rule_bundle_again):
        raise RuntimeError("M4C L/LR rule bundle builder drift")
    lr_projection = _require_kind(
        project_lr(l_result, rule_bundle, r_profile, binding_profile, query_batch),
        "LRProjectionResult",
    )

    r_apply = _require_kind(step_r(None, r_profile, lr_projection["command"]), "RTransition")
    r_state = r_apply["next_state"]
    r_state, frontier_equal = _advance_frontiers(r_state, r_profile, 1)
    if r_state["ready_batches"]:
        raise RuntimeError("R published stability at equality instead of strict passage")
    r_state, frontier_passed = _advance_frontiers(r_state, r_profile, 2)
    if len(r_state["ready_batches"]) != 1:
        raise RuntimeError("R did not produce exactly one ready batch")
    demand = {
        "kind": "RGrantDemand",
        "schema_version": "flrh-r-command/1",
        "profile_digest": r_profile["profile_digest"],
        "dataflow_version": r_profile["dataflow_version"],
        "batches": 1,
    }
    r_publish = _require_kind(step_r(r_state, r_profile, demand), "RTransition")
    if len(r_publish["published_batches"]) != 1:
        raise RuntimeError("R did not publish exactly one batch")
    published = r_publish["published_batches"][0]

    h_command = build_low_risk_h_command(published, r_profile["profile_digest"])
    h_projection = _require_kind(project_h_intent(h_command), "HProjection")
    if h_projection["event"] != "EFFECT_AUTHORIZED":
        raise RuntimeError("M4C low-risk authority route drift")
    intent = h_projection["intent"]
    receipt_binding = build_receipt_binding(accepted_event, h_command)

    replay_mode = "crash_after_external_success" if crash_after_external_success else "happy"
    recovery = None
    with tempfile.TemporaryDirectory(prefix="flrh-m4c-") as raw:
        workdir = Path(raw)
        database = workdir / "harness.sqlite3"
        adapter_path = workdir / "fake-adapter.sqlite3"
        run_id = intent["correlation_id"]
        checkpoint = {
            "kind": "M4CCheckpoint",
            "stage": "authority_projected",
            "projection_digest": h_projection["projection_digest"],
        }

        if crash_after_external_success:
            worker_envelope = {
                "kind": "M4CCrashWorkerEnvelope",
                "schema_version": "flrh-m4c-crash-worker/1",
                "h_command": fresh(h_command),
                "receipt_binding": fresh(receipt_binding),
                "checkpoint": fresh(checkpoint),
            }
            worker_payload_digest = canonical_digest(worker_envelope)
            completed = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--crash-worker", str(database), str(adapter_path)],
                cwd=workdir,
                input=canonical_bytes(worker_envelope) + b"\n",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if completed.returncode != 86 or completed.stdout or completed.stderr:
                raise RuntimeError(
                    "M4C crash worker boundary drift: "
                    + json.dumps({
                        "returncode": completed.returncode,
                        "stdout": completed.stdout.decode("utf-8", "replace"),
                        "stderr": completed.stderr.decode("utf-8", "replace"),
                    }, sort_keys=True)
                )
            counts_at_crash = _counts(adapter_path)
            if counts_at_crash["mutation_count"] != 1:
                raise RuntimeError("M4C crash worker did not mutate exactly once")
            pre_recovery = verify_run(database, run_id)
            adapter = FakeAdapter(durable_path=adapter_path)
            harness = DurableHarness(
                database,
                adapter,
                now=lambda: 111,
                receipt_evidence=build_receipt_evidence(h_projection),
            )
            token = harness.acquire_lease(run_id, "runner:m4c:recovery", ttl_seconds=10)
            reconciliation = harness.reconcile_next(token)
            recovery = {
                "crash_point": "after_external_success",
                "process_model": "subprocess_os_exit_reopen",
                "worker_exit_code": 86,
                "worker_payload_digest": worker_payload_digest,
                "mutation_count_at_crash": counts_at_crash["mutation_count"],
                "pre_recovery_verification": pre_recovery,
                "reopen_epoch": 111,
                "reconciliation_result": reconciliation,
            }
            post_commit_verification = pre_recovery
        else:
            adapter = FakeAdapter(durable_path=adapter_path)
            harness = DurableHarness(
                database,
                adapter,
                now=lambda: 100,
                receipt_evidence=build_receipt_evidence(h_projection),
            )
            harness.create_run(run_id, checkpoint, max_pending=1, max_attempts=3)
            token = harness.acquire_lease(run_id, "runner:m4c", ttl_seconds=10)
            committed = harness.commit_intent(token, intent, receipt_binding=receipt_binding)
            if not committed:
                raise RuntimeError("fresh M4C intent was not committed")
            post_commit_verification = verify_run(database, run_id)
            action = harness.dispatch_next(token)
            if action is None or action.get("outcome") != "confirmed_success":
                raise RuntimeError("M4C fake destination did not confirm success")

        receipts = harness.receipts(run_id)
        if len(receipts) != 1:
            raise RuntimeError("M4C durable store did not contain exactly one receipt")
        action_receipt = receipts[0]
        durable_verification = verify_run(database, run_id)
        durable_status = harness.run_status(run_id)
        adapter_counts = _counts(adapter_path)
        harness.close()

    trace = _build_trace(
        accepted_event,
        l_result,
        r_profile,
        frontier_passed,
        h_projection,
        receipt_binding,
        action_receipt,
        post_commit_verification,
        durable_verification,
    )

    evidence = {
        "kind": "M4CReplayEvidence",
        "schema_version": "flrh-m4c-replay/1",
        "contract_version": M4C_CONTRACT,
        "replay_mode": replay_mode,
        "status": "SLICE_CONFORMED",
        "outer_fsm_stop_state": "HONOR_PENDING_INTERRUPT",
        "trace_claim": "FSM_CONFORMANCE_PROJECTION_ONLY",
        "outer_reducer_executed": False,
        "trace_source": {
            "path": "spec/run-fsm.v1.json",
            "sha256": FSM_SHA256,
            "schema_version": "flrh-run-fsm/v1",
            "authority": "sole-authoritative-outer-control-fsm",
            "machine_id": "control",
        },
        "prior_materialization": None,
        "adapter_profile": "FakeAdapter",
        "accepted_event": fresh(accepted_event),
        "f_transition": fresh(f_transition),
        "rule_bundle": fresh(rule_bundle),
        "l_input_deltas": fresh(l_input_deltas),
        "l_result": fresh(l_result),
        "binding_profile": fresh(binding_profile),
        "query_batch": fresh(query_batch),
        "lr_projection": fresh(lr_projection),
        "r_profile": fresh(r_profile),
        "r_apply_transition": fresh(r_apply),
        "r_equal_frontier_transitions": fresh(frontier_equal),
        "r_passed_frontier_transitions": fresh(frontier_passed),
        "r_publish_transition": fresh(r_publish),
        "r_published_batch": fresh(published),
        "h_command": fresh(h_command),
        "h_projection": fresh(h_projection),
        "receipt_binding": fresh(receipt_binding),
        "action_receipt": fresh(action_receipt),
        "m4b_verification": fresh(durable_verification),
        "durable_run_status": durable_status,
        "adapter_counts": adapter_counts,
        "recovery": recovery,
        "trace": trace,
    }
    evidence["evidence_digest"] = canonical_digest({
        "kind": "M4CReplayEvidencePreimage",
        "contract_version": M4C_CONTRACT,
        "evidence": fresh(evidence),
    })
    return evidence


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "--crash-worker":
        payload = json.loads(sys.stdin.buffer.read())
        return _run_crash_worker(Path(sys.argv[2]), Path(sys.argv[3]), payload)
    if len(sys.argv) != 1:
        raise ValueError("unsupported M4C replay arguments")
    mode = "happy"
    if not sys.stdin.isatty():
        raw = sys.stdin.buffer.read()
        if raw.strip():
            value = json.loads(raw)
            if not isinstance(value, dict) or set(value) - {"mode"}:
                raise ValueError("M4C replay envelope must contain only mode")
            mode = value.get("mode", "happy")
    if mode not in ("happy", "crash_after_external_success"):
        raise ValueError("unsupported M4C replay mode")
    result = run_reference_chain(mode == "crash_after_external_success")
    sys.stdout.buffer.write(canonical_bytes(result) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
