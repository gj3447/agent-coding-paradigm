#!/usr/bin/env python3
"""Nonnormative process guard for the proposed direct L-to-R seam.

The only production waist admitted here is
``flrh_lr_seam.project_lr(l_result, rule_bundle, r_profile,
binding_profile, query_batch)``.  The helper rejects input mutation and output
aliases but deliberately does not reinterpret eligibility or call H.
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


INPUT_KEYS = frozenset(
    {
        "mode",
        "l_result",
        "rule_bundle",
        "r_profile",
        "binding_profile",
        "query_batch",
    }
)


class ProjectLR(Protocol):
    def __call__(
        self,
        l_result: Any,
        rule_bundle: Any,
        r_profile: Any,
        binding_profile: Any,
        query_batch: Any,
    ) -> dict[str, Any]: ...


def _mutable_container_ids(value: Any, seen: set[int] | None = None) -> set[int]:
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


def validate_input_document(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("L/R replay input must be one JSON object")
    keys = set(value)
    if keys != INPUT_KEYS:
        raise ValueError(
            "L/R replay input keys mismatch: "
            f"missing={sorted(INPUT_KEYS - keys)}, extra={sorted(keys - INPUT_KEYS)}"
        )
    if value.get("mode") != "single":
        raise ValueError("L/R replay mode must be 'single'")
    return value


def call_project_lr(
    projector: ProjectLR,
    l_result: Any,
    rule_bundle: Any,
    r_profile: Any,
    binding_profile: Any,
    query_batch: Any,
) -> dict[str, Any]:
    """Call the public seam and reject mutation or caller-container aliases."""

    arguments = (l_result, rule_bundle, r_profile, binding_profile, query_batch)
    input_ids: set[int] = set()
    for value in arguments:
        input_ids.update(_mutable_container_ids(value))
    result = projector(*arguments)
    if not isinstance(result, dict):
        raise TypeError("flrh_lr_seam.project_lr must return a JSON object")
    if input_ids & _mutable_container_ids(result):
        raise ValueError("flrh_lr_seam.project_lr returned an input-owned container")
    return result


def run_document(projector: ProjectLR, document: Mapping[str, Any]) -> dict[str, Any]:
    validated = validate_input_document(document)
    return call_project_lr(
        projector,
        validated["l_result"],
        validated["rule_bundle"],
        validated["r_profile"],
        validated["binding_profile"],
        validated["query_batch"],
    )


__all__ = [
    "AttemptedMutation",
    "AuthorityGuard",
    "GuardViolation",
    "INPUT_KEYS",
    "ProjectLR",
    "call_project_lr",
    "run_document",
    "validate_input_document",
    "write_tracking_copy",
]
