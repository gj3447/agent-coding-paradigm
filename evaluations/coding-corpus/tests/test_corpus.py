from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import corpus as corpus_bridge  # noqa: E402
from corpus import (  # noqa: E402
    CorpusError,
    PreparedCase,
    check_cases,
    default_corpus_path,
    load_cases,
    repository_root,
    score_candidate,
    validate_history,
)
from task import _verifier_observation, company_coding  # noqa: E402


class CorpusBridgeTests(unittest.TestCase):
    def test_catalog_is_unique_and_bound_to_available_history(self) -> None:
        cases = load_cases()
        self.assertEqual(len(cases), len({case.id for case in cases}))
        validate_history(repository_root(), cases)

    def test_lakatotree_slice_is_decoded_by_the_ts_authority(self) -> None:
        cases = load_cases(HERE / "lakatotree.jsonl")
        self.assertEqual(
            [
                "lakatotree-metric-direction",
                "lakatotree-hard-core-guard",
                "lakatotree-lineage-cycle",
            ],
            [case.id for case in cases],
        )
        self.assertTrue(all(case.verifier[2] == "pytest" for case in cases))

    def test_duplicate_keys_and_path_escape_fail_in_ts(self) -> None:
        original = json.loads(default_corpus_path().read_text(encoding="utf-8").splitlines()[0])
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            duplicate = root / "duplicate.jsonl"
            line = json.dumps(original, separators=(",", ":"))
            duplicate.write_text(line[:-1] + ',"id":"duplicate"}\n', encoding="utf-8")
            with self.assertRaisesRegex(CorpusError, "duplicate JSON key"):
                load_cases(duplicate)

            escaped = root / "escaped.jsonl"
            escaped_case = copy.deepcopy(original)
            escaped_case["verifier_paths"] = ["../tests/escape.py"]
            escaped.write_text(json.dumps(escaped_case) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(CorpusError, "repository-relative"):
                load_cases(escaped)

    def test_admission_summary_comes_from_ts_effect(self) -> None:
        checks = check_cases(repository_root(), load_cases())
        self.assertTrue(checks)
        self.assertEqual([], [check.case_id for check in checks if not check.valid])

    def test_score_policy_comes_from_ts_and_binds_metadata(self) -> None:
        case = load_cases()[0]
        oracle = "test_example (tests.Example.test_example) ... ok\nRan 1 test in 0.01s\nOK\n"
        completed = {
            "kind": "completed",
            "returncode": 0,
            "stdout": oracle,
            "stderr": "",
        }
        accepted = score_candidate(
            default_corpus_path(),
            case.id,
            case.metadata(),
            completed,
            {**completed, "stdout": oracle.replace("0.01s", "8.75s")},
        )
        self.assertTrue(accepted.correct)
        unbound = score_candidate(
            default_corpus_path(),
            case.id,
            {**case.metadata(), "unexpected": True},
            completed,
            completed,
        )
        self.assertFalse(unbound.correct)
        self.assertEqual("sample metadata is not corpus-bound", unbound.explanation)

    def test_python_client_uses_no_shell_and_forwards_no_ambient_secret(self) -> None:
        response = {
            "schema_version": corpus_bridge.RESPONSE_VERSION,
            "ok": True,
            "operation": "catalog",
            "value": {"cases": []},
        }
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(response).encode(), stderr=b""
        )
        with patch.dict(os.environ, {"AWS_SECRET_ACCESS_KEY": "must-not-cross"}), patch(
            "corpus.subprocess.run", return_value=completed
        ) as run:
            self.assertEqual((), load_cases(Path("/tmp/corpus;touch-escaped")))
        args, kwargs = run.call_args
        self.assertIsInstance(args[0], list)
        self.assertNotIn("corpus;touch-escaped", " ".join(args[0]))
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", kwargs["env"])
        self.assertNotIn("shell", kwargs)
        request = json.loads(kwargs["input"])
        self.assertIn("corpus;touch-escaped", request["corpus"])

    def test_bridge_deadline_closes_an_open_stdin_pipe(self) -> None:
        process = subprocess.Popen(
            [str(part) for part in corpus_bridge._BRIDGE_COMMAND],
            cwd=HERE,
            env=corpus_bridge._BRIDGE_ENVIRONMENT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            returncode = process.wait(timeout=8)
            self.assertEqual(1, returncode)
            self.assertIsNotNone(process.stdout)
            payload = json.loads(process.stdout.read())
            self.assertFalse(payload["ok"])
            self.assertIn("exceeded", payload["error"]["reason"])
        finally:
            if process.stdin is not None:
                process.stdin.close()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=2)
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()

    def test_verifier_observation_uses_the_shared_utf8_byte_budget(self) -> None:
        class Result:
            returncode = 0
            stdout = "😀" * 16_385
            stderr = ""

        self.assertEqual(
            {"kind": "execution_error", "error": "OutputLimitExceededError"},
            _verifier_observation(Result()),
        )

    def test_task_is_a_thin_mapping_over_prepared_cases(self) -> None:
        case = load_cases()[0]
        prepared = PreparedCase(
            case=case,
            metadata=case.metadata(),
            base_archive=Path("/tmp/base.tar"),
            oracle_archive=Path("/tmp/oracle.tar"),
            verifier_archive=Path("/tmp/verifier.tar"),
        )
        with self.assertRaisesRegex(ValueError, "epochs"):
            company_coding(epochs=0)
        with patch("task.prepare_corpus", return_value=(prepared,)):
            configured = company_coding()
        self.assertEqual(1, len(configured.dataset))
        self.assertEqual(case.metadata(), configured.dataset[0].metadata)


if __name__ == "__main__":
    unittest.main()
