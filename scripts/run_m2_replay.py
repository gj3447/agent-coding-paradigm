#!/usr/bin/env python3
"""Run exactly one M2 L-kernel request from stdin.

Input is one JSON object with exactly ``prior_materialization``, ``rule_bundle``,
``fact_delta_inputs``, and ``logical_time``.  On a valid request, stdout is
exactly one canonical JSON line and stderr is empty.  The public callable
contract is documented and enforced by :mod:`m2_guard`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from flrh_logic import solve_l  # noqa: E402
from flrh_logic.canonical import canonical_bytes  # noqa: E402
from m2_guard import call_solve_l, validate_input_document  # noqa: E402


def main() -> int:
    document = json.loads(sys.stdin.buffer.read())
    validated = validate_input_document(document)
    result = call_solve_l(solve_l, validated)
    sys.stdout.buffer.write(canonical_bytes(result) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
