#!/usr/bin/env python3
"""Nonnormative guard adapter for the M3 reactive kernel.

The public M3 boundary is ``step_r(prior_state, profile, command)``.  All
three arguments are explicit JSON values, the result must be a fresh JSON
object, and the callable may neither mutate caller-owned containers nor use
ambient authority.  The process-level authority traps are shared with the
already measured M1/M2 checkers; this module only fixes the M3 call and replay
envelopes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from m1_guard import (
    AttemptedMutation,
    AuthorityGuard,
    GuardViolation,
    write_tracking_copy,
)


SINGLE_INPUT_KEYS = frozenset({"mode", "prior_state", "profile", "command"})
SEQUENCE_INPUT_KEYS = frozenset({"mode", "prior_state", "profile", "commands"})


class StepR(Protocol):
    """Callable contract exported by :mod:`flrh_reactive`."""

    def __call__(
        self,
        prior_state: Any,
        profile: Any,
        command: Any,
    ) -> dict[str, Any]: ...


def _require_exact_keys(
    value: Mapping[str, Any], expected: frozenset[str], label: str
) -> None:
    keys = set(value)
    if keys != expected:
        missing = sorted(expected - keys)
        extra = sorted(keys - expected)
        raise ValueError(
            f"M3 {label} input keys mismatch: missing={missing}, extra={extra}"
        )


def validate_input_document(value: Any) -> Mapping[str, Any]:
    """Validate the approved single-command or sequence replay envelope."""

    if not isinstance(value, Mapping):
        raise TypeError("M3 replay input must be one JSON object")
    mode = value.get("mode")
    if mode == "single":
        _require_exact_keys(value, SINGLE_INPUT_KEYS, "single")
    elif mode == "sequence":
        _require_exact_keys(value, SEQUENCE_INPUT_KEYS, "sequence")
        commands = value.get("commands")
        if not isinstance(commands, list):
            raise TypeError("M3 sequence commands must be one JSON array")
    else:
        raise ValueError("M3 replay mode must be 'single' or 'sequence'")
    return value


def _mutable_container_ids(value: Any, seen: set[int] | None = None) -> set[int]:
    """Collect recursive JSON-container identities, including proxy mappings."""

    if seen is None:
        seen = set()
    identity = id(value)
    if identity in seen:
        return set()
    if isinstance(value, Mapping):
        seen.add(identity)
        identities = {identity}
        for item in value.values():
            identities.update(_mutable_container_ids(item, seen))
        return identities
    if isinstance(value, list):
        seen.add(identity)
        identities = {identity}
        for item in value:
            identities.update(_mutable_container_ids(item, seen))
        return identities
    return set()


def call_step_r(
    stepper: StepR,
    prior_state: Any,
    profile: Any,
    command: Any,
) -> dict[str, Any]:
    """Invoke M3 and reject output aliases into any caller-owned input."""

    input_ids: set[int] = set()
    for value in (prior_state, profile, command):
        input_ids.update(_mutable_container_ids(value))
    result = stepper(prior_state, profile, command)
    if not isinstance(result, dict):
        raise TypeError("flrh_reactive.step_r must return a JSON object")
    if input_ids & _mutable_container_ids(result):
        raise ValueError("flrh_reactive.step_r returned an input-owned container")
    return result


def run_document(stepper: StepR, document: Mapping[str, Any]) -> dict[str, Any]:
    """Execute an approved single command or a stop-on-rejection sequence."""

    validated = validate_input_document(document)
    prior_state = validated["prior_state"]
    profile = validated["profile"]
    if validated["mode"] == "single":
        return call_step_r(stepper, prior_state, profile, validated["command"])

    results: list[dict[str, Any]] = []
    final_state = prior_state
    for command in validated["commands"]:
        result = call_step_r(stepper, final_state, profile, command)
        results.append(result)
        result_kind = result.get("kind")
        if result_kind == "RRejection":
            break
        if result_kind != "RTransition":
            raise ValueError("M3 sequence result must be RTransition or RRejection")
        if "next_state" not in result:
            raise ValueError("successful M3 result omitted next_state")
        final_state = result["next_state"]
    return {
        "kind": "M3ReplaySequence",
        "results": results,
        "final_state": final_state,
    }


__all__ = [
    "AttemptedMutation",
    "AuthorityGuard",
    "GuardViolation",
    "SEQUENCE_INPUT_KEYS",
    "SINGLE_INPUT_KEYS",
    "StepR",
    "call_step_r",
    "run_document",
    "validate_input_document",
    "write_tracking_copy",
]
