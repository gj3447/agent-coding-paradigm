"""Ordinary discovery entry point for the explicit proposed M4A aggregate gate."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class M4ACandidateGateTests(unittest.TestCase):
    def test_proposed_aggregate_gate(self):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts/validate_m4a.py"), "--allow-proposed"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
        self.assertIn('"status": "PROPOSED_PENDING_MEASUREMENT"', completed.stdout)


if __name__ == "__main__":
    unittest.main()
