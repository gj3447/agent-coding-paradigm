#!/usr/bin/env python3
"""Frozen-fixture oracle independent of the M4A reference implementation."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from m4a_fixtures import canonical_bytes, digest, load_cases

ROOT = Path(__file__).resolve().parents[1]
PATHS = {
    "reject:multi-item": "/published_batch",
    "reject:ineligible": "/published_batch/eligibility_verdicts/0/status",
    "reject:conflicted": "/published_batch/eligibility_verdicts/0/status",
    "reject:deny": "/authority_snapshot/decision",
    "reject:ambiguous": "/authority_snapshot/decision",
    "reject:adapter": "/authority_snapshot/adapter_version",
    "reject:authority-expired": "/observed_at",
    "reject:request-drift": "/approval_request",
    "reject:binding-drift": "/approval/action_digest",
    "reject:expired": "/approval/expires_at",
    "reject:revoked": "/approval/revoked",
    "reject:consumed": "/approval/consumed",
    "reject:denied": "/approval/decision",
    "reject:field-drift": "/approval_context",
    "reject:command-digest": "/command_digest",
    "reject:approval-kind": "/approval/kind",
    "reject:authority-version-length": "/authority_snapshot/authority_version",
    "reject:precondition-id-length": "/published_batch/effect_proposals/0/preconditions",
    "reject:support-id-length": "/published_batch/eligibility_verdicts/0/support_derivation_ids",
}


def _trusted_command_digest(command: dict[str, Any]) -> str:
    core = {key: copy.deepcopy(value) for key, value in command.items() if key != "command_digest"}
    return digest({"kind": "M4ACommandPreimage", "contract_version": "flrh-h-authority/1", **core})


def _assert_fsm_evidence(command: dict[str, Any], projection: dict[str, Any]) -> None:
    fsm = json.loads((ROOT / "spec/run-fsm.v1.json").read_text(encoding="utf-8"))
    transitions = {item["event"]: item for item in fsm["machines"][0]["transitions"]}
    event = projection["control_event"]
    proposal = command["published_batch"]["effect_proposals"][0]
    snapshot = command["authority_snapshot"]
    expected = {
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
    for field in transitions[event["type"]]["evidence_required"]:
        if event["payload"].get(field) != expected[field]:
            raise AssertionError(f"frozen M4A golden has invalid {event['type']} evidence: {field}")


def project_expected(command: dict[str, Any]) -> dict[str, Any]:
    corpus = load_cases()
    encoded = canonical_bytes(command)
    for case in corpus["success_cases"]:
        if canonical_bytes(case["command"]) == encoded:
            projection = json.loads((ROOT / case["golden"]).read_text(encoding="utf-8"))
            _assert_fsm_evidence(command, projection)
            return projection
    for case in corpus["rejection_cases"]:
        if canonical_bytes(case["command"]) != encoded:
            continue
        trusted = _trusted_command_digest(command)
        context: dict[str, Any] = {}
        if case["id"] == "reject:multi-item":
            context = {"expected": 1, "actual": 2}
        elif case["id"] == "reject:adapter":
            context = {"expected": "publisher/1", "actual": "publisher/2"}
        elif case["id"] == "reject:binding-drift":
            context = {"expected": command["published_batch"]["effect_proposals"][0]["action_digest"], "actual": command["approval"]["action_digest"]}
        elif case["id"] == "reject:command-digest":
            context = {"expected": trusted, "actual": command["command_digest"]}
        elif case["id"] == "reject:approval-kind":
            context = {"expected": "HApproval", "actual": command["approval"]["kind"]}
        return {"kind": "HRejection", "schema_version": "flrh-h-projection-result/1", "contract_version": "flrh-h-authority/1", "code": case["expected_code"], "path": PATHS[case["id"]], "command_digest": trusted, "context": context}
    raise AssertionError("command is outside the frozen M4A oracle corpus")


__all__ = ["project_expected"]
