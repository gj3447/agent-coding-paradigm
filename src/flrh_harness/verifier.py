"""Independent read-only SQL verifier for one bounded M4B run."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from .canonical import canonical_bytes, digest


_PROTOCOL = json.loads(
    (Path(__file__).resolve().parents[2] / "spec/schema/protocol.v1.schema.json").read_text(encoding="utf-8")
)
_PROTOCOL_VALIDATOR = Draft202012Validator(_PROTOCOL, format_checker=FormatChecker())
_BINDING_KEYS = {"command_digest", "input_root_digest", "platform_digest"}
_REQUEST_KEYS = {
    "kind", "proposal_id", "capability", "authority_digest", "adapter_version",
    "requested_at", "context_digest", "policy_version", "approver_scope", "run_id",
    "workflow_version", "action_digest", "artifact_digest", "destination_digest",
    "visibility", "scope", "actor", "expires_at", "nonce", "rationale",
    "request_id", "request_digest",
}
_APPROVAL_KEYS = {
    "kind", "request_digest", "decision", "capability", "authority_digest",
    "adapter_version", "context_digest", "policy_version", "approver_scope", "run_id",
    "workflow_version", "action_digest", "artifact_digest", "destination_digest",
    "visibility", "scope", "actor", "expires_at", "nonce", "rationale",
    "issued_at", "revoked", "consumed", "approval_digest",
}


def _decode(row, column, label, errors):
    try:
        value = json.loads(row[column])
        if canonical_bytes(value).decode("utf-8") != row[column]:
            errors.append(f"{label}_NONCANONICAL")
        return value
    except (json.JSONDecodeError, TypeError, ValueError):
        errors.append(f"{label}_INVALID_JSON")
        return None


def verify_run(path: Path, run_id: str):
    connection = sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    errors = []
    run = connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if run is None:
        connection.close()
        return {"kind": "M4BVerificationReport", "run_id": run_id, "valid": False,
                "errors": ["RUN_MISSING"], "intent_count": 0, "receipt_count": 0, "pending_count": 0}

    checkpoint = connection.execute("SELECT * FROM checkpoints WHERE run_id=?", (run_id,)).fetchone()
    if checkpoint is None:
        errors.append("CHECKPOINT_MISSING")
    else:
        payload = _decode(checkpoint, "payload_json", "CHECKPOINT", errors)
        if checkpoint["schema_version"] != "flrh-h-checkpoint/1":
            errors.append("CHECKPOINT_VERSION")
        if payload is not None and checkpoint["payload_hash"] != digest(
            {"schema_version": checkpoint["schema_version"], "payload": payload}
        ):
            errors.append("CHECKPOINT_HASH")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        errors.append("FOREIGN_KEY")
    if not 1 <= run["max_pending"] <= 1024:
        errors.append("RUN_MAX_PENDING")
    if not 1 <= run["max_attempts"] <= 16:
        errors.append("RUN_MAX_ATTEMPTS")
    if run["status"] not in {"active", "cancelled", "timed_out", "budget_exhausted", "quarantined"}:
        errors.append("RUN_STATUS")
    if run["pending_interrupt"] not in {None, "cancel", "timeout", "budget_exhausted"}:
        errors.append("PENDING_INTERRUPT")

    intents = connection.execute("SELECT * FROM intents WHERE run_id=? ORDER BY intent_id", (run_id,)).fetchall()
    intent_values = {}
    for row in intents:
        value = _decode(row, "intent_json", "INTENT", errors)
        if value is None:
            continue
        if value.get("kind") != "EffectIntent" or list(_PROTOCOL_VALIDATOR.iter_errors(value)):
            errors.append("INTENT_SCHEMA")
        if digest(value) != row["intent_digest"]:
            errors.append("INTENT_DIGEST")
        if value.get("intent_id") != row["intent_id"] or value.get("idempotency_key") != row["idempotency_key"]:
            errors.append("INTENT_LINK")
        if not 1 <= row["generation"] <= run["generation"]:
            errors.append("INTENT_GENERATION")
        intent_values[row["intent_id"]] = value

    bindings = {row["intent_id"]: row for row in connection.execute(
        "SELECT b.* FROM receipt_bindings b JOIN intents i USING(intent_id) WHERE i.run_id=?", (run_id,)
    )}
    outboxes = {row["intent_id"]: row for row in connection.execute(
        "SELECT o.* FROM outbox o JOIN intents i USING(intent_id) WHERE i.run_id=?", (run_id,)
    )}
    receipts = {row["intent_id"]: row for row in connection.execute(
        "SELECT r.* FROM receipts r JOIN intents i USING(intent_id) WHERE i.run_id=?", (run_id,)
    )}
    attempts = {}
    for row in connection.execute(
        "SELECT a.* FROM attempts a JOIN intents i USING(intent_id) WHERE i.run_id=? ORDER BY a.intent_id,a.sequence", (run_id,)
    ):
        attempts.setdefault(row["intent_id"], []).append(row)
        if not 1 <= row["generation"] <= run["generation"]:
            errors.append("ATTEMPT_GENERATION")

    approval_rows = connection.execute("SELECT * FROM approvals WHERE run_id=?", (run_id,)).fetchall()
    approvals_by_intent = {}
    intent_row_ids = {row["intent_id"] for row in intents}
    for row in approval_rows:
        approvals_by_intent.setdefault(row["intent_id"], []).append(row)
        if row["intent_id"] not in intent_row_ids:
            errors.append("APPROVAL_ORPHAN")

    for intent_id, value in intent_values.items():
        binding_row = bindings.get(intent_id)
        binding = None
        if binding_row is None:
            errors.append("RECEIPT_BINDING_MISSING")
        else:
            binding = _decode(binding_row, "binding_json", "RECEIPT_BINDING", errors)
            if binding is not None:
                if set(binding) != _BINDING_KEYS:
                    errors.append("RECEIPT_BINDING_SCHEMA")
                if digest(binding) != binding_row["binding_digest"]:
                    errors.append("RECEIPT_BINDING_DIGEST")

        outbox = outboxes.get(intent_id)
        receipt_row = receipts.get(intent_id)
        history = attempts.get(intent_id, [])
        if len(history) > run["max_attempts"]:
            errors.append("ATTEMPT_BOUND")
        if [item["sequence"] for item in history] != list(range(1, len(history) + 1)):
            errors.append("ATTEMPT_SEQUENCE")
        allowed_attempt_statuses = {"started", "transient", "unknown", "reconciled_not_applied", "confirmed_success", "confirmed_failure"}
        if any(item["status"] not in allowed_attempt_statuses for item in history):
            errors.append("ATTEMPT_STATUS")
        if any(item["attempt_id"] != f"attempt:{intent_id}:{item['sequence']}" for item in history):
            errors.append("ATTEMPT_ID")
        if [item["generation"] for item in history] != sorted(item["generation"] for item in history):
            errors.append("ATTEMPT_GENERATION_ORDER")
        if any(item["status"] not in {"transient", "reconciled_not_applied"} for item in history[:-1]):
            errors.append("ATTEMPT_TRANSITION")
        if outbox is None:
            errors.append("OUTBOX_MISSING")
            continue
        if (outbox["status"] == "done") != (receipt_row is not None):
            errors.append("OUTBOX_RECEIPT_COHERENCE")
        if history:
            expected_statuses = {
                "pending": {"transient", "reconciled_not_applied"},
                "started": {"started"},
                "reconcile": {"unknown"},
                "done": {"confirmed_success", "confirmed_failure"},
            }
            if history[-1]["status"] not in expected_statuses.get(outbox["status"], set()):
                errors.append("ATTEMPT_OUTBOX_COHERENCE")
            expected_route = {"pending": "retry" if history[-1]["status"] == "transient" else "dispatch",
                              "started": "dispatch", "reconcile": "reconcile", "done": "terminal"}
            if outbox["route"] != expected_route.get(outbox["status"]):
                errors.append("OUTBOX_ROUTE_COHERENCE")
        elif outbox["status"] != "pending":
            errors.append("ATTEMPT_OUTBOX_COHERENCE")
        elif outbox["route"] != "dispatch":
            errors.append("OUTBOX_ROUTE_COHERENCE")

        if receipt_row is not None:
            wire = _decode(receipt_row, "receipt_json", "RECEIPT", errors)
            if wire is not None:
                if wire.get("kind") != "ActionReceipt" or list(_PROTOCOL_VALIDATOR.iter_errors(wire)):
                    errors.append("RECEIPT_SCHEMA")
                if digest(wire) != receipt_row["receipt_digest"]:
                    errors.append("RECEIPT_DIGEST")
                copied = {
                    "intent_id", "action_digest", "cause_id", "correlation_id", "capability",
                    "authority_digest", "destination_digest", "goal_id", "obligation_id",
                    "adapter_version", "assessed_risk", "approval_required", "approval_digest",
                    "idempotency_key",
                }
                if any(wire.get(key) != value.get(key) for key in copied):
                    errors.append("RECEIPT_INTENT_LINK")
                if binding is None or any(wire.get(key) != binding.get(key) for key in _BINDING_KEYS):
                    errors.append("RECEIPT_BINDING_LINK")
                if wire.get("outcome") not in ("confirmed_success", "confirmed_failure"):
                    errors.append("RECEIPT_OUTCOME")
                if not history or wire.get("attempt_id") != history[-1]["attempt_id"] or history[-1]["status"] != wire.get("outcome"):
                    errors.append("ATTEMPT_RECEIPT_COHERENCE")

        approvals = approvals_by_intent.get(intent_id, [])
        if bool(value.get("approval_required")) != (len(approvals) == 1):
            errors.append("APPROVAL_CARDINALITY")
        for approval_row in approvals:
            request = _decode(approval_row, "request_json", "APPROVAL_REQUEST", errors)
            approval = _decode(approval_row, "approval_json", "APPROVAL", errors)
            if request is None or approval is None:
                continue
            if set(request) != _REQUEST_KEYS or request.get("kind") != "HApprovalRequest" or set(approval) != _APPROVAL_KEYS or approval.get("kind") != "HApproval":
                errors.append("APPROVAL_SCHEMA")
            request_core = {key: item for key, item in request.items() if key not in ("request_id", "request_digest")}
            request_digest = digest({"kind": "M4AApprovalRequestPreimage", "contract_version": "flrh-h-authority/1", **request_core})
            approval_core = {key: item for key, item in approval.items() if key != "approval_digest"}
            approval_digest = digest({"kind": "M4AApprovalPreimage", "contract_version": "flrh-h-authority/1", **approval_core})
            if request.get("request_digest") != request_digest or request.get("request_id") != "approval-request:" + request_digest.split(":", 1)[1]:
                errors.append("APPROVAL_REQUEST_DIGEST")
            if approval.get("approval_digest") != approval_digest:
                errors.append("APPROVAL_DIGEST")
            if (approval_row["approval_digest"] != approval_digest or value.get("approval_digest") != approval_digest
                    or approval.get("request_digest") != request_digest):
                errors.append("APPROVAL_LINK")
            intent_links = ("proposal_id", "action_digest", "destination_digest", "capability", "authority_digest", "adapter_version")
            if any(request.get(key) != value.get(key) for key in intent_links):
                errors.append("APPROVAL_INTENT_LINK")
            paired = set(request) - {"kind", "proposal_id", "requested_at", "request_id", "request_digest"}
            if any(approval.get(key) != request.get(key) for key in paired):
                errors.append("APPROVAL_PAIR_LINK")
            if request.get("workflow_version") != value.get("versions", {}).get("workflow") or approval_row["workflow_version"] != request.get("workflow_version"):
                errors.append("APPROVAL_WORKFLOW")
            if request.get("run_id") != value.get("correlation_id"):
                errors.append("APPROVAL_RUN_CORRELATION")
            if approval.get("decision") != "grant" or approval.get("revoked") or approval.get("consumed") or approval_row["consumed"] != 1:
                errors.append("APPROVAL_STATE")

    intent_count = len(intents)
    receipt_count = len(receipts)
    pending_count = sum(1 for row in outboxes.values() if row["status"] != "done")
    if run["status"] != "active" and pending_count:
        errors.append("TERMINAL_PENDING_EFFECT")
    if run["status"] != "active" and run["pending_interrupt"] is not None:
        errors.append("TERMINAL_INTERRUPT")
    connection.close()
    return {"kind": "M4BVerificationReport", "run_id": run_id, "valid": not errors,
            "errors": sorted(set(errors)), "intent_count": intent_count,
            "receipt_count": receipt_count, "pending_count": pending_count}
