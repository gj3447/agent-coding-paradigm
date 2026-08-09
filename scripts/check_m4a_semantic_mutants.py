#!/usr/bin/env python3
"""Exercise frozen fail-closed M4A rejection sensitivity cases.

These are input mutations, not source-code mutation testing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from flrh_authority import project_h_intent
from m4a_fixtures import load_cases


def main() -> int:
    corpus = load_cases()
    detected = []
    for case in corpus["rejection_cases"]:
        result = project_h_intent(case["command"])
        if result.get("kind") != "HRejection" or result.get("code") != case["expected_code"]:
            raise AssertionError(f"sensitivity case escaped: {case['id']}: {result}")
        detected.append(case["id"])
    print(json.dumps({"cases": detected, "sensitivity_cases_detected": len(detected), "status": "PASS"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
