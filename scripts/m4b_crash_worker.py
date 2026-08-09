#!/usr/bin/env python3
"""Subprocess crash injector. Exit 86 represents an abrupt process death."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from flrh_harness import CrashInjected, DurableHarness, FakeAdapter

DIGEST_A="sha256:"+"a"*64; DIGEST_B="sha256:"+"b"*64; DIGEST_C="sha256:"+"c"*64
VERSIONS={key:"v1" for key in ("workflow","state_schema","event_schema","graph_schema","rule_set","dataflow","canonicalization","tool","model","oracle","gate","resolver","composition_profile")}
def evidence(value,attempt_id,outcome): return {"output_digests":[DIGEST_A],"trace_ref":"trace:m4b:crash","outcome":outcome}
def binding(): return {"command_digest":DIGEST_A,"input_root_digest":DIGEST_B,"platform_digest":DIGEST_C}

def value():
    return {"kind":"EffectIntent","intent_id":"intent:m4b:crash","proposal_id":"proposal:m4b:crash","batch_id":"batch:m4b:crash","effect_type":"fixture.write","action_digest":DIGEST_A,"capability":"fixture.write","authority_digest":DIGEST_B,"cause_id":"cause:m4b:crash","correlation_id":"correlation:m4b:crash","idempotency_key":"idem:m4b:crash","destination_digest":DIGEST_C,"goal_id":"goal:m4b:crash","obligation_id":"obligation:m4b:crash","adapter_version":"fake-adapter/1","assessed_risk":"reversible","approval_required":False,"approval_digest":None,"preconditions":[],"versions":VERSIONS}

def main():
    db,destination,cutpoint=Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3]
    harness=DurableHarness(db,FakeAdapter(durable_path=destination),now=lambda:100,receipt_evidence=evidence)
    harness.create_run("run:m4b:crash",{"round":0})
    token=harness.acquire_lease("run:m4b:crash","runner:crash",ttl_seconds=10)
    if cutpoint=="before_intent": os._exit(86)
    harness.commit_intent(token,value(),receipt_binding=binding())
    if cutpoint=="after_intent": os._exit(86)
    try: harness.dispatch_next(token,crash_point="after_external_success")
    except CrashInjected: os._exit(86)
    raise SystemExit(2)

if __name__=="__main__": main()
