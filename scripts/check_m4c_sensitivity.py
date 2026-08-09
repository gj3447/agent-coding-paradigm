#!/usr/bin/env python3
"""Behavioral adjacent-binding sensitivity checks for the M4C verifier."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from flrh_kernel.canonical import canonical_digest
from m4c_verifier import verify_m4c_evidence
from run_m4c_replay import run_reference_chain


def _redigest(value):
    value.pop("evidence_digest", None)
    value["evidence_digest"] = canonical_digest({
        "kind": "M4CReplayEvidencePreimage",
        "contract_version": "flrh-m4c-integration/1",
        "evidence": copy.deepcopy(value),
    })


def _mutations(baseline, crash):
    rows = []

    def adjacent(path, mutate):
        value = copy.deepcopy(baseline)
        mutate(value)
        rows.append((path, value))

    adjacent("/l_input_deltas/0/delta/causation_id", lambda value: value["l_input_deltas"][0]["delta"].__setitem__("causation_id", "event:forged"))
    adjacent("/lr_projection/l_materialization_digest", lambda value: value["lr_projection"].__setitem__("l_materialization_digest", "sha256:" + "0" * 64))
    adjacent("/r_published_batch/effect_proposals/0/proposal_id", lambda value: value["r_published_batch"]["effect_proposals"][0].__setitem__("proposal_id", "proposal:forged"))
    adjacent("/h_projection/intent/proposal_id", lambda value: value["h_projection"]["intent"].__setitem__("proposal_id", "proposal:forged"))
    adjacent("/receipt_binding/command_digest", lambda value: value["receipt_binding"].__setitem__("command_digest", "sha256:" + "1" * 64))
    adjacent("/action_receipt/intent_id", lambda value: value["action_receipt"].__setitem__("intent_id", "intent:forged"))
    adjacent("/m4b_verification/pending_count", lambda value: value["m4b_verification"].__setitem__("pending_count", 1))
    adjacent("/trace/2/event", lambda value: value["trace"][2].__setitem__("event", "EFFECT_AUTHORIZED"))

    stale_outer = copy.deepcopy(baseline)
    stale_outer["evidence_digest"] = "sha256:" + "f" * 64
    rows.append(("/evidence_digest", stale_outer))

    forged_f = copy.deepcopy(baseline)
    forged_tuple = forged_f["f_transition"]["fact_deltas"][0]["tuple"]
    forged_tuple["artifact_digest"] = "sha256:" + "a" * 64
    forged_f["l_input_deltas"][0]["delta"]["tuple"] = copy.deepcopy(forged_tuple)
    _redigest(forged_f)
    rows.append(("/f_transition/fact_deltas/0/tuple/artifact_digest", forged_f))

    forged_l = copy.deepcopy(baseline)
    forged_l["l_result"]["stats"]["rule_firing_count"] += 1
    _redigest(forged_l)
    rows.append(("/l_result/stats/rule_firing_count", forged_l))

    forged_proposal = copy.deepcopy(baseline)
    for proposal in (
        forged_proposal["f_transition"]["effect_proposals"][0],
        forged_proposal["r_published_batch"]["effect_proposals"][0],
        forged_proposal["h_command"]["published_batch"]["effect_proposals"][0],
    ):
        proposal["proposal_id"] = "proposal:forged"
    forged_proposal["h_projection"]["intent"]["proposal_id"] = "proposal:forged"
    _redigest(forged_proposal)
    rows.append(("/f_transition/effect_proposals/0/proposal_id", forged_proposal))

    forged_intent = copy.deepcopy(baseline)
    forged_intent["h_projection"]["intent"]["intent_id"] = "intent:forged"
    forged_intent["action_receipt"]["intent_id"] = "intent:forged"
    _redigest(forged_intent)
    rows.append(("/h_projection/intent/intent_id", forged_intent))

    missing_chain = copy.deepcopy(baseline)
    for key in (
        "accepted_event", "rule_bundle", "binding_profile", "query_batch", "r_profile",
        "r_apply_transition", "r_equal_frontier_transitions",
        "r_passed_frontier_transitions", "r_publish_transition",
    ):
        missing_chain.pop(key)
    _redigest(missing_chain)
    rows.append(("/accepted_event", missing_chain))

    forged_recovery = copy.deepcopy(baseline)
    forged_recovery["recovery"] = copy.deepcopy(crash["recovery"])
    forged_recovery["adapter_counts"] = copy.deepcopy(crash["adapter_counts"])
    _redigest(forged_recovery)
    rows.append(("/recovery", forged_recovery))

    missing_stage_digest = copy.deepcopy(baseline)
    missing_stage_digest["f_transition"].pop("transition_digest")
    _redigest(missing_stage_digest)
    rows.append(("/f_transition/transition_digest", missing_stage_digest))
    return tuple(rows)


def main() -> int:
    baseline = run_reference_chain()
    baseline_result = verify_m4c_evidence(baseline)
    if baseline_result.get("kind") != "M4CVerificationReceipt":
        raise AssertionError("M4C pristine baseline did not verify")
    crash = run_reference_chain(crash_after_external_success=True)
    crash_result = verify_m4c_evidence(crash)
    if crash_result.get("kind") != "M4CVerificationReceipt":
        raise AssertionError("M4C crash baseline did not verify")

    detected = []
    escaped = []
    for expected_path, value in _mutations(baseline, crash):
        result = verify_m4c_evidence(value)
        if (
            result.get("kind") == "M4CVerificationFailure"
            and result.get("code") == "INTEGRATION_BINDING_MISMATCH"
            and result.get("path") == expected_path
        ):
            detected.append(expected_path)
        else:
            escaped.append({"expected_path": expected_path, "result": result})
    if escaped:
        raise AssertionError("M4C sensitivity escape: " + json.dumps(escaped, sort_keys=True))

    report = {
        "kind": "M4CSensitivityReport",
        "schema_version": "flrh-m4c-sensitivity/1",
        "baseline_verified": True,
        "sensitivity_cases": len(detected),
        "sensitivity_cases_detected": len(detected),
        "escaped": 0,
        "paths": detected,
    }
    print(json.dumps(report, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
