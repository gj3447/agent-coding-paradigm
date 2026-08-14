"""Run the same admitted corpus through ReAct and Aider, then summarize logs."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

from inspect_ai.log import list_eval_logs, read_eval_log

from corpus import check_cases, load_cases


HERE = Path(__file__).resolve().parent
MODEL_ID = "qwen3.6-35b-a3b"
REACT_MODEL = f"openai-api/dgx/{MODEL_ID}"
AIDER_CONTROL_MODEL = "mockllm/model"


def _read_secret(path: Path) -> str:
    secret = path.read_text(encoding="utf-8").strip()
    if not secret or len(secret) > 4_096 or "\n" in secret or "\r" in secret:
        raise ValueError("DGX key file is empty or malformed")
    return secret


def _inspect_executable() -> Path:
    executable = Path(sys.executable).with_name("inspect")
    if not executable.is_file():
        raise FileNotFoundError(f"Inspect executable is unavailable: {executable}")
    return executable


def build_eval_command(
    *,
    agent: str,
    corpus: Path,
    repository: Path,
    log_dir: Path,
    dgx_base_url: str,
    limit: str | None,
) -> list[str]:
    if agent not in {"react", "aider"}:
        raise ValueError(f"unsupported arm: {agent}")
    model = REACT_MODEL if agent == "react" else AIDER_CONTROL_MODEL
    command = [
        str(_inspect_executable()),
        "eval",
        str(HERE / "task.py") + "@company_coding",
        "-T",
        f"corpus={corpus}",
        "-T",
        f"repository={repository}",
        "-T",
        f"agent={agent}",
        "-T",
        "split=calibration",
        "-T",
        "epochs=1",
        "--model",
        model,
        "--max-connections",
        "1",
        "--adaptive-connections",
        "false",
        "--max-retries",
        "0",
        "--timeout",
        "180",
        "--attempt-timeout",
        "300",
        "--max-samples",
        "1",
        "--max-tasks",
        "1",
        "--max-sandboxes",
        "1",
        "--token-limit",
        "32000",
        "--turn-limit",
        "8",
        "--time-limit",
        "1800",
        "--max-tokens",
        "4096",
        "--temperature",
        "0",
        "--log-dir",
        str(log_dir),
        "--display",
        "none",
        "--no-log-model-api",
        "--no-fail-on-error",
    ]
    if agent == "react":
        command.extend(("--model-base-url", dgx_base_url))
    if limit is not None:
        command.extend(("--limit", limit))
    return command


def _new_log(log_dir: Path, before: set[str]):
    candidates = [info for info in list_eval_logs(str(log_dir)) if info.name not in before]
    if len(candidates) != 1:
        names = sorted(info.name for info in candidates)
        raise RuntimeError(f"expected one new eval log, found {names}")
    return read_eval_log(candidates[0])


def _usage(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return {}


def summarize(agent: str, log: Any) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    for sample in log.samples or []:
        scores = {
            name: score.model_dump(mode="json")
            for name, score in (sample.scores or {}).items()
        }
        gateway = None
        if isinstance(sample.output.metadata, dict):
            gateway = sample.output.metadata.get("gateway")
        samples.append(
            {
                "id": sample.id,
                "scores": scores,
                "total_time": sample.total_time,
                "working_time": sample.working_time,
                "turn_count": sample.turn_count,
                "token_limit_usage": sample.token_limit_usage,
                "model_usage": {
                    name: _usage(usage) for name, usage in sample.model_usage.items()
                },
                "gateway": gateway,
                "error": sample.error.message if sample.error is not None else None,
            }
        )
    return {
        "agent": agent,
        "log": log.location,
        "status": log.status,
        "task_version": log.eval.task_version,
        "started_at": log.stats.started_at,
        "completed_at": log.stats.completed_at,
        "samples": samples,
    }


def run_arm(
    *,
    agent: str,
    corpus: Path,
    repository: Path,
    log_dir: Path,
    dgx_base_url: str,
    dgx_key: str,
    dgx_key_file: Path,
    limit: str | None,
) -> dict[str, Any]:
    log_dir.mkdir(parents=True, exist_ok=True)
    before = {info.name for info in list_eval_logs(str(log_dir))}
    command = build_eval_command(
        agent=agent,
        corpus=corpus,
        repository=repository,
        log_dir=log_dir,
        dgx_base_url=dgx_base_url,
        limit=limit,
    )
    environment = os.environ.copy()
    if agent == "react":
        environment["DGX_API_KEY"] = dgx_key
    else:
        environment["DGX_API_KEY_FILE"] = str(dgx_key_file)
    completed = subprocess.run(
        command,
        cwd=HERE,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    log = _new_log(log_dir, before)
    summary = summarize(agent, log)
    summary["command_exit"] = completed.returncode
    if completed.returncode != 0:
        summary["command_stderr_tail"] = completed.stderr[-2_000:]
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--log-dir", type=Path, required=True)
    parser.add_argument("--dgx-key-file", type=Path, required=True)
    parser.add_argument(
        "--dgx-base-url",
        default="http://192.168.0.23:18000/v1",
    )
    parser.add_argument("--arms", choices=("both", "react", "aider"), default="both")
    parser.add_argument("--limit")
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args(argv)

    corpus = args.corpus.resolve()
    repository = args.repository.resolve()
    cases = load_cases(corpus)
    invalid = [check.case_id for check in check_cases(repository, cases) if not check.valid]
    if invalid:
        raise RuntimeError(f"corpus admission failed for: {invalid}")
    dgx_key = _read_secret(args.dgx_key_file)
    agents = ("react", "aider") if args.arms == "both" else (args.arms,)
    result = {
        "schema_version": "coding-corpus-comparison/v1",
        "corpus": str(corpus),
        "repository": str(repository),
        "repository_head": subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        ).stdout.strip(),
        "arms": [
            run_arm(
                agent=agent,
                corpus=corpus,
                repository=repository,
                log_dir=args.log_dir.resolve(),
                dgx_base_url=args.dgx_base_url,
                dgx_key=dgx_key,
                dgx_key_file=args.dgx_key_file.resolve(),
                limit=args.limit,
            )
            for agent in agents
        ],
    }
    encoded = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.summary is not None:
        destination = args.summary.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(encoded, encoding="utf-8")
        os.replace(temporary, destination)
    print(encoded, end="")
    return 0 if all(arm["command_exit"] == 0 for arm in result["arms"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
