"""Bounded SQLite-backed M4B L_RT harness reference."""

from __future__ import annotations

import copy
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from jsonschema import Draft202012Validator, FormatChecker

from .adapter import AdapterConflictError, AdapterStaleFenceError, FakeAdapter
from .canonical import canonical_bytes, digest


class HarnessError(RuntimeError): pass
class ConflictError(HarnessError): pass
class StaleFenceError(HarnessError): pass
class ApprovalRejected(HarnessError): pass
class ReconciliationRequired(HarnessError): pass
class QuarantinedError(HarnessError): pass
class CrashInjected(HarnessError): pass


INTENT_FIELDS = {
    "kind", "intent_id", "proposal_id", "batch_id", "effect_type", "action_digest",
    "capability", "authority_digest", "cause_id", "correlation_id", "idempotency_key",
    "destination_digest", "goal_id", "obligation_id", "adapter_version", "assessed_risk",
    "approval_required", "approval_digest", "preconditions", "versions",
}
REQUEST_FIELDS = {
    "kind", "proposal_id", "capability", "authority_digest", "adapter_version",
    "requested_at", "context_digest", "policy_version", "approver_scope", "run_id",
    "workflow_version", "action_digest", "artifact_digest", "destination_digest",
    "visibility", "scope", "actor", "expires_at", "nonce", "rationale",
    "request_id", "request_digest",
}
APPROVAL_FIELDS = {
    "kind", "request_digest", "decision", "capability", "authority_digest",
    "adapter_version", "context_digest", "policy_version", "approver_scope", "run_id",
    "workflow_version", "action_digest", "artifact_digest", "destination_digest",
    "visibility", "scope", "actor", "expires_at", "nonce", "rationale",
    "issued_at", "revoked", "consumed", "approval_digest",
}
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
MAX_PENDING_CEILING = 1024
MAX_ATTEMPTS_CEILING = 16
_PROTOCOL_SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "spec/schema/protocol.v1.schema.json").read_text(encoding="utf-8")
)
_PROTOCOL_VALIDATOR = Draft202012Validator(_PROTOCOL_SCHEMA, format_checker=FormatChecker())


def _rfc3339(epoch: int) -> str:
    """Format an injected Unix epoch without consulting an ambient clock."""
    if not isinstance(epoch,int) or isinstance(epoch,bool): raise ValueError("invalid injected epoch")
    days, seconds = divmod(epoch, 86400)
    z = days + 719468
    era = z // 146097
    day_of_era = z - era * 146097
    year_of_era = (day_of_era - day_of_era // 1460 + day_of_era // 36524 - day_of_era // 146096) // 365
    year = year_of_era + era * 400
    day_of_year = day_of_era - (365 * year_of_era + year_of_era // 4 - year_of_era // 100)
    month_prime = (5 * day_of_year + 2) // 153
    day = day_of_year - (153 * month_prime + 2) // 5 + 1
    month = month_prime + (3 if month_prime < 10 else -9)
    year += month <= 2
    if not 1 <= year <= 9999: raise ValueError("injected epoch outside RFC 3339 profile")
    hour, seconds = divmod(seconds, 3600); minute, second = divmod(seconds, 60)
    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}Z"


def _validate_intent(value: Dict[str, Any]) -> None:
    protocol_errors = sorted(
        _PROTOCOL_VALIDATOR.iter_errors(value),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if protocol_errors:
        raise ValueError("protocol schema rejected EffectIntent")
    if not isinstance(value, dict) or set(value) != INTENT_FIELDS or value.get("kind") != "EffectIntent":
        raise ValueError("not an exact EffectIntent")
    for name in ("action_digest", "authority_digest", "destination_digest"):
        if not isinstance(value[name], str) or not DIGEST_RE.fullmatch(value[name]): raise ValueError(f"invalid {name}")
    if value["approval_digest"] is not None and not DIGEST_RE.fullmatch(value["approval_digest"]): raise ValueError("invalid approval_digest")
    if value["assessed_risk"] not in ("read_only", "reversible", "high_risk_external"): raise ValueError("invalid risk")
    if value["approval_required"] != (value["assessed_risk"] == "high_risk_external"): raise ValueError("risk/approval mismatch")
    if value["approval_required"] != (value["approval_digest"] is not None): raise ValueError("approval binding mismatch")
    if not isinstance(value["preconditions"], list) or len(value["preconditions"]) != len(set(value["preconditions"])): raise ValueError("invalid preconditions")
    expected_versions = {"workflow","state_schema","event_schema","graph_schema","rule_set","dataflow","canonicalization","tool","model","oracle","gate","resolver","composition_profile"}
    if not isinstance(value["versions"], dict) or set(value["versions"]) != expected_versions: raise ValueError("invalid versions")
    for name in INTENT_FIELDS - {"approval_digest", "preconditions", "versions", "approval_required"}:
        if not isinstance(value[name], str) or not value[name]: raise ValueError(f"invalid {name}")


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs(
 run_id TEXT PRIMARY KEY, status TEXT NOT NULL, generation INTEGER NOT NULL,
 lease_owner TEXT, lease_expires_epoch INTEGER, pending_interrupt TEXT,
 max_pending INTEGER NOT NULL, max_attempts INTEGER NOT NULL
) STRICT;
CREATE TABLE IF NOT EXISTS checkpoints(
 run_id TEXT PRIMARY KEY REFERENCES runs(run_id), seq INTEGER NOT NULL,
 schema_version TEXT NOT NULL, payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL
) STRICT;
CREATE TABLE IF NOT EXISTS approvals(
 approval_digest TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id),
 intent_id TEXT NOT NULL UNIQUE REFERENCES intents(intent_id) DEFERRABLE INITIALLY DEFERRED,
 workflow_version TEXT NOT NULL,
 request_json TEXT NOT NULL, approval_json TEXT NOT NULL, consumed INTEGER NOT NULL CHECK(consumed IN (0,1))
) STRICT;
CREATE TABLE IF NOT EXISTS intents(
 intent_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id),
 idempotency_key TEXT NOT NULL UNIQUE, intent_digest TEXT NOT NULL, intent_json TEXT NOT NULL,
 generation INTEGER NOT NULL
) STRICT;
CREATE TABLE IF NOT EXISTS receipt_bindings(
 intent_id TEXT PRIMARY KEY REFERENCES intents(intent_id), binding_json TEXT NOT NULL,
 binding_digest TEXT NOT NULL
) STRICT;
CREATE TABLE IF NOT EXISTS outbox(
 intent_id TEXT PRIMARY KEY REFERENCES intents(intent_id), status TEXT NOT NULL,
 sequence INTEGER NOT NULL UNIQUE, route TEXT NOT NULL
) STRICT;
CREATE TABLE IF NOT EXISTS attempts(
 attempt_id TEXT PRIMARY KEY, intent_id TEXT NOT NULL REFERENCES intents(intent_id),
 generation INTEGER NOT NULL, status TEXT NOT NULL, sequence INTEGER NOT NULL,
 UNIQUE(intent_id,sequence)
) STRICT;
CREATE TABLE IF NOT EXISTS receipts(
 intent_id TEXT PRIMARY KEY REFERENCES intents(intent_id), receipt_digest TEXT NOT NULL,
 receipt_json TEXT NOT NULL
) STRICT;
"""


class DurableHarness:
    def __init__(self, path: Path, adapter: FakeAdapter, *, now: Callable[[], int], receipt_evidence: Callable[[Dict[str,Any],str,str],Dict[str,Any]]):
        self.path = Path(path); self.adapter = adapter; self.now = now; self.receipt_evidence = receipt_evidence
        self.connection = sqlite3.connect(str(self.path), isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("PRAGMA trusted_schema=OFF")
        self.connection.executescript(SCHEMA_SQL)

    def close(self):
        if getattr(self, "connection", None) is not None:
            self.connection.close(); self.connection = None

    def _begin(self): self.connection.execute("BEGIN IMMEDIATE")
    def _row(self, run_id):
        row = self.connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None: raise KeyError(run_id)
        return row

    def create_run(self, run_id: str, checkpoint: Dict[str, Any], *, max_pending: int = 64, max_attempts: int = 3):
        if not isinstance(max_pending,int) or isinstance(max_pending,bool) or not 1 <= max_pending <= MAX_PENDING_CEILING: raise ValueError("invalid max_pending")
        if not isinstance(max_attempts,int) or isinstance(max_attempts,bool) or not 1 <= max_attempts <= MAX_ATTEMPTS_CEILING: raise ValueError("invalid max_attempts")
        payload = canonical_bytes(checkpoint).decode(); bound = digest({"schema_version":"flrh-h-checkpoint/1","payload":checkpoint})
        self._begin()
        try:
            self.connection.execute("INSERT INTO runs VALUES(?,'active',0,NULL,NULL,NULL,?,?)", (run_id,max_pending,max_attempts))
            self.connection.execute("INSERT INTO checkpoints VALUES(?,0,'flrh-h-checkpoint/1',?,?)", (run_id,payload,bound))
            self.connection.commit()
        except Exception: self.connection.rollback(); raise

    def acquire_lease(self, run_id: str, owner: str, *, ttl_seconds: int) -> str:
        if ttl_seconds <= 0: raise ValueError("positive ttl required")
        self._begin()
        try:
            row = self._row(run_id)
            if row["lease_expires_epoch"] is not None and self.now() < row["lease_expires_epoch"] and row["lease_owner"] != owner:
                raise StaleFenceError("active lease held")
            generation = row["generation"] + 1
            changed=self.connection.execute("UPDATE runs SET generation=?,lease_owner=?,lease_expires_epoch=? WHERE run_id=? AND generation=?", (generation,owner,self.now()+ttl_seconds,run_id,row["generation"]))
            if changed.rowcount!=1: raise StaleFenceError("lease compare-and-swap lost")
            self.connection.commit(); return f"{run_id}|{owner}|{generation}"
        except Exception: self.connection.rollback(); raise

    def _check_token(self, token: str, *, current_epoch=None):
        try: run_id, owner, raw_generation = token.rsplit("|",2); generation=int(raw_generation)
        except Exception as error: raise StaleFenceError("malformed fence") from error
        row = self._row(run_id)
        if current_epoch is None: current_epoch=self.now()
        if row["status"] == "quarantined": raise QuarantinedError(run_id)
        if row["generation"] != generation or row["lease_owner"] != owner or current_epoch >= row["lease_expires_epoch"]:
            raise StaleFenceError("stale fence")
        return run_id, generation

    def _checkpoint(self, run_id, payload):
        row=self.connection.execute("SELECT seq FROM checkpoints WHERE run_id=?",(run_id,)).fetchone()
        schema="flrh-h-checkpoint/1"; encoded=canonical_bytes(payload).decode(); bound=digest({"schema_version":schema,"payload":payload})
        self.connection.execute("UPDATE checkpoints SET seq=?,schema_version=?,payload_json=?,payload_hash=? WHERE run_id=?",(row[0]+1,schema,encoded,bound,run_id))

    def _decode_checkpoint(self, row):
        payload=json.loads(row["payload_json"])
        if row["schema_version"] != "flrh-h-checkpoint/1" or row["payload_hash"] != digest({"schema_version":row["schema_version"],"payload":payload}):
            raise QuarantinedError(row["run_id"])
        return payload

    def _quarantine(self, run_id):
        self._begin(); self.connection.execute("UPDATE runs SET status='quarantined' WHERE run_id=?",(run_id,)); self.connection.commit()

    def load_checkpoint(self, run_id):
        row=self.connection.execute("SELECT * FROM checkpoints WHERE run_id=?",(run_id,)).fetchone()
        try: return self._decode_checkpoint(row)
        except (QuarantinedError, json.JSONDecodeError, TypeError, ValueError):
            self._quarantine(run_id); raise QuarantinedError(run_id)

    def _validate_approval(self, intent, request, value, *, current_epoch=None):
        if not intent["approval_required"]:
            if value is not None or request is not None: raise ApprovalRejected("unexpected approval")
            return
        if current_epoch is None: current_epoch=self.now()
        if not isinstance(request,dict) or set(request)!=REQUEST_FIELDS or not isinstance(value,dict) or set(value)!=APPROVAL_FIELDS: raise ApprovalRejected("shape")
        request_core={key:copy.deepcopy(item) for key,item in request.items() if key not in ("request_id","request_digest")}
        expected_request=digest({"kind":"M4AApprovalRequestPreimage","contract_version":"flrh-h-authority/1",**request_core})
        if request["kind"]!="HApprovalRequest" or request["request_digest"]!=expected_request or request["request_id"]!="approval-request:"+expected_request.split(":",1)[1]: raise ApprovalRejected("request digest")
        approval_core={key:copy.deepcopy(item) for key,item in value.items() if key!="approval_digest"}
        expected_approval=digest({"kind":"M4AApprovalPreimage","contract_version":"flrh-h-authority/1",**approval_core})
        if value["approval_digest"]!=expected_approval or value["approval_digest"]!=intent["approval_digest"]: raise ApprovalRejected("approval digest")
        bindings={"proposal_id":intent["proposal_id"],"action_digest":intent["action_digest"],"destination_digest":intent["destination_digest"],"capability":intent["capability"],"authority_digest":intent["authority_digest"],"adapter_version":intent["adapter_version"],"workflow_version":intent["versions"]["workflow"]}
        if any(request[key]!=expected for key,expected in bindings.items()): raise ApprovalRejected("request binding")
        if request["run_id"]!=intent["correlation_id"]: raise ApprovalRejected("request run binding")
        for key in REQUEST_FIELDS - {"kind", "proposal_id", "requested_at", "request_id", "request_digest"}:
            if value[key]!=request[key]: raise ApprovalRejected("approval binding")
        if value["kind"]!="HApproval" or value["request_digest"]!=request["request_digest"] or value["decision"]!="grant" or value["revoked"] or value["consumed"]: raise ApprovalRejected("approval state")
        if request["requested_at"]>value["issued_at"] or value["issued_at"]>current_epoch or value["expires_at"]!=request["expires_at"] or not current_epoch<value["expires_at"]: raise ApprovalRejected("approval time")

    def commit_intent(self, token, intent, *, receipt_binding, approval_request=None, approval=None):
        _validate_intent(intent); precheck_epoch=self.now(); run_id,generation=self._check_token(token,current_epoch=precheck_epoch)
        if not isinstance(receipt_binding,dict) or set(receipt_binding)!={"command_digest","input_root_digest","platform_digest"} or any(not isinstance(receipt_binding[key],str) or not DIGEST_RE.fullmatch(receipt_binding[key]) for key in receipt_binding): raise ValueError("invalid receipt binding")
        row=self._row(run_id)
        if row["status"]!="active" or row["pending_interrupt"] is not None: raise HarnessError("run does not accept new work")
        self._validate_approval(intent,approval_request,approval,current_epoch=precheck_epoch)
        checkpoint=self.load_checkpoint(run_id)
        encoded=canonical_bytes(intent).decode(); bound=digest(intent)
        self._begin()
        try:
            transaction_epoch=self.now()
            row=self._check_token(token,current_epoch=transaction_epoch) and self._row(run_id)
            if row["status"]!="active" or row["pending_interrupt"] is not None: raise HarnessError("run does not accept new work")
            self._validate_approval(intent,approval_request,approval,current_epoch=transaction_epoch)
            pending=self.connection.execute("SELECT COUNT(*) FROM outbox o JOIN intents i USING(intent_id) WHERE i.run_id=? AND o.status!='done'",(run_id,)).fetchone()[0]
            if pending>=row["max_pending"]: raise HarnessError("max_pending exceeded")
            checkpoint=self._decode_checkpoint(self.connection.execute("SELECT * FROM checkpoints WHERE run_id=?",(run_id,)).fetchone())
            existing=self.connection.execute("SELECT i.intent_digest,b.binding_digest FROM intents i JOIN receipt_bindings b USING(intent_id) WHERE i.intent_id=? OR i.idempotency_key=?",(intent["intent_id"],intent["idempotency_key"])).fetchone()
            if existing:
                if existing[0]==bound and existing[1]==digest(receipt_binding): self.connection.rollback(); return False
                raise ConflictError("duplicate identity with different intent")
            if approval is not None:
                try: self.connection.execute("INSERT INTO approvals VALUES(?,?,?,?,?,?,1)",(approval["approval_digest"],run_id,intent["intent_id"],intent["versions"]["workflow"],canonical_bytes(approval_request).decode(),canonical_bytes(approval).decode()))
                except sqlite3.IntegrityError as error: raise ApprovalRejected("approval replay") from error
            sequence=self.connection.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM outbox").fetchone()[0]
            self.connection.execute("INSERT INTO intents VALUES(?,?,?,?,?,?)",(intent["intent_id"],run_id,intent["idempotency_key"],bound,encoded,generation))
            self.connection.execute("INSERT INTO receipt_bindings VALUES(?,?,?)",(intent["intent_id"],canonical_bytes(receipt_binding).decode(),digest(receipt_binding)))
            self.connection.execute("INSERT INTO outbox VALUES(?,'pending',?,'dispatch')",(intent["intent_id"],sequence))
            checkpoint["last_committed_intent_id"]=intent["intent_id"]
            self._checkpoint(run_id,checkpoint); self.connection.commit(); return True
        except (QuarantinedError, json.JSONDecodeError, TypeError, ValueError):
            self.connection.rollback(); self._quarantine(run_id); raise QuarantinedError(run_id)
        except Exception: self.connection.rollback(); raise

    def pending_intents(self, run_id):
        return [row[0] for row in self.connection.execute("SELECT i.intent_id FROM intents i JOIN outbox o USING(intent_id) WHERE i.run_id=? AND o.status!='done' ORDER BY o.sequence",(run_id,))]

    def _next(self, run_id):
        return self.connection.execute("SELECT i.*,o.status,o.route FROM intents i JOIN outbox o USING(intent_id) WHERE i.run_id=? AND o.status!='done' ORDER BY o.sequence LIMIT 1",(run_id,)).fetchone()

    def _prepare_receipt(self, intent, outcome):
        attempt=self.connection.execute("SELECT attempt_id FROM attempts WHERE intent_id=? ORDER BY sequence DESC LIMIT 1",(intent["intent_id"],)).fetchone()
        if attempt is None: raise ConflictError("receipt without attempt")
        binding_row=self.connection.execute("SELECT binding_json,binding_digest FROM receipt_bindings WHERE intent_id=?",(intent["intent_id"],)).fetchone()
        if binding_row is None: raise ConflictError("receipt binding missing")
        binding=json.loads(binding_row[0])
        if digest(binding)!=binding_row[1]: raise ConflictError("receipt binding corrupt")
        attempt_id=attempt[0]
        supplied=self.receipt_evidence(copy.deepcopy(intent),attempt_id,outcome)
        expected={"output_digests","trace_ref","outcome"}
        if not isinstance(supplied,dict) or set(supplied)!=expected: raise ValueError("incomplete receipt evidence")
        if supplied["outcome"]!=outcome: raise ConflictError("receipt outcome observation drift")
        recorded_at=_rfc3339(self.now())
        receipt={"kind":"ActionReceipt","intent_id":intent["intent_id"],"action_digest":intent["action_digest"],"command_digest":binding["command_digest"],"input_root_digest":binding["input_root_digest"],"platform_digest":binding["platform_digest"],"cause_id":intent["cause_id"],"correlation_id":intent["correlation_id"],"capability":intent["capability"],"authority_digest":intent["authority_digest"],"destination_digest":intent["destination_digest"],"goal_id":intent["goal_id"],"obligation_id":intent["obligation_id"],"adapter_version":intent["adapter_version"],"assessed_risk":intent["assessed_risk"],"approval_required":intent["approval_required"],"approval_digest":intent["approval_digest"],"attempt_id":attempt_id,"idempotency_key":intent["idempotency_key"],"output_digests":supplied["output_digests"],"outcome":supplied["outcome"],"trace_ref":supplied["trace_ref"],"recorded_at":recorded_at}
        if list(_PROTOCOL_VALIDATOR.iter_errors(receipt)): raise ValueError("receipt evidence does not form an exact ActionReceipt")
        receipt=json.loads(canonical_bytes(receipt))
        return receipt,binding_row[1]

    def _record_receipt(self, token, run_id, intent, generation, outcome):
        # Observation/evidence injection is a port call and must occur outside the SQLite writer transaction.
        receipt,binding_digest=self._prepare_receipt(intent,outcome)
        encoded=canonical_bytes(receipt).decode(); bound=digest(receipt)
        self._begin()
        try:
            self._check_token(token)
            attempt=self.connection.execute("SELECT attempt_id FROM attempts WHERE intent_id=? ORDER BY sequence DESC LIMIT 1",(intent["intent_id"],)).fetchone()
            current_binding=self.connection.execute("SELECT binding_digest FROM receipt_bindings WHERE intent_id=?",(intent["intent_id"],)).fetchone()
            if attempt is None or attempt[0]!=receipt["attempt_id"] or current_binding is None or current_binding[0]!=binding_digest: raise ConflictError("receipt evidence changed")
            existing=self.connection.execute("SELECT receipt_digest FROM receipts WHERE intent_id=?",(intent["intent_id"],)).fetchone()
            if existing and existing[0]!=bound: raise ConflictError("receipt conflict")
            self.connection.execute("INSERT OR IGNORE INTO receipts VALUES(?,?,?)",(intent["intent_id"],bound,encoded))
            self.connection.execute("UPDATE outbox SET status='done',route='terminal' WHERE intent_id=?",(intent["intent_id"],))
            self.connection.execute("UPDATE attempts SET status=? WHERE attempt_id=(SELECT attempt_id FROM attempts WHERE intent_id=? ORDER BY sequence DESC LIMIT 1)",(outcome,intent["intent_id"]))
            checkpoint=self._decode_checkpoint(self.connection.execute("SELECT * FROM checkpoints WHERE run_id=?",(run_id,)).fetchone()); checkpoint["last_receipt_digest"]=bound; self._checkpoint(run_id,checkpoint)
            self.connection.commit(); return receipt
        except (QuarantinedError, json.JSONDecodeError, TypeError, ValueError):
            self.connection.rollback(); self._quarantine(run_id); raise QuarantinedError(run_id)
        except Exception: self.connection.rollback(); raise

    def dispatch_next(self, token, *, crash_point=None):
        run_id,generation=self._check_token(token); row=self._next(run_id)
        run=self._row(run_id)
        if run["status"]!="active": raise HarnessError("run does not allow dispatch")
        if row is None: return None
        intent=json.loads(row["intent_json"])
        prior=self.connection.execute("SELECT status FROM attempts WHERE intent_id=? ORDER BY sequence DESC LIMIT 1",(intent["intent_id"],)).fetchone()
        if prior and prior[0] in ("started","unknown"): raise ReconciliationRequired(intent["intent_id"])
        self._begin()
        try:
            self._check_token(token); run=self._row(run_id)
            if run["status"]!="active": raise HarnessError("run does not allow dispatch")
            seq=self.connection.execute("SELECT COUNT(*)+1 FROM attempts WHERE intent_id=?",(intent["intent_id"],)).fetchone()[0]
            if seq>run["max_attempts"]: raise HarnessError("max_attempts exceeded")
            attempt_id=f"attempt:{intent['intent_id']}:{seq}"
            self.connection.execute("INSERT INTO attempts VALUES(?,?,?,'started',?)",(attempt_id,intent["intent_id"],generation,seq))
            self.connection.execute("UPDATE outbox SET status='started',route='dispatch' WHERE intent_id=?",(intent["intent_id"],)); self.connection.commit()
        except Exception: self.connection.rollback(); raise
        if crash_point=="after_attempt": raise CrashInjected("after_attempt")
        try: result=self.adapter.apply(intent,generation)
        except (AdapterConflictError,AdapterStaleFenceError) as error: raise ConflictError(str(error)) from error
        if crash_point=="after_external_success": raise CrashInjected("after_external_success")
        outcome=result["outcome"]
        if outcome in ("confirmed_success","confirmed_failure"):
            return self._record_receipt(token,run_id,intent,generation,outcome)
        self._begin()
        try:
            self._check_token(token)
            if outcome=="transient":
                self.connection.execute("UPDATE attempts SET status='transient' WHERE attempt_id=?",(attempt_id,)); self.connection.execute("UPDATE outbox SET status='pending',route='retry' WHERE intent_id=?",(intent["intent_id"],)); route="retry"
            else:
                self.connection.execute("UPDATE attempts SET status='unknown' WHERE attempt_id=?",(attempt_id,)); self.connection.execute("UPDATE outbox SET status='reconcile',route='reconcile' WHERE intent_id=?",(intent["intent_id"],)); route="reconcile"
            self.connection.commit(); return {"outcome":outcome,"route":route}
        except Exception: self.connection.rollback(); raise

    def reconcile_next(self, token):
        run_id,generation=self._check_token(token); row=self._next(run_id)
        if row is None: return "nothing_pending"
        intent=json.loads(row["intent_json"])
        try: result=self.adapter.query(intent,generation)
        except (AdapterConflictError,AdapterStaleFenceError) as error: raise ConflictError(str(error)) from error
        if result=="confirmed_success": self._record_receipt(token,run_id,intent,generation,result)
        elif result=="not_applied":
            self._begin()
            try:
                self._check_token(token)
                self.connection.execute("UPDATE attempts SET status='reconciled_not_applied' WHERE intent_id=? AND status IN ('started','unknown')",(intent["intent_id"],)); self.connection.execute("UPDATE outbox SET status='pending',route='dispatch' WHERE intent_id=?",(intent["intent_id"],)); self.connection.commit()
            except Exception: self.connection.rollback(); raise
        return result

    def receipts(self, run_id):
        return [json.loads(row[0]) for row in self.connection.execute("SELECT r.receipt_json FROM receipts r JOIN intents i USING(intent_id) WHERE i.run_id=? ORDER BY i.intent_id",(run_id,))]

    def reconcile_receipt(self, token, receipt):
        run_id,_=self._check_token(token); row=self.connection.execute("SELECT receipt_json FROM receipts r JOIN intents i USING(intent_id) WHERE i.run_id=? AND r.intent_id=?",(run_id,receipt["intent_id"])).fetchone()
        if row is None: raise ConflictError("unknown receipt")
        if canonical_bytes(json.loads(row[0])) != canonical_bytes(receipt): raise ConflictError("receipt conflict")
        return receipt["outcome"]

    def request_interrupt(self, token, kind):
        if kind not in ("cancel","timeout","budget_exhausted"): raise ValueError(kind)
        run_id,_=self._check_token(token); self._begin()
        try:
            self._check_token(token); row=self._row(run_id)
            if row["status"]!="active": raise HarnessError("terminal run does not accept interrupts")
            if row["pending_interrupt"] is not None:
                if row["pending_interrupt"]==kind:
                    self.connection.rollback(); return kind
                raise ConflictError("different interrupt already pending")
            self.connection.execute("UPDATE runs SET pending_interrupt=? WHERE run_id=?",(kind,run_id)); self.connection.commit(); return kind
        except Exception: self.connection.rollback(); raise

    def honor_interrupt(self, token):
        run_id,_=self._check_token(token); row=self._row(run_id)
        if row["pending_interrupt"] is None: return row["status"]
        if self._next(run_id) is not None: raise ReconciliationRequired("effect pending")
        status={"cancel":"cancelled","timeout":"timed_out","budget_exhausted":"budget_exhausted"}[row["pending_interrupt"]]
        self._begin()
        try:
            self._check_token(token); self.connection.execute("UPDATE runs SET status=?,pending_interrupt=NULL WHERE run_id=?",(status,run_id)); self.connection.commit(); return status
        except Exception: self.connection.rollback(); raise

    def record_round(self, token, evidence_digest, *, meaningful_gain):
        if not DIGEST_RE.fullmatch(evidence_digest): raise ValueError("invalid evidence digest")
        run_id,_=self._check_token(token); run=self._row(run_id)
        if run["status"]!="active" or run["pending_interrupt"] is not None: raise HarnessError("run does not accept rounds")
        checkpoint=self.load_checkpoint(run_id); count=0 if meaningful_gain else int(checkpoint.get("no_progress_count",0))+1
        checkpoint.update({"no_progress_count":count,"last_evidence_digest":evidence_digest})
        self._begin()
        try:
            self._check_token(token); run=self._row(run_id)
            if run["status"]!="active" or run["pending_interrupt"] is not None: raise HarnessError("run does not accept rounds")
            self._checkpoint(run_id,checkpoint)
            if count>=3:
                pending=self.connection.execute("SELECT COUNT(*) FROM outbox o JOIN intents i USING(intent_id) WHERE i.run_id=? AND o.status!='done'",(run_id,)).fetchone()[0]
                if pending:
                    self.connection.execute("UPDATE runs SET pending_interrupt=COALESCE(pending_interrupt,'budget_exhausted') WHERE run_id=?",(run_id,))
                else:
                    self.connection.execute("UPDATE runs SET status='budget_exhausted' WHERE run_id=?",(run_id,))
            self.connection.commit(); return count
        except Exception: self.connection.rollback(); raise

    def run_status(self, run_id): return self._row(run_id)["status"]
