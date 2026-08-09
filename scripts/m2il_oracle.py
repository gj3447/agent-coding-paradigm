"""Independent M2-IL comparison oracle; never imports the candidate package."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any


def canonical_bytes(value: Any) -> bytes:
    def normalize(item: Any) -> Any:
        if item is None or isinstance(item, bool):
            return item
        if isinstance(item, int) and not isinstance(item, bool) and -(2**63) <= item <= 2**63 - 1:
            return item
        if isinstance(item, str) and unicodedata.normalize("NFC", item) == item:
            return item
        if isinstance(item, list):
            return [normalize(child) for child in item]
        if isinstance(item, dict) and all(isinstance(key, str) for key in item):
            for key in item:
                if any(0xD800 <= ord(character) <= 0xDFFF for character in key):
                    raise ValueError("outside flrh-cjson/1: surrogate object key")
                if unicodedata.normalize("NFC", key) != key:
                    raise ValueError("outside flrh-cjson/1: non-NFC object key")
            return {key: normalize(item[key]) for key in sorted(item)}
        raise ValueError("outside flrh-cjson/1")
    return json.dumps(normalize(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def pinned_public_m2_reference(prior_materialization: Any, rule_bundle: Any, fact_delta_inputs: Any, logical_time: Any) -> dict[str, Any]:
    """Call only the inherited public M2 boundary after candidate construction."""
    from flrh_logic import solve_l
    return solve_l(prior_materialization, rule_bundle, fact_delta_inputs, logical_time)


def assert_exact(candidate: Any, oracle: Any) -> None:
    if canonical_bytes(candidate) != canonical_bytes(oracle):
        raise AssertionError("M2IL_EQUIVALENCE_VIOLATION")


def naive_semantics(descriptor: dict[str, Any], bundle_ref: str, active_delta_refs: list[str]) -> dict[str, Any]:
    """Stdlib-only ground-rule scan independent of both production packages."""
    bundles = descriptor.get("bundles", descriptor.get("base_rule_bundles"))
    deltas = descriptor.get("deltas", descriptor.get("base_fact_delta_inputs"))
    bundle = bundles[bundle_ref]
    slots = {name: {"positive": set(), "negative": set()} for name in descriptor["atoms"]}
    for ref in active_delta_refs:
        delta = deltas[ref]
        if delta["diff"] != 1: raise ValueError("active ledger must contain insertions")
        slots[delta["atom_ref"]][delta["polarity"]].add(delta["derivation_id"])
    satisfied = set()
    for stratum in sorted({rule["stratum"] for rule in bundle["rules"]} | {item["referenced_stratum"] for rule in bundle["rules"] for item in rule["default_not_positive"]}):
        changed = True
        while changed:
            changed = False
            for rule in sorted((item for item in bundle["rules"] if item["stratum"] == stratum), key=lambda item: canonical_bytes(item)):
                required = all(slots[item["atom_ref"]][item["polarity"]] for item in rule["required"])
                defaults = all(not slots[item["atom_ref"]]["positive"] for item in rule["default_not_positive"])
                if required and defaults and rule["rule_id"] not in satisfied:
                    satisfied.add(rule["rule_id"]); slots[rule["head"]["atom_ref"]][rule["head"]["polarity"]].add("derived:" + rule["rule_id"]); changed = True
    states = {}
    conflicts = []
    for name in bundle["query_atom_refs"]:
        pos, neg = slots[name]["positive"], slots[name]["negative"]
        state = "BOTH" if pos and neg else "TRUE_ONLY" if pos else "FALSE_ONLY" if neg else "NEITHER"
        states[name] = {"state": state, "positive_support_ids": sorted(pos), "negative_support_ids": sorted(neg), "positive_support_count": len(pos), "negative_support_count": len(neg)}
        if state == "BOTH": conflicts.append(name)
    return {"states": states, "satisfied_rules": sorted(satisfied), "conflicts": sorted(conflicts)}


def naive_derived_delta(previous: dict[str, Any] | None, current: dict[str, Any], descriptor: dict[str, Any], bundle_ref: str) -> list[dict[str, Any]]:
    bundle = descriptor.get("bundles", descriptor.get("base_rule_bundles"))[bundle_ref]
    rules = {item["rule_id"]: item for item in bundle["rules"]}
    before = set(previous["satisfied_rules"] if previous else [])
    after = set(current["satisfied_rules"])
    rows = []
    for rule_id, diff in [(item, 1) for item in after-before] + [(item, -1) for item in before-after]:
        head = rules[rule_id]["head"]
        rows.append({"rule_id": rule_id, "atom_ref": head["atom_ref"], "polarity": head["polarity"], "diff": diff})
    return sorted(rows, key=canonical_bytes)
