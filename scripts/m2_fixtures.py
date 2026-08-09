#!/usr/bin/env python3
"""Read-only helpers for the bounded M2 conformance corpus."""

from __future__ import annotations

import copy
import hashlib
import json
import unicodedata
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "fixtures/m2/cases.json"


def load_cases() -> dict[str, Any]:
    """Load a fresh corpus value so no test can share mutated fixture state."""

    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def fresh(value: Any) -> Any:
    """Return a recursively independent input value for mutation checks."""

    return copy.deepcopy(value)


CONTRACT = "flrh-l-kernel/1"
PROFILE = "flrh-l-ground-stratified/1"
CANONICALIZATION = "flrh-cjson/1"


def canonical_bytes(value: Any) -> bytes:
    """Independent canonical bytes for the closed ASCII-heavy fixture domain."""

    def check(item: Any) -> None:
        if item is None or isinstance(item, bool):
            return
        if isinstance(item, int) and not isinstance(item, bool):
            if not -(2**63) <= item <= 2**63 - 1:
                raise ValueError("integer outside signed-64-bit domain")
            return
        if isinstance(item, str):
            if unicodedata.normalize("NFC", item) != item:
                raise ValueError("non-NFC fixture string")
            return
        if isinstance(item, list):
            for child in item:
                check(child)
            return
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError("non-string fixture key")
                check(key)
                check(child)
            return
        raise ValueError(f"non-canonical fixture value: {type(item).__name__}")

    check(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def _ordered(values: list[Any]) -> list[Any]:
    return sorted(values, key=canonical_bytes)


def literal(atom: dict[str, Any], polarity: str) -> dict[str, Any]:
    return {"kind": "LLiteral", "polarity": polarity, "atom": fresh(atom)}


def materialize_rule_bundle(
    corpus: dict[str, Any], ref_or_template: str | dict[str, Any], reverse_rules: bool = False
) -> dict[str, Any]:
    template = (
        corpus["base_rule_bundles"][ref_or_template]
        if isinstance(ref_or_template, str)
        else ref_or_template
    )
    atoms = corpus["atoms"]
    rules = []
    for rule_template in template["rules"]:
        head = literal(
            atoms[rule_template["head"]["atom_ref"]], rule_template["head"]["polarity"]
        )
        required = _ordered(
            [literal(atoms[item["atom_ref"]], item["polarity"]) for item in rule_template["required"]]
        )
        defaults = _ordered(
            [
                {
                    "kind": "LDefaultNotPositive",
                    "atom": fresh(atoms[item["atom_ref"]]),
                    "referenced_stratum": item["referenced_stratum"],
                }
                for item in rule_template["default_not_positive"]
            ]
        )
        preimage = {
            "kind": "M2RulePreimage",
            "contract_version": CONTRACT,
            "profile_id": PROFILE,
            "rule_id": rule_template["rule_id"],
            "stratum": rule_template["stratum"],
            "head": head,
            "ordered_required_body": required,
            "ordered_default_not_positive_body": defaults,
        }
        rule_digest = digest(preimage)
        rules.append(
            {
                "kind": "LRule",
                "rule_id": rule_template["rule_id"],
                "stratum": rule_template["stratum"],
                "head": head,
                "required_body": required,
                "default_not_positive_body": defaults,
                "rule_digest": rule_digest,
            }
        )
    rules = _ordered(rules)
    if reverse_rules:
        rules.reverse()
    queries = _ordered([fresh(atoms[name]) for name in template["query_atom_refs"]])
    rule_set_version = template.get("rule_set_version", "rules/m2-test/1")
    dataflow_version = template.get("dataflow_version", "dataflow/m2-test/1")
    preimage = {
        "kind": "M2RuleBundlePreimage",
        "contract_version": CONTRACT,
        "profile_id": PROFILE,
        "rule_set_version": rule_set_version,
        "dataflow_version": dataflow_version,
        "canonicalization_version": CANONICALIZATION,
        "limits": fresh(template["limits"]),
        "ordered_query_atoms": queries,
        "ordered_rules": _ordered(rules),
    }
    return {
        "kind": "LRuleBundle",
        "schema_version": "flrh-l-rules/1",
        "contract_version": CONTRACT,
        "profile_id": PROFILE,
        "rule_set_version": rule_set_version,
        "dataflow_version": dataflow_version,
        "canonicalization_version": CANONICALIZATION,
        "limits": fresh(template["limits"]),
        "query_atoms": queries,
        "rules": rules,
        "rule_bundle_digest": digest(preimage),
    }


def materialize_delta_input(
    corpus: dict[str, Any], delta_ref: str, logical_time: int,
    *, rule_set_version: str = "rules/m2-test/1",
    dataflow_version: str = "dataflow/m2-test/1"
) -> dict[str, Any]:
    if delta_ref == "$m1_positive_seam":
        delta = fresh(corpus["m1_positive_seam"])
        return {
            "kind": "LFactDeltaInput",
            "schema_version": "flrh-l-input/1",
            "polarity": "positive",
            "delta": delta,
        }
    template = corpus["base_fact_delta_inputs"][delta_ref]
    delta = {
        "kind": "FactDelta",
        "tuple": fresh(corpus["atoms"][template["atom_ref"]]),
        "logical_time": logical_time,
        "diff": template["diff"],
        "derivation_id": template["derivation_id"],
        "causation_id": f"event:m2:{logical_time}",
        "provenance_delta": fresh(
            template.get(
                "provenance_delta",
                {"fixture_derivation_id": template["derivation_id"]},
            )
        ),
        "rule_set_version": rule_set_version,
        "dataflow_version": dataflow_version,
    }
    return {
        "kind": "LFactDeltaInput",
        "schema_version": "flrh-l-input/1",
        "polarity": template["polarity"],
        "delta": delta,
    }


def materialize_case(
    corpus: dict[str, Any], case: dict[str, Any], *, reverse_rules: bool = False,
    reverse_deltas: bool = False, logical_time: int = 1
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    bundle = materialize_rule_bundle(corpus, case["bundle_ref"], reverse_rules=reverse_rules)
    deltas = [
        materialize_delta_input(
            corpus,
            ref,
            logical_time,
            rule_set_version=bundle["rule_set_version"],
            dataflow_version=bundle["dataflow_version"],
        )
        for ref in case["delta_refs"]
    ]
    if reverse_deltas:
        deltas.reverse()
    for mutation in case.get("mutations", []):
        target: Any = bundle if mutation["target"] == "rule_bundle" else deltas
        for component in mutation["path"][:-1]:
            target = target[component]
        target[mutation["path"][-1]] = fresh(mutation["value"])
    return bundle, deltas


def materialize_sequence_step(
    corpus: dict[str, Any], sequence: dict[str, Any], step_index: int,
    logical_time: int
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    bundle = materialize_rule_bundle(corpus, sequence["bundle_ref"])
    deltas = [
        materialize_delta_input(
            corpus,
            ref,
            logical_time,
            rule_set_version=bundle["rule_set_version"],
            dataflow_version=bundle["dataflow_version"],
        )
        for ref in sequence["steps"][step_index]
    ]
    return bundle, deltas
