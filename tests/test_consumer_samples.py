from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_consumer_samples", ROOT / "scripts" / "validate_consumer_samples.py"
)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)
CORPUS = json.loads((ROOT / "fixtures/consumer-samples/cases.json").read_text(encoding="utf-8"))


class ConsumerSampleTests(unittest.TestCase):
    def test_proposed_synthetic_corpus_is_admitted(self) -> None:
        report = VALIDATOR.validate()
        self.assertEqual("PROPOSED_CORPUS_ADMISSION", report["status"])
        self.assertEqual(1, report["samples"])
        self.assertEqual(6, report["variants"])
        self.assertEqual(6, report["data_lanes"])

    def test_private_value_is_rejected_even_when_schema_valid(self) -> None:
        corpus = copy.deepcopy(CORPUS)
        corpus["samples"][0]["task"]["objective"] = "Send the job to 192.0.2.10"
        with self.assertRaisesRegex(AssertionError, "ipv4 leaked"):
            VALIDATOR.validate(corpus)

    def test_unknown_outcome_cannot_bypass_reconciliation(self) -> None:
        corpus = copy.deepcopy(CORPUS)
        variants = corpus["samples"][0]["variants"]
        unknown = next(item for item in variants if item["variant_id"] == "variant:unknown-after-dispatch")
        unknown["expected_route"] = ["dispatch", "verify", "terminal"]
        with self.assertRaisesRegex(AssertionError, "bypasses reconciliation"):
            VALIDATOR.validate(corpus)

    def test_duplicate_identity_cannot_become_retry(self) -> None:
        corpus = copy.deepcopy(CORPUS)
        variants = corpus["samples"][0]["variants"]
        duplicate = next(item for item in variants if item["variant_id"] == "variant:duplicate-intent-conflict")
        duplicate["expected_route"] = ["reconcile", "retry"]
        with self.assertRaisesRegex(AssertionError, "identity conflict became retry"):
            VALIDATOR.validate(corpus)

    def test_producer_self_report_cannot_complete(self) -> None:
        corpus = copy.deepcopy(CORPUS)
        variants = corpus["samples"][0]["variants"]
        self_report = next(item for item in variants if item["variant_id"] == "variant:producer-self-report-only")
        self_report["expected_route"] = ["verification_required", "terminal"]
        self_report["expected_terminal"] = "SUCCEEDED"
        with self.assertRaisesRegex(AssertionError, "self-report completed"):
            VALIDATOR.validate(corpus)


if __name__ == "__main__":
    unittest.main()
