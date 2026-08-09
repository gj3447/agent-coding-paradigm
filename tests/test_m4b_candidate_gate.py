"""Ordinary discovery entry point for the explicit proposed M4B aggregate gate."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT=Path(__file__).resolve().parents[1]


class M4BCandidateGateTests(unittest.TestCase):
    def test_proposed_aggregate_gate_is_manifested_and_nonrecursive(self):
        manifest=json.loads((ROOT/"spec/m4b-manifest.v1.json").read_text(encoding="utf-8"))
        self.assertIn("tests/test_m4b_candidate_gate.py",manifest["tools"])
        self.assertIn("spec/m4b-manifest.v1.json",manifest["normative_contracts"])
        self.assertTrue(manifest["inherited_dependencies"])
        completed=subprocess.run([sys.executable,str(ROOT/"scripts/validate_m4b.py"),"--allow-proposed"],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.assertEqual(0,completed.returncode,completed.stderr or completed.stdout)
        self.assertIn('"status":"PROPOSED_PENDING_MEASUREMENT"',completed.stdout)


if __name__=="__main__": unittest.main()
