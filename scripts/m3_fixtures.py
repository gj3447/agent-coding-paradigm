#!/usr/bin/env python3
"""Materialize the frozen M3 fixture corpus without importing the kernel."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "fixtures/m3/cases.json"


def load_cases(path: Path = CASES_PATH) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("M3 fixture corpus must be one JSON object")
    return value


def materialize_profile(corpus: Mapping[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(corpus["profile"])


def materialize_delta(corpus: Mapping[str, Any], delta_ref: str) -> dict[str, Any]:
    return copy.deepcopy(corpus["deltas"][delta_ref])


def materialize_command(corpus: Mapping[str, Any], descriptor: Mapping[str, Any]) -> dict[str, Any]:
    del corpus
    return copy.deepcopy(descriptor)


def materialize_sequence(
    corpus: Mapping[str, Any], sequence: Mapping[str, Any]
) -> tuple[dict[str, Any] | None, dict[str, Any], list[dict[str, Any]]]:
    prior = copy.deepcopy(sequence.get("prior_state"))
    profile = materialize_profile(corpus)
    commands = [
        materialize_command(corpus, step["command"])
        for step in sequence["steps"]
    ]
    return prior, profile, commands


def find_by_id(values: list[Mapping[str, Any]], fixture_id: str) -> Mapping[str, Any]:
    for value in values:
        if value["id"] == fixture_id:
            return value
    raise KeyError(fixture_id)


__all__ = [
    "CASES_PATH",
    "ROOT",
    "find_by_id",
    "load_cases",
    "materialize_command",
    "materialize_delta",
    "materialize_profile",
    "materialize_sequence",
]
