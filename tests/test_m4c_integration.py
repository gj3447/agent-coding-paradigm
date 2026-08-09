"""Failing-first tests for the bounded M4C public integration profile."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from flrh_kernel.canonical import canonical_bytes, canonical_digest
from m4c_verifier import verify_m4c_evidence
from run_m4c_replay import run_reference_chain


class M4CIntegrationTests(unittest.TestCase):
    @staticmethod
    def _redigest(value):
        value.pop("evidence_digest", None)
        value["evidence_digest"] = canonical_digest({
            "kind": "M4CReplayEvidencePreimage",
            "contract_version": "flrh-m4c-integration/1",
            "evidence": copy.deepcopy(value),
        })

    def test_01_live_public_chain_closes_exactly_one_effect(self):
        evidence = run_reference_chain()
        receipt = verify_m4c_evidence(evidence)

        self.assertEqual("SLICE_CONFORMED", evidence["status"])
        self.assertEqual("HONOR_PENDING_INTERRUPT", evidence["outer_fsm_stop_state"])
        self.assertEqual("active", evidence["durable_run_status"])
        self.assertEqual("ActionReceipt", evidence["action_receipt"]["kind"])
        self.assertEqual("confirmed_success", evidence["action_receipt"]["outcome"])
        self.assertEqual({"intent_count": 1, "receipt_count": 1, "pending_count": 0}, {
            key: evidence["m4b_verification"][key]
            for key in ("intent_count", "receipt_count", "pending_count")
        })
        self.assertEqual("M4CVerificationReceipt", receipt["kind"])
        self.assertEqual("SLICE_CONFORMED", receipt["status"])

    def test_02_adjacent_lineage_mutations_fail_closed(self):
        baseline = run_reference_chain()
        mutations = (
            ("/l_input_deltas/0/delta/causation_id", lambda value: value["l_input_deltas"][0]["delta"].__setitem__("causation_id", "event:forged")),
            ("/lr_projection/l_materialization_digest", lambda value: value["lr_projection"].__setitem__("l_materialization_digest", "sha256:" + "0" * 64)),
            ("/r_published_batch/effect_proposals/0/proposal_id", lambda value: value["r_published_batch"]["effect_proposals"][0].__setitem__("proposal_id", "proposal:forged")),
            ("/h_projection/intent/proposal_id", lambda value: value["h_projection"]["intent"].__setitem__("proposal_id", "proposal:forged")),
            ("/receipt_binding/command_digest", lambda value: value["receipt_binding"].__setitem__("command_digest", "sha256:" + "1" * 64)),
            ("/action_receipt/intent_id", lambda value: value["action_receipt"].__setitem__("intent_id", "intent:forged")),
            ("/m4b_verification/pending_count", lambda value: value["m4b_verification"].__setitem__("pending_count", 1)),
            ("/trace/2/event", lambda value: value["trace"][2].__setitem__("event", "EFFECT_AUTHORIZED")),
        )
        for expected_path, mutate in mutations:
            with self.subTest(path=expected_path):
                value = copy.deepcopy(baseline)
                mutate(value)
                result = verify_m4c_evidence(value)
                self.assertEqual("M4CVerificationFailure", result["kind"])
                self.assertEqual("INTEGRATION_BINDING_MISMATCH", result["code"])
                self.assertEqual(expected_path, result["path"])

    def test_03_post_success_crash_reconciles_without_second_mutation(self):
        evidence = run_reference_chain(crash_after_external_success=True)
        receipt = verify_m4c_evidence(evidence)

        self.assertEqual("after_external_success", evidence["recovery"]["crash_point"])
        self.assertEqual(1, evidence["recovery"]["pre_recovery_verification"]["pending_count"])
        self.assertEqual("confirmed_success", evidence["recovery"]["reconciliation_result"])
        self.assertEqual({"apply_count": 1, "query_count": 1, "mutation_count": 1}, evidence["adapter_counts"])
        self.assertEqual("M4CVerificationReceipt", receipt["kind"])

    def test_04_replay_is_byte_deterministic(self):
        self.assertEqual(canonical_bytes(run_reference_chain()), canonical_bytes(run_reference_chain()))

    def test_05_contract_stays_proposed_and_never_claims_success(self):
        contract = json.loads((ROOT / "spec/m4c-integration-contract.v1.json").read_text(encoding="utf-8"))
        manifest = json.loads((ROOT / "spec/m4c-manifest.v1.json").read_text(encoding="utf-8"))
        self.assertEqual("PROPOSED_PENDING_MEASUREMENT", contract["status"])
        self.assertEqual("PROPOSED_PENDING_MEASUREMENT", manifest["status"])
        self.assertEqual("HONOR_PENDING_INTERRUPT", contract["fsm_projection"]["stop_state"])
        self.assertEqual("SLICE_CONFORMED", contract["fsm_projection"]["terminal_claim"])
        self.assertEqual("FSM_CONFORMANCE_PROJECTION_ONLY", contract["fsm_projection"]["trace_claim"])
        self.assertIs(False, contract["fsm_projection"]["outer_reducer_executed"])
        self.assertNotIn(b'"SUCCEEDED"', canonical_bytes(contract["fsm_projection"]))
        self.assertTrue(contract["constraints"]["prior_materialization_must_be_null"])
        self.assertEqual("FakeAdapter", contract["constraints"]["adapter_profile"])

    def test_06_cross_consistent_and_redigested_forgery_fails_closed(self):
        baseline = run_reference_chain()

        stale_outer = copy.deepcopy(baseline)
        stale_outer["evidence_digest"] = "sha256:" + "f" * 64

        forged_f = copy.deepcopy(baseline)
        forged_tuple = forged_f["f_transition"]["fact_deltas"][0]["tuple"]
        forged_tuple["artifact_digest"] = "sha256:" + "a" * 64
        forged_f["l_input_deltas"][0]["delta"]["tuple"] = copy.deepcopy(forged_tuple)
        self._redigest(forged_f)

        forged_l = copy.deepcopy(baseline)
        forged_l["l_result"]["stats"]["rule_firing_count"] += 1
        self._redigest(forged_l)

        forged_proposal = copy.deepcopy(baseline)
        for proposal in (
            forged_proposal["f_transition"]["effect_proposals"][0],
            forged_proposal["r_published_batch"]["effect_proposals"][0],
            forged_proposal["h_command"]["published_batch"]["effect_proposals"][0],
        ):
            proposal["proposal_id"] = "proposal:forged"
        forged_proposal["h_projection"]["intent"]["proposal_id"] = "proposal:forged"
        self._redigest(forged_proposal)

        forged_intent = copy.deepcopy(baseline)
        forged_intent["h_projection"]["intent"]["intent_id"] = "intent:forged"
        forged_intent["action_receipt"]["intent_id"] = "intent:forged"
        self._redigest(forged_intent)

        missing_r = copy.deepcopy(baseline)
        for key in (
            "accepted_event",
            "rule_bundle",
            "binding_profile",
            "query_batch",
            "r_profile",
            "r_apply_transition",
            "r_equal_frontier_transitions",
            "r_passed_frontier_transitions",
            "r_publish_transition",
        ):
            missing_r.pop(key)
        self._redigest(missing_r)

        crash = run_reference_chain(crash_after_external_success=True)
        forged_recovery = copy.deepcopy(baseline)
        forged_recovery["recovery"] = copy.deepcopy(crash["recovery"])
        forged_recovery["adapter_counts"] = copy.deepcopy(crash["adapter_counts"])
        self._redigest(forged_recovery)

        cases = (
            ("/evidence_digest", stale_outer),
            ("/f_transition/fact_deltas/0/tuple/artifact_digest", forged_f),
            ("/l_result/stats/rule_firing_count", forged_l),
            ("/f_transition/effect_proposals/0/proposal_id", forged_proposal),
            ("/h_projection/intent/intent_id", forged_intent),
            ("/accepted_event", missing_r),
            ("/recovery", forged_recovery),
        )
        for expected_path, value in cases:
            with self.subTest(path=expected_path):
                result = verify_m4c_evidence(value)
                self.assertEqual("M4CVerificationFailure", result["kind"])
                self.assertEqual("INTEGRATION_BINDING_MISMATCH", result["code"])
                self.assertEqual(expected_path, result["path"])

    def test_07_missing_stage_digest_is_a_typed_failure(self):
        value = run_reference_chain()
        value["f_transition"].pop("transition_digest")
        self._redigest(value)
        result = verify_m4c_evidence(value)
        self.assertEqual("M4CVerificationFailure", result["kind"])
        self.assertEqual("/f_transition/transition_digest", result["path"])

    def test_08_crash_recovery_is_a_real_process_boundary(self):
        evidence = run_reference_chain(crash_after_external_success=True)
        recovery = evidence["recovery"]
        self.assertEqual("subprocess_os_exit_reopen", recovery["process_model"])
        self.assertEqual(86, recovery["worker_exit_code"])
        self.assertEqual(1, recovery["mutation_count_at_crash"])
        self.assertEqual(111, recovery["reopen_epoch"])
        self.assertTrue(recovery["worker_payload_digest"].startswith("sha256:"))

    def test_09_receipt_and_detached_report_shapes_fail_closed(self):
        baseline = run_reference_chain()
        mutations = (
            ("/action_receipt/recorded_at", lambda value: value["action_receipt"].pop("recorded_at")),
            ("/action_receipt/extra", lambda value: value["action_receipt"].__setitem__("extra", "forged")),
            ("/m4b_verification/kind", lambda value: value["m4b_verification"].__setitem__("kind", "ForgedReport")),
            ("/m4b_verification/run_id", lambda value: value["m4b_verification"].__setitem__("run_id", "run:forged")),
            ("/m4b_verification/intent_count", lambda value: value["m4b_verification"].__setitem__("intent_count", True)),
        )
        for expected_path, mutate in mutations:
            with self.subTest(path=expected_path):
                value = copy.deepcopy(baseline)
                mutate(value)
                self._redigest(value)
                result = verify_m4c_evidence(value)
                self.assertEqual("M4CVerificationFailure", result["kind"])
                self.assertEqual(expected_path, result["path"])


if __name__ == "__main__":
    unittest.main()
