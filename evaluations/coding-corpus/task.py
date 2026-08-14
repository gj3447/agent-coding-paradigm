"""Inspect task for the repository's historical coding corpus."""

from __future__ import annotations

import atexit
import base64
import binascii
import json
import shutil
import subprocess
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
    CorpusCase,
    archive_revision,
    check_cases,
    load_cases,
    repository_root,
    validate_history,
    verifier_signature,
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
def _sample(case: CorpusCase, repo: Path) -> Sample:
    base_archive = _ARCHIVE_ROOT / f"{case.id}-base.tar"
    oracle_archive = _ARCHIVE_ROOT / f"{case.id}-oracle.tar"
    archive_revision(repo, case.base_sha, base_archive)
    archive_revision(repo, case.oracle_sha, oracle_archive)
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
        metadata=case.metadata(),
        files={
            "/opt/coding-corpus/repository.tar": str(base_archive),
            "verifier:/opt/coding-corpus/repository.tar": str(base_archive),
            "oracle:/opt/coding-corpus/repository.tar": str(oracle_archive),
        },
        setup=setup,
    )


@scorer(metrics=[accuracy()])
def repository_verifier(
    corpus_path: str,
    repository: str,
    agent: Literal["react", "aider"],
):
    async def score(state: TaskState, target: Target) -> Score:
        del target
        cases = {case.id: case for case in load_cases(Path(corpus_path))}
        case_id = state.metadata.get("case_id")
        case = cases.get(case_id)
        if case is None or state.metadata != case.metadata():
            return Score(value=INCORRECT, explanation="sample metadata is not corpus-bound")
        gateway_metrics: dict[str, object] | None = None
        if agent == "aider":
            output_metadata = state.output.metadata
            if not isinstance(output_metadata, dict):
                return Score(
                    value=INCORRECT,
                    explanation="Aider output lacks gateway-bound run metadata",
                )
            raw_gateway_metrics = output_metadata.get("gateway")
            gateway_validation = output_metadata.get("gateway_validation")
            if not (
                isinstance(raw_gateway_metrics, dict)
                and gateway_validation
                == {
                    "schema_version": "model-gateway-validation/v1",
                    "valid": True,
                    "error": None,
                }
            ):
                return Score(
                    value=INCORRECT,
                    explanation="Aider gateway metrics lack TS validation authority",
                )
            gateway_metrics = raw_gateway_metrics

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

        root = Path(repository).resolve()
        for relative in case.verifier_paths:
            completed = subprocess.run(
                ["git", "-C", str(root), "show", f"{case.oracle_sha}:{relative}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if completed.returncode != 0:
                return Score(
                    value=INCORRECT,
                    explanation=f"verifier material unavailable: {relative}",
                )
            await verifier_environment.write_file(f"{WORKSPACE}/{relative}", completed.stdout)

        verifier_argv = ["/usr/local/bin/python3", *case.verifier[1:]]
        oracle_result = await oracle_environment.exec(
            verifier_argv,
            cwd=WORKSPACE,
            env={"PYTHONPATH": f"{WORKSPACE}/src:{WORKSPACE}/scripts"},
            timeout=case.timeout_seconds,
            timeout_retry=False,
        )
        oracle_signature = verifier_signature(
            case.verifier, oracle_result.stdout, oracle_result.stderr
        )
        if not oracle_result.success or not oracle_signature:
            raise RuntimeError(
                "oracle verifier did not produce a successful admitted signature"
            )

        try:
            result = await verifier_environment.exec(
                verifier_argv,
                cwd=WORKSPACE,
                env={"PYTHONPATH": f"{WORKSPACE}/src:{WORKSPACE}/scripts"},
                timeout=case.timeout_seconds,
                timeout_retry=False,
            )
        except (TimeoutError, OutputLimitExceededError, UnicodeDecodeError) as exc:
            return Score(
                value=INCORRECT,
                explanation=f"candidate verifier could not complete: {type(exc).__name__}",
                metadata={"case_id": case.id, "execution_error": type(exc).__name__},
            )
        candidate_signature = verifier_signature(
            case.verifier, result.stdout, result.stderr
        )
        stdout = result.stdout[-4_000:]
        stderr = result.stderr[-4_000:]
        verified = result.success and candidate_signature == oracle_signature
        return Score(
            value=CORRECT if verified else INCORRECT,
            explanation=(
                f"verifier exit={result.returncode}; "
                f"oracle_signature_match={candidate_signature == oracle_signature}\n"
                f"stdout:\n{stdout}\nstderr:\n{stderr}"
            ),
            metadata={
                "agent": agent,
                "returncode": result.returncode,
                "case_id": case.id,
                "oracle_signature_match": candidate_signature == oracle_signature,
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

        metrics: dict[str, object] = {}
        gateway_validation: dict[str, object] = {}
        try:
            raw_metrics = await gateway.read_file("/tmp/gateway/metrics.json")
            decoded = json.loads(raw_metrics)
            if isinstance(decoded, dict):
                metrics = decoded
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
            if validated.success and isinstance(validation_payload, dict):
                gateway_validation = validation_payload
        except (
            FileNotFoundError,
            json.JSONDecodeError,
            UnicodeDecodeError,
            TypeError,
            TimeoutError,
            OutputLimitExceededError,
        ):
            metrics = {"metrics_unavailable": True}

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
            "gateway": metrics,
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
    all_cases = load_cases(Path(corpus))
    validate_history(repo, all_cases)
    cases = tuple(case for case in all_cases if case.split == split)
    if not cases:
        raise ValueError(f"corpus contains no {split} cases")
    invalid = [
        check.case_id
        for check in check_cases(repo, all_cases)
        if not check.valid
    ]
    if invalid:
        raise ValueError(f"corpus admission failed for: {invalid}")
    return Task(
        dataset=[_sample(case, repo) for case in cases],
        solver=selected_solver,
        scorer=repository_verifier(corpus, str(repo), agent),
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
