from __future__ import annotations
import subprocess, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class M2ILCandidateGate(unittest.TestCase):
    def test_nonrecursive_candidate_validator(self):
        completed=subprocess.run([sys.executable,'scripts/validate_m2il.py'],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(completed.returncode,0,completed.stdout+completed.stderr)
if __name__=='__main__': unittest.main()
