"""Thin Python client for the TypeScript Effect corpus authority."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


HERE = Path(__file__).resolve().parent
REQUEST_VERSION = "coding-corpus-bridge-request/v1"
RESPONSE_VERSION = "coding-corpus-bridge-response/v1"
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_NODE = Path(shutil.which("node") or "/usr/bin/node").resolve()
_BRIDGE_COMMAND = (_NODE, "--import", "tsx", HERE / "src" / "cli.ts", "bridge")
_BRIDGE_ENVIRONMENT = {
    "PATH": os.pathsep.join((str(_NODE.parent), "/usr/local/bin", "/usr/bin", "/bin")),
    "HOME": "/nonexistent",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_NO_LAZY_FETCH": "1",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_TERMINAL_PROMPT": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONNOUSERSITE": "1",
}


class CorpusError(ValueError):
    """Closed bridge, corpus, history, or admission failure."""


@dataclass(frozen=True)
class CorpusCase:
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
    _corpus_path: Path = field(repr=False, compare=False)

    def metadata(self) -> dict[str, Any]:
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
class CaseCheck:
    case_id: str
    baseline_returncode: int
    admitted_solution_returncode: int
    oracle_returncode: int
    valid: bool


@dataclass(frozen=True)
class PreparedCase:
    case: CorpusCase
    metadata: Mapping[str, object]
    base_archive: Path
    oracle_archive: Path
    verifier_archive: Path


@dataclass(frozen=True)
class ScoreDecision:
    kind: str
    correct: bool | None = None
    explanation: str | None = None
    returncode: int | None = None
    oracle_signature_match: bool | None = None
    execution_error: str | None = None
    reason: str | None = None


def repository_root() -> Path:
    """Return the repository root without consulting ambient environment state."""
    return Path(__file__).resolve().parents[2]


def default_corpus_path() -> Path:
    return HERE / "pilot.jsonl"


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CorpusError(f"duplicate JSON key in bridge response: {key}")
        result[key] = value
    return result


def _object(value: object, keys: set[str], context: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise CorpusError(f"invalid {context} object")
    return value


def _string(value: object, context: str) -> str:
    if not isinstance(value, str):
        raise CorpusError(f"invalid {context} string")
    return value


def _integer(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CorpusError(f"invalid {context} integer")
    return value


def _string_tuple(value: object, context: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CorpusError(f"invalid {context} string list")
    return tuple(value)


def _invoke_bridge(request: Mapping[str, object], *, timeout: int) -> object:
    encoded = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    try:
        completed = subprocess.run(
            [str(part) for part in _BRIDGE_COMMAND],
            cwd=HERE,
            env=_BRIDGE_ENVIRONMENT,
            input=encoded,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CorpusError(f"TypeScript corpus bridge could not complete: {type(exc).__name__}") from exc
    if len(completed.stdout) > _MAX_RESPONSE_BYTES:
        raise CorpusError("TypeScript corpus bridge response exceeds the limit")
    try:
        response = json.loads(
            completed.stdout.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, CorpusError) as exc:
        raise CorpusError("TypeScript corpus bridge returned invalid JSON") from exc
    if not isinstance(response, dict) or response.get("schema_version") != RESPONSE_VERSION:
        raise CorpusError("TypeScript corpus bridge returned an unsupported response")
    if response.get("ok") is False:
        envelope = _object(response, {"schema_version", "ok", "error"}, "bridge error")
        error = envelope["error"]
        reason = error.get("reason") if isinstance(error, dict) else None
        raise CorpusError(reason if isinstance(reason, str) else "TypeScript corpus bridge failed")
    envelope = _object(
        response,
        {"schema_version", "ok", "operation", "value"},
        "bridge success",
    )
    if envelope["ok"] is not True or completed.returncode != 0:
        raise CorpusError("TypeScript corpus bridge success disagrees with process status")
    if envelope["operation"] != request.get("operation"):
        raise CorpusError("TypeScript corpus bridge operation mismatch")
    return envelope["value"]


_CASE_KEYS = {
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


def _decode_case(value: object, corpus_path: Path) -> CorpusCase:
    raw = _object(value, _CASE_KEYS, "corpus case")
    return CorpusCase(
        id=_string(raw["id"], "case id"),
        input=_string(raw["input"], "case input"),
        base_sha=_string(raw["base_sha"], "base sha"),
        oracle_sha=_string(raw["oracle_sha"], "oracle sha"),
        split=_string(raw["split"], "split"),
        submission_paths=_string_tuple(raw["submission_paths"], "submission paths"),
        verifier_paths=_string_tuple(raw["verifier_paths"], "verifier paths"),
        verifier=_string_tuple(raw["verifier"], "verifier"),
        timeout_seconds=_integer(raw["timeout_seconds"], "timeout seconds"),
        tags=_string_tuple(raw["tags"], "tags"),
        _corpus_path=corpus_path,
    )


def load_cases(path: Path | None = None) -> tuple[CorpusCase, ...]:
    corpus_path = (path or default_corpus_path()).resolve()
    value = _object(
        _invoke_bridge(
            {"schema_version": REQUEST_VERSION, "operation": "catalog", "corpus": str(corpus_path)},
            timeout=30,
        ),
        {"cases"},
        "catalog value",
    )
    cases = value["cases"]
    if not isinstance(cases, list):
        raise CorpusError("invalid catalog cases")
    return tuple(_decode_case(case, corpus_path) for case in cases)


def _corpus_path(cases: Iterable[CorpusCase]) -> Path:
    materialized = tuple(cases)
    if not materialized:
        raise CorpusError("case selection is empty")
    paths = {case._corpus_path for case in materialized}
    if len(paths) != 1:
        raise CorpusError("cases do not share one corpus source")
    return next(iter(paths))


def validate_history(repo: Path, cases: Iterable[CorpusCase]) -> None:
    corpus_path = _corpus_path(cases)
    _invoke_bridge(
        {
            "schema_version": REQUEST_VERSION,
            "operation": "validate",
            "corpus": str(corpus_path),
            "repository": str(repo.resolve()),
        },
        timeout=300,
    )


def _decode_check(value: object) -> CaseCheck:
    raw = _object(
        value,
        {
            "case_id",
            "baseline_returncode",
            "admitted_solution_returncode",
            "oracle_returncode",
            "valid",
        },
        "case check",
    )
    valid = raw["valid"]
    if not isinstance(valid, bool):
        raise CorpusError("invalid case check validity")
    return CaseCheck(
        case_id=_string(raw["case_id"], "case check id"),
        baseline_returncode=_integer(raw["baseline_returncode"], "baseline returncode"),
        admitted_solution_returncode=_integer(
            raw["admitted_solution_returncode"], "admitted solution returncode"
        ),
        oracle_returncode=_integer(raw["oracle_returncode"], "oracle returncode"),
        valid=valid,
    )


def check_cases(repo: Path, cases: Sequence[CorpusCase]) -> tuple[CaseCheck, ...]:
    corpus_path = _corpus_path(cases)
    value = _object(
        _invoke_bridge(
            {
                "schema_version": REQUEST_VERSION,
                "operation": "admit",
                "corpus": str(corpus_path),
                "repository": str(repo.resolve()),
                "python_executable": str(Path(sys.executable).absolute()),
            },
            timeout=41 * 60,
        ),
        {"checks"},
        "admit value",
    )
    checks = value["checks"]
    if not isinstance(checks, list):
        raise CorpusError("invalid admission checks")
    return tuple(_decode_check(check) for check in checks)


def prepare_corpus(
    corpus: Path,
    repository: Path,
    split: str,
    archive_directory: Path,
) -> tuple[PreparedCase, ...]:
    value = _object(
        _invoke_bridge(
            {
                "schema_version": REQUEST_VERSION,
                "operation": "prepare",
                "corpus": str(corpus.resolve()),
                "repository": str(repository.resolve()),
                "python_executable": str(Path(sys.executable).absolute()),
                "archive_directory": str(archive_directory.resolve()),
                "split": split,
            },
            timeout=41 * 60,
        ),
        {"cases"},
        "prepare value",
    )
    raw_cases = value["cases"]
    if not isinstance(raw_cases, list):
        raise CorpusError("invalid prepared cases")
    result: list[PreparedCase] = []
    corpus_path = corpus.resolve()
    for value_case in raw_cases:
        raw = _object(
            value_case,
            {"case", "metadata", "base_archive", "oracle_archive", "verifier_archive"},
            "prepared case",
        )
        metadata = raw["metadata"]
        if not isinstance(metadata, dict):
            raise CorpusError("invalid prepared metadata")
        result.append(
            PreparedCase(
                case=_decode_case(raw["case"], corpus_path),
                metadata=dict(metadata),
                base_archive=Path(_string(raw["base_archive"], "base archive")),
                oracle_archive=Path(_string(raw["oracle_archive"], "oracle archive")),
                verifier_archive=Path(_string(raw["verifier_archive"], "verifier archive")),
            )
        )
    return tuple(result)


def score_candidate(
    corpus: Path,
    case_id: str,
    metadata: object,
    oracle: Mapping[str, object],
    candidate: Mapping[str, object],
) -> ScoreDecision:
    raw = _invoke_bridge(
        {
            "schema_version": REQUEST_VERSION,
            "operation": "score",
            "corpus": str(corpus.resolve()),
            "case_id": case_id,
            "metadata": metadata,
            "oracle": oracle,
            "candidate": candidate,
        },
        timeout=30,
    )
    if not isinstance(raw, dict):
        raise CorpusError("invalid score decision")
    kind = raw.get("kind")
    if kind == "harness_error":
        envelope = _object(raw, {"kind", "reason"}, "harness score decision")
        return ScoreDecision(kind=kind, reason=_string(envelope["reason"], "score reason"))
    allowed = {"kind", "correct", "explanation", "returncode", "oracle_signature_match"}
    if "execution_error" in raw:
        allowed.add("execution_error")
    envelope = _object(raw, allowed, "score decision")
    if kind != "scored" or not isinstance(envelope["correct"], bool):
        raise CorpusError("invalid scored decision")
    returncode = envelope["returncode"]
    if returncode is not None:
        returncode = _integer(returncode, "score returncode")
    signature_match = envelope["oracle_signature_match"]
    if not isinstance(signature_match, bool):
        raise CorpusError("invalid score signature match")
    execution_error = envelope.get("execution_error")
    return ScoreDecision(
        kind="scored",
        correct=envelope["correct"],
        explanation=_string(envelope["explanation"], "score explanation"),
        returncode=returncode,
        oracle_signature_match=signature_match,
        execution_error=(
            _string(execution_error, "execution error") if execution_error is not None else None
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("list", "validate", "check"))
    parser.add_argument("--corpus", type=Path, default=default_corpus_path())
    parser.add_argument("--repo", type=Path, default=repository_root())
    args = parser.parse_args(argv)
    cases = load_cases(args.corpus)
    if args.command == "list":
        print(json.dumps({"cases": [case.metadata() for case in cases]}, separators=(",", ":")))
        return 0
    if args.command == "validate":
        validate_history(args.repo, cases)
        print(json.dumps({"status": "valid", "cases": len(cases)}, separators=(",", ":")))
        return 0
    checks = check_cases(args.repo, cases)
    print(json.dumps({"checks": [check.__dict__ for check in checks]}, separators=(",", ":")))
    return 0 if all(check.valid for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
