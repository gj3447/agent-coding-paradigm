#!/usr/bin/env python3
"""Aggregate candidate gate for one bounded proposed M4C integration profile."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from flrh_kernel.canonical import canonical_bytes
from m4c_verifier import TRACE, verify_m4c_evidence
from run_m4c_replay import run_reference_chain


EXPECTED = {
    "normative_contracts": ["spec/m4c-integration-contract.v1.json", "spec/m4c-manifest.v1.json"],
    "schemas": ["spec/schema/m4c-integration-contract.v1.schema.json", "spec/schema/m4c-fixtures.v1.schema.json", "spec/schema/m4c-manifest.v1.schema.json"],
    "schema_bindings": [
        {"artifact": "spec/m4c-integration-contract.v1.json", "schema": "spec/schema/m4c-integration-contract.v1.schema.json"},
        {"artifact": "spec/m4c-manifest.v1.json", "schema": "spec/schema/m4c-manifest.v1.schema.json"},
        {"artifact": "fixtures/m4c/cases.json", "schema": "spec/schema/m4c-fixtures.v1.schema.json"},
    ],
    "fixture": "fixtures/m4c/cases.json",
    "reference_implementation": ["scripts/m4c_verifier.py"],
    "tools": ["scripts/m4c_fixtures.py", "scripts/run_m4c_replay.py", "scripts/check_m4c_sensitivity.py", "scripts/validate_m4c.py", "tests/test_m4c_integration.py", "tests/test_m4c_candidate_gate.py"],
    "documentation": ["docs/M4C_INTEGRATED_SLICE.md"],
}

INHERITED = [
    "spec/run-fsm.v1.json",
    "spec/canonicalization.v1.json",
    "spec/schema/protocol.v1.schema.json",
    "spec/m1-kernel-contract.v1.json",
    "spec/m1-manifest.v1.json",
    "fixtures/m1/cases.json",
    "fixtures/m1/golden/observe-with-effect.transition.json",
    "spec/m2-logic-contract.v1.json",
    "spec/m2-manifest.v1.json",
    "spec/m3-reactive-contract.v1.json",
    "spec/m3-manifest.v1.json",
    "spec/lr-seam-contract.v1.json",
    "spec/lr-seam-manifest.v1.json",
    "scripts/lr_seam_fixtures.py",
    "spec/m4a-authority-contract.v1.json",
    "spec/m4a-manifest.v1.json",
    "spec/m4b-durable-contract.v1.json",
    "spec/m4b-manifest.v1.json",
]

NONREGRESSION = (
    ("scripts/validate_m0.py", ()),
    ("scripts/validate_m1.py", ()),
    ("scripts/validate_m2.py", ()),
    ("scripts/validate_m3.py", ()),
    ("scripts/validate_lr_seam.py", ()),
    ("scripts/validate_m4a.py", ("--allow-proposed",)),
    ("scripts/validate_m4b.py", ("--allow-proposed",)),
)


def load(relative: str):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def run(relative: str, *args: str) -> str:
    completed = subprocess.run(
        [sys.executable, str(ROOT / relative), *args],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if completed.returncode:
        raise AssertionError(f"{relative}: {completed.stderr or completed.stdout}")
    return completed.stdout.strip()


def validate_instance(value, schema, label: str) -> None:
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        error = errors[0]
        path = "/" + "/".join(map(str, error.absolute_path))
        raise AssertionError(f"{label} schema rejection at {path}: {error.message}")


def discovered_owned_paths():
    paths = set()
    for pattern in (
        "spec/m4c-*.json",
        "spec/schema/m4c-*.json",
        "fixtures/m4c/**/*",
        "scripts/m4c_*.py",
        "scripts/check_m4c_*.py",
    ):
        paths.update(path.relative_to(ROOT).as_posix() for path in ROOT.glob(pattern) if path.is_file())
    paths.update({
        "scripts/run_m4c_replay.py",
        "scripts/validate_m4c.py",
        "tests/test_m4c_integration.py",
        "tests/test_m4c_candidate_gate.py",
        "docs/M4C_INTEGRATED_SLICE.md",
    })
    return paths


def clean_process_replays():
    outputs = {"happy": [], "crash_after_external_success": []}
    descriptors = []
    profiles = (
        ("clean-a", "1", "UTC"),
        ("clean-b", "777", "Asia/Seoul"),
    )
    with tempfile.TemporaryDirectory(prefix="flrh-m4c-clean-") as raw:
        base = Path(raw)
        for name, hash_seed, timezone in profiles:
            cwd = base / name
            cwd.mkdir()
            env = os.environ.copy()
            env.update({
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONHASHSEED": hash_seed,
                "TZ": timezone,
                "TMPDIR": str(cwd),
            })
            for mode in ("happy", "crash_after_external_success"):
                completed = subprocess.run(
                    [sys.executable, str(ROOT / "scripts/run_m4c_replay.py")],
                    cwd=cwd,
                    env=env,
                    input=canonical_bytes({"mode": mode}) + b"\n",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                descriptor = f"{mode}:{name}"
                if completed.returncode or completed.stderr:
                    raise AssertionError(
                        f"M4C clean process {descriptor}: "
                        + completed.stderr.decode("utf-8", "replace")
                    )
                outputs[mode].append(completed.stdout)
                descriptors.append(descriptor)
    for mode, rows in outputs.items():
        if rows[0] != rows[1]:
            raise AssertionError(f"M4C clean process output mismatch: {mode}")
    return {mode: rows[0] for mode, rows in outputs.items()}, descriptors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-proposed", action="store_true")
    args = parser.parse_args()

    manifest = load("spec/m4c-manifest.v1.json")
    contract = load("spec/m4c-integration-contract.v1.json")
    cases = load("fixtures/m4c/cases.json")
    if not args.allow_proposed:
        raise SystemExit("M4C is PROPOSED_PENDING_MEASUREMENT; pass --allow-proposed for candidate validation")
    if {manifest["status"], contract["status"], cases["status"]} != {"PROPOSED_PENDING_MEASUREMENT"}:
        raise AssertionError("M4C status drift")

    for relative in EXPECTED["schemas"]:
        Draft202012Validator.check_schema(load(relative))
    for binding in EXPECTED["schema_bindings"]:
        validate_instance(load(binding["artifact"]), load(binding["schema"]), binding["artifact"])
    for field, expected in EXPECTED.items():
        if manifest.get(field) != expected:
            raise AssertionError(f"M4C manifest exact closure drift: {field}")

    inherited = manifest.get("inherited_dependencies", [])
    if [row.get("artifact") for row in inherited] != INHERITED:
        raise AssertionError("M4C inherited dependency order drift")
    if len(inherited) != len({row["artifact"] for row in inherited}):
        raise AssertionError("M4C inherited dependency duplicate")
    for row in inherited:
        path = ROOT / row["artifact"]
        if not path.is_file():
            raise AssertionError(f"M4C inherited dependency missing: {row['artifact']}")
        actual = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != row["sha256"]:
            raise AssertionError(f"M4C inherited dependency drift: {row['artifact']}")

    owned = [
        *manifest["normative_contracts"],
        *manifest["schemas"],
        manifest["fixture"],
        *manifest["reference_implementation"],
        *manifest["tools"],
        *manifest["documentation"],
    ]
    if len(owned) != len(set(owned)):
        raise AssertionError("M4C manifest owned path overlap")
    discovered = discovered_owned_paths()
    if set(owned) != discovered:
        raise AssertionError(f"M4C owned closure drift: missing={sorted(discovered - set(owned))}, extra={sorted(set(owned) - discovered)}")
    for relative in owned:
        if not (ROOT / relative).is_file():
            raise AssertionError(f"M4C owned artifact missing: {relative}")
    for relative in [*manifest["reference_implementation"], *manifest["tools"]]:
        if relative.endswith(".py"):
            ast.parse((ROOT / relative).read_text(encoding="utf-8"), filename=relative)

    if contract["fsm_projection"]["transitions"] != TRACE or cases["fsm_trace"] != TRACE:
        raise AssertionError("M4C FSM projection drift")
    if contract["fsm_projection"]["stop_state"] != "HONOR_PENDING_INTERRUPT":
        raise AssertionError("M4C stop-state drift")
    if contract["fsm_projection"]["terminal_claim"] != "SLICE_CONFORMED":
        raise AssertionError("M4C terminal-claim drift")
    if contract["fsm_projection"]["trace_claim"] != "FSM_CONFORMANCE_PROJECTION_ONLY":
        raise AssertionError("M4C trace-claim drift")
    if contract["fsm_projection"]["outer_reducer_executed"] is not False:
        raise AssertionError("M4C outer-reducer boundary drift")
    if b'"SUCCEEDED"' in canonical_bytes(contract["fsm_projection"]):
        raise AssertionError("M4C must not claim outer SUCCEEDED")
    if not contract["constraints"]["prior_materialization_must_be_null"]:
        raise AssertionError("M4C prior materialization boundary drift")
    if contract["constraints"]["adapter_profile"] != "FakeAdapter":
        raise AssertionError("M4C adapter boundary drift")
    docs = (ROOT / manifest["documentation"][0]).read_text(encoding="utf-8")
    for marker in ("PROPOSED_PENDING_MEASUREMENT", "SLICE_CONFORMED", "HONOR_PENDING_INTERRUPT", "FakeAdapter", "full-recompute L", "FSM_CONFORMANCE_PROJECTION_ONLY", "os._exit(86)", "detached", "not outer completion", "engine promotion"):
        if marker not in docs:
            raise AssertionError(f"M4C documentation boundary drift: {marker}")

    happy = run_reference_chain()
    crash = run_reference_chain(crash_after_external_success=True)
    for label, evidence in (("happy", happy), ("crash", crash)):
        verification = verify_m4c_evidence(evidence)
        if verification.get("kind") != "M4CVerificationReceipt":
            raise AssertionError(f"M4C {label} verification failed: {verification}")
    clean_outputs, clean_descriptors = clean_process_replays()
    expected_clean = {
        "happy": canonical_bytes(happy) + b"\n",
        "crash_after_external_success": canonical_bytes(crash) + b"\n",
    }
    if clean_outputs != expected_clean:
        raise AssertionError("M4C in-process/clean-process replay mismatch")

    run("tests/test_m4c_integration.py")
    sensitivity = json.loads(run("scripts/check_m4c_sensitivity.py"))
    if sensitivity["paths"] != cases["sensitivity_paths"] or sensitivity["escaped"] != 0:
        raise AssertionError("M4C sensitivity report drift")
    for relative, command_args in NONREGRESSION:
        run(relative, *command_args)

    report = {
        "kind": "M4CValidationReport",
        "status": manifest["status"],
        "manifest_owned_paths": len(owned),
        "inherited_dependencies": len(inherited),
        "inherited_nonregression_gates": len(NONREGRESSION),
        "public_pipeline_stages": len(contract["pipeline"]),
        "fsm_transitions": len(TRACE),
        "success_paths": len(cases["replay_modes"]),
        "crash_recovery_paths": 1,
        "sensitivity_cases": sensitivity["sensitivity_cases_detected"],
        "clean_processes": len(clean_descriptors),
        "clean_process_descriptors": clean_descriptors,
        "verification_checks": len(contract["verification"]["checks"]),
        "unit_test_gate": 1,
    }
    print(json.dumps(report, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
