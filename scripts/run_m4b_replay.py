#!/usr/bin/env python3
"""Run the frozen successful M4B replay and emit one canonical JSON line."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from flrh_harness import DurableHarness,FakeAdapter,verify_run

A="sha256:"+"a"*64; B="sha256:"+"b"*64; C="sha256:"+"c"*64
VERSIONS={key:"v1" for key in ("workflow","state_schema","event_schema","graph_schema","rule_set","dataflow","canonicalization","tool","model","oracle","gate","resolver","composition_profile")}
def evidence(value,attempt_id,outcome): return {"output_digests":[A],"trace_ref":"trace:m4b:replay","outcome":outcome}
def binding(): return {"command_digest":A,"input_root_digest":B,"platform_digest":C}

def intent():
    return {"kind":"EffectIntent","intent_id":"intent:m4b:replay","proposal_id":"proposal:m4b:replay","batch_id":"batch:m4b:replay","effect_type":"fixture.write","action_digest":A,"capability":"fixture.write","authority_digest":B,"cause_id":"cause:m4b:replay","correlation_id":"correlation:m4b:replay","idempotency_key":"idem:m4b:replay","destination_digest":C,"goal_id":"goal:m4b:replay","obligation_id":"obligation:m4b:replay","adapter_version":"fake-adapter/1","assessed_risk":"reversible","approval_required":False,"approval_digest":None,"preconditions":[],"versions":VERSIONS}

def run():
    with tempfile.TemporaryDirectory() as temporary:
        path=Path(temporary)/"run.sqlite3"; adapter=FakeAdapter(); harness=DurableHarness(path,adapter,now=lambda:100,receipt_evidence=evidence)
        harness.create_run("run:m4b:replay",{"round":0}); token=harness.acquire_lease("run:m4b:replay","runner:replay",ttl_seconds=10)
        harness.commit_intent(token,intent(),receipt_binding=binding()); harness.dispatch_next(token)
        result={"kind":"M4BReplaySummary","status":harness.run_status("run:m4b:replay"),"adapter":{"apply_count":adapter.apply_count,"query_count":adapter.query_count,"mutation_count":adapter.mutation_count},"verification":verify_run(path,"run:m4b:replay")}
        harness.close(); return result

if __name__=="__main__":
    print(json.dumps(run(),ensure_ascii=False,separators=(",",":"),sort_keys=True))
