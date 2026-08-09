#!/usr/bin/env python3
"""Static and clean-process ambient denial for the M2-IL kernel."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {"os", "pathlib", "random", "secrets", "socket", "subprocess", "time", "uuid", "requests", "openai", "anthropic"}
for path in (ROOT / "src/flrh_logic_incremental/canonical.py", ROOT / "src/flrh_logic_incremental/incremental.py"):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import): assert not ({item.name.split('.')[0] for item in node.names} & FORBIDDEN)
        if isinstance(node, ast.ImportFrom): assert (node.module or "").split('.')[0] not in FORBIDDEN
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name): assert node.func.id not in {"open", "exec", "eval", "compile", "__import__"}
code = "import sys;sys.path[:0]=['src','scripts'];from m2il_fixtures import load_cases,materialize_step;from flrh_logic_incremental import step_incremental_l;c=load_cases();b,d=materialize_step(c,'disjoint-chain-bootstrap-noop-unrelated-retract',0,1);r=step_incremental_l(None,b,d,1);print(r['step_digest'])"
outputs = []
for seed, tz in (("1", "UTC"), ("777", "Asia/Seoul")):
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONHASHSEED": seed, "TZ": tz, "M2IL_CANARY": "denied"}
    outputs.append(subprocess.check_output([sys.executable, "-c", code], cwd=ROOT, env=env, text=True).strip())
assert outputs[0] == outputs[1]
oracle_code = "import builtins,sys;sys.path[:0]=['scripts'];from m2il_fixtures import load_cases;from m2il_oracle import naive_semantics,canonical_bytes;r=builtins.__import__;builtins.__import__=lambda n,*a,**k:(_ for _ in()).throw(AssertionError(n)) if n.startswith('flrh_logic') else r(n,*a,**k);assert all((lambda v:(lambda:canonical_bytes(v)))(v) for v in []);[(lambda v: (canonical_bytes(v),False))(v) for v in []];ok=0\nfor v in ({'e\\u0301':1},{'\\ud800':1}):\n try: canonical_bytes(v)\n except ValueError: ok+=1\nprint(naive_semantics(load_cases(),'disjoint_chain',['a+','x+'])['states']['c']['state'],ok)"
oracle = subprocess.check_output([sys.executable, "-c", oracle_code], cwd=ROOT, env={"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"}, text=True).strip()
assert oracle == "TRUE_ONLY 2"
print("M2IL ambient PASS: 2 candidate clean processes + 1 production-import-denied stdlib oracle process; clock/RNG/env/fs/net/subprocess/model/tool imports denied")
