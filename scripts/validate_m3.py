#!/usr/bin/env python3
"""Aggregate validator for the bounded M3 scalar-frontier reference slice."""

from __future__ import annotations

import hashlib
import copy
import json
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import jsonschema
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[1]
JSONSCHEMA_SITE_PACKAGES = str(Path(jsonschema.__file__).resolve().parents[1])
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from m3_fixtures import load_cases
from m3_oracle import (
    canonical_bytes as oracle_canonical_bytes,
    delivery_id,
    profile_digest,
    run_sequence,
    step_expected,
    value_digest,
)
from flrh_reactive import step_r


EXPECTED_TOOLS = [
    "scripts/m1_guard.py", "scripts/validate_m0.py", "scripts/validate_m1.py",
    "scripts/validate_m2.py", "scripts/m3_fixtures.py", "scripts/m3_oracle.py",
    "scripts/m3_guard.py", "scripts/check_m3_ambient.py",
    "scripts/check_m3_semantic_mutants.py", "scripts/run_m3_replay.py",
    "scripts/validate_m3.py", "tests/test_m3_reactive.py",
]
MEASURED_STATUS = "MEASURED_REFERENCE_CONFORMANCE"
CLEAN_PROCESS_PROFILES = (
    {
        "label": "clean-a",
        "python_hash_seed": "37",
        "timezone": "UTC",
    },
    {
        "label": "clean-b",
        "python_hash_seed": "83",
        "timezone": "Asia/Seoul",
    },
)
EXPECTED_AMBIENT_REPORT = {
    "ambient_categories": [
        "clock",
        "randomness",
        "uuid",
        "environment",
        "filesystem",
        "network",
        "subprocess",
        "model_or_tool",
    ],
    "audit_guard_self_tests": 3,
    "explicit_guard_self_tests": 8,
    "guard_self_tests": 11,
    "import_attempts": 0,
    "import_metadata_checks": 10,
    "kernel_ambient_attempts": 0,
    "kernel_input_mutation_attempts": 0,
    "kernel_path_ambient_attempts": 0,
    "kernel_path_executions": 13,
    "kernel_path_input_mutation_attempts": 0,
    "kernel_path_profiles": 2,
    "kernel_path_rejections": 3,
    "kernel_path_successes": 10,
    "mutants_detected": 14,
}
EXPECTED_SEMANTIC_MUTANTS = (
    "frontier_non_strict",
    "frontier_global_max",
    "partial_epoch_publication",
    "item_level_demand",
    "overflow_accept_drop_max_open",
    "late_delta_acceptance",
    "eligibility_status_interpretation",
    "nested_value_rewrite",
    "nested_dataflow_version_drift",
    "authority_shaped_output",
)


def load_json(relative: str) -> Any:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def sha256_file(relative: str) -> str:
    return "sha256:" + hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def registry() -> Registry:
    resources = []
    for path in sorted((ROOT / "spec/schema").glob("*.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        if "$id" in schema:
            resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def validate(instance: Any, schema: dict[str, Any], schemas: Registry) -> None:
    errors = sorted(
        Draft202012Validator(schema, registry=schemas, format_checker=FormatChecker()).iter_errors(instance),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        error = errors[0]
        path = "/" + "/".join(str(item) for item in error.absolute_path)
        raise AssertionError(f"schema rejection at {path}: {error.message}")


def _prior_for_rejection(corpus, case):
    if case["prior_sequence_ref"] is None:
        return None
    sequence = next(item for item in corpus["success_sequences"] if item["id"] == case["prior_sequence_ref"])
    commands = [item["command"] for item in sequence["steps"][: case["prior_step"] + 1]]
    results = run_sequence(None, corpus["profile"], commands)
    return results[-1]["next_state"]


def _run_gate(relative: str) -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / relative)], cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    require(completed.returncode == 0, f"inherited gate failed: {relative}: {completed.stderr or completed.stdout}")


def _run_production(profile, commands):
    state = None
    results = []
    for command in commands:
        result = step_r(state, profile, command)
        results.append(result)
        if result["kind"] == "RRejection":
            break
        state = result["next_state"]
    return results


def _clean_environment(
    home: Path,
    temporary: Path,
    *,
    python_hash_seed: str,
    timezone: str,
    poison: str,
    pythonpath: str = "",
) -> dict[str, str]:
    environment = {
        "FLRH_M3_PROCESS_POISON": poison,
        "HOME": str(home),
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": os.defpath,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": python_hash_seed,
        "TMPDIR": str(temporary),
        "TZ": timezone,
    }
    if "SystemRoot" in os.environ:
        environment["SystemRoot"] = os.environ["SystemRoot"]
    if pythonpath:
        environment["PYTHONPATH"] = pythonpath
    return environment


def _parse_canonical_line(raw: bytes, *, label: str) -> Any:
    require(raw.endswith(b"\n"), f"{label} did not emit a newline-terminated JSON line")
    require(raw.count(b"\n") == 1, f"{label} emitted more than one stdout line")
    payload = raw[:-1]
    require(bool(payload), f"{label} emitted an empty JSON line")
    try:
        parsed = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AssertionError(f"{label} emitted invalid UTF-8 JSON: {error}") from error
    require(
        oracle_canonical_bytes(parsed) == payload,
        f"{label} stdout was not independently canonical",
    )
    return parsed


def _run_clean_pair(
    relative: str,
    *,
    stdin: bytes,
    descriptor: str,
    pythonpath: str = "",
) -> Any:
    outputs: list[bytes] = []
    parsed_outputs: list[Any] = []
    temporary_roots: set[str] = set()
    for process_profile in CLEAN_PROCESS_PROFILES:
        with tempfile.TemporaryDirectory(
            prefix=f"flrh-m3-{descriptor}-{process_profile['label']}-"
        ) as temporary_root:
            root = Path(temporary_root)
            cwd = root / "cwd"
            home = root / "home"
            temporary = root / "tmp"
            cwd.mkdir()
            home.mkdir()
            temporary.mkdir()
            require(str(root) not in temporary_roots, f"{descriptor} reused a temporary root")
            temporary_roots.add(str(root))
            completed = subprocess.run(
                [sys.executable, "-B", str(ROOT / relative)],
                cwd=cwd,
                env=_clean_environment(
                    home,
                    temporary,
                    python_hash_seed=process_profile["python_hash_seed"],
                    timezone=process_profile["timezone"],
                    poison=f"{descriptor}:{process_profile['label']}",
                    pythonpath=pythonpath,
                ),
                input=stdin,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            require(
                completed.returncode == 0,
                f"{descriptor} {process_profile['label']} failed: "
                f"{completed.stderr.decode('utf-8', 'replace') or completed.stdout.decode('utf-8', 'replace')}",
            )
            require(
                completed.stderr == b"",
                f"{descriptor} {process_profile['label']} emitted stderr: "
                f"{completed.stderr.decode('utf-8', 'replace')}",
            )
            outputs.append(completed.stdout)
            parsed_outputs.append(
                _parse_canonical_line(
                    completed.stdout,
                    label=f"{descriptor} {process_profile['label']}",
                )
            )
    require(len(outputs) == 2, f"{descriptor} did not execute exactly two clean processes")
    require(outputs[0] == outputs[1], f"{descriptor} stdout bytes varied by process profile")
    require(parsed_outputs[0] == parsed_outputs[1], f"{descriptor} parsed reports differed")
    return parsed_outputs[0]


def _clean_replay(profile, commands):
    document = {
        "mode": "sequence",
        "prior_state": None,
        "profile": profile,
        "commands": commands,
    }
    replay = _run_clean_pair(
        "scripts/run_m3_replay.py",
        stdin=oracle_canonical_bytes(document) + b"\n",
        descriptor="replay",
    )
    require(
        isinstance(replay, dict)
        and set(replay) == {"kind", "results", "final_state"}
        and replay["kind"] == "M3ReplaySequence"
        and isinstance(replay["results"], list),
        "clean replay emitted a malformed sequence envelope",
    )
    return replay


def _clean_ambient_report() -> dict[str, Any]:
    report = _run_clean_pair(
        "scripts/check_m3_ambient.py",
        stdin=b"",
        descriptor="ambient",
    )
    require(isinstance(report, dict), "clean ambient checker did not emit an object")
    require(report == EXPECTED_AMBIENT_REPORT, "clean ambient report coverage/count drift")
    return report


def _clean_semantic_mutation_report() -> dict[str, Any]:
    report = _run_clean_pair(
        "scripts/check_m3_semantic_mutants.py",
        stdin=b"",
        descriptor="semantic-mutants",
        pythonpath=JSONSCHEMA_SITE_PACKAGES,
    )
    require(isinstance(report, dict), "clean semantic mutation checker did not emit an object")
    require(
        set(report) == {
            "baseline", "completion_gate_axis_count", "contract", "contract_sha256",
            "escaped_count", "invalid_mutant_count", "killed_count", "kind",
            "mutant_count", "mutants", "oracle", "oracle_independent",
            "oracle_sha256", "per_mutant_timeout_seconds", "schema_version", "source",
            "source_sha256", "source_stable", "status", "wire_schema",
            "wire_schema_sha256",
        },
        "clean semantic mutation report field drift",
    )
    require(report["kind"] == "M3SemanticMutationReport", "semantic report kind drift")
    require(report["schema_version"] == "m3-semantic-mutation-report/1", "semantic report schema drift")
    require(report["status"] == "PASS", "semantic mutation gate did not pass")
    require(report["completion_gate_axis_count"] == 10, "semantic contract-axis count drift")
    require(report["mutant_count"] == 10, "semantic mutant count drift")
    require(report["killed_count"] == 10, "semantic mutant kill count drift")
    require(report["escaped_count"] == 0, "semantic mutant escaped")
    require(report["invalid_mutant_count"] == 0, "semantic mutant was invalid")
    require(report["source_stable"] is True, "semantic source changed during mutation run")
    require(report["oracle_independent"] is True, "semantic oracle independence claim drift")
    require(report["per_mutant_timeout_seconds"] == 10, "semantic mutant timeout drift")
    expected_paths = {
        "source": "src/flrh_reactive/reactive.py",
        "oracle": "scripts/m3_oracle.py",
        "contract": "spec/m3-reactive-contract.v1.json",
        "wire_schema": "spec/schema/m3-reactive.v1.schema.json",
    }
    for key, relative in expected_paths.items():
        require(report[key] == relative, f"semantic report path drift: {key}")
        require(report[f"{key}_sha256"] == sha256_file(relative), f"semantic report digest drift: {key}")
    baseline = report["baseline"]
    require(
        baseline == {
            "kind": "M3SemanticBaselineReceipt",
            "probe_count": 10,
            "reason": None,
            "schema_document_count": 112,
            "source_sha256": sha256_file("src/flrh_reactive/reactive.py"),
            "status": "PASS",
            "step_count": 34,
        },
        "semantic baseline receipt drift",
    )
    mutants = report["mutants"]
    require(isinstance(mutants, list) and len(mutants) == 10, "semantic mutant receipts drift")
    require(
        tuple(item.get("name") for item in mutants) == EXPECTED_SEMANTIC_MUTANTS,
        "semantic mutant identity/order drift",
    )
    for item in mutants:
        require(item.get("kind") == "M3SemanticMutantReceipt", "semantic mutant receipt kind drift")
        require(item.get("outcome") == "KILLED", f"semantic mutant not killed: {item.get('name')}")
        require(item.get("anchor_matches") == 1, f"semantic mutant anchor drift: {item.get('name')}")
        require(item.get("invalid_reason") is None, f"semantic mutant invalid: {item.get('name')}")
        require(isinstance(item.get("divergence_step"), int), f"semantic divergence missing: {item.get('name')}")
    return report


def _randomized_value_delta(
    profile: dict[str, Any],
    *,
    source_id: str,
    logical_time: int,
    value_kind: str,
    value: dict[str, Any],
) -> dict[str, Any]:
    bound = value_digest(value_kind, value)
    return {
        "kind": "RValueDelta",
        "schema_version": "flrh-r-value-delta/1",
        "delivery_id": delivery_id(
            source_id,
            logical_time,
            profile["dataflow_version"],
            value_kind,
            bound,
        ),
        "source_id": source_id,
        "logical_time": logical_time,
        "diff": 1,
        "dataflow_version": profile["dataflow_version"],
        "value_kind": value_kind,
        "value_digest": bound,
        "value": copy.deepcopy(value),
    }


def _validate_randomized_slow_consumer(
    corpus: dict[str, Any],
    wire_schema: dict[str, Any],
    schemas: Registry,
) -> dict[str, int]:
    rng = random.Random(20260809)
    trials = 32
    oracle_comparisons = 0
    slow_consumer_trials = 0
    capacity_rejections = 0
    boundary_matrix = (
        (1, 0, 1),
        (2, 0, 1),
        (2, 1, 1),
        (3, 1, 1),
        (3, 2, 1),
    )
    for trial in range(trials):
        profile = copy.deepcopy(corpus["profile"])
        if trial < len(boundary_matrix):
            epoch_count, demand, ready_limit = boundary_matrix[trial]
        else:
            epoch_count = rng.randint(1, 3)
            demand = rng.randint(0, 3)
            ready_limit = rng.randint(1, 3)
        profile["limits"].update(
            {
                "max_deltas_per_command": 8,
                "max_active_values": 8,
                "max_open_epochs": 3,
                "max_ready_batches": ready_limit,
                "max_demand_per_command": 3,
                "max_outstanding_demand": 3,
            }
        )
        profile["profile_digest"] = profile_digest(profile)
        deltas = []
        for offset in range(epoch_count):
            logical_time = 3 + (2 * offset)
            suffix = f"random-{trial}-{logical_time}"
            proposal = copy.deepcopy(corpus["proposals"]["m1_effect_proposal"])
            proposal.update(
                {
                    "proposal_id": f"proposal:m3:{suffix}",
                    "proposal_dedup_key": f"proposal-dedup:m3:{suffix}",
                    "cause_id": f"cause:m3:proposal:{suffix}",
                }
            )
            verdict = copy.deepcopy(corpus["verdicts"]["m3_verdict"])
            verdict.update(
                {
                    "proposal_id": proposal["proposal_id"],
                    "verdict_id": f"verdict:m3:{suffix}",
                    "cause_id": f"cause:m3:verdict:{suffix}",
                }
            )
            deltas.extend(
                [
                    _randomized_value_delta(
                        profile,
                        source_id="source:m3:a",
                        logical_time=logical_time,
                        value_kind="effect_proposal",
                        value=proposal,
                    ),
                    _randomized_value_delta(
                        profile,
                        source_id="source:m3:b",
                        logical_time=logical_time,
                        value_kind="eligibility_verdict",
                        value=verdict,
                    ),
                ]
            )
        left_deltas = copy.deepcopy(deltas)
        right_deltas = copy.deepcopy(deltas)
        rng.shuffle(left_deltas)
        rng.shuffle(right_deltas)
        if left_deltas == right_deltas:
            right_deltas.reverse()

        def commands_for(ordered_deltas: list[dict[str, Any]]) -> list[dict[str, Any]]:
            base = {
                "schema_version": "flrh-r-command/1",
                "profile_digest": profile["profile_digest"],
                "dataflow_version": profile["dataflow_version"],
            }
            commands = []
            if demand:
                commands.append({"kind": "RGrantDemand", **base, "batches": demand})
            commands.append({"kind": "RApplyDeltaBatch", **base, "deltas": ordered_deltas})
            frontiers = [
                {"kind": "RAdvanceFrontier", **base, "source_id": "source:m3:a", "low_watermark": 8},
                {"kind": "RAdvanceFrontier", **base, "source_id": "source:m3:b", "low_watermark": 8},
            ]
            if trial % 2:
                frontiers.reverse()
            return commands + frontiers

        observed_runs = []
        for ordered_deltas in (left_deltas, right_deltas):
            commands = commands_for(ordered_deltas)
            expected = run_sequence(None, profile, commands)
            actual = _run_production(profile, commands)
            for result in expected + actual:
                validate(result, wire_schema, schemas)
            require(
                oracle_canonical_bytes(actual) == oracle_canonical_bytes(expected),
                f"randomized production/oracle mismatch: trial {trial}",
            )
            observed_runs.append(actual)
            oracle_comparisons += 1
        require(
            oracle_canonical_bytes(observed_runs[0])
            == oracle_canonical_bytes(observed_runs[1]),
            f"randomized delta-order mismatch: trial {trial}",
        )
        if demand < epoch_count:
            slow_consumer_trials += 1
        if observed_runs[0][-1]["kind"] == "RRejection":
            require(
                observed_runs[0][-1]["code"] == "QUEUE_CAPACITY_EXCEEDED",
                f"unexpected randomized rejection: trial {trial}",
            )
            capacity_rejections += 1
    require(slow_consumer_trials > 0, "randomized corpus missed slow-consumer trials")
    require(capacity_rejections > 0, "randomized corpus missed capacity rejection")
    return {
        "randomized_order_trials": trials,
        "randomized_oracle_comparisons": oracle_comparisons,
        "slow_consumer_trials": slow_consumer_trials,
        "randomized_capacity_rejections": capacity_rejections,
    }


def validate_all(require_measured: bool = True) -> dict[str, int | str]:
    manifest = load_json("spec/m3-manifest.v1.json")
    contract = load_json("spec/m3-reactive-contract.v1.json")
    claim_ledger = load_json("spec/claims.v1.json")
    corpus = load_cases()
    schemas = registry()
    wire_schema = load_json("spec/schema/m3-reactive.v1.schema.json")

    require(manifest["non_normative_tools"] == EXPECTED_TOOLS, "M3 tool closure/order drift")
    require(manifest["status"] in {"PROPOSED_PENDING_MEASUREMENT", MEASURED_STATUS}, "unknown M3 status")
    require(manifest["status"] == contract["status"], "M3 manifest/contract status drift")
    claim = next(
        (item for item in claim_ledger["claims"] if item["id"] == "m3-scalar-frontier-r-contract"),
        None,
    )
    require(claim is not None, "M3 claim-ledger entry missing")
    expected_claim_status = (
        "MEASURED" if manifest["status"] == MEASURED_STATUS else "PROPOSED"
    )
    require(claim["epistemic_status"] == expected_claim_status, "M3 claim-ledger status drift")
    m3_doc = (ROOT / "docs/M3_REACTIVE.md").read_text(encoding="utf-8")
    require(
        f"> Status: **{manifest['status']}**." in m3_doc,
        "M3 document status drift",
    )
    for path in manifest["normative_contracts"] + manifest["reference_implementation"] + EXPECTED_TOOLS + manifest["golden_outputs"]:
        require((ROOT / path).is_file(), f"manifest artifact missing: {path}")
    for dependency in manifest["inherited_normative_dependencies"] + manifest["inherited_fixture_dependencies"]:
        require(sha256_file(dependency["artifact"]) == dependency["sha256"], f"inherited digest drift: {dependency['artifact']}")

    for relative in manifest["self_validating_schemas"]:
        schema = load_json(relative)
        Draft202012Validator.check_schema(schema)
    for binding in manifest["schema_bindings"]:
        validate(load_json(binding["artifact"]), load_json(binding["schema"]), schemas)

    require(corpus["profile"]["profile_digest"] == profile_digest(corpus["profile"]), "profile digest drift")
    for delta in corpus["deltas"].values():
        require(delta["value_digest"] == value_digest(delta["value_kind"], delta["value"]), "value digest drift")
        require(
            delta["delivery_id"] == delivery_id(delta["source_id"], delta["logical_time"], delta["dataflow_version"], delta["value_kind"], delta["value_digest"]),
            "delivery identity drift",
        )

    transition_count = 0
    publication_count = 0
    for sequence in corpus["success_sequences"]:
        commands = [item["command"] for item in sequence["steps"]]
        results = run_sequence(None, corpus["profile"], commands)
        production = _run_production(corpus["profile"], commands)
        require(len(production) == len(results), f"production/oracle result-count mismatch: {sequence['id']}")
        for result_index, (actual, expected) in enumerate(zip(production, results)):
            validate(expected, wire_schema, schemas)
            validate(actual, wire_schema, schemas)
            require(
                oracle_canonical_bytes(actual) == oracle_canonical_bytes(expected),
                f"production/oracle byte mismatch: {sequence['id']} step {result_index}",
            )
        require(len(results) == len(commands), f"oracle sequence rejected: {sequence['id']}")
        for step, result in zip(sequence["steps"], results):
            require(result["kind"] == step["expected_kind"], f"kind drift: {sequence['id']}")
            require(len(result["published_batches"]) == step["expected_publication_count"], f"publication drift: {sequence['id']}")
            if "expected_transition_digest" in step:
                require(result["transition_digest"] == step["expected_transition_digest"], f"transition drift: {sequence['id']}")
            transition_count += 1
            publication_count += len(result["published_batches"])

    for case in corpus["rejection_cases"]:
        prior = _prior_for_rejection(corpus, case)
        expected = step_expected(prior, corpus["profile"], case["command"])
        actual = step_r(prior, corpus["profile"], case["command"])
        validate(case["expected"], wire_schema, schemas)
        validate(expected, wire_schema, schemas)
        validate(actual, wire_schema, schemas)
        require(
            oracle_canonical_bytes(expected) == oracle_canonical_bytes(case["expected"]),
            f"rejection oracle byte drift: {case['id']}",
        )
        require(
            oracle_canonical_bytes(actual) == oracle_canonical_bytes(expected),
            f"rejection production byte drift: {case['id']}",
        )

    for golden in corpus["goldens"]:
        require(golden["path"] in manifest["golden_outputs"], f"unmanifested golden: {golden['path']}")
    stable_sequence = next(item for item in corpus["success_sequences"] if item["id"] == "sequence:frontier-stable")
    stable_commands = [item["command"] for item in stable_sequence["steps"]]
    stable_golden = load_json("fixtures/m3/golden/frontier-stable.transition.json")
    late_golden = load_json("fixtures/m3/golden/late-delta.rejection.json")
    validate(stable_golden, wire_schema, schemas)
    validate(late_golden, wire_schema, schemas)
    require(
        oracle_canonical_bytes(stable_golden)
        == oracle_canonical_bytes(run_sequence(None, corpus["profile"], stable_commands)[-1]),
        "stable golden canonical-byte drift",
    )
    require(
        oracle_canonical_bytes(late_golden)
        == oracle_canonical_bytes(corpus["rejection_cases"][0]["expected"]),
        "late golden canonical-byte drift",
    )

    sequences = {item["id"]: item for item in corpus["success_sequences"]}
    for pair in corpus["equivalence_pairs"]:
        left = run_sequence(None, corpus["profile"], [step["command"] for step in sequences[pair["left_sequence_ref"]]["steps"]])
        right = run_sequence(None, corpus["profile"], [step["command"] for step in sequences[pair["right_sequence_ref"]]["steps"]])
        if pair["comparison"] == "full_transition_bytes":
            require(oracle_canonical_bytes(left) == oracle_canonical_bytes(right), f"equivalence drift: {pair['id']}")
        elif pair["comparison"] == "final_state_digest":
            require(left[-1]["next_state"]["state_digest"] == right[-1]["next_state"]["state_digest"], f"equivalence drift: {pair['id']}")
        else:
            require([x.get("published_batches", []) for x in left] == [x.get("published_batches", []) for x in right], f"equivalence drift: {pair['id']}")

    expected_stable_results = run_sequence(None, corpus["profile"], stable_commands)
    clean_replay = _clean_replay(corpus["profile"], stable_commands)
    for result in clean_replay["results"]:
        validate(result, wire_schema, schemas)
    validate(clean_replay["final_state"], wire_schema, schemas)
    require(
        oracle_canonical_bytes(clean_replay)
        == oracle_canonical_bytes({
                "kind": "M3ReplaySequence",
                "results": expected_stable_results,
                "final_state": expected_stable_results[-1]["next_state"],
            }),
        "base clean replay/oracle mismatch",
    )
    alternate = copy.deepcopy(corpus["profile"])
    alternate["limits"]["max_outstanding_demand"] = 4
    alternate["profile_digest"] = profile_digest(alternate)
    alternate_command = {
        "kind": "RGrantDemand", "schema_version": "flrh-r-command/1",
        "profile_digest": alternate["profile_digest"], "dataflow_version": alternate["dataflow_version"], "batches": 1,
    }
    alternate_production = _run_production(alternate, [alternate_command])
    alternate_oracle = run_sequence(None, alternate, [alternate_command])
    for result in alternate_production + alternate_oracle:
        validate(result, wire_schema, schemas)
    require(
        oracle_canonical_bytes(alternate_production) == oracle_canonical_bytes(alternate_oracle),
        "alternate-profile production/oracle mismatch",
    )
    randomized = _validate_randomized_slow_consumer(corpus, wire_schema, schemas)
    ambient_report = _clean_ambient_report()
    semantic_report = _clean_semantic_mutation_report()

    require(len(corpus["success_sequences"]) >= 3, "success corpus coverage floor")
    require(transition_count >= 7, "transition coverage floor")
    require(len(corpus["rejection_cases"]) >= 2, "rejection coverage floor")
    require(len(corpus["equivalence_pairs"]) >= 1, "equivalence coverage floor")
    require(len(corpus["goldens"]) == 2, "golden closure floor")

    for inherited in ("scripts/validate_m0.py", "scripts/validate_m1.py", "scripts/validate_m2.py"):
        _run_gate(inherited)
    tests = subprocess.run(
        [sys.executable, "-m", "unittest", "tests.test_m3_reactive", "-v"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    require(tests.returncode == 0, f"M3 tests failed: {tests.stderr or tests.stdout}")
    if require_measured:
        require(manifest["status"] == MEASURED_STATUS, "M3 has not been promoted to measured status")
    return {
        "status": manifest["status"],
        "success_sequences": len(corpus["success_sequences"]),
        "transitions": transition_count,
        "rejections": len(corpus["rejection_cases"]),
        "publications": publication_count,
        "mechanics_tests": len(manifest["mechanics_tests"]),
        "clean_replay_processes": len(CLEAN_PROCESS_PROFILES),
        "clean_ambient_processes": len(CLEAN_PROCESS_PROFILES),
        "clean_semantic_processes": len(CLEAN_PROCESS_PROFILES),
        "clean_process_dimensions": "cwd+HOME+PYTHONHASHSEED+TZ+poison",
        "ambient_kernel_paths": ambient_report["kernel_path_executions"],
        "ambient_mutants_detected": ambient_report["mutants_detected"],
        "semantic_mutants_detected": semantic_report["killed_count"],
        **randomized,
    }


def main() -> int:
    allowed = {"--allow-proposed"}
    unexpected = [argument for argument in sys.argv[1:] if argument not in allowed]
    require(not unexpected, f"unknown arguments: {unexpected}")
    print(
        json.dumps(
            validate_all(require_measured="--allow-proposed" not in sys.argv),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
