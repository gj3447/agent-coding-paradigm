"""Ordinary discovery entry point for the proposed M4C-IL aggregate gate."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class M4CILCandidateGateTests(unittest.TestCase):
    def test_proposed_aggregate_gate_is_manifested_and_nonrecursive(self):
        manifest = json.loads(
            (ROOT / "spec/m4cil-manifest.v1.json").read_text(encoding="utf-8")
        )
        self.assertEqual("PROPOSED_PENDING_MEASUREMENT", manifest["status"])
        self.assertEqual(14, len(manifest["owned_closure"]))
        self.assertEqual(14, len(set(manifest["owned_closure"])))
        self.assertIn("tests/test_m4cil_candidate_gate.py", manifest["owned_closure"])
        self.assertEqual(36, len(manifest["inherited_sha256_pins"]))

        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts/validate_m4cil.py"), "--allow-proposed"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        self.assertEqual("PROPOSED_PENDING_MEASUREMENT", report["status"])
        self.assertEqual(14, report["manifest_owned_paths"])
        self.assertEqual(36, report["inherited_dependencies"])
        self.assertEqual(7, report["public_pipeline_stages"])
        self.assertEqual(2, report["success_paths"])
        self.assertEqual(1, report["crash_recovery_paths"])
        self.assertEqual(16, report["sensitivity_cases"])
        self.assertEqual(4, report["clean_processes"])
        self.assertEqual(10, report["verification_checks"])
        self.assertEqual(1, report["unit_test_gate"])
        self.assertIn(report["closure_mode"], {"precommit-added-only", "committed-clean"})
        expected_gate = (
            "DEFERRED_UNTIL_COMMITTED_CLEAN"
            if report["closure_mode"] == "precommit-added-only"
            else "PASS"
        )
        self.assertEqual(expected_gate, report["inherited_gate_state"])


if __name__ == "__main__":
    unittest.main()
