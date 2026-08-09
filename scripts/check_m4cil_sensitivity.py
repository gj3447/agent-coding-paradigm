#!/usr/bin/env python3
"""Behavioral source-binding sensitivity checks for the M4C-IL verifier."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from flrh_kernel.canonical import canonical_digest
from m4cil_fixtures import M4CIL_CONTRACT
from m4cil_verifier import verify_m4cil_evidence
from run_m4cil_replay import run_incremental_reference_chain


Mutation = Tuple[str, str, Dict[str, Any]]


def _redigest(value: Dict[str, Any]) -> None:
    value.pop("evidence_digest", None)
    value["evidence_digest"] = canonical_digest({
        "kind": "M4CILEvidencePreimage",
        "contract_version": M4CIL_CONTRACT,
        **copy.deepcopy(value),
    })


def _mutated(
    baseline: Dict[str, Any],
    case_id: str,
    expected_path: str,
    mutate: Callable[[Dict[str, Any]], None],
) -> Mutation:
    value = copy.deepcopy(baseline)
    mutate(value)
    _redigest(value)
    return case_id, expected_path, value


def _mutations(
    baseline: Dict[str, Any], crash: Dict[str, Any]
) -> List[Mutation]:
    zero = "sha256:" + "0" * 64
    one = "sha256:" + "1" * 64
    rows = [
        _mutated(
            baseline,
            "bootstrap-checkpoint-digest",
            "/bootstrap_logic_step/next_checkpoint/checkpoint_digest",
            lambda value: value["bootstrap_logic_step"]["next_checkpoint"].__setitem__(
                "checkpoint_digest", zero
            ),
        ),
        _mutated(
            baseline,
            "reuse-prior-checkpoint-digest",
            "/reuse_logic_step/reuse_receipt/prior_checkpoint_digest",
            lambda value: value["reuse_logic_step"]["reuse_receipt"].__setitem__(
                "prior_checkpoint_digest", zero
            ),
        ),
        _mutated(
            baseline,
            "reuse-cache-hit-accounting",
            "/reuse_logic_step/reuse_receipt/candidate_cache_hits",
            lambda value: value["reuse_logic_step"]["reuse_receipt"].__setitem__(
                "candidate_cache_hits",
                value["reuse_logic_step"]["reuse_receipt"]["candidate_cache_hits"] + 1,
            ),
        ),
        _mutated(
            baseline,
            "reuse-body-evaluation-accounting",
            "/reuse_logic_step/reuse_receipt/executed_candidate_body_evaluations",
            lambda value: value["reuse_logic_step"]["reuse_receipt"].__setitem__(
                "executed_candidate_body_evaluations", 1
            ),
        ),
        _mutated(
            baseline,
            "final-fixpoint-digest",
            "/reuse_logic_step/fixpoint_result/fixpoint_digest",
            lambda value: value["reuse_logic_step"]["fixpoint_result"].__setitem__(
                "fixpoint_digest", zero
            ),
        ),
        _mutated(
            baseline,
            "lr-fixpoint-binding",
            "/lr_projection/l_fixpoint_digest",
            lambda value: value["lr_projection"].__setitem__("l_fixpoint_digest", zero),
        ),
        _mutated(
            baseline,
            "accepted-event-logical-time",
            "/accepted_event/logical_time",
            lambda value: value["accepted_event"].__setitem__(
                "logical_time", value["accepted_event"]["logical_time"] + 1
            ),
        ),
        _mutated(
            baseline,
            "bootstrap-delta-causation",
            "/bootstrap_input_deltas/0/delta/causation_id",
            lambda value: value["bootstrap_input_deltas"][0]["delta"].__setitem__(
                "causation_id", "event:forged"
            ),
        ),
        _mutated(
            baseline,
            "r-frontier-logical-time",
            "/r_passed_frontier_transitions/0/next_state/global_low_watermark",
            lambda value: value["r_passed_frontier_transitions"][0][
                "next_state"
            ].__setitem__(
                "global_low_watermark",
                value["r_passed_frontier_transitions"][0]["next_state"][
                    "global_low_watermark"
                ]
                + 1,
            ),
        ),
        _mutated(
            baseline,
            "h-intent-proposal-id",
            "/h_projection/intent/proposal_id",
            lambda value: value["h_projection"]["intent"].__setitem__(
                "proposal_id", "proposal:forged"
            ),
        ),
        _mutated(
            baseline,
            "durable-checkpoint-logic-lineage",
            "/durable_checkpoint/logic_fixpoint_digest",
            lambda value: value["durable_checkpoint"].__setitem__(
                "logic_fixpoint_digest", zero
            ),
        ),
        _mutated(
            baseline,
            "receipt-input-root-binding",
            "/receipt_binding/input_root_digest",
            lambda value: value["receipt_binding"].__setitem__(
                "input_root_digest", one
            ),
        ),
        _mutated(
            baseline,
            "action-receipt-intent-id",
            "/action_receipt/intent_id",
            lambda value: value["action_receipt"].__setitem__(
                "intent_id", "intent:forged"
            ),
        ),
        _mutated(
            baseline,
            "durable-pending-count",
            "/m4b_verification/pending_count",
            lambda value: value["m4b_verification"].__setitem__("pending_count", 1),
        ),
        _mutated(
            baseline,
            "fsm-trace-event",
            "/trace/2/event",
            lambda value: value["trace"][2].__setitem__(
                "event", "EFFECT_AUTHORIZED"
            ),
        ),
        _mutated(
            crash,
            "crash-worker-payload-digest",
            "/recovery/worker_payload_digest",
            lambda value: value["recovery"].__setitem__(
                "worker_payload_digest", zero
            ),
        ),
    ]
    return rows


def main() -> int:
    baseline = run_incremental_reference_chain(False)
    crash = run_incremental_reference_chain(True)
    for label, value in (("happy", baseline), ("crash", crash)):
        result = verify_m4cil_evidence(value)
        if result.get("kind") != "M4CILVerificationReceipt":
            raise AssertionError(f"M4C-IL pristine {label} evidence failed: {result}")

    detected = []
    escaped = []
    for case_id, expected_path, value in _mutations(baseline, crash):
        result = verify_m4cil_evidence(value)
        if (
            result.get("kind") == "M4CILVerificationFailure"
            and result.get("code") == "EVIDENCE_MISMATCH"
            and result.get("path") == expected_path
        ):
            detected.append({"case": case_id, "path": expected_path})
        else:
            escaped.append({
                "case": case_id,
                "expected_path": expected_path,
                "result": result,
            })
    if escaped:
        raise AssertionError(
            "M4C-IL sensitivity escape: " + json.dumps(escaped, sort_keys=True)
        )

    report = {
        "kind": "M4CILSensitivityReport",
        "schema_version": "flrh-m4cil-sensitivity/1",
        "baseline_verified": True,
        "crash_baseline_verified": True,
        "sensitivity_cases": len(detected),
        "sensitivity_cases_detected": len(detected),
        "escaped": 0,
        "detected": detected,
    }
    print(json.dumps(report, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
