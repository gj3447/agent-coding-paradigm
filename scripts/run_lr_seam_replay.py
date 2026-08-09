#!/usr/bin/env python3
"""Run one or a deterministic sequence of direct L-to-R projections from stdin."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from flrh_lr_seam import project_lr  # noqa: E402
from flrh_lr_seam.canonical import canonical_bytes  # noqa: E402


ARGUMENT_KEYS = frozenset(
    {"l_result", "rule_bundle", "r_profile", "binding_profile", "query_batch"}
)


def _run_case(case: Any) -> dict[str, Any]:
    if not isinstance(case, dict) or set(case) != ARGUMENT_KEYS:
        raise ValueError("each replay case must contain exactly the five project_lr arguments")
    return project_lr(
        case["l_result"], case["rule_bundle"], case["r_profile"],
        case["binding_profile"], case["query_batch"],
    )


def run_document(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ValueError("replay envelope must be one object")
    if document.get("mode") == "single" and set(document) == {"mode", *ARGUMENT_KEYS}:
        return {"mode": "single", "result": _run_case({key: document[key] for key in ARGUMENT_KEYS})}
    if document.get("mode") == "sequence" and set(document) == {"mode", "cases"}:
        if not isinstance(document["cases"], list) or not document["cases"]:
            raise ValueError("sequence cases must be a non-empty list")
        results = []
        for case in document["cases"]:
            result = _run_case(case)
            results.append(result)
            if result["kind"] == "LRProjectionRejection":
                break
        return {"mode": "sequence", "results": results}
    raise ValueError("unsupported replay envelope")


def main() -> int:
    document = json.loads(sys.stdin.buffer.read())
    sys.stdout.buffer.write(canonical_bytes(run_document(document)) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
