#!/usr/bin/env python3
"""Static and clean-process ambient-dependency check for M4A."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

from m4a_fixtures import find_case, load_cases

ROOT = Path(__file__).resolve().parents[1]
BANNED_IMPORTS = {"os", "pathlib", "random", "secrets", "socket", "subprocess", "time", "uuid"}


def main() -> int:
    paths = sorted((ROOT / "src/flrh_authority").glob("*.py"))
    import_checks = 0
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                names = {(node.module or "").split(".")[0]}
            else:
                continue
            import_checks += 1
            overlap = names & BANNED_IMPORTS
            if overlap:
                raise AssertionError(f"ambient import in {path}: {sorted(overlap)}")
    command = find_case(load_cases(), "success:approval-granted")
    stdin = json.dumps(command, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode() + b"\n"
    outputs = []
    for seed, timezone in (("31", "UTC"), ("79", "Asia/Seoul")):
        env = {"PATH": os.defpath, "PYTHONHASHSEED": seed, "TZ": timezone, "LANG": "C", "LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/run_m4a_replay.py")], cwd=ROOT, env=env, input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode or result.stderr:
            raise AssertionError(result.stderr.decode() or result.stdout.decode())
        outputs.append(result.stdout)
    if outputs[0] != outputs[1]:
        raise AssertionError("M4A output varied across clean process profiles")
    print(json.dumps({"ambient_categories": sorted(BANNED_IMPORTS), "source_paths": len(paths), "import_checks": import_checks, "clean_processes": 2, "ambient_import_attempts": 0, "status": "PASS"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
