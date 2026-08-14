from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from corpus import (  # noqa: E402
    CaseCheck,
    CorpusCase,
    CorpusError,
    VerifierRun,
    check_cases,
    default_corpus_path,
    load_cases,
    pytest_signature,
    repository_root,
    unittest_signature,
    validate_history,
    verifier_signature,
)
from task import company_coding  # noqa: E402


class CorpusTests(unittest.TestCase):
    def test_repository_root_has_an_explicit_standalone_override(self) -> None:
        with patch.dict(os.environ, {"CODING_CORPUS_REPOSITORY": "/tmp/source-repo"}):
            self.assertEqual(Path("/tmp/source-repo"), repository_root())

    def test_pilot_is_unique_and_bound_to_available_history(self) -> None:
        cases = load_cases()
        self.assertEqual(len(cases), len({case.id for case in cases}))
        validate_history(repository_root(), cases)

    def test_lakatotree_slice_contains_the_three_vetted_pytest_cases(self) -> None:
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

    def test_duplicate_key_and_path_escape_fail_closed(self) -> None:
        case = load_cases()[0]
        raw = {
            "id": case.id,
            "input": case.input,
            "base_sha": case.base_sha,
            "oracle_sha": case.oracle_sha,
            "split": case.split,
            "submission_paths": list(case.submission_paths),
            "verifier_paths": list(case.verifier_paths),
            "verifier": list(case.verifier),
            "timeout_seconds": case.timeout_seconds,
            "tags": list(case.tags),
        }
        escaped = copy.deepcopy(raw)
        escaped["verifier_paths"] = ["../tests/escape.py"]
        with self.assertRaisesRegex(CorpusError, "repository-relative"):
            CorpusCase.from_mapping(escaped)

        fake_command = copy.deepcopy(raw)
        fake_command["verifier"] = ["python3", "-c", "print('OK')"]
        with self.assertRaisesRegex(CorpusError, "verbose unittest"):
            CorpusCase.from_mapping(fake_command)

        pytest_command = copy.deepcopy(raw)
        pytest_command["verifier_paths"] = ["tests/test_example.py"]
        pytest_command["verifier"] = [
            "python3",
            "-m",
            "pytest",
            "-vv",
            "-p",
            "no:cacheprovider",
            "tests/test_example.py",
        ]
        parsed = CorpusCase.from_mapping(pytest_command)
        self.assertEqual(tuple(pytest_command["verifier"]), parsed.verifier)

        malformed_pytest_commands = (
            ["python", *pytest_command["verifier"][1:]],
            [*pytest_command["verifier"][:-1], "tests/unit/test_example.py"],
            [*pytest_command["verifier"], "tests/test_second.py"],
            ["python3", "-m", "pytest", "-q", "tests/test_example.py"],
        )
        for command in malformed_pytest_commands:
            malformed = copy.deepcopy(pytest_command)
            malformed["verifier"] = command
            with self.subTest(command=command):
                with self.assertRaisesRegex(CorpusError, "closed pytest"):
                    CorpusCase.from_mapping(malformed)

        unlisted = copy.deepcopy(pytest_command)
        unlisted["verifier_paths"] = ["tests/test_other.py"]
        with self.assertRaisesRegex(CorpusError, "listed in verifier_paths"):
            CorpusCase.from_mapping(unlisted)

        with tempfile.TemporaryDirectory() as raw_dir:
            corpus = Path(raw_dir) / "duplicate.jsonl"
            line = default_corpus_path().read_text(encoding="utf-8").splitlines()[0]
            line = line[:-1] + ',"id":"duplicate"}'
            corpus.write_text(line + "\n", encoding="utf-8")
            with self.assertRaisesRegex(CorpusError, "duplicate JSON key"):
                load_cases(corpus)

    def test_each_pilot_fails_at_base_and_passes_at_oracle(self) -> None:
        checks = check_cases(repository_root(), load_cases())
        failures = [
            {
                "case_id": check.case_id,
                "baseline": check.baseline.returncode,
                "admitted_solution": check.admitted_solution.returncode,
                "oracle": check.oracle.returncode,
            }
            for check in checks
            if not check.valid
        ]
        self.assertEqual([], failures, json.dumps(failures, sort_keys=True))

    def test_task_rejects_unbounded_or_unavailable_trials(self) -> None:
        with self.assertRaisesRegex(ValueError, "epochs"):
            company_coding(epochs=0)
        with self.assertRaisesRegex(ValueError, "no heldout cases"):
            company_coding(split="heldout")
        configured = company_coding()
        self.assertEqual(len(load_cases()), len(configured.dataset))

    def test_verifier_requires_the_oracle_unittest_signature(self) -> None:
        oracle = "test_example (tests.Example.test_example) ... ok\nRan 1 test in 0.01s\nOK\n"
        equivalent = "test_example (tests.Example.test_example) ... ok\nRan 1 test in 8.75s\nOK\n"
        verifier = ("python3", "-m", "unittest", "tests.test_example", "-v")
        self.assertEqual(
            unittest_signature(oracle, ""),
            unittest_signature(equivalent, ""),
        )
        self.assertEqual(
            unittest_signature(oracle, ""),
            verifier_signature(verifier, equivalent, ""),
        )
        self.assertNotEqual(unittest_signature(oracle, ""), unittest_signature("", ""))
        self.assertEqual((), unittest_signature("OK\n", ""))
        self.assertEqual((), unittest_signature("Ran 0 tests in 0.01s\nOK\n", ""))
        self.assertEqual((), verifier_signature(("python3", "-c", "print('OK')"), oracle, ""))

    def test_pytest_signature_requires_positive_consistent_verbose_evidence(self) -> None:
        verifier = (
            "python3",
            "-m",
            "pytest",
            "-vv",
            "-p",
            "no:cacheprovider",
            "tests/test_example.py",
        )
        oracle = """\
============================= test session starts ==============================
collecting ... collected 2 items

tests/test_example.py::test_alpha PASSED                         [ 50%]
tests/test_example.py::test_beta PASSED [100%]

============================== 2 passed in 0.01s ===============================
"""
        equivalent = oracle.replace("0.01s", "8.75s")
        expected = (
            "tests/test_example.py::test_alpha ... PASSED",
            "tests/test_example.py::test_beta ... PASSED",
            "collected 2 items",
            "2 passed",
        )
        self.assertEqual(expected, pytest_signature(oracle, ""))
        self.assertEqual(expected, pytest_signature(equivalent, ""))
        self.assertEqual(expected, verifier_signature(verifier, oracle, ""))
        self.assertEqual(
            (),
            verifier_signature(
                verifier,
                oracle.replace("tests/test_example.py", "tests/test_other.py"),
                "",
            ),
        )

        baseline = VerifierRun("base", 1, "1 failed in 0.01s\n", "")
        admitted = VerifierRun("base+solution", 0, equivalent, "")
        full_oracle = VerifierRun("oracle", 0, oracle, "")
        self.assertTrue(
            CaseCheck(
                "pytest-case",
                baseline,
                admitted,
                full_oracle,
                verifier=verifier,
            ).valid
        )

    def test_pytest_signature_rejects_empty_zero_and_fabricated_transcripts(self) -> None:
        zero = """\
============================= test session starts ==============================
collecting ... collected 0 items
============================ no tests ran in 0.01s =============================
"""
        fabricated = (
            "============================== 1 passed in 0.01s ==============================\n",
            """\
collecting ... collected 1 item
tests/test_example.py::test_alpha PASSED [100%]
============================== 1 passed in 0.01s ===============================
""",
            """\
collecting ... collected 2 items
tests/test_example.py::test_alpha PASSED [100%]
============================== 2 passed in 0.01s ===============================
""",
            """\
collecting ... collected 2 items
tests/test_example.py::test_alpha PASSED [ 50%]
tests/test_example.py::test_alpha PASSED [100%]
============================== 2 passed in 0.01s ===============================
""",
            """\
collecting ... collected 1 item
tests/test_example.py::test_alpha FAILED [100%]
============================== 1 passed in 0.01s ===============================
""",
        )
        self.assertEqual((), pytest_signature("", ""))
        self.assertEqual((), pytest_signature(zero, ""))
        for transcript in fabricated:
            with self.subTest(transcript=transcript):
                self.assertEqual((), pytest_signature(transcript, ""))


if __name__ == "__main__":
    unittest.main()
