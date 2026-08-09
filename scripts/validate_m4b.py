#!/usr/bin/env python3
"""Aggregate validator for the bounded proposed M4B durability candidate."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))

import flrh_harness


EXPECTED={
    "normative_contracts":["spec/m4b-durable-contract.v1.json","spec/m4b-manifest.v1.json"],
    "schemas":["spec/schema/m4b-durable-contract.v1.schema.json","spec/schema/m4b-fixtures.v1.schema.json","spec/schema/m4b-manifest.v1.schema.json"],
    "schema_bindings":[
        {"artifact":"spec/m4b-durable-contract.v1.json","schema":"spec/schema/m4b-durable-contract.v1.schema.json"},
        {"artifact":"spec/m4b-manifest.v1.json","schema":"spec/schema/m4b-manifest.v1.schema.json"},
        {"artifact":"fixtures/m4b/cases.json","schema":"spec/schema/m4b-fixtures.v1.schema.json"},
    ],
    "fixture":"fixtures/m4b/cases.json",
    "goldens":["fixtures/m4b/golden/replay.summary.json"],
    "reference_implementation":["src/flrh_harness/__init__.py","src/flrh_harness/adapter.py","src/flrh_harness/canonical.py","src/flrh_harness/harness.py","src/flrh_harness/verifier.py"],
    "tools":["scripts/m4b_crash_worker.py","scripts/m4b_fixtures.py","scripts/run_m4b_replay.py","scripts/check_m4b_ambient.py","scripts/check_m4b_crashes.py","scripts/check_m4b_adversarial_sensitivity.py","scripts/validate_m4b.py","tests/test_m4b_durable.py","tests/test_m4b_candidate_gate.py"],
    "documentation":["docs/M4B_DURABLE.md"],
    "public_api":["DurableHarness","FakeAdapter","verify_run"],
}
INHERITED=[
    "spec/schema/protocol.v1.schema.json","spec/canonicalization.v1.json",
    "src/flrh_kernel/__init__.py","src/flrh_kernel/canonical.py",
    "spec/m4a-authority-contract.v1.json","spec/m4a-manifest.v1.json",
    "spec/schema/m4a-authority.v1.schema.json","spec/schema/m4a-contract.v1.schema.json",
    "spec/schema/m4a-fixtures.v1.schema.json","spec/schema/m4a-manifest.v1.schema.json",
    "src/flrh_authority/__init__.py","src/flrh_authority/canonical.py","src/flrh_authority/authority.py",
    "fixtures/m4a/cases.json","fixtures/m4a/golden/low-risk.projection.json",
    "fixtures/m4a/golden/approval-request.projection.json","fixtures/m4a/golden/approval-granted.projection.json",
    "scripts/m4a_fixtures.py",
]


def load(relative: str):
    return json.loads((ROOT/relative).read_text(encoding="utf-8"))


def run(relative: str, *args: str):
    completed=subprocess.run([sys.executable,str(ROOT/relative),*args],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if completed.returncode:
        raise AssertionError(f"{relative}: {completed.stderr or completed.stdout}")
    return completed.stdout.strip()


def validate_instance(value, schema, label: str):
    errors=sorted(Draft202012Validator(schema).iter_errors(value),key=lambda error:tuple(str(item) for item in error.absolute_path))
    if errors:
        error=errors[0]
        raise AssertionError(f"{label} schema rejection at /{'/'.join(map(str,error.absolute_path))}: {error.message}")


def discovered_owned_paths():
    paths=set()
    for pattern in ("src/flrh_harness/*.py","spec/m4b-*.json","spec/schema/m4b-*.json","fixtures/m4b/**/*","scripts/m4b_*.py","scripts/check_m4b_*.py"):
        paths.update(path.relative_to(ROOT).as_posix() for path in ROOT.glob(pattern) if path.is_file())
    paths.update({"scripts/run_m4b_replay.py","scripts/validate_m4b.py","tests/test_m4b_durable.py","tests/test_m4b_candidate_gate.py","docs/M4B_DURABLE.md"})
    return paths


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--allow-proposed",action="store_true"); args=parser.parse_args()
    manifest=load("spec/m4b-manifest.v1.json"); contract=load("spec/m4b-durable-contract.v1.json"); cases=load("fixtures/m4b/cases.json")
    if not args.allow_proposed:
        raise SystemExit("M4B is proposed; pass --allow-proposed for local validation")
    if {manifest["status"],contract["status"],cases["status"]}!={"PROPOSED_PENDING_MEASUREMENT"}:
        raise AssertionError("M4B status drift")

    for path in EXPECTED["schemas"]:
        Draft202012Validator.check_schema(load(path))
    for binding in EXPECTED["schema_bindings"]:
        validate_instance(load(binding["artifact"]),load(binding["schema"]),binding["artifact"])
    for field,expected in EXPECTED.items():
        if manifest.get(field)!=expected:
            raise AssertionError(f"manifest exact closure drift: {field}")
        if isinstance(expected,list) and len(expected)!=len({json.dumps(item,sort_keys=True) for item in expected}):
            raise AssertionError(f"validator expected list is not unique: {field}")

    inherited=manifest.get("inherited_dependencies",[])
    if [item.get("artifact") for item in inherited]!=INHERITED or len(inherited)!=len({item.get("artifact") for item in inherited}):
        raise AssertionError("manifest inherited dependency order/uniqueness drift")
    for dependency in inherited:
        path=ROOT/dependency["artifact"]
        if not path.is_file(): raise AssertionError(f"missing inherited dependency: {dependency['artifact']}")
        actual="sha256:"+hashlib.sha256(path.read_bytes()).hexdigest()
        if dependency["sha256"]!=actual: raise AssertionError(f"dependency drift: {dependency['artifact']}")

    owned=[*manifest["normative_contracts"],*manifest["schemas"],manifest["fixture"],*manifest["goldens"],*manifest["reference_implementation"],*manifest["tools"],*manifest["documentation"]]
    if len(owned)!=len(set(owned)): raise AssertionError("manifest owned path overlap")
    if set(owned)!=discovered_owned_paths():
        raise AssertionError(f"manifest owned closure drift: missing={sorted(discovered_owned_paths()-set(owned))}, extra={sorted(set(owned)-discovered_owned_paths())}")
    for relative in owned:
        if not (ROOT/relative).is_file(): raise AssertionError(f"missing owned artifact: {relative}")
    for relative in [*manifest["reference_implementation"],*manifest["tools"]]:
        if relative.endswith(".py"): ast.parse((ROOT/relative).read_text(encoding="utf-8"),filename=relative)
    if manifest["public_api"]!=list(flrh_harness.__all__): raise AssertionError("package public API drift")
    if contract["public_api"]!=manifest["public_api"]: raise AssertionError("contract public API drift")

    docs=(ROOT/manifest["documentation"][0]).read_text(encoding="utf-8")
    required_docs=("PROPOSED_PENDING_MEASUREMENT","M4A policy decisions","real destination","production safety","engine promotion","not exactly-once")
    if any(marker not in docs for marker in required_docs): raise AssertionError("documentation status/nonclaim drift")
    required_boundary=("PROPOSED only","M4A policy correctness","real-destination safety","exactly-once delivery","engine promotion")
    if any(marker not in manifest["completion_boundary"] for marker in required_boundary): raise AssertionError("manifest completion boundary drift")

    replay=json.loads(run("scripts/run_m4b_replay.py")); golden=load(manifest["goldens"][0])
    if replay!=golden: raise AssertionError("replay differs from golden")
    run("tests/test_m4b_durable.py")
    ambient=json.loads(run("scripts/check_m4b_ambient.py")); crashes=json.loads(run("scripts/check_m4b_crashes.py")); sensitivity=json.loads(run("scripts/check_m4b_adversarial_sensitivity.py"))
    report={"kind":"M4BValidationReport","status":manifest["status"],"fault_tests":len(cases["fault_tests"]),"approval_mutations":len(cases["approval_mutations"]),"subprocess_cutpoints":crashes["passed"],"adversarial_sensitivity_cases":sensitivity["adversarial_sensitivity_cases_detected"],"ambient_violations":ambient["violations"],"replay_matches":True,"manifest_owned_paths":len(owned),"inherited_dependencies":len(inherited),"public_api":len(manifest["public_api"])}
    print(json.dumps(report,separators=(",",":"),sort_keys=True))


if __name__=="__main__": main()
