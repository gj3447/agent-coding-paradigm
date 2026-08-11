from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_agent_source_registry", ROOT / "scripts" / "validate_agent_source_registry.py"
)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)
REGISTRY = json.loads((ROOT / "research/agent-coding-source-registry.v1.json").read_text(encoding="utf-8"))


class AgentSourceRegistryTests(unittest.TestCase):
    def test_pinned_metadata_snapshot_is_valid(self) -> None:
        report = VALIDATOR.validate()
        self.assertEqual("MEASURED_METADATA_SNAPSHOT_VALIDATED", report["status"])
        self.assertEqual(17, report["sources"])
        self.assertEqual({"Apache-2.0": 8, "MIT": 9}, report["license_counts"])
        self.assertEqual(0, report["vendored_sources"])
        self.assertFalse(report["stars_are_quality_evidence"])

    def test_stars_cannot_be_promoted_to_quality_evidence(self) -> None:
        registry = copy.deepcopy(REGISTRY)
        registry["selection"]["stars_are_quality_evidence"] = True
        with self.assertRaisesRegex(AssertionError, "schema rejection"):
            VALIDATOR.validate(registry)

    def test_vendoring_cannot_be_silently_enabled(self) -> None:
        registry = copy.deepcopy(REGISTRY)
        registry["selection"]["vendoring"] = True
        with self.assertRaisesRegex(AssertionError, "schema rejection"):
            VALIDATOR.validate(registry)

    def test_duplicate_repository_is_rejected(self) -> None:
        registry = copy.deepcopy(REGISTRY)
        registry["sources"][1]["repository"] = registry["sources"][0]["repository"]
        registry["sources"][1]["url"] = registry["sources"][0]["url"]
        with self.assertRaisesRegex(AssertionError, "duplicate repository"):
            VALIDATOR.validate(registry)

    def test_future_head_commit_is_rejected(self) -> None:
        registry = copy.deepcopy(REGISTRY)
        registry["sources"][0]["head_committed_at"] = "2026-08-12T00:00:00Z"
        with self.assertRaisesRegex(AssertionError, "future head commit"):
            VALIDATOR.validate(registry)


if __name__ == "__main__":
    unittest.main()
