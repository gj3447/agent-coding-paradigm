#!/usr/bin/env python3
"""One-line canonical JSON replay entry point for M4A."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from flrh_authority import project_h_intent
from flrh_authority.canonical import canonical_bytes


def main() -> int:
    raw = sys.stdin.buffer.read()
    if raw.count(b"\n") != 1 or not raw.endswith(b"\n"):
        raise SystemExit("expected exactly one newline-terminated JSON object")
    command = json.loads(raw)
    sys.stdout.buffer.write(canonical_bytes(project_h_intent(command)) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
