"""Single-source loader and verifier for the coding-agent pilot corpus."""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
CASE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")
PYTEST_FILE = re.compile(r"^tests/[A-Za-z_][A-Za-z0-9_]*\.py$")
CASE_KEYS = {
    "id",
    "input",
    "base_sha",
    "oracle_sha",
    "split",
    "submission_paths",
    "verifier_paths",
    "verifier",
    "timeout_seconds",
    "tags",
}


def _is_unittest_verifier(verifier: Sequence[str]) -> bool:
    return (
        len(verifier) >= 5
        and all(isinstance(item, str) for item in verifier)
        and verifier[0] in {"python", "python3"}
        and tuple(verifier[1:3]) == ("-m", "unittest")
        and verifier[-1] == "-v"
        and all(
            re.fullmatch(r"tests(?:\.[A-Za-z_][A-Za-z0-9_]*)+", module)
            for module in verifier[3:-1]
        )
    )


def _is_pytest_verifier(verifier: Sequence[str]) -> bool:
    return (
        len(verifier) == 7
        and all(isinstance(item, str) for item in verifier)
        and tuple(verifier[:6])
        == ("python3", "-m", "pytest", "-vv", "-p", "no:cacheprovider")
        and bool(PYTEST_FILE.fullmatch(verifier[6]))
    )


class CorpusError(ValueError):
    """Closed validation failure for corpus input or repository history."""


@dataclass(frozen=True)
class CorpusCase:
    """One historical coding task and its hidden deterministic verifier."""

    id: str
    input: str
    base_sha: str
    oracle_sha: str
    split: str
    submission_paths: tuple[str, ...]
    verifier_paths: tuple[str, ...]
    verifier: tuple[str, ...]
    timeout_seconds: int
    tags: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CorpusCase":
        keys = set(value)
        if keys != CASE_KEYS:
            missing = sorted(CASE_KEYS - keys)
            extra = sorted(keys - CASE_KEYS)
            raise CorpusError(f"case keys differ; missing={missing}, extra={extra}")

        case_id = _bounded_string(value["id"], "id", 3, 80)
        if not CASE_ID.fullmatch(case_id):
            raise CorpusError("id must be lower-case hyphen syntax")
        instruction = _bounded_string(value["input"], "input", 32, 8_000)
        base_sha = _full_sha(value["base_sha"], "base_sha")
        oracle_sha = _full_sha(value["oracle_sha"], "oracle_sha")
        if base_sha == oracle_sha:
            raise CorpusError("base_sha and oracle_sha must differ")

        split = _bounded_string(value["split"], "split", 4, 16)
        if split not in {"calibration", "validation", "heldout"}:
            raise CorpusError("split must be calibration, validation, or heldout")

        submission_paths = _string_tuple(value["submission_paths"], "submission_paths", 1, 16)
        for raw_path in submission_paths:
            _repository_path(raw_path, "submission")
        if len(set(submission_paths)) != len(submission_paths):
            raise CorpusError("submission_paths contains duplicates")

        verifier_paths = _string_tuple(value["verifier_paths"], "verifier_paths", 1, 16)
        for raw_path in verifier_paths:
            path = _repository_path(raw_path, "verifier")
            if path.parts[0] not in {"tests", "fixtures", "spec"}:
                raise CorpusError(f"verifier path is outside the admitted roots: {raw_path}")
        if len(set(verifier_paths)) != len(verifier_paths):
            raise CorpusError("verifier_paths contains duplicates")
        overlap = sorted(set(submission_paths) & set(verifier_paths))
        if overlap:
            raise CorpusError(f"submission and verifier paths overlap: {overlap}")

        verifier = _string_tuple(value["verifier"], "verifier", 2, 32)
        is_unittest = _is_unittest_verifier(verifier)
        is_pytest = _is_pytest_verifier(verifier)
        if not (is_unittest or is_pytest):
            raise CorpusError(
                "verifier must be a verbose unittest module command or a closed pytest file command"
            )
        if is_pytest and verifier[-1] not in verifier_paths:
            raise CorpusError("pytest verifier path must be listed in verifier_paths")
        if any("\x00" in item or "\n" in item or "\r" in item for item in verifier):
            raise CorpusError("verifier arguments must be single-line strings")

        timeout = value["timeout_seconds"]
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 600:
            raise CorpusError("timeout_seconds must be an integer from 1 through 600")

        tags = _string_tuple(value["tags"], "tags", 1, 16)
        if len(set(tags)) != len(tags):
            raise CorpusError("tags contains duplicates")
        for tag in tags:
            if not CASE_ID.fullmatch(tag):
                raise CorpusError(f"tag is not lower-case hyphen syntax: {tag}")

        return cls(
            id=case_id,
            input=instruction,
            base_sha=base_sha,
            oracle_sha=oracle_sha,
            split=split,
            submission_paths=submission_paths,
            verifier_paths=verifier_paths,
            verifier=verifier,
            timeout_seconds=timeout,
            tags=tags,
        )

    def metadata(self) -> dict[str, Any]:
        """Return the data needed by the post-agent scorer."""
        return {
            "case_id": self.id,
            "base_sha": self.base_sha,
            "oracle_sha": self.oracle_sha,
            "split": self.split,
            "submission_paths": list(self.submission_paths),
            "verifier_paths": list(self.verifier_paths),
            "verifier": list(self.verifier),
            "timeout_seconds": self.timeout_seconds,
            "tags": list(self.tags),
        }


@dataclass(frozen=True)
class VerifierRun:
    revision: str
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class CaseCheck:
    case_id: str
    baseline: VerifierRun
    admitted_solution: VerifierRun
    oracle: VerifierRun
    verifier: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        solution_signature = verifier_signature(
            self.verifier,
            self.admitted_solution.stdout,
            self.admitted_solution.stderr,
        )
        oracle_signature = verifier_signature(
            self.verifier, self.oracle.stdout, self.oracle.stderr
        )
        return (
            self.baseline.returncode != 0
            and self.admitted_solution.returncode == 0
            and self.oracle.returncode == 0
            and bool(solution_signature)
            and solution_signature == oracle_signature
        )


def unittest_signature(stdout: str, stderr: str) -> tuple[str, ...]:
    """Extract stable, positive unittest completion evidence."""
    lines = [line.strip() for line in f"{stdout}\n{stderr}".splitlines()]
    statuses = tuple(
        line
        for line in lines
        if re.fullmatch(
            r"test_[^\n]+ \.\.\. (?:ok|skipped .+|expected failure)", line
        )
    )
    ran_matches = tuple(
        match
        for line in lines
        if (match := re.fullmatch(r"Ran ([1-9][0-9]*) tests? in [0-9.]+s", line))
    )
    terminals = tuple(
        line for line in lines if re.fullmatch(r"OK(?: \([^\n()]+\))?", line)
    )
    if (
        len(ran_matches) != 1
        or len(terminals) != 1
        or int(ran_matches[0].group(1)) != len(statuses)
        or len(set(statuses)) != len(statuses)
    ):
        return ()
    return (*statuses, f"Ran {len(statuses)} tests", terminals[0])


def pytest_signature(
    stdout: str,
    stderr: str,
    expected_path: str | None = None,
) -> tuple[str, ...]:
    """Extract stable, positive evidence from the one admitted verbose pytest form."""
    lines = [line.strip() for line in f"{stdout}\n{stderr}".splitlines()]
    status_pattern = re.compile(
        r"(?P<path>tests/[^\s:]+\.py)::(?P<node>[^\r\n]+?) "
        r"(?P<status>PASSED|FAILED|SKIPPED|XFAIL|XPASS|ERROR) "
        r"\s*\[\s*(?:100|[0-9]{1,2})%\]"
    )
    statuses: list[str] = []
    for line in lines:
        match = status_pattern.fullmatch(line)
        if match is None:
            continue
        path = match.group("path")
        if (
            match.group("status") != "PASSED"
            or not PYTEST_FILE.fullmatch(path)
            or (expected_path is not None and path != expected_path)
        ):
            return ()
        statuses.append(f"{path}::{match.group('node')} ... PASSED")

    collected_matches = tuple(
        match
        for line in lines
        if (
            match := re.fullmatch(
                r"(?:collecting \.\.\. )?collected ([0-9]+) items?", line
            )
        )
    )
    terminal_matches = tuple(
        match
        for line in lines
        if (
            match := re.fullmatch(
                r"=+\s+([1-9][0-9]*) passed"
                r"(?:, [1-9][0-9]* warnings?)?"
                r" in [0-9]+(?:\.[0-9]+)?s\s+=+",
                line,
            )
        )
    )
    session_starts = tuple(
        line
        for line in lines
        if re.fullmatch(r"=+\s+test session starts\s+=+", line)
    )
    if (
        len(session_starts) != 1
        or len(collected_matches) != 1
        or len(terminal_matches) != 1
    ):
        return ()
    collected = int(collected_matches[0].group(1))
    passed = int(terminal_matches[0].group(1))
    if (
        collected < 1
        or collected != passed
        or collected != len(statuses)
        or len(set(statuses)) != len(statuses)
    ):
        return ()
    return (*statuses, f"collected {collected} items", f"{passed} passed")


def verifier_signature(
    verifier: Sequence[str], stdout: str, stderr: str
) -> tuple[str, ...]:
    """Dispatch only the closed verifier forms admitted by ``CorpusCase``."""
    if _is_unittest_verifier(verifier):
        return unittest_signature(stdout, stderr)
    if _is_pytest_verifier(verifier):
        return pytest_signature(stdout, stderr, verifier[-1])
    return ()


def repository_root() -> Path:
    override = os.environ.get("CODING_CORPUS_REPOSITORY")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[2]


def default_corpus_path() -> Path:
    return Path(__file__).resolve().parent / "pilot.jsonl"


def load_cases(path: Path | None = None) -> tuple[CorpusCase, ...]:
    source = path or default_corpus_path()
    cases: list[CorpusCase] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip():
            continue
        try:
            raw = json.loads(raw_line, object_pairs_hook=_reject_duplicate_keys)
        except (json.JSONDecodeError, CorpusError) as exc:
            raise CorpusError(f"{source}:{line_number}: {exc}") from exc
        if not isinstance(raw, dict):
            raise CorpusError(f"{source}:{line_number}: case must be an object")
        case = CorpusCase.from_mapping(raw)
        if case.id in seen:
            raise CorpusError(f"{source}:{line_number}: duplicate id {case.id}")
        seen.add(case.id)
        cases.append(case)
    if not cases:
        raise CorpusError(f"{source}: corpus is empty")
    return tuple(cases)


def validate_history(repo: Path, cases: Iterable[CorpusCase]) -> None:
    _require_repository(repo)
    for case in cases:
        _require_commit(repo, case.base_sha)
        _require_commit(repo, case.oracle_sha)
        ancestor = _git(
            repo,
            ["merge-base", "--is-ancestor", case.base_sha, case.oracle_sha],
            check=False,
        )
        if ancestor.returncode != 0:
            raise CorpusError(f"{case.id}: base_sha is not an ancestor of oracle_sha")
        for relative in case.verifier_paths:
            _git(repo, ["cat-file", "-e", f"{case.oracle_sha}:{relative}"])
        for relative in case.submission_paths:
            _git(repo, ["cat-file", "-e", f"{case.base_sha}:{relative}"])
            _git(repo, ["cat-file", "-e", f"{case.oracle_sha}:{relative}"])


def archive_revision(repo: Path, revision: str, destination: Path) -> None:
    """Write a solution-history-free tar archive for one committed revision."""
    _require_commit(repo, revision)
    completed = _git(repo, ["archive", "--format=tar", revision])
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(completed.stdout)


def materialize_revision(repo: Path, revision: str, destination: Path) -> None:
    completed = _git(repo, ["archive", "--format=tar", revision])
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(fileobj=io.BytesIO(completed.stdout), mode="r:") as archive:
        archive.extractall(destination, filter="data")


def overlay_verifier(repo: Path, case: CorpusCase, destination: Path) -> None:
    """Install oracle verifier material only after the agent turn has ended."""
    for relative in case.verifier_paths:
        content = _git(repo, ["show", f"{case.oracle_sha}:{relative}"]).stdout
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def overlay_admitted_solution(repo: Path, case: CorpusCase, destination: Path) -> None:
    """Apply only the oracle files the agent is permitted to submit."""
    for relative in case.submission_paths:
        content = _git(repo, ["show", f"{case.oracle_sha}:{relative}"]).stdout
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def run_verifier(case: CorpusCase, checkout: Path, revision: str) -> VerifierRun:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(checkout / "src") + os.pathsep + str(checkout / "scripts")
    try:
        completed = subprocess.run(
            [sys.executable, *case.verifier[1:]],
            cwd=checkout,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=case.timeout_seconds,
            check=False,
        )
        return VerifierRun(revision, completed.returncode, completed.stdout, completed.stderr)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return VerifierRun(revision, 124, stdout, stderr + "\nverifier timed out")


def check_case(repo: Path, case: CorpusCase) -> CaseCheck:
    with tempfile.TemporaryDirectory(prefix=f"coding-corpus-{case.id}-") as raw:
        root = Path(raw)
        baseline_checkout = root / "baseline"
        solution_checkout = root / "admitted-solution"
        oracle_checkout = root / "oracle"
        materialize_revision(repo, case.base_sha, baseline_checkout)
        overlay_verifier(repo, case, baseline_checkout)
        baseline = run_verifier(case, baseline_checkout, case.base_sha)
        materialize_revision(repo, case.base_sha, solution_checkout)
        overlay_verifier(repo, case, solution_checkout)
        overlay_admitted_solution(repo, case, solution_checkout)
        admitted_solution = run_verifier(
            case, solution_checkout, f"{case.base_sha}+admitted-solution"
        )
        materialize_revision(repo, case.oracle_sha, oracle_checkout)
        overlay_verifier(repo, case, oracle_checkout)
        oracle = run_verifier(case, oracle_checkout, case.oracle_sha)
        return CaseCheck(
            case.id,
            baseline,
            admitted_solution,
            oracle,
            verifier=case.verifier,
        )


def check_cases(repo: Path, cases: Sequence[CorpusCase]) -> tuple[CaseCheck, ...]:
    validate_history(repo, cases)
    return tuple(check_case(repo, case) for case in cases)


def _bounded_string(value: Any, name: str, minimum: int, maximum: int) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        raise CorpusError(f"{name} must be a string of length {minimum} through {maximum}")
    return value


def _full_sha(value: Any, name: str) -> str:
    text = _bounded_string(value, name, 40, 40)
    if not FULL_SHA.fullmatch(text):
        raise CorpusError(f"{name} must be a full lower-case Git SHA")
    return text


def _string_tuple(value: Any, name: str, minimum: int, maximum: int) -> tuple[str, ...]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise CorpusError(f"{name} must be a list with {minimum} through {maximum} items")
    if not all(isinstance(item, str) and item for item in value):
        raise CorpusError(f"{name} items must be non-empty strings")
    return tuple(value)


def _repository_path(raw_path: str, kind: str) -> PurePosixPath:
    path = PurePosixPath(raw_path)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise CorpusError(f"{kind} path is not repository-relative: {raw_path}")
    return path


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CorpusError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _require_repository(repo: Path) -> None:
    completed = _git(repo, ["rev-parse", "--is-inside-work-tree"], check=False)
    if completed.returncode != 0 or completed.stdout.strip() != b"true":
        raise CorpusError(f"not a Git worktree: {repo}")


def _require_commit(repo: Path, revision: str) -> None:
    completed = _git(repo, ["cat-file", "-e", f"{revision}^{{commit}}"], check=False)
    if completed.returncode != 0:
        raise CorpusError(f"commit is unavailable: {revision}")


def _git(
    repo: Path,
    args: Sequence[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise CorpusError(f"git {' '.join(args)} failed: {detail}")
    return completed


def _summary(check: CaseCheck) -> dict[str, Any]:
    return {
        "case_id": check.case_id,
        "baseline_returncode": check.baseline.returncode,
        "admitted_solution_returncode": check.admitted_solution.returncode,
        "oracle_returncode": check.oracle.returncode,
        "valid": check.valid,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("list", "validate", "check"))
    parser.add_argument("--corpus", type=Path, default=default_corpus_path())
    parser.add_argument("--repo", type=Path, default=repository_root())
    args = parser.parse_args(argv)

    cases = load_cases(args.corpus)
    if args.command == "list":
        for case in cases:
            print(json.dumps({"id": case.id, "tags": case.tags}, separators=(",", ":")))
        return 0

    validate_history(args.repo.resolve(), cases)
    if args.command == "validate":
        print(json.dumps({"status": "valid", "cases": len(cases)}, separators=(",", ":")))
        return 0

    checks = check_cases(args.repo.resolve(), cases)
    print(json.dumps({"checks": [_summary(check) for check in checks]}, separators=(",", ":")))
    return 0 if all(check.valid for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
