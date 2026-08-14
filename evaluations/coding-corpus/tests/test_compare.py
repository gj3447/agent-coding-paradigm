from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from compare import (  # noqa: E402
    AIDER_CONTROL_MODEL,
    REACT_MODEL,
    _read_secret,
    build_eval_command,
)


class CompareRunnerTests(unittest.TestCase):
    def _command(self, agent: str) -> list[str]:
        return build_eval_command(
            agent=agent,
            corpus=Path("/corpus.jsonl"),
            repository=Path("/repository"),
            log_dir=Path("/logs"),
            dgx_base_url="http://dgx.internal:18000/v1",
            limit=None,
        )

    def test_react_and_aider_commands_share_the_bounded_harness(self) -> None:
        react = self._command("react")
        aider = self._command("aider")
        for command in (react, aider):
            joined = "\n".join(command)
            self.assertIn("--max-samples\n1", joined)
            self.assertIn("--max-sandboxes\n1", joined)
            self.assertIn("--max-retries\n0", joined)
            self.assertIn("--token-limit\n32000", joined)
            self.assertIn("--temperature\n0", joined)
            self.assertNotIn("secret", joined.lower())
        self.assertEqual(REACT_MODEL, react[react.index("--model") + 1])
        self.assertEqual(AIDER_CONTROL_MODEL, aider[aider.index("--model") + 1])
        self.assertIn("--model-base-url", react)
        self.assertNotIn("--model-base-url", aider)

    def test_unknown_arm_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported arm"):
            self._command("typo")

    def test_secret_file_is_bounded_and_never_part_of_argv(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            key = Path(raw) / "key"
            key.write_text("bounded-value\n", encoding="utf-8")
            self.assertEqual("bounded-value", _read_secret(key))
            key.write_text("\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "empty or malformed"):
                _read_secret(key)

if __name__ == "__main__":
    unittest.main()
