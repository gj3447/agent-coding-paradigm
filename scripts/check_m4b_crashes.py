#!/usr/bin/env python3
"""Exercise real os._exit cutpoints and report durable destination evidence."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]; sys.path[:0]=[str(ROOT/"src"),str(ROOT/"scripts")]
from flrh_harness import DurableHarness,FakeAdapter,verify_run
from m4b_crash_worker import binding,evidence

def main():
    results=[]
    with tempfile.TemporaryDirectory() as temporary:
        for cutpoint,expected in (("before_intent",0),("after_intent",0),("after_external_success",1)):
            base=Path(temporary); db=base/f"{cutpoint}.db"; destination=base/f"{cutpoint}-destination.db"
            completed=subprocess.run([sys.executable,str(ROOT/"scripts/m4b_crash_worker.py"),str(db),str(destination),cutpoint])
            observed=FakeAdapter.inspect(destination)["mutation_count"]
            if completed.returncode!=86 or observed!=expected: raise SystemExit(f"cutpoint failed: {cutpoint}")
            reopened=DurableHarness(db,FakeAdapter(durable_path=destination),now=lambda:111,receipt_evidence=evidence)
            token=reopened.acquire_lease("run:m4b:crash","runner:recovery",ttl_seconds=10)
            reconciliation=reopened.reconcile_next(token)
            if cutpoint=="after_intent":
                if reconciliation!="not_applied": raise SystemExit("committed intent did not reconcile not_applied")
                reopened.dispatch_next(token)
            elif cutpoint=="after_external_success" and reconciliation!="confirmed_success":
                raise SystemExit("external success was not reconciled")
            report=verify_run(db,"run:m4b:crash"); reopened.close()
            final=FakeAdapter.inspect(destination)["mutation_count"]
            expected_final=0 if cutpoint=="before_intent" else 1
            if final!=expected_final or not report["valid"]: raise SystemExit(f"recovery failed: {cutpoint}: {report}")
            results.append({"cutpoint":cutpoint,"exit_code":completed.returncode,"mutation_count_at_crash":observed,"mutation_count_after_recovery":final,"reconciliation":reconciliation,"verified":True})
    print(json.dumps({"kind":"M4BCrashReport","cutpoints":results,"passed":len(results)},separators=(",",":"),sort_keys=True))

if __name__=="__main__": main()
