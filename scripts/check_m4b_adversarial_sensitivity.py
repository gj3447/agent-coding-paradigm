#!/usr/bin/env python3
"""Behavioral adversarial sensitivity cases; no source mutation is claimed."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"src")); sys.path.insert(0,str(ROOT/"scripts"))
from flrh_harness import ConflictError,DurableHarness,FakeAdapter,QuarantinedError,ReconciliationRequired,StaleFenceError,verify_run
from run_m4b_replay import intent
from run_m4b_replay import binding, evidence

def main():
    detected=[]
    with tempfile.TemporaryDirectory() as temporary:
        base=Path(temporary)
        # stale_generation_acceptance
        clock=[100]; h=DurableHarness(base/"fence.db",FakeAdapter(),now=lambda:clock[0],receipt_evidence=evidence); h.create_run("run:fence",{"round":0}); old=h.acquire_lease("run:fence","a",ttl_seconds=1); clock[0]=102; new=h.acquire_lease("run:fence","b",ttl_seconds=10)
        try: h.commit_intent(old,intent(),receipt_binding=binding())
        except StaleFenceError: detected.append("stale_generation_acceptance")
        h.close()
        # duplicate_identity_rewrite
        h=DurableHarness(base/"conflict.db",FakeAdapter(),now=lambda:100,receipt_evidence=evidence); h.create_run("run:conflict",{"round":0}); token=h.acquire_lease("run:conflict","a",ttl_seconds=10); first=intent(); h.commit_intent(token,first,receipt_binding=binding()); changed=dict(first); changed["action_digest"]="sha256:"+"d"*64
        try: h.commit_intent(token,changed,receipt_binding=binding())
        except ConflictError: detected.append("duplicate_identity_rewrite")
        h.close()
        # blind_retry_after_started
        adapter=FakeAdapter(); h=DurableHarness(base/"unknown.db",adapter,now=lambda:100,receipt_evidence=evidence); h.create_run("run:unknown",{"round":0}); token=h.acquire_lease("run:unknown","a",ttl_seconds=10); h.commit_intent(token,intent(),receipt_binding=binding())
        try: h.dispatch_next(token,crash_point="after_external_success")
        except Exception: pass
        try: h.dispatch_next(token)
        except ReconciliationRequired: detected.append("blind_retry_after_started")
        h.close()
        # corrupt_checkpoint_resume
        h=DurableHarness(base/"corrupt.db",FakeAdapter(),now=lambda:100,receipt_evidence=evidence); h.create_run("run:corrupt",{"round":0}); h.close(); c=sqlite3.connect(base/"corrupt.db"); c.execute("UPDATE checkpoints SET payload_json='{}'"); c.commit(); c.close(); h=DurableHarness(base/"corrupt.db",FakeAdapter(),now=lambda:100,receipt_evidence=evidence)
        try: h.load_checkpoint("run:corrupt")
        except QuarantinedError: detected.append("corrupt_checkpoint_resume")
        h.close()
        # receipt_only_without_checkpoint: abort checkpoint update after external success and
        # observe that receipt/outbox/attempt terminalization all roll back together.
        adapter=FakeAdapter(); h=DurableHarness(base/"atomic.db",adapter,now=lambda:100,receipt_evidence=evidence); h.create_run("run:atomic",{"round":0}); token=h.acquire_lease("run:atomic","a",ttl_seconds=10); h.commit_intent(token,intent(),receipt_binding=binding())
        h.connection.execute("CREATE TRIGGER reject_checkpoint BEFORE UPDATE ON checkpoints BEGIN SELECT RAISE(ABORT,'fault'); END")
        try: h.dispatch_next(token)
        except sqlite3.IntegrityError: pass
        counts=(h.connection.execute("SELECT COUNT(*) FROM receipts").fetchone()[0],h.connection.execute("SELECT status FROM outbox").fetchone()[0],h.connection.execute("SELECT status FROM attempts").fetchone()[0])
        if counts==(0,"started","started"): detected.append("receipt_only_without_checkpoint")
        h.close()
        # retry_exhaustion_handoff_bypass
        class UnprovenQueryAdapter(FakeAdapter):
            def query(self,value,generation):
                self._increment("query_count")
                return "outcome_unknown"
        adapter=UnprovenQueryAdapter(outcomes={"intent:m4b:replay":["transient"]}); h=DurableHarness(base/"retry-exhausted.db",adapter,now=lambda:100,receipt_evidence=evidence); h.create_run("run:retry-exhausted",{"round":0},max_attempts=1); token=h.acquire_lease("run:retry-exhausted","a",ttl_seconds=10); h.commit_intent(token,intent(),receipt_binding=binding()); h.dispatch_next(token)
        try: h.dispatch_next(token)
        except ReconciliationRequired: pass
        first=h.reconcile_next(token); second=h.reconcile_next(token)
        try: h.dispatch_next(token)
        except ReconciliationRequired:
            state=tuple(h.connection.execute("SELECT status,route FROM outbox").fetchone())
            if first==second=="human_reconciliation" and state==("reconcile","human_reconciliation") and adapter.apply_count==adapter.query_count==1:
                detected.append("retry_exhaustion_handoff_bypass")
        h.close()
        # retry_exhaustion_receipt_before_query
        adapter=FakeAdapter(outcomes={"intent:m4b:replay":["transient"]}); h=DurableHarness(base/"retry-receipt-order.db",adapter,now=lambda:100,receipt_evidence=evidence); h.create_run("run:retry-order",{"round":0},max_attempts=1); token=h.acquire_lease("run:retry-order","a",ttl_seconds=10); candidate=intent(); h.commit_intent(token,candidate,receipt_binding=binding()); h.dispatch_next(token)
        try: h.dispatch_next(token)
        except ReconciliationRequired: pass
        try: h._record_receipt(token,"run:retry-order",candidate,1,"confirmed_failure",terminal_route="retry_exhausted",preserve_attempt_status=True)
        except ConflictError:
            state=tuple(h.connection.execute("SELECT status,route FROM outbox").fetchone())
            if adapter.query_count==0 and state==("reconcile","retry_exhausted") and not h.receipts("run:retry-order") and verify_run(base/"retry-receipt-order.db","run:retry-order")["valid"]:
                detected.append("retry_exhaustion_receipt_before_query")
        h.close()
    expected={"stale_generation_acceptance","duplicate_identity_rewrite","blind_retry_after_started","corrupt_checkpoint_resume","receipt_only_without_checkpoint","retry_exhaustion_handoff_bypass","retry_exhaustion_receipt_before_query"}
    if set(detected)!=expected: raise SystemExit(f"undetected: {sorted(expected-set(detected))}")
    print(json.dumps({"kind":"M4BAdversarialSensitivityReport","adversarial_sensitivity_cases_detected":len(detected),"cases":sorted(detected)},separators=(",",":"),sort_keys=True))

if __name__=="__main__": main()
