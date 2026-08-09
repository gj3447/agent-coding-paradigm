#!/usr/bin/env python3
"""Ambient-authority and input-mutation guard adapter for the M2 L kernel.

The exported ``call_solve_l`` boundary documents the executable M2 contract:
``solve_l(prior_materialization, rule_bundle, fact_delta_inputs, logical_time)``
must return a fresh JSON object.  All four inputs are explicit JSON values; the
callable may neither mutate them nor consult clocks, randomness, environment,
files, network, subprocesses, model clients, or tool clients.

M2 deliberately reuses the already hardened M1 process guard.  This module is
the small M2-specific layer: it names the four-argument contract and applies
write-tracking proxies without duplicating the ambient trap implementation.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from m1_guard import (  # re-exported for the M2 admission checker
    AttemptedMutation,
    AuthorityGuard,
    GuardViolation,
    write_tracking_copy,
)


INPUT_KEYS = frozenset(
    {
        "prior_materialization",
        "rule_bundle",
        "fact_delta_inputs",
        "logical_time",
    }
)


class SolveL(Protocol):
    """Callable contract exported by ``flrh_logic.solve_l``.

    The result is a fresh JSON object.  It must be a deterministic function of
    only these four values and must not retain or mutate input-owned containers.
    """

    def __call__(
        self,
        prior_materialization: Any,
        rule_bundle: Any,
        fact_delta_inputs: Any,
        logical_time: Any,
    ) -> dict[str, Any]: ...


def validate_input_document(value: Any) -> Mapping[str, Any]:
    """Require exactly the four explicit inputs admitted by the M2 runner."""

    if not isinstance(value, Mapping):
        raise TypeError("M2 replay input must be one JSON object")
    keys = set(value)
    if keys != INPUT_KEYS:
        missing = sorted(INPUT_KEYS - keys)
        extra = sorted(keys - INPUT_KEYS)
        raise ValueError(f"M2 replay input keys mismatch: missing={missing}, extra={extra}")
    return value


def _mutable_container_ids(value: Any, seen: set[int] | None = None) -> set[int]:
    """Collect JSON container identities without assuming plain ``dict`` inputs."""

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


def call_solve_l(solver: SolveL, document: Mapping[str, Any]) -> dict[str, Any]:
    """Invoke the M2 boundary and enforce fresh-container output ownership."""

    validated = validate_input_document(document)
    input_container_ids = _mutable_container_ids(validated)
    result = solver(
        validated["prior_materialization"],
        validated["rule_bundle"],
        validated["fact_delta_inputs"],
        validated["logical_time"],
    )
    if not isinstance(result, dict):
        raise TypeError("flrh_logic.solve_l must return a JSON object")
    aliases = input_container_ids & _mutable_container_ids(result)
    if aliases:
        raise ValueError("flrh_logic.solve_l returned an input-owned container")
    return result


__all__ = [
    "AttemptedMutation",
    "AuthorityGuard",
    "GuardViolation",
    "INPUT_KEYS",
    "SolveL",
    "call_solve_l",
    "validate_input_document",
    "write_tracking_copy",
]
