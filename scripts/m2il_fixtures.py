#!/usr/bin/env python3
"""Fresh materializers for the frozen M2-IL descriptor corpus."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from m2_fixtures import materialize_delta_input, materialize_rule_bundle


ROOT = Path(__file__).resolve().parents[1]


def load_cases() -> dict[str, Any]:
    return json.loads((ROOT / "fixtures/m2il/cases.json").read_text(encoding="utf-8"))


def _as_m2_corpus(corpus: dict[str, Any]) -> dict[str, Any]:
    return {"atoms": copy.deepcopy(corpus["atoms"]), "base_rule_bundles": copy.deepcopy(corpus["bundles"]), "base_fact_delta_inputs": copy.deepcopy(corpus["deltas"])}


def materialize_bundle(corpus: dict[str, Any], bundle_ref: str, reverse_rules: bool = False) -> dict[str, Any]:
    return materialize_rule_bundle(_as_m2_corpus(corpus), bundle_ref, reverse_rules=reverse_rules)


def materialize_delta(corpus: dict[str, Any], ref: str, logical_time: int, bundle: dict[str, Any]) -> dict[str, Any]:
    return materialize_delta_input(_as_m2_corpus(corpus), ref, logical_time, rule_set_version=bundle["rule_set_version"], dataflow_version=bundle["dataflow_version"])


def materialize_step(corpus: dict[str, Any], sequence_id: str, index: int, logical_time: int, reverse_rules: bool = False, reverse_deltas: bool = False) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sequence = next(item for item in corpus["sequences"] if item["id"] == sequence_id)
    bundle = materialize_bundle(corpus, sequence["bundle_ref"], reverse_rules=reverse_rules)
    deltas = [materialize_delta(corpus, ref, logical_time, bundle) for ref in sequence["steps"][index]]
    if reverse_deltas: deltas.reverse()
    return bundle, deltas
