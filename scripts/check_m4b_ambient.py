#!/usr/bin/env python3
"""Fail closed on ambient clock, randomness, process, or network imports in M4B."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FILES=sorted((ROOT/"src/flrh_harness").glob("*.py"))
FORBIDDEN={"time","datetime","random","secrets","uuid","os","subprocess","socket","requests","urllib","http","asyncio"}

def main():
    violations=[]; imports=0
    for path in FILES:
        tree=ast.parse(path.read_text(encoding="utf-8"),filename=str(path))
        for node in ast.walk(tree):
            names=[]
            if isinstance(node,ast.Import): names=[alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node,ast.ImportFrom) and node.module: names=[node.module.split(".")[0]]
            imports+=len(names)
            for name in names:
                if name in FORBIDDEN: violations.append(f"{path.name}:{name}")
    if violations: raise SystemExit("ambient imports: "+",".join(violations))
    print(json.dumps({"kind":"M4BAmbientReport","files":len(FILES),"imports_checked":imports,"violations":0},separators=(",",":"),sort_keys=True))

if __name__=="__main__": main()
