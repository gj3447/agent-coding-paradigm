#!/usr/bin/env python3
"""Load and deterministically expand the compact M4A fixture corpus."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "flrh-h-authority/1"


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def _redigest_published(published: dict[str, Any]) -> None:
    published["published_batch_digest"] = digest({
        "kind": "M3PublishedBatchPreimage", "contract_version": "flrh-r-kernel/1",
        "batch": published["batch"],
        "ordered_effect_proposals": published["effect_proposals"],
        "ordered_eligibility_verdicts": published["eligibility_verdicts"],
    })


def _snapshot(published: dict[str, Any], risk: str, decision: str = "allow") -> dict[str, Any]:
    proposal = published["effect_proposals"][0]
    value = {
        "kind": "HAuthoritySnapshot", "authority_version": "authority/1",
        "proposal_id": proposal["proposal_id"], "effect_type": proposal["effect_type"],
        "capability": "capability:artifact.publish", "decision": decision,
        "assessed_risk": risk, "adapter_version": proposal["versions"]["tool"],
        "destination_digest": proposal["destination_digest"], "valid_from": 0,
        "valid_until": 200, "revoked": False,
    }
    value["authority_digest"] = digest({"kind": "M4AAuthorityPreimage", "contract_version": CONTRACT, **value})
    return value


def _context(published: dict[str, Any]) -> dict[str, Any]:
    proposal = published["effect_proposals"][0]
    value = {"kind": "HApprovalContext", "policy_version": "approval-policy/1", "approver_scope": "scope:artifact-publishers", "requested_at": 100, "run_id": proposal["correlation_id"], "workflow_version": proposal["versions"]["workflow"], "action_digest": proposal["action_digest"], "artifact_digest": "sha256:" + "a" * 64, "destination_digest": proposal["destination_digest"], "visibility": "visibility:external", "scope": "scope:artifact-publishers", "actor": "actor:fixture-approver", "expires_at": 150, "nonce": "nonce:m4a:1", "rationale": "rationale:fixture"}
    value["context_digest"] = digest({"kind": "M4AApprovalContextPreimage", "contract_version": CONTRACT, **value})
    return value


def _request(published: dict[str, Any], snapshot: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    proposal = published["effect_proposals"][0]
    core = {"kind": "HApprovalRequest", "proposal_id": proposal["proposal_id"], "capability": snapshot["capability"], "authority_digest": snapshot["authority_digest"], "adapter_version": snapshot["adapter_version"], "requested_at": context["requested_at"], **{key: context[key] for key in ("context_digest", "policy_version", "approver_scope", "run_id", "workflow_version", "action_digest", "artifact_digest", "destination_digest", "visibility", "scope", "actor", "expires_at", "nonce", "rationale")}}
    bound = digest({"kind": "M4AApprovalRequestPreimage", "contract_version": CONTRACT, **core})
    return {**core, "request_id": "approval-request:" + bound.split(":", 1)[1], "request_digest": bound}


def _approval(published: dict[str, Any], snapshot: dict[str, Any], request: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    proposal = published["effect_proposals"][0]
    value = {"kind": "HApproval", "request_digest": request["request_digest"], "decision": "grant", "capability": snapshot["capability"], "authority_digest": snapshot["authority_digest"], "adapter_version": snapshot["adapter_version"], "issued_at": 110, "revoked": False, "consumed": False, **{key: context[key] for key in ("context_digest", "policy_version", "approver_scope", "run_id", "workflow_version", "action_digest", "artifact_digest", "destination_digest", "visibility", "scope", "actor", "expires_at", "nonce", "rationale")}}
    value["approval_digest"] = digest({"kind": "M4AApprovalPreimage", "contract_version": CONTRACT, **value})
    return value


def _command(state: str, profile_digest: str, published: dict[str, Any], snapshot: dict[str, Any], context=None, request=None, approval=None, observed=100) -> dict[str, Any]:
    value = {"kind": "HProjectIntentCommand", "schema_version": "flrh-h-project-intent-command/1", "contract_version": CONTRACT, "control_state": state, "r_profile_digest": profile_digest, "published_batch": published, "authority_snapshot": snapshot, "approval_context": context, "approval_request": request, "approval": approval, "observed_at": observed, "effect_sequence": 1}
    value["command_digest"] = digest({"kind": "M4ACommandPreimage", "contract_version": CONTRACT, **value})
    return value


def _redigest_snapshot(value: dict[str, Any]) -> None:
    core = {key: item for key, item in value.items() if key != "authority_digest"}
    value["authority_digest"] = digest({"kind": "M4AAuthorityPreimage", "contract_version": CONTRACT, **core})


def _redigest_approval(value: dict[str, Any]) -> None:
    core = {key: item for key, item in value.items() if key != "approval_digest"}
    value["approval_digest"] = digest({"kind": "M4AApprovalPreimage", "contract_version": CONTRACT, **core})


def _redigest_command(value: dict[str, Any]) -> None:
    core = {key: item for key, item in value.items() if key != "command_digest"}
    value["command_digest"] = digest({"kind": "M4ACommandPreimage", "contract_version": CONTRACT, **core})


def load_cases() -> dict[str, Any]:
    metadata = json.loads((ROOT / "fixtures/m4a/cases.json").read_text(encoding="utf-8"))
    transition = json.loads((ROOT / "fixtures/m3/golden/frontier-stable.transition.json").read_text(encoding="utf-8"))
    published = transition["published_batches"][0]
    profile_digest = transition["profile_digest"]
    low = _command("PLAN_EFFECTS", profile_digest, copy.deepcopy(published), _snapshot(published, "reversible"))
    context = _context(published)
    high_snapshot = _snapshot(published, "high_risk_external")
    request = _request(published, high_snapshot, context)
    high = _command("PLAN_EFFECTS", profile_digest, copy.deepcopy(published), copy.deepcopy(high_snapshot), copy.deepcopy(context))
    granted = _command("WAIT_APPROVAL", profile_digest, copy.deepcopy(published), copy.deepcopy(high_snapshot), copy.deepcopy(context), copy.deepcopy(request), _approval(published, high_snapshot, request, context), observed=120)
    commands = {"success:low-risk": low, "success:approval-request": high, "success:approval-granted": granted}
    success = [{"id": item["id"], "command": copy.deepcopy(commands[item["id"]]), "golden": item["golden"]} for item in metadata["success_cases"]]
    rejections = []
    for item in metadata["rejection_cases"]:
        value = copy.deepcopy(commands[item["base"]])
        op = item["op"]
        if op == "multi-item":
            value["published_batch"]["effect_proposals"].append(copy.deepcopy(value["published_batch"]["effect_proposals"][0]))
            value["published_batch"]["eligibility_verdicts"].append(copy.deepcopy(value["published_batch"]["eligibility_verdicts"][0]))
            _redigest_published(value["published_batch"]); _redigest_command(value)
        elif op in {"ineligible", "conflicted"}:
            value["published_batch"]["eligibility_verdicts"][0]["status"] = op
            _redigest_published(value["published_batch"]); _redigest_command(value)
        elif op in {"deny", "ambiguous"}:
            value["authority_snapshot"]["decision"] = op
            _redigest_snapshot(value["authority_snapshot"]); _redigest_command(value)
        elif op == "adapter-mismatch":
            value["authority_snapshot"]["adapter_version"] = "publisher/2"
            _redigest_snapshot(value["authority_snapshot"]); _redigest_command(value)
        elif op == "authority-expired":
            value["authority_snapshot"]["valid_until"] = value["observed_at"]
            _redigest_snapshot(value["authority_snapshot"]); _redigest_command(value)
        elif op == "approval-request-drift":
            value["approval_request"]["nonce"] = "nonce:m4a:drift"
            _redigest_command(value)
        elif op == "approval-binding-drift":
            value["approval"]["action_digest"] = "sha256:" + "a" * 64
            _redigest_approval(value["approval"]); _redigest_command(value)
        elif op == "approval-expired":
            value["approval"]["issued_at"] = value["observed_at"] + 1
            _redigest_approval(value["approval"]); _redigest_command(value)
        elif op == "approval-revoked":
            value["approval"]["revoked"] = True
            _redigest_approval(value["approval"]); _redigest_command(value)
        elif op == "approval-consumed":
            value["approval"]["consumed"] = True
            _redigest_approval(value["approval"]); _redigest_command(value)
        elif op == "approval-denied":
            value["approval"]["decision"] = "deny"
            _redigest_approval(value["approval"]); _redigest_command(value)
        elif op == "approval-field-drift":
            value["approval_context"] = _context(published); _redigest_command(value)
        elif op == "command-digest-drift":
            value["effect_sequence"] = 2
        elif op == "approval-kind-drift":
            value["approval"]["kind"] = "NotHApproval"
            _redigest_approval(value["approval"]); _redigest_command(value)
        elif op == "authority-version-too-long":
            value["authority_snapshot"]["authority_version"] = "a" * 129
            _redigest_snapshot(value["authority_snapshot"]); _redigest_command(value)
        elif op == "precondition-id-too-long":
            value["published_batch"]["effect_proposals"][0]["preconditions"] = ["p" * 129]
            _redigest_published(value["published_batch"]); _redigest_command(value)
        elif op == "support-id-too-long":
            value["published_batch"]["eligibility_verdicts"][0]["support_derivation_ids"] = ["s" * 129]
            _redigest_published(value["published_batch"]); _redigest_command(value)
        else:
            raise AssertionError(f"unknown M4A fixture op: {op}")
        rejections.append({"id": item["id"], "expected_code": item["expected_code"], "command": value})
    return {"schema_version": metadata["schema_version"], "success_cases": success, "rejection_cases": rejections}


def find_case(corpus: dict[str, Any], identifier: str) -> dict[str, Any]:
    for group in ("success_cases", "rejection_cases"):
        for case in corpus[group]:
            if case["id"] == identifier:
                return copy.deepcopy(case["command"])
    raise KeyError(identifier)


__all__ = ["find_case", "load_cases"]
