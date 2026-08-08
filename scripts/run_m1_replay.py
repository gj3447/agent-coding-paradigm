#!/usr/bin/env python3
"""Emit exactly one canonical M1 fixture result for clean-process replay."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from flrh_kernel import canonical_bytes, step_f  # noqa: E402
from m1_fixtures import (  # noqa: E402
    find_case,
    find_replay_sequence,
    materialize_case,
    materialize_replay_sequence,
)


def _reverse_objects(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _reverse_objects(item)
            for key, item in reversed(tuple(value.items()))
        }
    if isinstance(value, list):
        return [_reverse_objects(item) for item in value]
    return value


def _run_case(corpus: dict[str, Any], case_id: str, reverse_objects: bool) -> dict[str, Any]:
    document = materialize_case(corpus, find_case(corpus, case_id))
    if reverse_objects:
        document = _reverse_objects(document)
    return step_f(document["snapshot"], document["accepted_event"])


def _run_sequence(corpus: dict[str, Any], sequence_id: str, reverse_objects: bool) -> dict[str, Any]:
    sequence = find_replay_sequence(corpus, sequence_id)
    snapshot, events = materialize_replay_sequence(corpus, sequence)
    if reverse_objects:
        snapshot = _reverse_objects(snapshot)
        events = [_reverse_objects(event) for event in events]
    transitions = []
    for event in events:
        result = step_f(snapshot, event)
        transitions.append(result)
        if result["kind"] != "FTransition":
            break
        snapshot = result["next_snapshot"]
    return {
        "kind": "M1ReplayResult",
        "sequence_id": sequence_id,
        "transitions": transitions,
        "final_snapshot": snapshot,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--case")
    selection.add_argument("--sequence")
    parser.add_argument("--reverse-objects", action="store_true")
    args = parser.parse_args(argv)
    corpus = json.loads((ROOT / "fixtures/m1/cases.json").read_text(encoding="utf-8"))
    if args.case is not None:
        result = _run_case(corpus, args.case, args.reverse_objects)
    else:
        result = _run_sequence(corpus, args.sequence, args.reverse_objects)
    sys.stdout.buffer.write(canonical_bytes(result) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
