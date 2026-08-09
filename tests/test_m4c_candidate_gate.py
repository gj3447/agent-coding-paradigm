"""Ordinary discovery entry point for the explicit proposed M4C aggregate gate."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class M4CCandidateGateTests(unittest.TestCase):
    def test_proposed_aggregate_gate_is_manifested_and_nonrecursive(self):
        manifest = json.loads((ROOT / "spec/m4c-manifest.v1.json").read_text(encoding="utf-8"))
        self.assertIn("tests/test_m4c_candidate_gate.py", manifest["tools"])
        self.assertIn("spec/m4c-manifest.v1.json", manifest["normative_contracts"])
        self.assertEqual(18, len(manifest["inherited_dependencies"]))
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts/validate_m4c.py"), "--allow-proposed"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        self.assertEqual("PROPOSED_PENDING_MEASUREMENT", report["status"])
        self.assertEqual(2, report["success_paths"])
        self.assertEqual(16, report["sensitivity_cases"])
        self.assertEqual(4, report["clean_processes"])
        self.assertEqual(9, report["verification_checks"])


if __name__ == "__main__":
    unittest.main()
