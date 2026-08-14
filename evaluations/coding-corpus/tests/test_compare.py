from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import compare  # noqa: E402


class CompareCompatibilityTests(unittest.TestCase):
    def test_wrapper_forwards_arguments_to_the_typescript_composition_root(self) -> None:
        tsx = HERE / "node_modules" / ".bin" / "tsx"
        command = compare.compatibility_command(
            ["--corpus", "pilot.jsonl", "--dgx-base-url", "http://dgx:18000/v1"]
        )
        self.assertEqual(str(tsx), command[0])
        self.assertEqual(str(HERE / "src" / "compare-cli.ts"), command[1])
        self.assertEqual("--corpus", command[2])
        self.assertFalse(hasattr(compare, "list_eval_logs"))
        self.assertFalse(hasattr(compare, "build_eval_command"))

    def test_main_replaces_the_python_process_instead_of_duplicating_policy(self) -> None:
        with patch.object(compare.os, "execv") as execute:
            with self.assertRaisesRegex(AssertionError, "unexpectedly"):
                compare.main(["--arms", "react"])
        command = compare.compatibility_command(["--arms", "react"])
        execute.assert_called_once_with(command[0], command)


if __name__ == "__main__":
    unittest.main()
