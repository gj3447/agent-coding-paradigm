#!/usr/bin/env python3
"""Failing-first conformance tests for the bounded M4C-IL profile."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from flrh_kernel.canonical import canonical_bytes, canonical_digest
from m4cil_fixtures import (
    M4CIL_CONTRACT,
    build_incremental_input_root_digest,
    build_l_inputs,
    load_chain_inputs,
)
from m4cil_verifier import verify_m4cil_evidence
from run_m4cil_replay import run_incremental_reference_chain
from validate_m4cil import _assert_semantic_boundaries


class M4CILIntegrationTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.happy = run_incremental_reference_chain(False)
        cls.crash = run_incremental_reference_chain(True)

    def test_01_happy_chain_uses_real_incremental_checkpoint_reuse(self):
        value = self.happy
        self.assertEqual(value["kind"], "M4CILReplayEvidence")
        self.assertEqual(value["status"], "SLICE_CONFORMED")
        self.assertEqual(value["replay_mode"], "happy")
        bootstrap = value["bootstrap_logic_step"]
        reuse = value["reuse_logic_step"]
        self.assertEqual(bootstrap["kind"], "LPersistentLStep")
        self.assertEqual(reuse["kind"], "LPersistentLStep")
        _, expected_deltas, _, _, _ = build_l_inputs(value["f_transition"])
        self.assertEqual(value["bootstrap_input_deltas"], expected_deltas)
        self.assertEqual(value["reuse_input_deltas"], [])
        self.assertEqual(
            reuse["reuse_receipt"]["prior_checkpoint_digest"],
            bootstrap["next_checkpoint"]["checkpoint_digest"],
        )
        self.assertEqual(
            reuse["fixpoint_result"]["prior_materialization_digest"],
            bootstrap["fixpoint_result"]["next_materialization"]["materialization_digest"],
        )
        self.assertGreater(reuse["reuse_receipt"]["candidate_cache_hits"], 0)
        self.assertEqual(reuse["reuse_receipt"]["executed_candidate_body_evaluations"], 0)
        self.assertEqual(reuse["reuse_receipt"]["public_m2_solve_calls"], 2)
        self.assertEqual(value["lr_projection"]["l_fixpoint_digest"], reuse["fixpoint_result"]["fixpoint_digest"])

    def test_02_reuse_accounting_frontier_and_durable_receipt_are_exact(self):
        value = self.happy
        receipt = value["reuse_logic_step"]["reuse_receipt"]
        self.assertEqual(
            receipt["candidate_cache_hits"] + receipt["candidate_cache_misses"],
            receipt["candidate_cache_lookups"],
        )
        self.assertEqual(
            receipt["reused_candidate_body_evaluations"]
            + receipt["executed_candidate_body_evaluations"],
            receipt["accounted_candidate_body_evaluations"],
        )
        final_time = value["reuse_logic_step"]["fixpoint_result"]["logical_time"]
        self.assertEqual(final_time, 2)
        self.assertTrue(all(row["next_state"]["global_low_watermark"] == final_time for row in value["r_equal_frontier_transitions"][-1:]))
        self.assertTrue(all(row["next_state"]["global_low_watermark"] == final_time + 1 for row in value["r_passed_frontier_transitions"][-1:]))
        self.assertEqual(value["action_receipt"]["outcome"], "confirmed_success")
        self.assertEqual(value["m4b_verification"]["intent_count"], 1)
        self.assertEqual(value["m4b_verification"]["receipt_count"], 1)
        self.assertEqual(value["m4b_verification"]["pending_count"], 0)
        self.assertEqual(value["adapter_counts"], {"apply_count": 1, "mutation_count": 1, "query_count": 0})
        self.assertEqual(
            value["receipt_binding"]["input_root_digest"],
            build_incremental_input_root_digest(
                value["accepted_event"],
                value["bootstrap_logic_step"],
                value["reuse_logic_step"],
            ),
        )

    def test_03_durable_checkpoint_readback_preserves_incremental_lineage(self):
        value = self.happy
        initial = value["durable_checkpoint"]
        readback = value["durable_checkpoint_readback"]
        for key in (
            "bootstrap_step_digest",
            "bootstrap_checkpoint_digest",
            "reuse_step_digest",
            "logic_fixpoint_digest",
            "logic_checkpoint",
            "projection_digest",
        ):
            self.assertEqual(readback[key], initial[key])
        self.assertEqual(readback["last_committed_intent_id"], value["h_projection"]["intent"]["intent_id"])
        self.assertEqual(readback["last_receipt_digest"], canonical_digest(value["action_receipt"]))

    def test_04_actual_subprocess_crash_reopens_and_reconciles_without_resend(self):
        value = self.crash
        recovery = value["recovery"]
        self.assertEqual(value["replay_mode"], "crash_after_external_success")
        self.assertEqual(recovery["process_model"], "subprocess_os_exit_reopen")
        self.assertEqual(recovery["worker_exit_code"], 86)
        self.assertEqual(recovery["mutation_count_at_crash"], 1)
        self.assertEqual(recovery["pre_recovery_verification"]["pending_count"], 1)
        self.assertEqual(recovery["reconciliation_result"], "confirmed_success")
        self.assertEqual(value["adapter_counts"], {"apply_count": 1, "mutation_count": 1, "query_count": 1})
        self.assertEqual(value["m4b_verification"]["receipt_count"], 1)
        self.assertEqual(value["m4b_verification"]["pending_count"], 0)

    def test_05_source_bound_verifier_rejects_coherent_redigested_forgery(self):
        attacks = []

        lineage = copy.deepcopy(self.happy)
        lineage["reuse_logic_step"]["reuse_receipt"]["candidate_cache_hits"] += 1
        attacks.append(lineage)

        checkpoint = copy.deepcopy(self.happy)
        checkpoint["durable_checkpoint"]["logic_checkpoint"]["through_logical_time"] += 1
        attacks.append(checkpoint)

        feed = copy.deepcopy(self.happy)
        feed["lr_projection"]["l_fixpoint_digest"] = feed["bootstrap_logic_step"]["fixpoint_result"]["fixpoint_digest"]
        attacks.append(feed)

        crash = copy.deepcopy(self.crash)
        crash["recovery"]["mutation_count_at_crash"] = 2
        attacks.append(crash)

        for value in attacks:
            value["evidence_digest"] = canonical_digest({
                "kind": "M4CILEvidencePreimage",
                "contract_version": M4CIL_CONTRACT,
                **{key: item for key, item in value.items() if key != "evidence_digest"},
            })
            with self.subTest(keys=sorted(value)):
                result = verify_m4cil_evidence(value)
                self.assertEqual(result["kind"], "M4CILVerificationFailure")

    def test_06_verifier_reexecutes_sources_instead_of_trusting_stored_stages(self):
        forged = copy.deepcopy(self.happy)
        forged["accepted_event"]["logical_time"] += 10
        forged["accepted_event"]["event_digest"] = canonical_digest({
            "kind": "AcceptedEventPreimage",
            **{key: value for key, value in forged["accepted_event"].items() if key != "event_digest"},
        })
        result = verify_m4cil_evidence(forged)
        self.assertEqual(result["kind"], "M4CILVerificationFailure")

    def test_07_public_inputs_are_immutable(self):
        inputs = load_chain_inputs()
        before = canonical_bytes(inputs)
        run_incremental_reference_chain(False, chain_inputs=inputs)
        self.assertEqual(canonical_bytes(inputs), before)

    def test_08_incremental_rejection_stops_before_lr_r_h_and_effects(self):
        inputs = load_chain_inputs()
        inputs["rule_bundle"]["rule_bundle_digest"] = "sha256:" + "0" * 64
        with mock.patch("run_m4cil_replay.project_lr") as lr, mock.patch("run_m4cil_replay.step_r") as reactive, mock.patch("run_m4cil_replay.project_h_intent") as authority:
            result = run_incremental_reference_chain(False, chain_inputs=inputs)
        self.assertEqual(result["kind"], "M4CILReplayRejection")
        lr.assert_not_called()
        reactive.assert_not_called()
        authority.assert_not_called()

    def test_09_two_clean_processes_match_for_happy_and_crash(self):
        runner = ROOT / "scripts/run_m4cil_replay.py"
        for mode in ("happy", "crash_after_external_success"):
            payload = canonical_bytes({"mode": mode}) + b"\n"
            outputs = []
            for seed, timezone in (("1", "UTC"), ("777", "Pacific/Honolulu")):
                completed = subprocess.run(
                    [sys.executable, str(runner)],
                    cwd=ROOT,
                    input=payload,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env={**dict(__import__("os").environ), "PYTHONHASHSEED": seed, "TZ": timezone, "PYTHONDONTWRITEBYTECODE": "1"},
                    check=True,
                )
                self.assertEqual(completed.stderr, b"")
                outputs.append(completed.stdout)
            self.assertEqual(outputs[0], outputs[1])

    def test_10_claim_boundaries_and_verification_receipt_are_schema_closed(self):
        contract = json.loads(
            (ROOT / "spec/m4cil-integration-contract.v1.json").read_text()
        )
        cases = json.loads((ROOT / "fixtures/m4cil/cases.json").read_text())
        manifest = json.loads((ROOT / "spec/m4cil-manifest.v1.json").read_text())
        contract_schema = json.loads(
            (
                ROOT
                / "spec/schema/m4cil-integration-contract.v1.schema.json"
            ).read_text()
        )
        fixture_schema = json.loads(
            (ROOT / "spec/schema/m4cil-fixtures.v1.schema.json").read_text()
        )
        manifest_schema = json.loads(
            (ROOT / "spec/schema/m4cil-manifest.v1.schema.json").read_text()
        )
        docs = (ROOT / "docs/M4CIL_INTEGRATED_INCREMENTAL_SLICE.md").read_text()

        evil_claims = [f"evil-{index}" for index in range(10)]
        attacks = []
        value = copy.deepcopy(contract)
        value["purpose"] = "Promote a production engine."
        attacks.append((contract_schema, value))
        value = copy.deepcopy(contract)
        value["non_claims"] = evil_claims
        attacks.append((contract_schema, value))
        value = copy.deepcopy(contract)
        value["completion_boundary"] = "PRODUCTION READY"
        attacks.append((contract_schema, value))
        value = copy.deepcopy(cases)
        value["non_claims"] = evil_claims
        attacks.append((fixture_schema, value))
        value = copy.deepcopy(manifest)
        value["completion_boundary"] = "ENGINE AND LAKATOS PROGRESS"
        attacks.append((manifest_schema, value))
        for schema, value in attacks:
            with self.subTest(keys=sorted(value)):
                self.assertFalse(Draft202012Validator(schema).is_valid(value))

        value = copy.deepcopy(contract)
        value["non_claims"] = evil_claims
        with self.assertRaisesRegex(AssertionError, "non-claim boundary drift"):
            _assert_semantic_boundaries(value, cases, docs)
        value = copy.deepcopy(cases)
        value["non_claims"] = evil_claims
        with self.assertRaisesRegex(AssertionError, "non-claim boundary drift"):
            _assert_semantic_boundaries(contract, value, docs)

        receipt_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": contract_schema["$defs"],
            "$ref": "#/$defs/VerificationReceipt",
        }
        receipt = verify_m4cil_evidence(self.happy)
        value = copy.deepcopy(receipt)
        value["checks"] = [f"evil-{index}" for index in range(10)]
        self.assertFalse(Draft202012Validator(receipt_schema).is_valid(value))
        value = copy.deepcopy(receipt)
        value["stage_digests"] = {
            f"evil-{index}": "sha256:" + f"{index:064x}" for index in range(11)
        }
        self.assertFalse(Draft202012Validator(receipt_schema).is_valid(value))


if __name__ == "__main__":
    unittest.main()
