#!/usr/bin/env python3
"""Aggregate validation for the proposed M4A pure authority slice."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from flrh_authority import project_h_intent
from flrh_authority.authority import REJECTION_CODES
from m4a_fixtures import digest, load_cases
from m4a_oracle import project_expected


def load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def registry() -> Registry:
    resources = []
    for path in sorted((ROOT / "spec/schema").glob("*.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        if "$id" in schema:
            resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def validate(value, schema, schemas) -> None:
    errors = sorted(Draft202012Validator(schema, registry=schemas).iter_errors(value), key=lambda e: tuple(str(x) for x in e.absolute_path))
    if errors:
        first = errors[0]
        raise AssertionError(f"schema rejection at /{'/'.join(map(str, first.absolute_path))}: {first.message}")


def validation_error_paths(value, schema, schemas) -> set[str]:
    pending = list(Draft202012Validator(schema, registry=schemas).iter_errors(value))
    paths = set()
    while pending:
        error = pending.pop()
        paths.add("/" + "/".join(map(str, error.absolute_path)))
        pending.extend(error.context)
    return paths


def run(relative: str, *args: str) -> dict:
    completed = subprocess.run([sys.executable, str(ROOT / relative), *args], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode:
        raise AssertionError(f"{relative} failed: {completed.stderr or completed.stdout}")
    lines = completed.stdout.strip().splitlines()
    line = lines[-1] if lines else ""
    return json.loads(line) if line.startswith("{") else {"status": "PASS"}


def semantic_fsm_evidence(command: dict) -> dict:
    proposal = command["published_batch"]["effect_proposals"][0]
    snapshot = command["authority_snapshot"]
    return {
        "action_digest": proposal["action_digest"],
        "risk_classification": snapshot["assessed_risk"],
        "policy_verdict": digest({
            "kind": "M4APolicyVerdictEvidencePreimage",
            "contract_version": "flrh-h-authority/1",
            "r_profile_digest": command["r_profile_digest"],
            "eligibility_verdict": command["published_batch"]["eligibility_verdicts"][0],
            "authority_decision": snapshot["decision"],
            "authority_digest": snapshot["authority_digest"],
            "assessed_risk": snapshot["assessed_risk"],
        }),
        "capability_digest": digest({
            "kind": "M4ACapabilityEvidencePreimage",
            "contract_version": "flrh-h-authority/1",
            "capability": snapshot["capability"],
            "authority_digest": snapshot["authority_digest"],
            "proposal_id": proposal["proposal_id"],
            "effect_type": proposal["effect_type"],
            "action_digest": proposal["action_digest"],
            "destination_digest": proposal["destination_digest"],
            "adapter_version": snapshot["adapter_version"],
        }),
        "exact_hash_approval_digest": command["approval"]["approval_digest"] if command["approval"] else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-proposed", action="store_true")
    args = parser.parse_args()
    if not args.allow_proposed:
        raise SystemExit("M4A status is PROPOSED_PENDING_MEASUREMENT; pass --allow-proposed explicitly")
    schemas = registry()
    wire = load("spec/schema/m4a-authority.v1.schema.json")
    contract = load("spec/m4a-authority-contract.v1.json")
    manifest = load("spec/m4a-manifest.v1.json")
    for path in ("spec/schema/m4a-authority.v1.schema.json", "spec/schema/m4a-contract.v1.schema.json", "spec/schema/m4a-fixtures.v1.schema.json", "spec/schema/m4a-manifest.v1.schema.json"):
        Draft202012Validator.check_schema(load(path))
    validate(contract, load("spec/schema/m4a-contract.v1.schema.json"), schemas)
    validate(manifest, load("spec/schema/m4a-manifest.v1.schema.json"), schemas)
    validate(load("fixtures/m4a/cases.json"), load("spec/schema/m4a-fixtures.v1.schema.json"), schemas)
    expected_manifest = {
        "normative_contracts": ["spec/m4a-authority-contract.v1.json","spec/m4a-manifest.v1.json","spec/schema/m4a-authority.v1.schema.json","spec/schema/m4a-contract.v1.schema.json","spec/schema/m4a-fixtures.v1.schema.json","spec/schema/m4a-manifest.v1.schema.json"],
        "goldens": ["fixtures/m4a/golden/low-risk.projection.json","fixtures/m4a/golden/approval-request.projection.json","fixtures/m4a/golden/approval-granted.projection.json"],
        "reference_implementation": ["src/flrh_authority/__init__.py","src/flrh_authority/canonical.py","src/flrh_authority/authority.py"],
        "documentation": ["docs/M4A_AUTHORITY.md"],
        "tools": ["scripts/m4a_fixtures.py","scripts/m4a_oracle.py","scripts/run_m4a_replay.py","scripts/check_m4a_ambient.py","scripts/check_m4a_semantic_mutants.py","scripts/validate_m4a.py","tests/test_m4a_authority.py","tests/test_m4a_candidate_gate.py"],
    }
    for field, expected in expected_manifest.items():
        if manifest[field] != expected or len(expected) != len(set(expected)):
            raise AssertionError(f"manifest closure drift: {field}")
    owned = [manifest["fixture"], *manifest["normative_contracts"], *manifest["goldens"], *manifest["reference_implementation"], *manifest["documentation"], *manifest["tools"]]
    if len(owned) != len(set(owned)):
        raise AssertionError("manifest owned path overlap")
    for path in owned:
        if not (ROOT / path).is_file():
            raise AssertionError(f"manifest path missing: {path}")
    for path in [*manifest["reference_implementation"], *manifest["tools"]]:
        if path.endswith(".py"):
            ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path)
    schema_codes = set(wire["$defs"]["Rejection"]["properties"]["code"]["enum"])
    if set(contract["rejection_codes"]) != schema_codes or schema_codes != set(REJECTION_CODES):
        raise AssertionError("closed rejection vocabulary drift")
    for dependency in manifest["inherited_dependencies"]:
        actual = "sha256:" + hashlib.sha256((ROOT / dependency["artifact"]).read_bytes()).hexdigest()
        if actual != dependency["sha256"]:
            raise AssertionError(f"dependency drift: {dependency['artifact']}")
    fsm = load("spec/run-fsm.v1.json")
    fsm_transitions = {item["event"]: item for item in fsm["machines"][0]["transitions"]}
    schema_runtime_parity = {
        "reject:approval-kind": "/approval/kind",
        "reject:authority-version-length": "/authority_snapshot/authority_version",
        "reject:precondition-id-length": "/published_batch/effect_proposals/0/preconditions/0",
        "reject:support-id-length": "/published_batch/eligibility_verdicts/0/support_derivation_ids/0",
    }
    corpus = load_cases()
    success = rejection = 0
    for group in ("success_cases", "rejection_cases"):
        for case in corpus[group]:
            if group == "success_cases":
                validate(case["command"], wire, schemas)
            actual = project_h_intent(case["command"])
            validate(actual, wire, schemas)
            if actual != project_expected(case["command"]):
                raise AssertionError(f"oracle mismatch: {case['id']}")
            if group == "success_cases":
                golden = load(case["golden"])
                validate(golden, wire, schemas)
                if golden != actual:
                    raise AssertionError(f"golden drift: {case['id']}")
                authorities = {"EFFECT_AUTHORIZED": ("policy_evaluator", "effect.authorize_low_risk"), "APPROVAL_REQUIRED": ("policy_evaluator", "approval.request"), "APPROVAL_GRANTED": ("human_approver", "approval.grant_exact_hash")}
                event = actual["control_event"]
                if (event["actor_role"], event["capability"]) != authorities[actual["event"]] or event["type"] != actual["event"]:
                    raise AssertionError(f"control event authority drift: {case['id']}")
                transition = fsm_transitions[event["type"]]
                if transition["from"] != case["command"]["control_state"] or transition["to"] != actual["next_control_state"]:
                    raise AssertionError(f"control event transition drift: {case['id']}")
                semantic = semantic_fsm_evidence(case["command"])
                for field in transition["evidence_required"]:
                    if event["payload"].get(field) != semantic[field]:
                        raise AssertionError(f"control event evidence drift: {case['id']}:{field}")
                success += 1
            else:
                expected_schema_path = schema_runtime_parity.get(case["id"])
                if expected_schema_path is not None and expected_schema_path not in validation_error_paths(case["command"], wire, schemas):
                    raise AssertionError(f"schema/runtime parity drift: {case['id']}:{expected_schema_path}")
                rejection += 1
    tests = run("tests/test_m4a_authority.py")
    ambient = run("scripts/check_m4a_ambient.py")
    sensitivity = run("scripts/check_m4a_semantic_mutants.py")
    print(json.dumps({"status":"PROPOSED_PENDING_MEASUREMENT","success_paths":success,"rejection_paths":rejection,"rejection_sensitivity_cases":sensitivity["sensitivity_cases_detected"],"schema_runtime_parity_cases":len(schema_runtime_parity),"ambient_source_paths":ambient["source_paths"],"clean_processes":ambient["clean_processes"],"unit_test_gate":1,"contract_status":contract["status"],"manifest_owned_paths":len(owned)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
