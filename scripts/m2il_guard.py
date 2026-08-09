#!/usr/bin/env python3
"""Checkpoint integrity and caller-mutation guard probes."""

from __future__ import annotations

import copy
from typing import Any


def corrupt(value: dict[str, Any], path: tuple[str, ...], replacement: Any) -> dict[str, Any]:
    result = copy.deepcopy(value); cursor = result
    for key in path[:-1]: cursor = cursor[key]
    cursor[path[-1]] = replacement
    return result


def assert_closed_rejection(value: dict[str, Any], code: str) -> None:
    assert value["kind"] == "LPersistentLRejection" and value["code"] == code
    assert "next_checkpoint" not in value and "fixpoint_result" not in value
