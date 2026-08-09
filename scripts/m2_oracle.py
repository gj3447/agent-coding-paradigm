#!/usr/bin/env python3
"""Independent naive full-recompute oracle for successful M2 evaluations.

This module intentionally does not import :mod:`flrh_logic`.  It applies a
finite ground rule bundle by repeated full scans, using only the independently
implemented fixture canonicalization helpers.  Validation and typed rejection
precedence belong to ``validate_m2.py``; invalid success inputs raise
``OracleInputError`` here.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from m2_fixtures import CANONICALIZATION, CONTRACT, PROFILE, canonical_bytes, digest


RULE_SCHEMA = "flrh-l-rules/1"
INPUT_SCHEMA = "flrh-l-input/1"
MATERIALIZATION_SCHEMA = "flrh-l-materialization/1"
RESULT_SCHEMA = "flrh-l-result/1"


class OracleInputError(ValueError):
    """The success-only oracle received an invalid or budget-exhausting input."""


def _fresh(value: Any) -> Any:
    return copy.deepcopy(value)


def _ordered(values: Sequence[Any]) -> list[Any]:
    return sorted((_fresh(value) for value in values), key=canonical_bytes)


def _ordered_strings(values: Sequence[str]) -> list[str]:
    return sorted(set(values), key=canonical_bytes)


def _identity(prefix: str, content_digest: str) -> str:
    return prefix + ":" + content_digest.split(":", 1)[1]


def _literal(atom: Mapping[str, Any], polarity: str) -> dict[str, Any]:
    return {"kind": "LLiteral", "polarity": polarity, "atom": _fresh(atom)}


def _fact_key(atom: Mapping[str, Any]) -> str:
    return digest(
        {
            "kind": "M2FactKeyPreimage",
            "contract_version": CONTRACT,
            "atom": _fresh(atom),
        }
    )


def _literal_key(literal: Mapping[str, Any]) -> str:
    return digest(
        {
            "kind": "M2LiteralKeyPreimage",
            "contract_version": CONTRACT,
            "literal": _fresh(literal),
        }
    )


def _base_support(delta_input: Mapping[str, Any]) -> dict[str, Any]:
    delta = delta_input["delta"]
    literal = _literal(delta["tuple"], delta_input["polarity"])
    content_digest = digest(
        {
            "kind": "M2BaseSupportContentPreimage",
            "contract_version": CONTRACT,
            "profile_id": PROFILE,
            "literal": literal,
            "provenance_delta": _fresh(delta["provenance_delta"]),
            "rule_set_version": delta["rule_set_version"],
            "dataflow_version": delta["dataflow_version"],
        }
    )
    return {
        "kind": "LBaseSupport",
        "derivation_id": delta["derivation_id"],
        "support_content_digest": content_digest,
        "literal": literal,
        "provenance_delta": _fresh(delta["provenance_delta"]),
        "rule_set_version": delta["rule_set_version"],
        "dataflow_version": delta["dataflow_version"],
    }


def _input_digest(delta_input: Mapping[str, Any]) -> str:
    return digest(
        {
            "kind": "M2InputDeltaPreimage",
            "contract_version": CONTRACT,
            "fact_delta_input": _fresh(delta_input),
        }
    )


def _apply_batch(
    prior: Mapping[str, Any] | None,
    inputs: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    ledger = {
        support["derivation_id"]: _fresh(support)
        for support in (prior or {}).get("base_supports", [])
    }
    unique_operations: dict[bytes, Mapping[str, Any]] = {}
    for item in inputs:
        encoded = canonical_bytes(item)
        unique_operations.setdefault(encoded, item)
    normalized = [unique_operations[key] for key in sorted(unique_operations)]

    seen_identity: dict[str, tuple[int, str]] = {}
    for item in normalized:
        delta = item["delta"]
        support = _base_support(item)
        derivation_id = support["derivation_id"]
        operation = (delta["diff"], support["support_content_digest"])
        previous_operation = seen_identity.get(derivation_id)
        if previous_operation is not None and previous_operation != operation:
            raise OracleInputError(f"ambiguous batch identity: {derivation_id}")
        seen_identity[derivation_id] = operation

        existing = ledger.get(derivation_id)
        if delta["diff"] == 1:
            if existing is None:
                ledger[derivation_id] = support
            elif existing["support_content_digest"] != support["support_content_digest"]:
                raise OracleInputError(f"derivation identity conflict: {derivation_id}")
        elif delta["diff"] == -1:
            if existing is None:
                raise OracleInputError(f"unknown derivation: {derivation_id}")
            if existing["support_content_digest"] != support["support_content_digest"]:
                raise OracleInputError(f"retraction content conflict: {derivation_id}")
            del ledger[derivation_id]
        else:
            raise OracleInputError("diff must be -1 or +1")

    return ledger, _ordered_strings([_input_digest(item) for item in normalized])


def _support_presence(
    base: Mapping[str, Mapping[str, Any]],
    derived: Mapping[str, Mapping[str, Any]],
) -> dict[str, list[str]]:
    presence: dict[str, list[str]] = {}
    for support in list(base.values()) + list(derived.values()):
        presence.setdefault(_literal_key(support["literal"]), []).append(
            support["derivation_id"]
        )
    return {key: _ordered_strings(ids) for key, ids in presence.items()}


def _fact_states(
    query_atoms: Sequence[Mapping[str, Any]],
    base: Mapping[str, Mapping[str, Any]],
    derived: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    atoms: dict[bytes, dict[str, Any]] = {
        canonical_bytes(atom): _fresh(atom) for atom in query_atoms
    }
    for support in list(base.values()) + list(derived.values()):
        atom = support["literal"]["atom"]
        atoms.setdefault(canonical_bytes(atom), _fresh(atom))

    presence = _support_presence(base, derived)
    states: list[dict[str, Any]] = []
    for atom_bytes in sorted(atoms):
        atom = atoms[atom_bytes]
        positive = presence.get(_literal_key(_literal(atom, "positive")), [])
        negative = presence.get(_literal_key(_literal(atom, "negative")), [])
        if positive and negative:
            state = "BOTH"
        elif positive:
            state = "TRUE_ONLY"
        elif negative:
            state = "FALSE_ONLY"
        else:
            state = "NEITHER"
        states.append(
            {
                "kind": "LFactState",
                "fact_key": _fact_key(atom),
                "atom": atom,
                "state": state,
                "positive_support_ids": _ordered_strings(positive),
                "negative_support_ids": _ordered_strings(negative),
            }
        )
    return _ordered(states)


def _conflicts(states: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for state in states:
        if state["state"] != "BOTH":
            continue
        preimage = {
            "kind": "M2ConflictPreimage",
            "contract_version": CONTRACT,
            "fact_key": state["fact_key"],
            "atom": _fresh(state["atom"]),
            "ordered_positive_support_ids": _fresh(state["positive_support_ids"]),
            "ordered_negative_support_ids": _fresh(state["negative_support_ids"]),
        }
        conflicts.append(
            {
                "kind": "LConflict",
                "conflict_id": _identity("conflict", digest(preimage)),
                "fact_key": state["fact_key"],
                "atom": _fresh(state["atom"]),
                "positive_support_ids": _fresh(state["positive_support_ids"]),
                "negative_support_ids": _fresh(state["negative_support_ids"]),
            }
        )
    return _ordered(conflicts)


def _stratum_digest(
    stratum: int,
    bundle_digest: str,
    base: Mapping[str, Mapping[str, Any]],
    derived: Mapping[str, Mapping[str, Any]],
    states: Sequence[Mapping[str, Any]],
) -> str:
    return digest(
        {
            "kind": "M2StratumPreimage",
            "contract_version": CONTRACT,
            "profile_id": PROFILE,
            "rule_bundle_digest": bundle_digest,
            "stratum": stratum,
            "ordered_base_supports": _ordered(list(base.values())),
            "ordered_derived_supports": _ordered(list(derived.values())),
            "ordered_fact_states": _ordered(states),
        }
    )


def _absence_witness(
    item: Mapping[str, Any], completed_stratum_digest: str
) -> dict[str, Any]:
    atom = _fresh(item["atom"])
    fact_key = _fact_key(atom)
    preimage = {
        "kind": "M2AbsenceWitnessPreimage",
        "contract_version": CONTRACT,
        "fact_key": fact_key,
        "atom": atom,
        "referenced_stratum": item["referenced_stratum"],
        "completed_stratum_digest": completed_stratum_digest,
    }
    return {
        "kind": "LAbsenceWitness",
        "fact_key": fact_key,
        "atom": atom,
        "referenced_stratum": item["referenced_stratum"],
        "completed_stratum_digest": completed_stratum_digest,
        "witness_digest": digest(preimage),
    }


def _derived_support(
    rule: Mapping[str, Any],
    witnesses: Sequence[Mapping[str, Any]],
    bundle: Mapping[str, Any],
) -> dict[str, Any]:
    premise_keys = _ordered_strings(
        [_literal_key(literal) for literal in rule["required_body"]]
    )
    ordered_witnesses = _ordered(witnesses)
    preimage = {
        "kind": "M2DerivedSupportContentPreimage",
        "contract_version": CONTRACT,
        "profile_id": PROFILE,
        "literal": _fresh(rule["head"]),
        "rule_id": rule["rule_id"],
        "rule_digest": rule["rule_digest"],
        "ordered_premise_literal_keys": premise_keys,
        "ordered_default_absence_witness_digests": _ordered_strings(
            [witness["witness_digest"] for witness in ordered_witnesses]
        ),
        "rule_set_version": bundle["rule_set_version"],
        "dataflow_version": bundle["dataflow_version"],
    }
    content_digest = digest(preimage)
    return {
        "kind": "LDerivedSupport",
        "derivation_id": _identity("derivation", content_digest),
        "support_content_digest": content_digest,
        "literal": _fresh(rule["head"]),
        "rule_id": rule["rule_id"],
        "rule_digest": rule["rule_digest"],
        "premise_literal_keys": premise_keys,
        "default_absence_witnesses": ordered_witnesses,
        "rule_set_version": bundle["rule_set_version"],
        "dataflow_version": bundle["dataflow_version"],
    }


def _derive_naively(
    base: Mapping[str, Mapping[str, Any]],
    bundle: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    derived: dict[str, dict[str, Any]] = {}
    derived_depth: dict[str, int] = {}
    literal_depth: dict[str, int] = {
        _literal_key(support["literal"]): 0 for support in base.values()
    }
    completed: dict[int, str] = {}
    stratum_entries: list[dict[str, Any]] = []
    evaluations = 0
    firings = 0
    scans = 0
    maximum_depth = 0

    rules = _ordered(bundle["rules"])
    strata = sorted(
        {rule["stratum"] for rule in rules}
        | {
            default["referenced_stratum"]
            for rule in rules
            for default in rule["default_not_positive_body"]
        }
    )
    for stratum in strata:
        stratum_rules = [rule for rule in rules if rule["stratum"] == stratum]
        while True:
            scans += 1
            changed = False
            presence = _support_presence(base, derived)
            for rule in stratum_rules:
                evaluations += 1
                required_keys = [_literal_key(item) for item in rule["required_body"]]
                if any(key not in presence for key in required_keys):
                    continue
                witnesses: list[dict[str, Any]] = []
                defaults_satisfied = True
                for default in rule["default_not_positive_body"]:
                    referenced = default["referenced_stratum"]
                    if referenced not in completed:
                        raise OracleInputError("default negation referenced an incomplete stratum")
                    positive_key = _literal_key(_literal(default["atom"], "positive"))
                    if positive_key in presence:
                        defaults_satisfied = False
                        break
                    witnesses.append(_absence_witness(default, completed[referenced]))
                if not defaults_satisfied:
                    continue
                support = _derived_support(rule, witnesses, bundle)
                existing_depth = derived_depth.get(rule["rule_id"])
                depth = 1 + max((literal_depth[key] for key in required_keys), default=0)
                if existing_depth is not None:
                    if depth < existing_depth:
                        derived_depth[rule["rule_id"]] = depth
                        head_key = _literal_key(support["literal"])
                        old_head_depth = literal_depth.get(head_key)
                        if old_head_depth is None or depth < old_head_depth:
                            literal_depth[head_key] = depth
                            changed = True
                    continue
                if firings >= bundle["limits"]["max_rule_firings"]:
                    raise OracleInputError("rule firing budget exhausted")
                derived[support["derivation_id"]] = support
                derived_depth[rule["rule_id"]] = depth
                head_key = _literal_key(support["literal"])
                literal_depth[head_key] = min(depth, literal_depth.get(head_key, depth))
                maximum_depth = max(maximum_depth, depth)
                firings += 1
                changed = True
            if not changed:
                break

        states = _fact_states(bundle["query_atoms"], base, derived)
        completed[stratum] = _stratum_digest(
            stratum, bundle["rule_bundle_digest"], base, derived, states
        )
        stratum_entries.append(
            {"kind": "LStratumDigest", "stratum": stratum, "digest": completed[stratum]}
        )

    maximum_depth = max(derived_depth.values(), default=0)
    if maximum_depth > bundle["limits"]["max_derivation_depth"]:
        raise OracleInputError("derivation depth budget exhausted")
    return derived, _ordered(stratum_entries), {
        "rule_evaluation_count": evaluations,
        "rule_firing_count": firings,
        "worklist_pop_count": scans,
        "max_derivation_depth": maximum_depth,
    }


def _materialization(
    base: Mapping[str, Mapping[str, Any]],
    derived: Mapping[str, Mapping[str, Any]],
    stratum_digests: Sequence[Mapping[str, Any]],
    bundle: Mapping[str, Any],
    logical_time: int,
) -> dict[str, Any]:
    states = _fact_states(bundle["query_atoms"], base, derived)
    body = {
        "kind": "LMaterialization",
        "schema_version": MATERIALIZATION_SCHEMA,
        "contract_version": CONTRACT,
        "profile_id": PROFILE,
        "rule_bundle_digest": bundle["rule_bundle_digest"],
        "rule_set_version": bundle["rule_set_version"],
        "dataflow_version": bundle["dataflow_version"],
        "canonicalization_version": CANONICALIZATION,
        "through_logical_time": logical_time,
        "base_supports": _ordered(list(base.values())),
        "derived_supports": _ordered(list(derived.values())),
        "fact_states": states,
        "conflicts": _conflicts(states),
        "stratum_digests": _ordered(stratum_digests),
    }
    body["materialization_digest"] = digest(
        {
            "kind": "M2MaterializationPreimage",
            "contract_version": CONTRACT,
            "materialization_without_materialization_digest": _fresh(body),
        }
    )
    return body


def _derived_delta(
    support: Mapping[str, Any],
    diff: int,
    causation_id: str,
    logical_time: int,
) -> dict[str, Any]:
    witnesses = support["default_absence_witnesses"]
    provenance = {
        "kind": "LDerivedProvenanceDelta",
        "rule_id": support["rule_id"],
        "rule_digest": support["rule_digest"],
        "premise_literal_keys": _fresh(support["premise_literal_keys"]),
        "default_absence_witness_digests": _ordered_strings(
            [witness["witness_digest"] for witness in witnesses]
        ),
        "support_content_digest": support["support_content_digest"],
    }
    return {
        "kind": "LFactDeltaInput",
        "schema_version": INPUT_SCHEMA,
        "polarity": support["literal"]["polarity"],
        "delta": {
            "kind": "FactDelta",
            "tuple": _fresh(support["literal"]["atom"]),
            "logical_time": logical_time,
            "diff": diff,
            "derivation_id": support["derivation_id"],
            "causation_id": causation_id,
            "provenance_delta": provenance,
            "rule_set_version": support["rule_set_version"],
            "dataflow_version": support["dataflow_version"],
        },
    }


def expected_success(
    prior_materialization: Mapping[str, Any] | None,
    rule_bundle: Mapping[str, Any],
    fact_delta_inputs: Sequence[Mapping[str, Any]],
    logical_time: int,
) -> dict[str, Any]:
    """Return the independent full-rescan ``LFixpointResult`` for valid inputs."""

    if rule_bundle.get("schema_version") != RULE_SCHEMA:
        raise OracleInputError("unsupported rule bundle")
    base, input_digests = _apply_batch(prior_materialization, fact_delta_inputs)
    derived, stratum_digests, counters = _derive_naively(base, rule_bundle)
    next_materialization = _materialization(
        base, derived, stratum_digests, rule_bundle, logical_time
    )

    prior_derived = {
        support["derivation_id"]: _fresh(support)
        for support in (prior_materialization or {}).get("derived_supports", [])
    }
    prior_digest = (
        prior_materialization["materialization_digest"]
        if prior_materialization is not None
        else None
    )
    invocation_preimage = {
        "kind": "M2InvocationPreimage",
        "contract_version": CONTRACT,
        "logical_time": logical_time,
        "rule_bundle_digest": rule_bundle["rule_bundle_digest"],
        "prior_materialization_digest": prior_digest,
        "ordered_input_delta_digests": input_digests,
    }
    causation_id = _identity("logic", digest(invocation_preimage))
    emitted: list[dict[str, Any]] = []
    for identity in sorted(set(derived) - set(prior_derived), key=canonical_bytes):
        emitted.append(_derived_delta(derived[identity], 1, causation_id, logical_time))
    for identity in sorted(set(prior_derived) - set(derived), key=canonical_bytes):
        emitted.append(
            _derived_delta(prior_derived[identity], -1, causation_id, logical_time)
        )

    body = {
        "kind": "LFixpointResult",
        "schema_version": RESULT_SCHEMA,
        "contract_version": CONTRACT,
        "logical_time": logical_time,
        "rule_bundle_digest": rule_bundle["rule_bundle_digest"],
        "prior_materialization_digest": prior_digest,
        "input_delta_digests": input_digests,
        "next_materialization": next_materialization,
        "derived_fact_deltas": _ordered(emitted),
        "stats": {
            "evaluation_mode": "full_recompute",
            **counters,
        },
    }
    body["fixpoint_digest"] = digest(
        {
            "kind": "M2FixpointPreimage",
            "contract_version": CONTRACT,
            "fixpoint_result_without_fixpoint_digest": _fresh(body),
        }
    )
    return body


def expected_sequence(
    rule_bundle: Mapping[str, Any],
    input_steps: Sequence[Sequence[Mapping[str, Any]]],
    *,
    first_logical_time: int = 1,
) -> list[dict[str, Any]]:
    """Full-recompute each successful sequence step and carry its materialization."""

    prior: dict[str, Any] | None = None
    results: list[dict[str, Any]] = []
    for offset, inputs in enumerate(input_steps):
        result = expected_success(
            prior, rule_bundle, inputs, first_logical_time + offset
        )
        results.append(result)
        prior = result["next_materialization"]
    return results


__all__ = ["OracleInputError", "expected_sequence", "expected_success"]
