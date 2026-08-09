#!/usr/bin/env python3
"""Run the bounded M4C-IL F -> incremental-L -> LR -> R -> H chain."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from flrh_authority import project_h_intent
from flrh_harness import CrashInjected, DurableHarness, FakeAdapter, verify_run
from flrh_kernel import step_f
from flrh_kernel.canonical import canonical_bytes, canonical_digest
from flrh_logic_incremental import step_incremental_l
from flrh_lr_seam import project_lr
from flrh_reactive import step_r
from m4cil_fixtures import (
    M4CIL_CONTRACT,
    M4CIL_PROFILE,
    build_durable_checkpoint,
    build_l_inputs,
    build_low_risk_h_command,
    build_lr_inputs,
    build_receipt_binding,
    build_receipt_evidence,
    fresh,
    load_chain_inputs,
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


def _require_kind(value: Any, expected: str, stage: str) -> Dict[str, Any]:
    if not isinstance(value, dict) or value.get("kind") != expected:
        raise RuntimeError(
            "M4C-IL public stage rejected: "
            + json.dumps({"stage": stage, "value": value}, sort_keys=True)
        )
    return value


def _rejection(stage: str, upstream: Any) -> Dict[str, Any]:
    value = {
        "kind": "M4CILReplayRejection",
        "schema_version": "flrh-m4cil-replay/1",
        "contract_version": M4CIL_CONTRACT,
        "code": "UPSTREAM_STAGE_REJECTION",
        "path": "/" + stage,
        "stage": stage,
        "upstream_rejection": fresh(upstream),
        "context": {},
    }
    value["rejection_digest"] = canonical_digest({
        "kind": "M4CILReplayRejectionPreimage",
        "contract_version": M4CIL_CONTRACT,
        **value,
    })
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
        transition = _require_kind(
            step_r(state, profile, command), "RTransition", "r_frontier"
        )
        transitions.append(transition)
        state = transition["next_state"]
    return state, transitions


def _counts(adapter_path: Path) -> Dict[str, int]:
    return FakeAdapter.inspect(adapter_path)


def _build_trace(
    accepted_event: Dict[str, Any],
    final_l_result: Dict[str, Any],
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
    materialization = final_l_result["next_materialization"]
    logical_time = final_l_result["logical_time"]
    control_event = h_projection["control_event"]
    intent = h_projection["intent"]
    evidence_rows = {
        "start": {
            "workflow_digest": canonical_digest({
                "kind": "M4CILWorkflowEvidencePreimage",
                "contract_version": M4CIL_CONTRACT,
                "workflow": accepted_event["versions"]["workflow"],
            }),
            "version_envelope_digest": canonical_digest({
                "kind": "M4CILVersionEnvelopeEvidencePreimage",
                "contract_version": M4CIL_CONTRACT,
                "versions": fresh(accepted_event["versions"]),
            }),
        },
        "accept-event": {
            "accepted_event_digest": canonical_digest(accepted_event),
            "cursor": {
                "kind": "M4CILBoundedFixtureCursor",
                "event_id": accepted_event["event_id"],
                "idempotency_key": accepted_event["idempotency_key"],
                "logical_time": accepted_event["logical_time"],
            },
        },
        "stabilize-epoch": {
            "state_digest": frontier_state["state_digest"],
            "support_digest": canonical_digest({
                "kind": "M4CILSupportEvidencePreimage",
                "contract_version": M4CIL_CONTRACT,
                "base_supports": fresh(materialization["base_supports"]),
                "derived_supports": fresh(materialization["derived_supports"]),
            }),
            "frontier_receipt": {
                "kind": "M4CILFrontierReceipt",
                "logical_time": logical_time,
                "global_low_watermark": frontier_state["global_low_watermark"],
                "source_frontiers": fresh(frontier_state["source_frontiers"]),
                "transition_digest": last_frontier["transition_digest"],
                "ready_batch_digest": frontier_state["ready_batches"][0][
                    "published_batch_digest"
                ],
            },
        },
        "authorize-low-risk": {
            "policy_verdict": control_event["payload"]["policy_verdict"],
            "capability_digest": control_event["payload"]["capability_digest"],
        },
        "dispatch-after-commit": {
            "atomic_intent_checkpoint_outbox_receipt": {
                "kind": "M4CILAtomicIntentCommitWitness",
                "intent_digest": canonical_digest(intent),
                "receipt_binding_digest": canonical_digest(receipt_binding),
                "post_commit_verification": fresh(post_commit_verification),
            },
        },
        "begin-reconciliation": {
            "attempt_id": action_receipt["attempt_id"],
            "idempotency_key": action_receipt["idempotency_key"],
            "response_hash": canonical_digest({
                "kind": "M4CILObservedAdapterResponsePreimage",
                "contract_version": M4CIL_CONTRACT,
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
        if set(evidence_rows[transition_id]) != set(transition["evidence_required"]):
            raise RuntimeError("M4C-IL trace evidence drift")
        authorities = fsm["event_authority"][transition["event"]]
        if len(authorities) != 1:
            raise RuntimeError("M4C-IL trace authority drift")
        guard_name = transition.get("guard")
        guard = None
        if guard_name:
            guard = {
                "name": guard_name,
                "reads": {name: True for name in fsm["guards"][guard_name]["reads"]},
                "result": True,
            }
        rows.append({
            "transition_id": transition_id,
            "from": transition["from"],
            "event": transition["event"],
            "to": transition["to"],
            "authority": {
                **authorities[0],
                "binding": bindings.get(transition_id, "SOURCE_REQUIREMENT_ONLY"),
            },
            "guard": guard,
            "evidence": evidence_rows[transition_id],
        })
    return rows


def _run_crash_worker(database: Path, adapter_path: Path, payload: Any) -> int:
    keys = {"kind", "schema_version", "h_command", "receipt_binding", "checkpoint"}
    if not isinstance(payload, dict) or set(payload) != keys:
        raise ValueError("invalid M4C-IL crash worker envelope")
    if payload["kind"] != "M4CILCrashWorkerEnvelope" or payload[
        "schema_version"
    ] != "flrh-m4cil-crash-worker/1":
        raise ValueError("unsupported M4C-IL crash worker envelope")
    h_projection = _require_kind(
        project_h_intent(payload["h_command"]), "HProjection", "h_projection"
    )
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
    token = harness.acquire_lease(run_id, "runner:m4cil:crash", ttl_seconds=10)
    if not harness.commit_intent(
        token, intent, receipt_binding=payload["receipt_binding"]
    ):
        raise RuntimeError("M4C-IL crash worker did not commit its fresh intent")
    try:
        harness.dispatch_next(token, crash_point="after_external_success")
    except CrashInjected:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(86)
    return 2


def run_incremental_reference_chain(
    crash_after_external_success: bool = False,
    *,
    chain_inputs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    inputs = fresh(load_chain_inputs() if chain_inputs is None else chain_inputs)
    required_inputs = {
        "snapshot",
        "accepted_event",
        "expected_f_transition",
        "rule_bundle",
        "bootstrap_input_deltas",
    }
    if not isinstance(inputs, dict) or set(inputs) != required_inputs:
        return _rejection("chain_inputs", inputs)

    snapshot = inputs["snapshot"]
    accepted_event = inputs["accepted_event"]
    f_transition = step_f(snapshot, accepted_event)
    if not isinstance(f_transition, dict) or f_transition.get("kind") != "FTransition":
        return _rejection("f_transition", f_transition)
    if canonical_bytes(f_transition) != canonical_bytes(inputs["expected_f_transition"]):
        return _rejection("f_transition", f_transition)

    live_bundle, live_deltas, _proposal, _requirements, _frontiers = build_l_inputs(
        f_transition
    )
    if canonical_bytes(live_deltas) != canonical_bytes(inputs["bootstrap_input_deltas"]):
        return _rejection("bootstrap_input_deltas", inputs["bootstrap_input_deltas"])
    rule_bundle = inputs["rule_bundle"]
    if canonical_bytes(live_bundle) != canonical_bytes(rule_bundle):
        # Let the public incremental boundary produce the typed cause when possible.
        candidate = step_incremental_l(
            None,
            rule_bundle,
            inputs["bootstrap_input_deltas"],
            accepted_event["logical_time"],
        )
        return _rejection("bootstrap_logic_step", candidate)

    bootstrap_step = step_incremental_l(
        None,
        rule_bundle,
        inputs["bootstrap_input_deltas"],
        accepted_event["logical_time"],
    )
    if not isinstance(bootstrap_step, dict) or bootstrap_step.get("kind") != "LPersistentLStep":
        return _rejection("bootstrap_logic_step", bootstrap_step)

    reuse_input_deltas: list[Dict[str, Any]] = []
    reuse_step = step_incremental_l(
        bootstrap_step["next_checkpoint"],
        rule_bundle,
        reuse_input_deltas,
        accepted_event["logical_time"] + 1,
    )
    if not isinstance(reuse_step, dict) or reuse_step.get("kind") != "LPersistentLStep":
        return _rejection("reuse_logic_step", reuse_step)
    reuse_receipt = reuse_step["reuse_receipt"]
    if (
        reuse_receipt["candidate_cache_hits"] < 1
        or reuse_receipt["executed_candidate_body_evaluations"] != 0
        or reuse_receipt["prior_checkpoint_digest"]
        != bootstrap_step["next_checkpoint"]["checkpoint_digest"]
    ):
        return _rejection("reuse_logic_step", reuse_step)

    final_l_result = reuse_step["fixpoint_result"]
    rule_bundle_again, r_profile, binding_profile, query_batch = build_lr_inputs(
        f_transition, final_l_result
    )
    if canonical_bytes(rule_bundle) != canonical_bytes(rule_bundle_again):
        return _rejection("query_batch", query_batch)
    lr_projection = project_lr(
        final_l_result, rule_bundle, r_profile, binding_profile, query_batch
    )
    if not isinstance(lr_projection, dict) or lr_projection.get("kind") != "LRProjectionResult":
        return _rejection("lr_projection", lr_projection)

    r_apply = _require_kind(
        step_r(None, r_profile, lr_projection["command"]),
        "RTransition",
        "r_apply_transition",
    )
    r_state = r_apply["next_state"]
    final_logical_time = final_l_result["logical_time"]
    r_state, frontier_equal = _advance_frontiers(
        r_state, r_profile, final_logical_time
    )
    if r_state["ready_batches"]:
        raise RuntimeError("R published M4C-IL stability at equality")
    r_state, frontier_passed = _advance_frontiers(
        r_state, r_profile, final_logical_time + 1
    )
    if len(r_state["ready_batches"]) != 1:
        raise RuntimeError("R did not produce one M4C-IL ready batch")
    demand = {
        "kind": "RGrantDemand",
        "schema_version": "flrh-r-command/1",
        "profile_digest": r_profile["profile_digest"],
        "dataflow_version": r_profile["dataflow_version"],
        "batches": 1,
    }
    r_publish = _require_kind(
        step_r(r_state, r_profile, demand), "RTransition", "r_publish_transition"
    )
    if len(r_publish["published_batches"]) != 1:
        raise RuntimeError("R did not publish one M4C-IL batch")
    published = r_publish["published_batches"][0]

    h_command = build_low_risk_h_command(published, r_profile["profile_digest"])
    h_projection = _require_kind(
        project_h_intent(h_command), "HProjection", "h_projection"
    )
    if h_projection["event"] != "EFFECT_AUTHORIZED":
        return _rejection("h_projection", h_projection)
    intent = h_projection["intent"]
    receipt_binding = build_receipt_binding(
        accepted_event, h_command, bootstrap_step, reuse_step
    )
    checkpoint = build_durable_checkpoint(h_projection, bootstrap_step, reuse_step)

    replay_mode = (
        "crash_after_external_success" if crash_after_external_success else "happy"
    )
    recovery = None
    with tempfile.TemporaryDirectory(prefix="flrh-m4cil-") as raw:
        workdir = Path(raw)
        database = workdir / "harness.sqlite3"
        adapter_path = workdir / "fake-adapter.sqlite3"
        run_id = intent["correlation_id"]

        if crash_after_external_success:
            worker_envelope = {
                "kind": "M4CILCrashWorkerEnvelope",
                "schema_version": "flrh-m4cil-crash-worker/1",
                "h_command": fresh(h_command),
                "receipt_binding": fresh(receipt_binding),
                "checkpoint": fresh(checkpoint),
            }
            worker_payload_digest = canonical_digest(worker_envelope)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--crash-worker",
                    str(database),
                    str(adapter_path),
                ],
                cwd=workdir,
                input=canonical_bytes(worker_envelope) + b"\n",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if completed.returncode != 86 or completed.stdout or completed.stderr:
                raise RuntimeError(
                    "M4C-IL crash worker drift: "
                    + json.dumps(
                        {
                            "returncode": completed.returncode,
                            "stdout": completed.stdout.decode("utf-8", "replace"),
                            "stderr": completed.stderr.decode("utf-8", "replace"),
                        },
                        sort_keys=True,
                    )
                )
            counts_at_crash = _counts(adapter_path)
            if counts_at_crash["mutation_count"] != 1:
                raise RuntimeError("M4C-IL crash worker mutation drift")
            pre_recovery = verify_run(database, run_id)
            adapter = FakeAdapter(durable_path=adapter_path)
            harness = DurableHarness(
                database,
                adapter,
                now=lambda: 111,
                receipt_evidence=build_receipt_evidence(h_projection),
            )
            token = harness.acquire_lease(
                run_id, "runner:m4cil:recovery", ttl_seconds=10
            )
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
            token = harness.acquire_lease(run_id, "runner:m4cil", ttl_seconds=10)
            if not harness.commit_intent(
                token, intent, receipt_binding=receipt_binding
            ):
                raise RuntimeError("fresh M4C-IL intent was not committed")
            post_commit_verification = verify_run(database, run_id)
            action = harness.dispatch_next(token)
            if action is None or action.get("outcome") != "confirmed_success":
                raise RuntimeError("M4C-IL fake destination did not confirm success")

        receipts = harness.receipts(run_id)
        if len(receipts) != 1:
            raise RuntimeError("M4C-IL durable store receipt cardinality drift")
        action_receipt = receipts[0]
        durable_verification = verify_run(database, run_id)
        durable_status = harness.run_status(run_id)
        durable_checkpoint_readback = harness.load_checkpoint(run_id)
        adapter_counts = _counts(adapter_path)
        harness.close()

    trace = _build_trace(
        accepted_event,
        final_l_result,
        r_profile,
        frontier_passed,
        h_projection,
        receipt_binding,
        action_receipt,
        post_commit_verification,
        durable_verification,
    )
    evidence = {
        "kind": "M4CILReplayEvidence",
        "schema_version": "flrh-m4cil-replay/1",
        "contract_version": M4CIL_CONTRACT,
        "profile_id": M4CIL_PROFILE,
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
        "adapter_profile": "FakeAdapter",
        "accepted_event": fresh(accepted_event),
        "f_transition": fresh(f_transition),
        "rule_bundle": fresh(rule_bundle),
        "bootstrap_input_deltas": fresh(inputs["bootstrap_input_deltas"]),
        "bootstrap_logic_step": fresh(bootstrap_step),
        "reuse_input_deltas": [],
        "reuse_logic_step": fresh(reuse_step),
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
        "durable_checkpoint": fresh(checkpoint),
        "durable_checkpoint_readback": fresh(durable_checkpoint_readback),
        "receipt_binding": fresh(receipt_binding),
        "action_receipt": fresh(action_receipt),
        "m4b_verification": fresh(durable_verification),
        "durable_run_status": durable_status,
        "adapter_counts": adapter_counts,
        "recovery": recovery,
        "trace": trace,
    }
    evidence["evidence_digest"] = canonical_digest({
        "kind": "M4CILEvidencePreimage",
        "contract_version": M4CIL_CONTRACT,
        **fresh(evidence),
    })
    return evidence


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "--crash-worker":
        return _run_crash_worker(
            Path(sys.argv[2]), Path(sys.argv[3]), json.loads(sys.stdin.buffer.read())
        )
    if len(sys.argv) != 1:
        raise ValueError("unsupported M4C-IL replay arguments")
    mode = "happy"
    if not sys.stdin.isatty():
        raw = sys.stdin.buffer.read()
        if raw.strip():
            value = json.loads(raw)
            if not isinstance(value, dict) or set(value) - {"mode"}:
                raise ValueError("M4C-IL replay envelope must contain only mode")
            mode = value.get("mode", "happy")
    if mode not in ("happy", "crash_after_external_success"):
        raise ValueError("unsupported M4C-IL replay mode")
    result = run_incremental_reference_chain(mode == "crash_after_external_success")
    sys.stdout.buffer.write(canonical_bytes(result) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
