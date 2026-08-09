#!/usr/bin/env python3
"""Deterministic frozen M2-IL sequence replay."""

from __future__ import annotations
import json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from flrh_logic_incremental import step_incremental_l
from m2il_fixtures import load_cases, materialize_step
c=load_cases(); rows=[]
for sequence in c["sequences"]:
    checkpoint=None
    for index in range(len(sequence["steps"])):
        bundle,deltas=materialize_step(c,sequence["id"],index,index+1); result=step_incremental_l(checkpoint,bundle,deltas,index+1)
        rows.append({"sequence":sequence["id"],"prefix":index+1,"kind":result["kind"],"step_digest":result.get("step_digest"),"candidate_hits":result.get("reuse_receipt",{}).get("candidate_cache_hits")})
        checkpoint=result.get("next_checkpoint")
print(json.dumps(rows,sort_keys=True,separators=(",",":")))
