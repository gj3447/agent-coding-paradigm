from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_agent_rule_routes", ROOT / "scripts" / "check_agent_rule_routes.py"
)
assert SPEC and SPEC.loader
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)
ROUTES = json.loads((ROOT / "agent-rules/routes.v1.json").read_text(encoding="utf-8"))


class AgentRuleRouteTests(unittest.TestCase):
    def test_routing_contract_is_admitted_without_prompt_cap(self) -> None:
        report = CHECKER.validate()
        self.assertEqual("PROPOSED_ROUTING_ADMISSION", report["status"])
        self.assertFalse(report["hard_prompt_token_limit"])
        self.assertFalse(report["truncation_allowed"])
        self.assertEqual(5, report["case_count"])
        self.assertTrue(all(case["tokens"] is None for case in report["cases"]))

    def test_large_relevant_rule_source_is_observed_not_rejected(self) -> None:
        semantic = (ROOT / "agent-rules/semantic-invariants.md").read_text(encoding="utf-8")
        report = CHECKER.validate(source_text_overrides={
            "agent-rules/semantic-invariants.md": semantic + ("\nRelevant explanatory evidence." * 10000)
        })
        kernel = next(case for case in report["cases"] if case["case_id"] == "route-case:kernel-change")
        self.assertGreater(kernel["context_observation"]["bytes"], 100000)

    def test_duplicate_rule_identity_is_a_conflict(self) -> None:
        semantic = (ROOT / "agent-rules/semantic-invariants.md").read_text(encoding="utf-8")
        with self.assertRaisesRegex(AssertionError, "duplicate rule ID GOV1"):
            CHECKER.validate(source_text_overrides={
                "agent-rules/semantic-invariants.md": semantic + "\n- `GOV1` — conflicting duplicate.\n"
            })

    def test_prompt_limit_cannot_be_enabled(self) -> None:
        routes = copy.deepcopy(ROUTES)
        routes["context_policy"]["hard_prompt_token_limit"] = True
        with self.assertRaisesRegex(AssertionError, "schema rejection"):
            CHECKER.validate(routes_document=routes)

    def test_manifest_closure_cannot_become_preload(self) -> None:
        routes = copy.deepcopy(ROUTES)
        routes["resolution"]["manifest_closure_semantics"] = "preload"
        with self.assertRaisesRegex(AssertionError, "schema rejection"):
            CHECKER.validate(routes_document=routes)


if __name__ == "__main__":
    unittest.main()
