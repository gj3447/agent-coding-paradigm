"""Inspect task for the repository's historical coding corpus."""

from __future__ import annotations

import atexit
import base64
import binascii
import json
import shutil
import tempfile
from pathlib import Path
from typing import Literal

from inspect_ai import Task, task
from inspect_ai.agent import react
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Target, accuracy, scorer
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool import bash
from inspect_ai.util import OutputLimitExceededError, sandbox

from corpus import (
    load_cases,
    PreparedCase,
    prepare_corpus,
    repository_root,
    score_candidate,
)


HERE = Path(__file__).resolve().parent
WORKSPACE = "/workspace/repo"
_ARCHIVE_ROOT = Path(tempfile.mkdtemp(prefix="coding-corpus-archives-"))
atexit.register(lambda: shutil.rmtree(_ARCHIVE_ROOT, ignore_errors=True))
OPERATING_PROMPT = (
    "Work only in /workspace/repo. Solve the user's task with the smallest coherent "
    "change. The hidden verifier is intentionally unavailable; do not search for it. "
    "Use rg and narrow sed ranges instead of dumping whole documentation trees. Make a "
    "concrete edit, run the nearest relevant test, and then finish. Do not use the "
    "network, inspect /opt/coding-corpus, or commit."
)


def _verifier_observation(result: object) -> dict[str, object]:
    stdout = getattr(result, "stdout", None)
    stderr = getattr(result, "stderr", None)
    returncode = getattr(result, "returncode", None)
    if not isinstance(stdout, str) or not isinstance(stderr, str) or not isinstance(returncode, int):
        return {"kind": "execution_error", "error": "InvalidVerifierResult"}
    if len(stdout.encode("utf-8")) + len(stderr.encode("utf-8")) > 64 * 1024:
        return {"kind": "execution_error", "error": "OutputLimitExceededError"}
    return {
        "kind": "completed",
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
    }


def _sample(prepared: PreparedCase) -> Sample:
    case = prepared.case
    setup = f"""set -eu
rm -rf {WORKSPACE}
mkdir -p {WORKSPACE}
mkdir -p /tmp/home
tar -xf /opt/coding-corpus/repository.tar -C {WORKSPACE}
cd {WORKSPACE}
git init -q
git config user.name 'Corpus Baseline'
git config user.email 'corpus@example.invalid'
git add -A
git commit -qm baseline
"""
    return Sample(
        id=case.id,
        input=case.input,
        target="The hidden deterministic verifier exits successfully.",
        metadata=dict(prepared.metadata),
        files={
            "/opt/coding-corpus/repository.tar": str(prepared.base_archive),
            "verifier:/opt/coding-corpus/repository.tar": str(prepared.base_archive),
            "verifier:/opt/coding-corpus/verifier.tar": str(prepared.verifier_archive),
            "oracle:/opt/coding-corpus/repository.tar": str(prepared.oracle_archive),
        },
        setup=setup,
    )


@scorer(metrics=[accuracy()])
def repository_verifier(
    corpus_path: str,
    agent: Literal["react", "aider"],
):
    async def score(state: TaskState, target: Target) -> Score:
        del target
        cases = {case.id: case for case in load_cases(Path(corpus_path))}
        case_id = state.metadata.get("case_id")
        case = cases.get(case_id)
        if case is None:
            return Score(value=INCORRECT, explanation="sample metadata is not corpus-bound")
        gateway_metrics: dict[str, object] | None = None
        if agent == "aider":
            output_metadata = state.output.metadata
            if not isinstance(output_metadata, dict):
                return Score(
                    value=INCORRECT,
                    explanation="Aider output lacks gateway-bound run metadata",
                )
            gateway_validation = output_metadata.get("gateway_validation")
            if not (
                isinstance(gateway_validation, dict)
                and set(gateway_validation)
                == {"schema_version", "valid", "error", "metrics"}
                and gateway_validation.get("schema_version")
                == "model-gateway-validation/v2"
                and gateway_validation.get("valid") is True
                and gateway_validation.get("error") is None
                and isinstance(gateway_validation.get("metrics"), dict)
            ):
                return Score(
                    value=INCORRECT,
                    explanation="Aider gateway metrics lack TS validation authority",
                )
            gateway_metrics = gateway_validation["metrics"]

        agent_environment = sandbox("default")
        verifier_environment = sandbox("verifier")
        oracle_environment = sandbox("oracle")
        setup = f"""set -eu
rm -rf {WORKSPACE}
mkdir -p {WORKSPACE}
mkdir -p /tmp/home
tar -xf /opt/coding-corpus/repository.tar -C {WORKSPACE}
"""
        for name, environment in (
            ("verifier", verifier_environment),
            ("oracle", oracle_environment),
        ):
            prepared = await environment.exec(
                ["sh", "-c", setup], timeout=60, timeout_retry=False
            )
            if not prepared.success:
                raise RuntimeError(f"{name} sandbox setup failed: {prepared.stderr[-1000:]}")
        verifier_overlay = await verifier_environment.exec(
            [
                "/usr/bin/tar",
                "-xf",
                "/opt/coding-corpus/verifier.tar",
                "-C",
                WORKSPACE,
            ],
            timeout=60,
            timeout_retry=False,
        )
        if not verifier_overlay.success:
            raise RuntimeError(
                f"verifier overlay failed: {verifier_overlay.stderr[-1000:]}"
            )

        for relative in case.submission_paths:
            source = f"{WORKSPACE}/{relative}"
            stat_result = await agent_environment.exec(
                ["/usr/bin/stat", "-c", "%F\n%s", "--", source],
                timeout=30,
                timeout_retry=False,
            )
            stat_lines = stat_result.stdout.splitlines()
            if (
                not stat_result.success
                or len(stat_lines) != 2
                or stat_lines[0] != "regular file"
            ):
                return Score(
                    value=INCORRECT,
                    explanation=f"submission is not a regular file: {relative}",
                )
            try:
                size = int(stat_lines[1])
            except ValueError:
                return Score(value=INCORRECT, explanation=f"submission size is invalid: {relative}")
            if not 0 <= size <= 1_000_000:
                return Score(value=INCORRECT, explanation=f"submission exceeds 1 MB: {relative}")
            encoded = await agent_environment.exec(
                ["/usr/bin/base64", "-w", "0", "--", source],
                timeout=30,
                timeout_retry=False,
            )
            try:
                content = base64.b64decode(encoded.stdout, validate=True)
            except (binascii.Error, ValueError):
                return Score(value=INCORRECT, explanation=f"submission copy failed: {relative}")
            if not encoded.success or len(content) != size:
                return Score(value=INCORRECT, explanation=f"submission copy failed: {relative}")
            await verifier_environment.write_file(f"{WORKSPACE}/{relative}", content)

        verifier_argv = ["/usr/local/bin/python3", *case.verifier[1:]]
        try:
            oracle_result = await oracle_environment.exec(
                verifier_argv,
                cwd=WORKSPACE,
                env={
                    "PYTHONPATH": f"{WORKSPACE}/src:{WORKSPACE}/scripts",
                    "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                },
                timeout=case.timeout_seconds,
                timeout_retry=False,
            )
        except (TimeoutError, OutputLimitExceededError, UnicodeDecodeError) as exc:
            oracle_observation: dict[str, object] = {
                "kind": "execution_error",
                "error": type(exc).__name__,
            }
        else:
            oracle_observation = _verifier_observation(oracle_result)
        candidate_observation: dict[str, object]
        try:
            result = await verifier_environment.exec(
                verifier_argv,
                cwd=WORKSPACE,
                env={
                    "PYTHONPATH": f"{WORKSPACE}/src:{WORKSPACE}/scripts",
                    "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                },
                timeout=case.timeout_seconds,
                timeout_retry=False,
            )
        except (TimeoutError, OutputLimitExceededError, UnicodeDecodeError) as exc:
            candidate_observation = {
                "kind": "execution_error",
                "error": type(exc).__name__,
            }
        else:
            candidate_observation = _verifier_observation(result)
        decision = score_candidate(
            Path(corpus_path),
            case.id,
            state.metadata,
            oracle_observation,
            candidate_observation,
        )
        if decision.kind == "harness_error":
            raise RuntimeError(decision.reason or "TypeScript score authority failed")
        return Score(
            value=CORRECT if decision.correct else INCORRECT,
            explanation=decision.explanation or "TypeScript score authority returned no detail",
            metadata={
                "agent": agent,
                "returncode": decision.returncode,
                "case_id": case.id,
                "oracle_signature_match": decision.oracle_signature_match,
                **(
                    {"execution_error": decision.execution_error}
                    if decision.execution_error is not None
                    else {}
                ),
                **({"gateway": gateway_metrics} if gateway_metrics is not None else {}),
            },
        )

    return score


AIDER_MODEL = "openai/qwen3.6-35b-a3b"
AIDER_SETTINGS = f"""- name: {AIDER_MODEL}
  edit_format: architect
  weak_model_name: {AIDER_MODEL}
  use_repo_map: true
  editor_model_name: {AIDER_MODEL}
  editor_edit_format: editor-whole
  use_temperature: false
  streaming: false
"""
AIDER_METADATA = json.dumps(
    {
        AIDER_MODEL: {
            "max_tokens": 4_096,
            "max_input_tokens": 28_672,
            "max_output_tokens": 4_096,
            "input_cost_per_token": 0,
            "output_cost_per_token": 0,
            "litellm_provider": "openai",
            "mode": "chat",
        }
    },
    separators=(",", ":"),
)


@solver
def aider_cli() -> Solver:
    """Run one pinned Aider turn inside the candidate sandbox."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        del generate
        candidate = sandbox("default")
        gateway = sandbox("model-gateway")
        task_path = "/opt/coding-corpus/task.txt"
        settings_path = "/opt/coding-corpus/model-settings.yml"
        metadata_path = "/opt/coding-corpus/model-metadata.json"
        await candidate.write_file(
            task_path, f"{OPERATING_PROMPT}\n\nUser task:\n{state.input_text}"
        )
        await candidate.write_file(settings_path, AIDER_SETTINGS)
        await candidate.write_file(metadata_path, AIDER_METADATA)
        argv = [
            "/opt/aider/bin/aider",
            "--model",
            AIDER_MODEL,
            "--openai-api-base",
            "http://model-gateway:8080/v1",
            "--openai-api-key",
            "candidate-placeholder",
            "--architect",
            "--editor-model",
            AIDER_MODEL,
            "--editor-edit-format",
            "editor-whole",
            "--weak-model",
            AIDER_MODEL,
            "--auto-accept-architect",
            "--yes-always",
            "--message-file",
            task_path,
            "--model-settings-file",
            settings_path,
            "--model-metadata-file",
            metadata_path,
            "--map-tokens",
            "1024",
            "--map-refresh",
            "manual",
            "--map-multiplier-no-files",
            "1",
            "--no-auto-commits",
            "--no-dirty-commits",
            "--no-gitignore",
            "--no-auto-lint",
            "--no-auto-test",
            "--no-analytics",
            "--no-check-update",
            "--no-show-release-notes",
            "--no-detect-urls",
            "--disable-playwright",
            "--no-suggest-shell-commands",
            "--no-pretty",
            "--no-stream",
            "--no-fancy-input",
            "--no-notifications",
            "--no-restore-chat-history",
            "--no-show-model-warnings",
            "--no-check-model-accepts-settings",
            "--config",
            "/dev/null",
            "--env-file",
            "/dev/null",
            "--aiderignore",
            "/dev/null",
            "--input-history-file",
            "/tmp/aider.input.history",
            "--chat-history-file",
            "/tmp/aider.chat.history.md",
            "--llm-history-file",
            "/tmp/aider.llm.history",
            "--timeout",
            "210",
        ]
        error: str | None = None
        returncode = 125
        stdout = ""
        stderr = ""
        try:
            result = await candidate.exec(
                argv,
                cwd=WORKSPACE,
                env={
                    "HOME": "/tmp/home",
                    "OPENAI_API_BASE": "http://model-gateway:8080/v1",
                    "OPENAI_API_KEY": "candidate-placeholder",
                },
                timeout=1_800,
                timeout_retry=False,
            )
            returncode = result.returncode
            stdout = result.stdout[-8_000:]
            stderr = result.stderr[-8_000:]
        except (TimeoutError, OutputLimitExceededError, UnicodeDecodeError) as exc:
            error = type(exc).__name__

        gateway_validation: dict[str, object] = {
            "schema_version": "model-gateway-validation/v2",
            "valid": False,
            "error": "metrics_unavailable",
            "metrics": None,
        }
        try:
            validated = await gateway.exec(
                [
                    "node",
                    "--no-strip-types",
                    "/opt/model-gateway/dist/gateway-cli.js",
                    "validate-metrics",
                ],
                timeout=30,
                timeout_retry=False,
            )
            validation_payload = json.loads(validated.stdout)
            if (
                validated.success
                and isinstance(validation_payload, dict)
                and set(validation_payload)
                == {"schema_version", "valid", "error", "metrics"}
            ):
                gateway_validation = validation_payload
        except (
            FileNotFoundError,
            json.JSONDecodeError,
            UnicodeDecodeError,
            TypeError,
            TimeoutError,
            OutputLimitExceededError,
        ):
            pass

        completion = (
            f"Aider exit={returncode}; execution_error={error or 'none'}\n"
            f"stdout:\n{stdout}\nstderr:\n{stderr}"
        )
        output = ModelOutput.from_content(
            model=f"aider/{AIDER_MODEL}",
            content=completion,
            stop_reason="stop" if returncode == 0 else "unknown",
            error=error,
        )
        output.metadata = {
            "agent": "aider-0.86.2",
            "returncode": returncode,
            "gateway_validation": gateway_validation,
        }
        state.output = output
        state.completed = True
        return state

    return solve


@task
def company_coding(
    corpus: str = str(HERE / "pilot.jsonl"),
    split: Literal["calibration", "validation", "heldout"] = "calibration",
    epochs: int = 1,
    agent: Literal["react", "aider"] = "react",
    repository: str = str(repository_root()),
) -> Task:
    """Run one bounded coding agent against the historical corpus."""
    if not 1 <= epochs <= 5:
        raise ValueError("epochs must be from 1 through 5")
    selected_solver: Solver
    compose_file: Path
    if agent == "react":
        selected_solver = react(
            prompt=OPERATING_PROMPT,
            tools=[bash(timeout=120, sandbox="default")],
        )
        compose_file = HERE / "compose.yaml"
    elif agent == "aider":
        selected_solver = aider_cli()
        compose_file = HERE / "compose-aider.yaml"
    else:
        raise ValueError(f"unsupported agent: {agent}")
    repo = Path(repository).resolve()
    cases = prepare_corpus(Path(corpus), repo, split, _ARCHIVE_ROOT)
    return Task(
        dataset=[_sample(case) for case in cases],
        solver=selected_solver,
        scorer=repository_verifier(corpus, agent),
        sandbox=("docker", str(compose_file)),
        epochs=epochs,
        fail_on_error=True,
        message_limit=80,
        token_limit=32_000,
        turn_limit=8,
        time_limit=1_800,
        version="pilot-3",
        metadata={
            "agent": agent,
            "repository": str(repo),
            "split": split,
            "submission_threat_model": "cooperative-agent-no-verifier-tampering",
        },
        tags=["coding-corpus", "historical", "pilot", split, agent],
    )
