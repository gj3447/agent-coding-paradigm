from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("validate_m0", ROOT / "scripts" / "validate_m0.py")
assert SPEC and SPEC.loader
M0 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M0)


class M0ContractTests(unittest.TestCase):
    def test_schemas_and_protocol_mutations(self) -> None:
        counts = M0.validate_schemas_and_fixtures()
        self.assertEqual(counts["schemas"], 10)
        self.assertEqual(counts["valid_protocol"], 10)
        self.assertEqual(counts["invalid_protocol"], 13)

    def test_logic_oracle(self) -> None:
        counts = M0.validate_logic()
        self.assertEqual(counts["truth"], 4)
        self.assertEqual(counts["default_negation"], 4)

    def test_canonical_golden_cases(self) -> None:
        counts = M0.validate_canonicalization()
        self.assertEqual(counts["canonical_different"], 2)
        self.assertEqual(counts["canonical_reject"], 5)

    def test_fsm_and_trace_coverage(self) -> None:
        counts = M0.validate_fsm()
        self.assertEqual(counts["fsm_transitions"], 25)
        self.assertEqual(counts["fsm_traces"], 18)
        self.assertEqual(counts["fsm_terminals"], 9)
        self.assertEqual(counts["fsm_interrupts"], 3)

    def test_bounded_loop_and_effect_closure(self) -> None:
        counts = M0.validate_loop()
        self.assertEqual(counts["loop_bound_states"], 20)
        self.assertEqual(counts["loop_bound_transitions"], 25)
        self.assertEqual(counts["effect_critical_states"], 5)

    def test_manifest_closes_only_m0(self) -> None:
        counts = M0.validate_manifest()
        self.assertEqual(counts["manifest_contracts"], 9)
        self.assertEqual(counts["manifest_schemas"], 10)
        self.assertEqual(counts["manifest_fixtures"], 5)
        self.assertEqual(counts["manifest_tools"], 2)


if __name__ == "__main__":
    unittest.main()
