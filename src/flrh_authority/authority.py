"""Pure deterministic singleton H authority and approval projection.

This module never persists, dispatches, executes, retries, or emits a receipt.
All authority and time facts are supplied data and are validated fail-closed.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Optional

from .canonical import INT64_MAX, CanonicalizationError, digest, thaw

CONTRACT = "flrh-h-authority/1"
COMMAND_SCHEMA = "flrh-h-project-intent-command/1"
RESULT_SCHEMA = "flrh-h-projection-result/1"
CANON = "flrh-cjson/1"
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/-]*$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

COMMAND_KEYS = frozenset({"kind", "schema_version", "contract_version", "control_state", "r_profile_digest", "published_batch", "authority_snapshot", "approval_context", "approval_request", "approval", "observed_at", "effect_sequence", "command_digest"})
PUBLISHED_KEYS = frozenset({"kind", "batch", "effect_proposals", "eligibility_verdicts", "published_batch_digest"})
BATCH_KEYS = frozenset({"kind", "batch_id", "logical_time", "low_watermark", "proposal_ids", "eligibility_verdict_ids", "batch_digest", "cause_id", "dataflow_version"})
PROPOSAL_KEYS = frozenset({"kind", "proposal_id", "effect_type", "action_digest", "cause_id", "correlation_id", "proposal_dedup_key", "destination_digest", "goal_id", "obligation_id", "declared_risk_hint", "preconditions", "versions"})
VERDICT_KEYS = frozenset({"kind", "verdict_id", "proposal_id", "status", "support_derivation_ids", "rule_set_version", "cause_id"})
SNAPSHOT_KEYS = frozenset({"kind", "authority_version", "proposal_id", "effect_type", "capability", "decision", "assessed_risk", "adapter_version", "destination_digest", "valid_from", "valid_until", "revoked", "authority_digest"})
LOOP_BINDING_KEYS = frozenset({"run_id", "workflow_version", "action_digest", "artifact_digest", "destination_digest", "visibility", "scope", "actor", "expires_at", "nonce", "rationale"})
CONTEXT_KEYS = frozenset({"kind", "policy_version", "approver_scope", "requested_at", "context_digest", *LOOP_BINDING_KEYS})
REQUEST_KEYS = frozenset({"kind", "request_id", "proposal_id", "capability", "authority_digest", "adapter_version", "requested_at", "context_digest", "policy_version", "approver_scope", "request_digest", *LOOP_BINDING_KEYS})
APPROVAL_KEYS = frozenset({"kind", "request_digest", "decision", "capability", "authority_digest", "adapter_version", "issued_at", "revoked", "consumed", "context_digest", "policy_version", "approver_scope", "approval_digest", *LOOP_BINDING_KEYS})
VERSION_KEYS = frozenset({"workflow", "state_schema", "event_schema", "graph_schema", "rule_set", "dataflow", "canonicalization", "tool", "model", "oracle", "gate", "resolver", "composition_profile"})
REJECTION_CODES = frozenset({"MALFORMED_COMMAND","MALFORMED_PUBLISHED_BATCH","MALFORMED_PROPOSAL","MALFORMED_VERDICT","MALFORMED_AUTHORITY_SNAPSHOT","MALFORMED_APPROVAL_CONTEXT","MALFORMED_APPROVAL_REQUEST","MALFORMED_APPROVAL","CANONICALIZATION_VIOLATION","UNSUPPORTED_COMMAND_SCHEMA","UNSUPPORTED_CONTRACT_VERSION","UNSUPPORTED_CANONICALIZATION","COMMAND_DIGEST_MISMATCH","NON_SINGLETON_BATCH","BATCH_IDENTITY_MISMATCH","BATCH_DIGEST_MISMATCH","PUBLISHED_BATCH_DIGEST_MISMATCH","VERSION_MISMATCH","PROPOSAL_INELIGIBLE","PROPOSAL_CONFLICTED","AUTHORITY_BINDING_MISMATCH","AUTHORITY_DIGEST_MISMATCH","AUTHORITY_DENIED","AUTHORITY_AMBIGUOUS","AUTHORITY_REVOKED","AUTHORITY_EXPIRED","ADAPTER_VERSION_MISMATCH","APPROVAL_FIELD_DRIFT","APPROVAL_CONTEXT_DIGEST_MISMATCH","APPROVAL_CONTEXT_BINDING_MISMATCH","APPROVAL_TIME_DRIFT","APPROVAL_REQUEST_DRIFT","APPROVAL_DIGEST_MISMATCH","APPROVAL_BINDING_MISMATCH","APPROVAL_DENIED","APPROVAL_REVOKED","APPROVAL_ALREADY_CONSUMED","APPROVAL_EXPIRED","INVALID_CONTROL_STATE"})


class _Reject(Exception):
    def __init__(self, code: str, path: str, expected: Any = None, actual: Any = None) -> None:
        self.code, self.path, self.expected, self.actual = code, path, expected, actual


def _exact(value: Any, keys: frozenset[str], code: str, path: str) -> Dict[str, Any]:
    if not isinstance(value, dict) or frozenset(value) != keys:
        raise _Reject(code, path)
    return value


def _id(value: Any, code: str, path: str) -> str:
    if not isinstance(value, str) or len(value) > 128 or ID_RE.fullmatch(value) is None:
        raise _Reject(code, path)
    return value


def _unique_ids(value: Any, code: str, path: str) -> list[str]:
    if not isinstance(value, list):
        raise _Reject(code, path)
    seen: set[str] = set()
    for item in value:
        identifier = _id(item, code, path)
        if identifier in seen:
            raise _Reject(code, path)
        seen.add(identifier)
    return value


def _dg(value: Any, code: str, path: str) -> str:
    if not isinstance(value, str) or DIGEST_RE.fullmatch(value) is None:
        raise _Reject(code, path)
    return value


def _version(value: Any, code: str, path: str) -> str:
    if not isinstance(value, str) or len(value) > 128 or VERSION_RE.fullmatch(value) is None:
        raise _Reject(code, path)
    return value


def _time(value: Any, code: str, path: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= INT64_MAX:
        raise _Reject(code, path)
    return value


def _same(actual: Any, expected: Any, code: str, path: str) -> None:
    if actual != expected:
        raise _Reject(code, path, expected, actual)


def _without(value: Mapping[str, Any], key: str) -> Dict[str, Any]:
    return {name: thaw(item) for name, item in value.items() if name != key}


def _validate_published(raw: Any, profile_digest: str) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    published = _exact(raw, PUBLISHED_KEYS, "MALFORMED_PUBLISHED_BATCH", "/published_batch")
    _same(published["kind"], "RPublishedBatch", "MALFORMED_PUBLISHED_BATCH", "/published_batch/kind")
    batch = _exact(published["batch"], BATCH_KEYS, "MALFORMED_PUBLISHED_BATCH", "/published_batch/batch")
    proposals, verdicts = published["effect_proposals"], published["eligibility_verdicts"]
    if not isinstance(proposals, list) or not isinstance(verdicts, list):
        raise _Reject("MALFORMED_PUBLISHED_BATCH", "/published_batch")
    if len(proposals) != 1 or len(verdicts) != 1:
        raise _Reject("NON_SINGLETON_BATCH", "/published_batch", 1, max(len(proposals), len(verdicts)))
    proposal = _exact(proposals[0], PROPOSAL_KEYS, "MALFORMED_PROPOSAL", "/published_batch/effect_proposals/0")
    verdict = _exact(verdicts[0], VERDICT_KEYS, "MALFORMED_VERDICT", "/published_batch/eligibility_verdicts/0")
    _same(batch["kind"], "StableProposalBatch", "MALFORMED_PUBLISHED_BATCH", "/published_batch/batch/kind")
    _same(proposal["kind"], "EffectProposal", "MALFORMED_PROPOSAL", "/published_batch/effect_proposals/0/kind")
    _same(verdict["kind"], "EligibilityVerdict", "MALFORMED_VERDICT", "/published_batch/eligibility_verdicts/0/kind")
    logical_time = _time(batch["logical_time"], "MALFORMED_PUBLISHED_BATCH", "/published_batch/batch/logical_time")
    low_watermark = _time(batch["low_watermark"], "MALFORMED_PUBLISHED_BATCH", "/published_batch/batch/low_watermark")
    if low_watermark <= logical_time:
        raise _Reject("MALFORMED_PUBLISHED_BATCH", "/published_batch/batch/low_watermark")
    for key in ("batch_id", "cause_id"):
        _id(batch[key], "MALFORMED_PUBLISHED_BATCH", f"/published_batch/batch/{key}")
    _version(batch["dataflow_version"], "MALFORMED_PUBLISHED_BATCH", "/published_batch/batch/dataflow_version")
    for key in ("proposal_id", "effect_type", "cause_id", "correlation_id", "proposal_dedup_key", "goal_id", "obligation_id"):
        _id(proposal[key], "MALFORMED_PROPOSAL", f"/published_batch/effect_proposals/0/{key}")
    if proposal["declared_risk_hint"] not in {"read_only", "reversible", "high_risk_external", "unknown"}:
        raise _Reject("MALFORMED_PROPOSAL", "/published_batch/effect_proposals/0/declared_risk_hint")
    preconditions = _unique_ids(proposal["preconditions"], "MALFORMED_PROPOSAL", "/published_batch/effect_proposals/0/preconditions")
    for key in ("verdict_id", "proposal_id", "cause_id"):
        _id(verdict[key], "MALFORMED_VERDICT", f"/published_batch/eligibility_verdicts/0/{key}")
    supports = _unique_ids(verdict["support_derivation_ids"], "MALFORMED_VERDICT", "/published_batch/eligibility_verdicts/0/support_derivation_ids")
    _version(verdict["rule_set_version"], "MALFORMED_VERDICT", "/published_batch/eligibility_verdicts/0/rule_set_version")
    _same(batch["proposal_ids"], [proposal["proposal_id"]], "BATCH_IDENTITY_MISMATCH", "/published_batch/batch/proposal_ids")
    _same(batch["eligibility_verdict_ids"], [verdict["verdict_id"]], "BATCH_IDENTITY_MISMATCH", "/published_batch/batch/eligibility_verdict_ids")
    _same(verdict["proposal_id"], proposal["proposal_id"], "BATCH_IDENTITY_MISMATCH", "/published_batch/eligibility_verdicts/0/proposal_id")
    versions = _exact(proposal["versions"], VERSION_KEYS, "MALFORMED_PROPOSAL", "/published_batch/effect_proposals/0/versions")
    for key, value in versions.items():
        _version(value, "MALFORMED_PROPOSAL", f"/published_batch/effect_proposals/0/versions/{key}")
    _same(versions["canonicalization"], CANON, "UNSUPPORTED_CANONICALIZATION", "/published_batch/effect_proposals/0/versions/canonicalization")
    _same(versions["dataflow"], batch["dataflow_version"], "VERSION_MISMATCH", "/published_batch/batch/dataflow_version")
    _same(versions["rule_set"], verdict["rule_set_version"], "VERSION_MISMATCH", "/published_batch/eligibility_verdicts/0/rule_set_version")
    for path, value in (("/published_batch/published_batch_digest", published["published_batch_digest"]), ("/published_batch/batch/batch_digest", batch["batch_digest"]), ("/published_batch/effect_proposals/0/action_digest", proposal["action_digest"]), ("/published_batch/effect_proposals/0/destination_digest", proposal["destination_digest"])):
        _dg(value, "MALFORMED_PUBLISHED_BATCH", path)
    expected_batch = digest({"kind": "M3StableBatchPreimage", "contract_version": "flrh-r-kernel/1", "profile_digest": profile_digest, "logical_time": logical_time, "low_watermark": low_watermark, "ordered_proposal_ids": [proposal["proposal_id"]], "ordered_eligibility_verdict_ids": [verdict["verdict_id"]], "dataflow_version": batch["dataflow_version"]})
    _same(batch["batch_digest"], expected_batch, "BATCH_DIGEST_MISMATCH", "/published_batch/batch/batch_digest")
    suffix = expected_batch.split(":", 1)[1]
    _same(batch["batch_id"], "batch:" + suffix, "BATCH_DIGEST_MISMATCH", "/published_batch/batch/batch_id")
    _same(batch["cause_id"], "reaction:" + suffix, "BATCH_DIGEST_MISMATCH", "/published_batch/batch/cause_id")
    expected_pub = digest({"kind": "M3PublishedBatchPreimage", "contract_version": "flrh-r-kernel/1", "batch": thaw(batch), "ordered_effect_proposals": [thaw(proposal)], "ordered_eligibility_verdicts": [thaw(verdict)]})
    _same(published["published_batch_digest"], expected_pub, "PUBLISHED_BATCH_DIGEST_MISMATCH", "/published_batch/published_batch_digest")
    return thaw(batch), thaw(proposal), thaw(verdict)


def _validate_snapshot(raw: Any, proposal: Mapping[str, Any], observed_at: int) -> Dict[str, Any]:
    snap = _exact(raw, SNAPSHOT_KEYS, "MALFORMED_AUTHORITY_SNAPSHOT", "/authority_snapshot")
    _same(snap["kind"], "HAuthoritySnapshot", "MALFORMED_AUTHORITY_SNAPSHOT", "/authority_snapshot/kind")
    _id(snap["authority_version"], "MALFORMED_AUTHORITY_SNAPSHOT", "/authority_snapshot/authority_version")
    expected = digest({"kind": "M4AAuthorityPreimage", "contract_version": CONTRACT, **_without(snap, "authority_digest")})
    _same(snap["authority_digest"], expected, "AUTHORITY_DIGEST_MISMATCH", "/authority_snapshot/authority_digest")
    _same(snap["proposal_id"], proposal["proposal_id"], "AUTHORITY_BINDING_MISMATCH", "/authority_snapshot/proposal_id")
    _same(snap["effect_type"], proposal["effect_type"], "AUTHORITY_BINDING_MISMATCH", "/authority_snapshot/effect_type")
    _same(snap["destination_digest"], proposal["destination_digest"], "AUTHORITY_BINDING_MISMATCH", "/authority_snapshot/destination_digest")
    _same(snap["adapter_version"], proposal["versions"]["tool"], "ADAPTER_VERSION_MISMATCH", "/authority_snapshot/adapter_version")
    if snap["decision"] == "deny":
        raise _Reject("AUTHORITY_DENIED", "/authority_snapshot/decision")
    if snap["decision"] != "allow":
        raise _Reject("AUTHORITY_AMBIGUOUS", "/authority_snapshot/decision")
    if snap["revoked"] is not False:
        raise _Reject("AUTHORITY_REVOKED", "/authority_snapshot/revoked")
    if not (_time(snap["valid_from"], "MALFORMED_AUTHORITY_SNAPSHOT", "/authority_snapshot/valid_from") <= observed_at < _time(snap["valid_until"], "MALFORMED_AUTHORITY_SNAPSHOT", "/authority_snapshot/valid_until")):
        raise _Reject("AUTHORITY_EXPIRED", "/observed_at")
    if snap["assessed_risk"] not in {"read_only", "reversible", "high_risk_external"}:
        raise _Reject("MALFORMED_AUTHORITY_SNAPSHOT", "/authority_snapshot/assessed_risk")
    _id(snap["capability"], "MALFORMED_AUTHORITY_SNAPSHOT", "/authority_snapshot/capability")
    return thaw(snap)


def _request(proposal: Mapping[str, Any], snap: Mapping[str, Any], context: Mapping[str, Any]) -> Dict[str, Any]:
    core = {"kind": "HApprovalRequest", "proposal_id": proposal["proposal_id"], "capability": snap["capability"], "authority_digest": snap["authority_digest"], "adapter_version": snap["adapter_version"], "requested_at": context["requested_at"], **{key: context[key] for key in ("context_digest", "policy_version", "approver_scope", *sorted(LOOP_BINDING_KEYS))}}
    request_digest = digest({"kind": "M4AApprovalRequestPreimage", "contract_version": CONTRACT, **core})
    return {**core, "request_id": "approval-request:" + request_digest.split(":", 1)[1], "request_digest": request_digest}


def _validate_context(raw: Any, observed_at: int, proposal: Mapping[str, Any]) -> Dict[str, Any]:
    context = _exact(raw, CONTEXT_KEYS, "MALFORMED_APPROVAL_CONTEXT", "/approval_context")
    _same(context["kind"], "HApprovalContext", "MALFORMED_APPROVAL_CONTEXT", "/approval_context/kind")
    expected = digest({"kind": "M4AApprovalContextPreimage", "contract_version": CONTRACT, **_without(context, "context_digest")})
    _same(context["context_digest"], expected, "APPROVAL_CONTEXT_DIGEST_MISMATCH", "/approval_context/context_digest")
    requested = _time(context["requested_at"], "MALFORMED_APPROVAL_CONTEXT", "/approval_context/requested_at")
    expires = _time(context["expires_at"], "MALFORMED_APPROVAL_CONTEXT", "/approval_context/expires_at")
    if requested != observed_at or expires <= requested:
        raise _Reject("APPROVAL_TIME_DRIFT", "/approval_context")
    for key in ("policy_version", "approver_scope", "run_id", "workflow_version", "visibility", "scope", "actor", "nonce", "rationale"):
        _id(context[key], "MALFORMED_APPROVAL_CONTEXT", f"/approval_context/{key}")
    for key in ("action_digest", "artifact_digest", "destination_digest"):
        _dg(context[key], "MALFORMED_APPROVAL_CONTEXT", f"/approval_context/{key}")
    bindings = {"run_id": proposal["correlation_id"], "workflow_version": proposal["versions"]["workflow"], "action_digest": proposal["action_digest"], "destination_digest": proposal["destination_digest"]}
    for key, expected_value in bindings.items():
        _same(context[key], expected_value, "APPROVAL_CONTEXT_BINDING_MISMATCH", f"/approval_context/{key}")
    return thaw(context)


def _intent(proposal: Mapping[str, Any], batch: Mapping[str, Any], snap: Mapping[str, Any], sequence: int, approval_digest: Optional[str]) -> Dict[str, Any]:
    transition_id = "consume-approval" if approval_digest is not None else "authorize-low-risk"
    idempotency = digest({"kind": "M4AIdempotencyPreimage", "contract_version": CONTRACT, "run_id": proposal["correlation_id"], "transition_id": transition_id, "effect_sequence": sequence, "action_digest": proposal["action_digest"], "adapter_version": snap["adapter_version"]})
    identity = digest({"kind": "M4AIntentIdentityPreimage", "contract_version": CONTRACT, "idempotency_digest": idempotency, "proposal_id": proposal["proposal_id"], "batch_id": batch["batch_id"], "authority_digest": snap["authority_digest"], "approval_digest": approval_digest})
    suffix = identity.split(":", 1)[1]
    return {"kind": "EffectIntent", "intent_id": "intent:" + suffix, "proposal_id": proposal["proposal_id"], "batch_id": batch["batch_id"], "effect_type": proposal["effect_type"], "action_digest": proposal["action_digest"], "capability": snap["capability"], "authority_digest": snap["authority_digest"], "cause_id": proposal["cause_id"], "correlation_id": proposal["correlation_id"], "idempotency_key": "effect:" + idempotency.split(":", 1)[1], "destination_digest": proposal["destination_digest"], "goal_id": proposal["goal_id"], "obligation_id": proposal["obligation_id"], "adapter_version": snap["adapter_version"], "assessed_risk": snap["assessed_risk"], "approval_required": approval_digest is not None, "approval_digest": approval_digest, "preconditions": sorted(proposal["preconditions"]), "versions": thaw(proposal["versions"])}


def _policy_verdict_digest(profile_digest: str, verdict: Mapping[str, Any], snap: Mapping[str, Any]) -> str:
    return digest({
        "kind": "M4APolicyVerdictEvidencePreimage",
        "contract_version": CONTRACT,
        "r_profile_digest": profile_digest,
        "eligibility_verdict": thaw(verdict),
        "authority_decision": snap["decision"],
        "authority_digest": snap["authority_digest"],
        "assessed_risk": snap["assessed_risk"],
    })


def _capability_digest(proposal: Mapping[str, Any], snap: Mapping[str, Any]) -> str:
    return digest({
        "kind": "M4ACapabilityEvidencePreimage",
        "contract_version": CONTRACT,
        "capability": snap["capability"],
        "authority_digest": snap["authority_digest"],
        "proposal_id": proposal["proposal_id"],
        "effect_type": proposal["effect_type"],
        "action_digest": proposal["action_digest"],
        "destination_digest": proposal["destination_digest"],
        "adapter_version": snap["adapter_version"],
    })


def _projection(command_digest: str, event: str, state: str, intent: Any, request: Any, evidence: Mapping[str, Any]) -> Dict[str, Any]:
    authorities = {"EFFECT_AUTHORIZED": ("policy_evaluator", "effect.authorize_low_risk"), "APPROVAL_REQUIRED": ("policy_evaluator", "approval.request"), "APPROVAL_GRANTED": ("human_approver", "approval.grant_exact_hash")}
    actor_role, capability = authorities[event]
    payload = {"command_digest": command_digest, **{key: value for key, value in evidence.items() if value is not None}}
    event_digest = digest({"kind": "M4AControlEventPreimage", "contract_version": CONTRACT, "type": event, "actor_role": actor_role, "capability": capability, "payload": payload})
    control_event = {"type": event, "actor_role": actor_role, "capability": capability, "event_id": "event:" + event_digest.split(":", 1)[1], "payload": payload}
    core = {"kind": "HProjection", "schema_version": RESULT_SCHEMA, "contract_version": CONTRACT, "command_digest": command_digest, "event": event, "control_event": control_event, "next_control_state": state, "intent": intent, "approval_request": request}
    return {**core, "projection_digest": digest({"kind": "M4AProjectionPreimage", "contract_version": CONTRACT, **core})}


def _rejection(code: str, path: str, command_digest: Optional[str], expected: Any = None, actual: Any = None) -> Dict[str, Any]:
    if code not in REJECTION_CODES:
        raise AssertionError(f"unregistered M4A rejection code: {code}")
    context = {}
    if expected is not None and isinstance(expected, (str, int, bool)):
        context["expected"] = expected
    if actual is not None and isinstance(actual, (str, int, bool)):
        context["actual"] = actual
    return {"kind": "HRejection", "schema_version": RESULT_SCHEMA, "contract_version": CONTRACT, "code": code, "path": path or "/", "command_digest": command_digest, "context": context}


def project_h_intent(command: Any) -> Dict[str, Any]:
    """Project one supplied stable pair into approval or intent data."""
    trusted_digest: Optional[str] = None
    try:
        cmd = _exact(command, COMMAND_KEYS, "MALFORMED_COMMAND", "/")
        _same(cmd["kind"], "HProjectIntentCommand", "MALFORMED_COMMAND", "/kind")
        _same(cmd["schema_version"], COMMAND_SCHEMA, "UNSUPPORTED_COMMAND_SCHEMA", "/schema_version")
        _same(cmd["contract_version"], CONTRACT, "UNSUPPORTED_CONTRACT_VERSION", "/contract_version")
        trusted_digest = digest({"kind": "M4ACommandPreimage", "contract_version": CONTRACT, **_without(cmd, "command_digest")})
        _same(cmd["command_digest"], trusted_digest, "COMMAND_DIGEST_MISMATCH", "/command_digest")
        observed = _time(cmd["observed_at"], "MALFORMED_COMMAND", "/observed_at")
        sequence = _time(cmd["effect_sequence"], "MALFORMED_COMMAND", "/effect_sequence")
        if sequence < 1:
            raise _Reject("MALFORMED_COMMAND", "/effect_sequence")
        profile_digest = _dg(cmd["r_profile_digest"], "MALFORMED_COMMAND", "/r_profile_digest")
        batch, proposal, verdict = _validate_published(cmd["published_batch"], profile_digest)
        if verdict["status"] == "ineligible":
            raise _Reject("PROPOSAL_INELIGIBLE", "/published_batch/eligibility_verdicts/0/status")
        if verdict["status"] == "conflicted":
            raise _Reject("PROPOSAL_CONFLICTED", "/published_batch/eligibility_verdicts/0/status")
        if verdict["status"] != "eligible":
            raise _Reject("MALFORMED_VERDICT", "/published_batch/eligibility_verdicts/0/status")
        snap = _validate_snapshot(cmd["authority_snapshot"], proposal, observed)
        if cmd["control_state"] == "PLAN_EFFECTS":
            if cmd["approval_request"] is not None or cmd["approval"] is not None:
                raise _Reject("APPROVAL_FIELD_DRIFT", "/approval_request")
            if snap["assessed_risk"] == "high_risk_external":
                context = _validate_context(cmd["approval_context"], observed, proposal)
                request = _request(proposal, snap, context)
                return _projection(trusted_digest, "APPROVAL_REQUIRED", "WAIT_APPROVAL", None, request, {"action_digest": proposal["action_digest"], "risk_classification": snap["assessed_risk"], "published_batch_digest": cmd["published_batch"]["published_batch_digest"], "authority_digest": snap["authority_digest"], "approval_context_digest": context["context_digest"], "approval_request_digest": request["request_digest"]})
            if cmd["approval_context"] is not None:
                raise _Reject("APPROVAL_FIELD_DRIFT", "/approval_context")
            intent = _intent(proposal, batch, snap, sequence, None)
            return _projection(trusted_digest, "EFFECT_AUTHORIZED", "COMMIT_INTENT", intent, None, {"policy_verdict": _policy_verdict_digest(profile_digest, verdict, snap), "capability_digest": _capability_digest(proposal, snap), "published_batch_digest": cmd["published_batch"]["published_batch_digest"], "authority_digest": snap["authority_digest"], "intent_id": intent["intent_id"]})
        if cmd["control_state"] != "WAIT_APPROVAL":
            raise _Reject("INVALID_CONTROL_STATE", "/control_state")
        if snap["assessed_risk"] != "high_risk_external":
            raise _Reject("APPROVAL_FIELD_DRIFT", "/authority_snapshot/assessed_risk")
        context = _validate_context(cmd["approval_context"], cmd["approval_context"]["requested_at"] if isinstance(cmd["approval_context"], dict) and isinstance(cmd["approval_context"].get("requested_at"), int) else observed, proposal)
        expected_request = _request(proposal, snap, context)
        supplied_request = _exact(cmd["approval_request"], REQUEST_KEYS, "MALFORMED_APPROVAL_REQUEST", "/approval_request")
        _same(thaw(supplied_request), expected_request, "APPROVAL_REQUEST_DRIFT", "/approval_request")
        approval = _exact(cmd["approval"], APPROVAL_KEYS, "MALFORMED_APPROVAL", "/approval")
        _same(approval["kind"], "HApproval", "MALFORMED_APPROVAL", "/approval/kind")
        expected_approval_digest = digest({"kind": "M4AApprovalPreimage", "contract_version": CONTRACT, **_without(approval, "approval_digest")})
        _same(approval["approval_digest"], expected_approval_digest, "APPROVAL_DIGEST_MISMATCH", "/approval/approval_digest")
        if approval["decision"] != "grant":
            raise _Reject("APPROVAL_DENIED", "/approval/decision")
        if approval["revoked"] is not False:
            raise _Reject("APPROVAL_REVOKED", "/approval/revoked")
        if approval["consumed"] is not False:
            raise _Reject("APPROVAL_ALREADY_CONSUMED", "/approval/consumed")
        bindings = {"request_digest": expected_request["request_digest"], "capability": snap["capability"], "authority_digest": snap["authority_digest"], "adapter_version": snap["adapter_version"], **{key: context[key] for key in ("context_digest", "policy_version", "approver_scope", *sorted(LOOP_BINDING_KEYS))}}
        for key, expected in bindings.items():
            _same(approval[key], expected, "APPROVAL_BINDING_MISMATCH", f"/approval/{key}")
        issued = _time(approval["issued_at"], "MALFORMED_APPROVAL", "/approval/issued_at")
        expires = _time(approval["expires_at"], "MALFORMED_APPROVAL", "/approval/expires_at")
        if issued < context["requested_at"] or issued > observed or expires != context["expires_at"] or not issued <= observed < expires:
            raise _Reject("APPROVAL_EXPIRED", "/approval/expires_at")
        intent = _intent(proposal, batch, snap, sequence, approval["approval_digest"])
        return _projection(trusted_digest, "APPROVAL_GRANTED", "COMMIT_INTENT", intent, None, {"exact_hash_approval_digest": approval["approval_digest"], "published_batch_digest": cmd["published_batch"]["published_batch_digest"], "authority_digest": snap["authority_digest"], "approval_context_digest": context["context_digest"], "approval_request_digest": expected_request["request_digest"], "approval_digest": approval["approval_digest"], "intent_id": intent["intent_id"]})
    except CanonicalizationError as exc:
        return _rejection("CANONICALIZATION_VIOLATION", exc.path, trusted_digest, exc.code)
    except _Reject as exc:
        return _rejection(exc.code, exc.path, trusted_digest, exc.expected, exc.actual)


__all__ = ["project_h_intent"]
