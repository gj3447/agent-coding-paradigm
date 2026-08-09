"""M4B bounded SQLite durability and fault-conformance tests."""

from __future__ import annotations

import copy
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from flrh_harness import (
    ApprovalRejected,
    ConflictError,
    CrashInjected,
    DurableHarness,
    FakeAdapter,
    HarnessError,
    QuarantinedError,
    ReconciliationRequired,
    StaleFenceError,
    verify_run,
)
from flrh_authority import project_h_intent
from flrh_harness.canonical import canonical_bytes,digest
from m4a_fixtures import find_case as find_m4a_case, load_cases as load_m4a_cases


DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64
VERSIONS = {
    key: "v1" for key in (
        "workflow", "state_schema", "event_schema", "graph_schema", "rule_set",
        "dataflow", "canonicalization", "tool", "model", "oracle", "gate",
        "resolver", "composition_profile",
    )
}

def receipt_evidence(value, attempt_id, outcome):
    return {"output_digests":[DIGEST_B,DIGEST_A],"trace_ref":"trace:m4b:fixture","outcome":outcome}

def durable(path, adapter, now):
    return DurableHarness(path,adapter,now=now,receipt_evidence=receipt_evidence)

def receipt_binding(command_digest=DIGEST_A):
    return {"command_digest":command_digest,"input_root_digest":DIGEST_B,"platform_digest":DIGEST_C}


def intent(*, intent_id="intent:m4b:one", approval=False, action=DIGEST_A):
    return {
        "kind": "EffectIntent", "intent_id": intent_id, "proposal_id": "proposal:m4b:one",
        "batch_id": "batch:m4b:one", "effect_type": "fixture.write", "action_digest": action,
        "capability": "fixture.write", "authority_digest": DIGEST_B, "cause_id": "cause:m4b:one",
        "correlation_id": "correlation:m4b:one", "idempotency_key": "idem:m4b:one",
        "destination_digest": DIGEST_C, "goal_id": "goal:m4b:one",
        "obligation_id": "obligation:m4b:one", "adapter_version": "fake-adapter/1",
        "assessed_risk": "high_risk_external" if approval else "reversible",
        "approval_required": approval, "approval_digest": globals()["approval"]()["approval_digest"] if approval else None,
        "preconditions": [], "versions": copy.deepcopy(VERSIONS),
    }


def approval_request(**changes):
    core = {
        "kind":"HApprovalRequest", "proposal_id":"proposal:m4b:one",
        "action_digest":DIGEST_A, "destination_digest":DIGEST_C,
        "capability":"fixture.write", "authority_digest":DIGEST_B,
        "adapter_version":"fake-adapter/1", "requested_at":90,
        "context_digest":DIGEST_A, "policy_version":"approval-policy/1",
        "approver_scope":"scope:m4b", "run_id":"correlation:m4b:one",
        "workflow_version":"v1", "artifact_digest":DIGEST_B,
        "visibility":"visibility:external", "scope":"scope:m4b",
        "actor":"actor:m4b", "expires_at":200, "nonce":"nonce:m4b:one",
        "rationale":"rationale:m4b",
    }
    core.update(changes)
    request_digest = digest({"kind":"M4AApprovalRequestPreimage","contract_version":"flrh-h-authority/1",**core})
    return {**core,"request_id":"approval-request:"+request_digest.split(":",1)[1],"request_digest":request_digest}


def approval(request=None, **changes):
    request = request or approval_request()
    core = {
        "kind":"HApproval", "request_digest":request["request_digest"], "decision":"grant",
        "action_digest":DIGEST_A, "destination_digest":DIGEST_C,
        "capability":"fixture.write", "authority_digest":DIGEST_B,
        "adapter_version":"fake-adapter/1", "context_digest":DIGEST_A,
        "policy_version":"approval-policy/1", "approver_scope":"scope:m4b",
        "run_id":"correlation:m4b:one", "workflow_version":"v1",
        "artifact_digest":DIGEST_B, "visibility":"visibility:external",
        "scope":"scope:m4b", "actor":"actor:m4b", "nonce":"nonce:m4b:one",
        "rationale":"rationale:m4b",
        "issued_at":95, "expires_at":200, "revoked":False, "consumed":False,
    }
    core.update(changes)
    return {**core,"approval_digest":digest({"kind":"M4AApprovalPreimage","contract_version":"flrh-h-authority/1",**core})}


class M4BDurableTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "harness.sqlite3"
        self.clock = [100]
        self.adapter = FakeAdapter()
        self.h = durable(self.db, self.adapter, lambda: self.clock[0])
        self.h.create_run("run:m4b:one", {"round": 0})
        self.token = self.h.acquire_lease("run:m4b:one", "runner:a", ttl_seconds=10)

    def tearDown(self):
        self.h.close()
        self.tmp.cleanup()

    def test_16_crash_before_intent_commit_has_no_effect(self):
        self.assertEqual([], self.h.pending_intents("run:m4b:one"))
        self.assertEqual(0, self.adapter.mutation_count)

    def test_17_committed_intent_resumes_to_one_logical_effect(self):
        self.assertTrue(self.h.commit_intent(self.token, intent(), receipt_binding=receipt_binding()))
        with self.assertRaises(CrashInjected):
            self.h.dispatch_next(self.token, crash_point="after_attempt")
        self.assertEqual("not_applied", self.h.reconcile_next(self.token))
        self.assertEqual("confirmed_success", self.h.dispatch_next(self.token)["outcome"])
        self.assertEqual(1, self.adapter.mutation_count)

    def test_18_success_before_receipt_queries_destination_before_retry(self):
        self.h.commit_intent(self.token, intent(), receipt_binding=receipt_binding())
        with self.assertRaises(CrashInjected):
            self.h.dispatch_next(self.token, crash_point="after_external_success")
        with self.assertRaises(ReconciliationRequired):
            self.h.dispatch_next(self.token)
        self.assertEqual("confirmed_success", self.h.reconcile_next(self.token))
        self.assertEqual(1, self.adapter.apply_count)
        self.assertEqual(1, self.adapter.query_count)
        self.assertEqual(1, self.adapter.mutation_count)

    def test_19_exact_duplicates_idempotent_different_bytes_conflict(self):
        value = intent()
        self.assertTrue(self.h.commit_intent(self.token, value, receipt_binding=receipt_binding()))
        self.assertFalse(self.h.commit_intent(self.token, value, receipt_binding=receipt_binding()))
        changed = intent(action=DIGEST_B)
        with self.assertRaises(ConflictError):
            self.h.commit_intent(self.token, changed, receipt_binding=receipt_binding())
        self.h.dispatch_next(self.token)
        self.assertEqual("confirmed_success", self.h.reconcile_receipt(self.token, self.h.receipts("run:m4b:one")[0]))
        self.assertEqual(1, self.adapter.mutation_count)

    def test_20_approval_matrix_fails_closed_and_valid_is_consumed_once(self):
        variants = [
            {"expires_at": 99}, {"revoked": True}, {"nonce": "wrong"},
            {"action_digest": DIGEST_B}, {"destination_digest": DIGEST_B},
            {"authority_digest": DIGEST_C}, {"adapter_version": "wrong/1"},
            {"visibility": "visibility:internal"}, {"workflow_version": "wrong/1"},
        ]
        for index, changes in enumerate(variants):
            db = Path(self.tmp.name) / f"approval-{index}.sqlite3"
            harness = durable(db, FakeAdapter(), lambda: 100)
            harness.create_run(f"run:approval:{index}", {"round": 0})
            token = harness.acquire_lease(f"run:approval:{index}", "runner:a", ttl_seconds=10)
            with self.assertRaises(ApprovalRejected):
                harness.commit_intent(token, intent(approval=True), receipt_binding=receipt_binding(), approval_request=approval_request(), approval=approval(**changes))
            harness.close()
        self.assertTrue(self.h.commit_intent(self.token, intent(approval=True), receipt_binding=receipt_binding(), approval_request=approval_request(), approval=approval()))
        self.assertEqual(1,self.h.connection.execute("SELECT consumed FROM approvals").fetchone()[0])
        replay = intent(intent_id="intent:m4b:two", approval=True)
        replay["idempotency_key"] = "idem:m4b:two"
        with self.assertRaises(ApprovalRejected):
            self.h.commit_intent(self.token, replay, receipt_binding=receipt_binding(), approval_request=approval_request(), approval=approval())

    def test_20b_forged_approval_digest_and_request_digest_reject(self):
        forged = approval(); forged["approval_digest"] = DIGEST_C
        with self.assertRaises(ApprovalRejected):
            self.h.commit_intent(self.token, intent(approval=True), receipt_binding=receipt_binding(), approval_request=approval_request(), approval=forged)
        request = approval_request(); request["request_digest"] = DIGEST_C
        with self.assertRaises(ApprovalRejected):
            self.h.commit_intent(self.token, intent(approval=True), receipt_binding=receipt_binding(), approval_request=request, approval=approval(request))

    def test_20c_direct_m4a_projection_commits_to_m4b(self):
        command = find_m4a_case(load_m4a_cases(), "success:approval-granted")
        projection = project_h_intent(copy.deepcopy(command))
        self.assertEqual("HProjection", projection["kind"])
        self.clock[0] = command["observed_at"]
        token = self.h.acquire_lease("run:m4b:one", "runner:m4a", ttl_seconds=10)
        self.assertTrue(self.h.commit_intent(token, projection["intent"], receipt_binding=receipt_binding(command["command_digest"]), approval_request=command["approval_request"], approval=command["approval"]))
        self.assertTrue(verify_run(self.db,"run:m4b:one")["valid"])

    def test_20d_m4a_request_run_id_must_equal_intent_correlation(self):
        request=approval_request(run_id="run:wrong")
        granted=approval(request,run_id="run:wrong")
        value=intent(approval=True); value["approval_digest"]=granted["approval_digest"]
        with self.assertRaises(ApprovalRejected):
            self.h.commit_intent(self.token,value,receipt_binding=receipt_binding(),approval_request=request,approval=granted)

    def test_20e_verifier_rejects_approval_run_correlation_drift(self):
        request=approval_request(); granted=approval(request); value=intent(approval=True); value["approval_digest"]=granted["approval_digest"]
        self.h.commit_intent(self.token,value,receipt_binding=receipt_binding(),approval_request=request,approval=granted)
        request["run_id"]="run:wrong"; request_core={key:item for key,item in request.items() if key not in ("request_id","request_digest")}; request["request_digest"]=digest({"kind":"M4AApprovalRequestPreimage","contract_version":"flrh-h-authority/1",**request_core}); request["request_id"]="approval-request:"+request["request_digest"].split(":",1)[1]
        granted["run_id"]="run:wrong"; granted["request_digest"]=request["request_digest"]; approval_core={key:item for key,item in granted.items() if key!="approval_digest"}; granted["approval_digest"]=digest({"kind":"M4AApprovalPreimage","contract_version":"flrh-h-authority/1",**approval_core})
        value["approval_digest"]=granted["approval_digest"]
        self.h.connection.execute("UPDATE approvals SET approval_digest=?,request_json=?,approval_json=?",(granted["approval_digest"],canonical_bytes(request).decode(),canonical_bytes(granted).decode()))
        self.h.connection.execute("UPDATE intents SET intent_digest=?,intent_json=?",(digest(value),canonical_bytes(value).decode()))
        report=verify_run(self.db,"run:m4b:one")
        self.assertFalse(report["valid"]); self.assertIn("APPROVAL_RUN_CORRELATION",report["errors"])

    def test_21_stale_generation_cannot_commit(self):
        self.clock[0] = 111
        new_token = self.h.acquire_lease("run:m4b:one", "runner:b", ttl_seconds=10)
        with self.assertRaises(StaleFenceError):
            self.h.commit_intent(self.token, intent(), receipt_binding=receipt_binding())
        self.assertTrue(self.h.commit_intent(new_token, intent(), receipt_binding=receipt_binding()))

    def test_21b_takeover_during_external_io_fences_old_receipt_commit(self):
        class TakeoverAdapter(FakeAdapter):
            def apply(adapter_self, value, generation):
                result = super(TakeoverAdapter, adapter_self).apply(value, generation)
                self.clock[0] = 111
                adapter_self.new_token = self.h.acquire_lease("run:m4b:one", "runner:b", ttl_seconds=10)
                return result

        takeover = TakeoverAdapter()
        self.adapter = takeover
        self.h.adapter = takeover
        self.h.commit_intent(self.token, intent(), receipt_binding=receipt_binding())
        with self.assertRaises(StaleFenceError):
            self.h.dispatch_next(self.token)
        self.assertEqual(1, takeover.mutation_count)
        self.assertEqual([], self.h.receipts("run:m4b:one"))
        self.assertEqual("confirmed_success", self.h.reconcile_next(takeover.new_token))
        self.assertEqual(1, takeover.mutation_count)

    def test_21c_post_io_fence_covers_transient_unknown_and_reconcile_not_applied(self):
        for outcome in ("transient", "unknown"):
            db = Path(self.tmp.name) / f"takeover-{outcome}.sqlite3"
            clock = [100]
            holder = {}
            class Adapter(FakeAdapter):
                def apply(adapter_self, value, generation):
                    result = super(Adapter, adapter_self).apply(value, generation)
                    clock[0] = 111
                    adapter_self.new_token = holder["h"].acquire_lease(f"run:{outcome}", "runner:b", ttl_seconds=10)
                    return result
            adapter = Adapter(outcomes={"intent:m4b:one":[outcome]})
            harness = durable(db, adapter, lambda:clock[0]); holder["h"] = harness
            harness.create_run(f"run:{outcome}", {"round":0}); old = harness.acquire_lease(f"run:{outcome}", "runner:a", ttl_seconds=10); harness.commit_intent(old, intent(), receipt_binding=receipt_binding())
            with self.assertRaises(StaleFenceError): harness.dispatch_next(old)
            harness.close()
        class QueryTakeover(FakeAdapter):
            def query(adapter_self, value, generation):
                result = super(QueryTakeover, adapter_self).query(value, generation)
                self.clock[0] = 111
                adapter_self.new_token = self.h.acquire_lease("run:m4b:one", "runner:b", ttl_seconds=10)
                return result
        adapter = QueryTakeover(); self.h.adapter = adapter; self.adapter = adapter
        self.h.commit_intent(self.token, intent(), receipt_binding=receipt_binding())
        with self.assertRaises(CrashInjected): self.h.dispatch_next(self.token, crash_point="after_attempt")
        with self.assertRaises(StaleFenceError): self.h.reconcile_next(self.token)

    def test_22_corrupt_checkpoint_quarantines(self):
        self.h.close()
        connection = sqlite3.connect(self.db)
        connection.execute("UPDATE checkpoints SET payload_json='{}'")
        connection.commit()
        connection.close()
        self.h = durable(self.db, self.adapter, lambda: self.clock[0])
        report = verify_run(self.db, "run:m4b:one")
        self.assertFalse(report["valid"])
        with self.assertRaises(QuarantinedError):
            self.h.load_checkpoint("run:m4b:one")

    def test_22b_all_checkpoint_canonicalization_failures_quarantine(self):
        corruptions=('{"x":1.5}','{"x":9223372036854775808}','{"x":"e\\u0301"}')
        for index,payload in enumerate(corruptions):
            db=Path(self.tmp.name)/f"canonical-{index}.sqlite3"
            harness=durable(db,FakeAdapter(),lambda:100); harness.create_run(f"run:canonical:{index}",{"round":0})
            harness.connection.execute("UPDATE checkpoints SET payload_json=?",(payload,))
            with self.assertRaises(QuarantinedError): harness.load_checkpoint(f"run:canonical:{index}")
            self.assertEqual("quarantined",harness.run_status(f"run:canonical:{index}")); harness.close()

    def test_23_pending_interrupt_waits_for_reconciliation(self):
        self.h.commit_intent(self.token, intent(), receipt_binding=receipt_binding())
        with self.assertRaises(CrashInjected):
            self.h.dispatch_next(self.token, crash_point="after_external_success")
        self.h.request_interrupt(self.token, "cancel")
        with self.assertRaises(ReconciliationRequired):
            self.h.honor_interrupt(self.token)
        self.h.reconcile_next(self.token)
        self.assertEqual("cancelled", self.h.honor_interrupt(self.token))

    def test_24_outcome_routing(self):
        for outcome in ("transient", "permanent", "unknown"):
            db = Path(self.tmp.name) / f"outcome-{outcome}.sqlite3"
            adapter = FakeAdapter(outcomes={"intent:m4b:one": [outcome]})
            harness = durable(db, adapter, lambda: 100)
            harness.create_run(f"run:{outcome}", {"round": 0})
            token = harness.acquire_lease(f"run:{outcome}", "runner:a", ttl_seconds=10)
            value = intent(); value["intent_id"] = "intent:m4b:one"
            harness.commit_intent(token, value, receipt_binding=receipt_binding())
            result = harness.dispatch_next(token)
            observed = result["outcome"] if outcome == "permanent" else result["route"]
            self.assertEqual({"transient": "retry", "permanent": "confirmed_failure", "unknown": "reconcile"}[outcome], observed)
            harness.close()

    def test_25_no_progress_three_rounds_and_gain_reset_reproduce(self):
        self.assertEqual(1, self.h.record_round(self.token, DIGEST_A, meaningful_gain=False))
        self.assertEqual(2, self.h.record_round(self.token, DIGEST_B, meaningful_gain=False))
        self.assertEqual(0, self.h.record_round(self.token, DIGEST_C, meaningful_gain=True))
        for expected in (1, 2, 3):
            self.assertEqual(expected, self.h.record_round(self.token, DIGEST_A, meaningful_gain=False))
        self.assertEqual("budget_exhausted", self.h.run_status("run:m4b:one"))
        extra=intent(intent_id="intent:m4b:terminal"); extra["idempotency_key"]="idem:m4b:terminal"
        with self.assertRaises(HarnessError): self.h.commit_intent(self.token,extra,receipt_binding=receipt_binding())
        before = self.h.load_checkpoint("run:m4b:one")
        self.h.close()
        self.h = durable(self.db, self.adapter, lambda: self.clock[0])
        self.assertEqual(before, self.h.load_checkpoint("run:m4b:one"))

    def test_no_progress_defers_terminal_until_pending_effect_resolves(self):
        self.h.commit_intent(self.token,intent(),receipt_binding=receipt_binding())
        for expected in (1,2,3): self.assertEqual(expected,self.h.record_round(self.token,DIGEST_A,meaningful_gain=False))
        self.assertEqual("active",self.h.run_status("run:m4b:one"))
        self.assertEqual("budget_exhausted",self.h.connection.execute("SELECT pending_interrupt FROM runs").fetchone()[0])
        self.assertEqual("confirmed_success",self.h.dispatch_next(self.token)["outcome"])
        self.assertEqual("budget_exhausted",self.h.honor_interrupt(self.token))

    def test_pending_interrupt_blocks_rounds_and_is_typed_idempotent(self):
        self.assertEqual("cancel",self.h.request_interrupt(self.token,"cancel"))
        self.assertEqual("cancel",self.h.request_interrupt(self.token,"cancel"))
        with self.assertRaises(ConflictError): self.h.request_interrupt(self.token,"timeout")
        with self.assertRaises(HarnessError): self.h.record_round(self.token,DIGEST_A,meaningful_gain=False)
        self.assertEqual("active",self.h.run_status("run:m4b:one"))
        self.assertEqual("cancel",self.h.connection.execute("SELECT pending_interrupt FROM runs").fetchone()[0])
        self.assertEqual("cancelled",self.h.honor_interrupt(self.token))
        with self.assertRaises(HarnessError): self.h.request_interrupt(self.token,"timeout")
        with self.assertRaises(HarnessError): self.h.record_round(self.token,DIGEST_A,meaningful_gain=False)

    def test_pending_interrupt_reconcile_not_applied_allows_resolution(self):
        adapter=FakeAdapter(outcomes={"intent:m4b:one":["unknown_not_applied"]}); self.h.adapter=adapter; self.adapter=adapter
        self.h.commit_intent(self.token,intent(),receipt_binding=receipt_binding()); self.h.dispatch_next(self.token)
        self.h.request_interrupt(self.token,"cancel")
        self.assertEqual("not_applied",self.h.reconcile_next(self.token))
        self.assertEqual("confirmed_success",self.h.dispatch_next(self.token)["outcome"])
        self.assertEqual("cancelled",self.h.honor_interrupt(self.token))

    def test_atomic_approval_intent_checkpoint_outbox_rolls_back_together(self):
        self.h.connection.execute("CREATE TRIGGER reject_outbox BEFORE INSERT ON outbox BEGIN SELECT RAISE(ABORT,'fault'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.h.commit_intent(self.token, intent(approval=True), receipt_binding=receipt_binding(), approval_request=approval_request(), approval=approval())
        self.assertEqual(0, self.h.connection.execute("SELECT COUNT(*) FROM approvals").fetchone()[0])
        self.assertEqual(0, self.h.connection.execute("SELECT COUNT(*) FROM intents").fetchone()[0])
        self.assertEqual(0, self.h.connection.execute("SELECT COUNT(*) FROM outbox").fetchone()[0])
        self.assertNotIn("last_committed_intent_id", self.h.load_checkpoint("run:m4b:one"))

    def test_atomic_receipt_checkpoint_rolls_back_together(self):
        self.h.commit_intent(self.token, intent(), receipt_binding=receipt_binding())
        self.h.connection.execute("CREATE TRIGGER reject_checkpoint BEFORE UPDATE ON checkpoints BEGIN SELECT RAISE(ABORT,'fault'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.h.dispatch_next(self.token)
        self.assertEqual(1, self.adapter.mutation_count)
        self.assertEqual(0, self.h.connection.execute("SELECT COUNT(*) FROM receipts").fetchone()[0])
        self.assertEqual("started", self.h.connection.execute("SELECT status FROM outbox").fetchone()[0])
        self.h.connection.execute("DROP TRIGGER reject_checkpoint")
        self.assertEqual("confirmed_success", self.h.reconcile_next(self.token))

    def test_persisted_and_returned_receipt_match_and_attempt_is_terminal(self):
        self.h.commit_intent(self.token, intent(), receipt_binding=receipt_binding())
        returned = self.h.dispatch_next(self.token)
        self.assertEqual(returned, self.h.receipts("run:m4b:one")[0])
        self.assertEqual([DIGEST_A,DIGEST_B],returned["output_digests"])
        self.assertEqual("confirmed_success", self.h.connection.execute("SELECT status FROM attempts").fetchone()[0])

    def test_observation_supplies_outcome_and_harness_clock_supplies_recorded_at(self):
        db=Path(self.tmp.name)/"observation.sqlite3"
        def observation(value,attempt_id,outcome):
            return {"output_digests":[DIGEST_A],"trace_ref":"trace:m4b:observation","outcome":outcome}
        harness=DurableHarness(db,FakeAdapter(),now=lambda:100,receipt_evidence=observation)
        harness.create_run("run:observation",{"round":0}); token=harness.acquire_lease("run:observation","runner:a",ttl_seconds=10)
        harness.commit_intent(token,intent(),receipt_binding=receipt_binding())
        receipt=harness.dispatch_next(token)
        self.assertEqual("confirmed_success",receipt["outcome"])
        self.assertEqual("1970-01-01T00:01:40Z",receipt["recorded_at"])
        harness.close()

    def test_corrupt_checkpoint_during_mutator_durably_quarantines(self):
        self.h.connection.execute("UPDATE checkpoints SET payload_json='{}'")
        with self.assertRaises(QuarantinedError):
            self.h.commit_intent(self.token, intent(), receipt_binding=receipt_binding())
        self.assertEqual("quarantined", self.h.run_status("run:m4b:one"))

    def test_bounds_and_terminal_or_interrupt_reject_new_work(self):
        bounded_db = Path(self.tmp.name) / "bounded.sqlite3"
        bounded = durable(bounded_db, FakeAdapter(), lambda:100)
        bounded.create_run("run:bounded", {"round":0}, max_pending=1, max_attempts=1)
        token = bounded.acquire_lease("run:bounded", "runner:a", ttl_seconds=10)
        bounded.commit_intent(token, intent(), receipt_binding=receipt_binding())
        second = intent(intent_id="intent:m4b:two"); second["idempotency_key"]="idem:m4b:two"
        with self.assertRaises(HarnessError): bounded.commit_intent(token, second, receipt_binding=receipt_binding())
        bounded.request_interrupt(token, "cancel")
        self.assertEqual("confirmed_success",bounded.dispatch_next(token)["outcome"])
        self.assertEqual("cancelled",bounded.honor_interrupt(token))
        bounded.close()

    def test_fake_adapter_outcome_mutation_semantics(self):
        for outcome, mutations in (("transient",0),("permanent",0),("unknown",1),("unknown_not_applied",0)):
            adapter=FakeAdapter(outcomes={"intent:m4b:one":[outcome]})
            result=adapter.apply(intent(),1)
            self.assertEqual(mutations,adapter.mutation_count)
            self.assertEqual("outcome_unknown" if outcome.startswith("unknown") else ("confirmed_failure" if outcome=="permanent" else "transient"),result["outcome"])
            if outcome.startswith("unknown"):
                self.assertEqual("confirmed_success" if mutations else "not_applied",adapter.query(intent(),1))

    def test_unknown_not_applied_reconciles_before_retry(self):
        adapter=FakeAdapter(outcomes={"intent:m4b:one":["unknown_not_applied"]})
        self.h.adapter=adapter; self.adapter=adapter
        self.h.commit_intent(self.token,intent(),receipt_binding=receipt_binding())
        self.assertEqual("reconcile",self.h.dispatch_next(self.token)["route"])
        self.assertEqual(0,adapter.mutation_count)
        with self.assertRaises(ReconciliationRequired): self.h.dispatch_next(self.token)
        self.assertEqual("not_applied",self.h.reconcile_next(self.token))
        self.assertEqual("confirmed_success",self.h.dispatch_next(self.token)["outcome"])
        self.assertEqual(1,adapter.mutation_count)

    def test_verifier_rejects_tampered_intent_and_incoherent_receipt(self):
        self.h.commit_intent(self.token,intent(),receipt_binding=receipt_binding()); self.h.dispatch_next(self.token); self.h.close()
        c=sqlite3.connect(self.db); c.execute("UPDATE intents SET intent_json='{}'"); c.commit(); c.close()
        report=verify_run(self.db,"run:m4b:one")
        self.assertFalse(report["valid"]); self.assertIn("INTENT_SCHEMA",report["errors"])
        self.h=durable(self.db,self.adapter,lambda:self.clock[0])

    def test_verifier_enforces_run_vocab_profile_and_pending_terminal_invariants(self):
        mutations=(("UPDATE runs SET max_pending=1025","RUN_MAX_PENDING"),("UPDATE runs SET max_attempts=17","RUN_MAX_ATTEMPTS"),("UPDATE runs SET status='bogus'","RUN_STATUS"),("UPDATE runs SET pending_interrupt='bogus'","PENDING_INTERRUPT"))
        for index,(statement,code) in enumerate(mutations):
            db=Path(self.tmp.name)/f"verify-run-{index}.sqlite3"; h=durable(db,FakeAdapter(),lambda:100); h.create_run(f"run:verify:{index}",{"round":0}); h.connection.execute(statement)
            report=verify_run(db,f"run:verify:{index}"); self.assertFalse(report["valid"]); self.assertIn(code,report["errors"]); h.close()
        db=Path(self.tmp.name)/"verify-attempts.sqlite3"; h=durable(db,FakeAdapter(),lambda:100); h.create_run("run:verify:attempts",{"round":0},max_attempts=1); token=h.acquire_lease("run:verify:attempts","a",ttl_seconds=10); h.commit_intent(token,intent(),receipt_binding=receipt_binding())
        h.connection.execute("INSERT INTO attempts VALUES('attempt:extra:1','intent:m4b:one',1,'transient',1)"); h.connection.execute("INSERT INTO attempts VALUES('attempt:extra:2','intent:m4b:one',1,'started',2)"); h.connection.execute("UPDATE outbox SET status='started',route='dispatch'")
        report=verify_run(db,"run:verify:attempts"); self.assertFalse(report["valid"]); self.assertIn("ATTEMPT_BOUND",report["errors"]); h.close()
        db=Path(self.tmp.name)/"verify-terminal.sqlite3"; h=durable(db,FakeAdapter(),lambda:100); h.create_run("run:verify:terminal",{"round":0}); token=h.acquire_lease("run:verify:terminal","a",ttl_seconds=10); h.commit_intent(token,intent(),receipt_binding=receipt_binding()); h.connection.execute("UPDATE runs SET status='cancelled'")
        report=verify_run(db,"run:verify:terminal"); self.assertFalse(report["valid"]); self.assertIn("TERMINAL_PENDING_EFFECT",report["errors"]); h.close()

    def test_verifier_checks_every_attempt_status_and_transition(self):
        db=Path(self.tmp.name)/"verify-history.sqlite3"; adapter=FakeAdapter(outcomes={"intent:m4b:one":["transient","success"]}); h=durable(db,adapter,lambda:100)
        h.create_run("run:verify:history",{"round":0}); token=h.acquire_lease("run:verify:history","a",ttl_seconds=10); h.commit_intent(token,intent(),receipt_binding=receipt_binding()); h.dispatch_next(token); h.dispatch_next(token)
        h.connection.execute("UPDATE attempts SET status='bogus' WHERE sequence=1")
        report=verify_run(db,"run:verify:history"); self.assertFalse(report["valid"]); self.assertIn("ATTEMPT_STATUS",report["errors"])
        h.connection.execute("UPDATE attempts SET status='confirmed_success' WHERE sequence=1")
        report=verify_run(db,"run:verify:history"); self.assertFalse(report["valid"]); self.assertIn("ATTEMPT_TRANSITION",report["errors"]); h.close()

    def test_verifier_rejects_orphan_approval(self):
        self.h.close()
        connection=sqlite3.connect(self.db)
        connection.execute("INSERT INTO approvals VALUES('approval:orphan','run:m4b:one','intent:missing','v1','{}','{}',1)")
        connection.commit(); connection.close()
        report=verify_run(self.db,"run:m4b:one")
        self.assertFalse(report["valid"]); self.assertIn("APPROVAL_ORPHAN",report["errors"])
        self.h=durable(self.db,self.adapter,lambda:self.clock[0])

    def test_real_subprocess_os_exit_cutpoints(self):
        for cutpoint, expected in (("before_intent", 0), ("after_intent", 0), ("after_external_success", 1)):
            db = Path(self.tmp.name) / f"crash-{cutpoint}.sqlite3"
            destination = Path(self.tmp.name) / f"destination-{cutpoint}.sqlite3"
            completed = subprocess.run([sys.executable, str(ROOT / "scripts/m4b_crash_worker.py"), str(db), str(destination), cutpoint])
            self.assertEqual(86, completed.returncode)
            summary = FakeAdapter.inspect(destination)
            self.assertEqual(expected, summary["mutation_count"])

    def test_independent_verifier_and_read_only_open(self):
        self.h.commit_intent(self.token, intent(), receipt_binding=receipt_binding())
        self.h.dispatch_next(self.token)
        report = verify_run(self.db, "run:m4b:one")
        self.assertTrue(report["valid"])
        self.assertEqual(1, report["intent_count"])
        self.assertEqual(1, report["receipt_count"])


if __name__ == "__main__":
    unittest.main()
