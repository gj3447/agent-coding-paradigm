#!/usr/bin/env python3
"""Independent materializers for the frozen direct L-to-R seam corpus."""

from __future__ import annotations

import copy
import hashlib
import json
import unicodedata
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "fixtures/lr-seam/cases.json"

LR_CONTRACT = "flrh-lr-seam/1"
LR_PROFILE_SCHEMA = "flrh-lr-profile/1"
LR_PROFILE_ID = "flrh-lr-four-valued/1"
LR_QUERY_SCHEMA = "flrh-lr-query/1"
CANONICALIZATION = "flrh-cjson/1"
L_CONTRACT = "flrh-l-kernel/1"
L_PROFILE = "flrh-l-ground-stratified/1"
R_CONTRACT = "flrh-r-kernel/1"
R_PROFILE_ID = "flrh-r-scalar-frontier/1"


def fresh(value: Any) -> Any:
    return copy.deepcopy(value)


def load_cases() -> dict[str, Any]:
    value = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("LR seam fixture corpus must be one object")
    return value


def _check_json(value: Any) -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        if not -(2**63) <= value <= 2**63 - 1:
            raise ValueError("integer outside signed-64-bit domain")
        return
    if isinstance(value, float):
        raise ValueError("floats are outside flrh-cjson/1")
    if isinstance(value, str):
        if unicodedata.normalize("NFC", value) != value:
            raise ValueError("non-NFC string")
        value.encode("utf-8")
        return
    if isinstance(value, list):
        for item in value:
            _check_json(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("non-string object key")
            _check_json(key)
            _check_json(item)
        return
    raise ValueError(f"unsupported JSON value: {type(value).__name__}")


def _normalize_root_sets(value: Any) -> Any:
    result = fresh(value)
    if not isinstance(result, dict):
        return result
    set_fields = {
        "EffectProposal": ("preconditions",),
        "EligibilityVerdict": ("support_derivation_ids",),
    }.get(result.get("kind"), ())
    for field in set_fields:
        if field in result:
            encoded = [canonical_bytes(item) for item in result[field]]
            if len(encoded) != len(set(encoded)):
                raise ValueError(f"duplicate set member: {field}")
            result[field] = [item for _, item in sorted(zip(encoded, result[field]), key=lambda pair: pair[0])]
    return result


def canonical_bytes(value: Any) -> bytes:
    _check_json(value)
    normalized = _normalize_root_sets(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def ordered(values: Sequence[Any]) -> list[Any]:
    return sorted((fresh(value) for value in values), key=canonical_bytes)


def literal(atom: Mapping[str, Any], polarity: str = "positive") -> dict[str, Any]:
    return {"kind": "LLiteral", "polarity": polarity, "atom": fresh(atom)}


def materialize_rule_bundle(
    *,
    query_atoms: Sequence[Mapping[str, Any]],
    rules: Sequence[Mapping[str, Any]] = (),
    rule_set_version: str = "rules/lr-test/1",
    dataflow_version: str = "dataflow/0",
    max_rule_firings: int = 32,
    max_derivation_depth: int = 8,
) -> dict[str, Any]:
    materialized_rules: list[dict[str, Any]] = []
    for template in rules:
        required = ordered(template["required_body"])
        defaults = ordered(template.get("default_not_positive_body", []))
        preimage = {
            "kind": "M2RulePreimage",
            "contract_version": L_CONTRACT,
            "profile_id": L_PROFILE,
            "rule_id": template["rule_id"],
            "stratum": template.get("stratum", 0),
            "head": fresh(template["head"]),
            "ordered_required_body": required,
            "ordered_default_not_positive_body": defaults,
        }
        materialized_rules.append(
            {
                "kind": "LRule",
                "rule_id": template["rule_id"],
                "stratum": template.get("stratum", 0),
                "head": fresh(template["head"]),
                "required_body": required,
                "default_not_positive_body": defaults,
                "rule_digest": digest(preimage),
            }
        )
    materialized_rules = ordered(materialized_rules)
    queries = ordered(query_atoms)
    limits = {
        "max_rule_firings": max_rule_firings,
        "max_derivation_depth": max_derivation_depth,
    }
    preimage = {
        "kind": "M2RuleBundlePreimage",
        "contract_version": L_CONTRACT,
        "profile_id": L_PROFILE,
        "rule_set_version": rule_set_version,
        "dataflow_version": dataflow_version,
        "canonicalization_version": CANONICALIZATION,
        "limits": limits,
        "ordered_query_atoms": queries,
        "ordered_rules": materialized_rules,
    }
    return {
        "kind": "LRuleBundle",
        "schema_version": "flrh-l-rules/1",
        "contract_version": L_CONTRACT,
        "profile_id": L_PROFILE,
        "rule_set_version": rule_set_version,
        "dataflow_version": dataflow_version,
        "canonicalization_version": CANONICALIZATION,
        "limits": limits,
        "query_atoms": queries,
        "rules": materialized_rules,
        "rule_bundle_digest": digest(preimage),
    }


def fact_delta_input(
    atom: Mapping[str, Any],
    *,
    logical_time: int,
    polarity: str,
    derivation_id: str,
    diff: int = 1,
    rule_set_version: str = "rules/lr-test/1",
    dataflow_version: str = "dataflow/0",
) -> dict[str, Any]:
    return {
        "kind": "LFactDeltaInput",
        "schema_version": "flrh-l-input/1",
        "polarity": polarity,
        "delta": {
            "kind": "FactDelta",
            "tuple": fresh(atom),
            "logical_time": logical_time,
            "diff": diff,
            "derivation_id": derivation_id,
            "causation_id": f"event:lr:{logical_time}",
            "provenance_delta": {"fixture_derivation_id": derivation_id},
            "rule_set_version": rule_set_version,
            "dataflow_version": dataflow_version,
        },
    }


def materialize_r_profile(
    *, dataflow_version: str = "dataflow/0", max_deltas_per_command: int = 32
) -> dict[str, Any]:
    limits = {
        "max_deltas_per_command": max_deltas_per_command,
        "max_active_values": max_deltas_per_command,
        "max_open_epochs": 8,
        "max_ready_batches": 8,
        "max_demand_per_command": 8,
        "max_outstanding_demand": 16,
    }
    source_ids = ["source:lr:proposal", "source:lr:verdict"]
    without = {
        "kind": "RDataflowProfile",
        "schema_version": "flrh-r-profile/1",
        "contract_version": R_CONTRACT,
        "profile_id": R_PROFILE_ID,
        "dataflow_version": dataflow_version,
        "canonicalization_version": CANONICALIZATION,
        "source_ids": ordered(source_ids),
        "late_event_policy": "reject",
        "overflow_policy": "reject_new",
        "limits": limits,
    }
    profile_digest = digest(
        {
            "kind": "M3ProfilePreimage",
            "contract_version": R_CONTRACT,
            "profile_id": R_PROFILE_ID,
            "dataflow_version": dataflow_version,
            "canonicalization_version": CANONICALIZATION,
            "ordered_source_ids": without["source_ids"],
            "late_event_policy": "reject",
            "overflow_policy": "reject_new",
            "limits": limits,
        }
    )
    return {**without, "profile_digest": profile_digest}


def materialize_binding_profile(
    *,
    rule_set_version: str = "rules/lr-test/1",
    dataflow_version: str = "dataflow/0",
    max_queries: int = 8,
    max_fact_requirements_per_query: int = 4,
) -> dict[str, Any]:
    without = {
        "kind": "LRBindingProfile",
        "schema_version": LR_PROFILE_SCHEMA,
        "contract_version": LR_CONTRACT,
        "profile_id": LR_PROFILE_ID,
        "canonicalization_version": CANONICALIZATION,
        "rule_set_version": rule_set_version,
        "dataflow_version": dataflow_version,
        "proposal_source_id": "source:lr:proposal",
        "verdict_source_id": "source:lr:verdict",
        "neither_policy": "deny_unproven",
        "conflict_policy": "emit_conflicted",
        "limits": {
            "max_queries": max_queries,
            "max_fact_requirements_per_query": max_fact_requirements_per_query,
        },
    }
    preimage = {
        "kind": "LRProfilePreimage",
        "contract_version": LR_CONTRACT,
        "profile_id": LR_PROFILE_ID,
        "rule_set_version": rule_set_version,
        "dataflow_version": dataflow_version,
        "canonicalization_version": CANONICALIZATION,
        "proposal_source_id": without["proposal_source_id"],
        "verdict_source_id": without["verdict_source_id"],
        "neither_policy": without["neither_policy"],
        "conflict_policy": without["conflict_policy"],
        "limits": without["limits"],
    }
    return {**without, "profile_digest": digest(preimage)}


def _base_proposal() -> dict[str, Any]:
    transition = json.loads(
        (ROOT / "fixtures/m1/golden/observe-with-effect.transition.json").read_text(
            encoding="utf-8"
        )
    )
    return fresh(transition["effect_proposals"][0])


def materialize_proposal(
    suffix: str,
    preconditions: Sequence[str],
    *,
    rule_set_version: str = "rules/lr-test/1",
    dataflow_version: str = "dataflow/0",
) -> dict[str, Any]:
    proposal = _base_proposal()
    proposal.update(
        {
            "proposal_id": f"proposal:lr:{suffix}",
            "proposal_dedup_key": f"proposal-dedup:lr:{suffix}",
            "cause_id": f"cause:lr:proposal:{suffix}",
            "preconditions": ordered(preconditions),
        }
    )
    proposal["versions"]["rule_set"] = rule_set_version
    proposal["versions"]["dataflow"] = dataflow_version
    return proposal


def materialize_requirement(
    precondition_id: str, atom: Mapping[str, Any], polarity: str = "positive"
) -> dict[str, Any]:
    return {
        "kind": "LRFactRequirement",
        "precondition_id": precondition_id,
        "literal": literal(atom, polarity),
    }


def _query_digest(proposal: Mapping[str, Any], requirements: Sequence[Mapping[str, Any]], frontier_ids: Sequence[str]) -> str:
    return digest(
        {
            "kind": "LRQueryPreimage",
            "contract_version": LR_CONTRACT,
            "proposal": fresh(proposal),
            "ordered_fact_requirements": ordered(requirements),
            "ordered_frontier_precondition_ids": ordered(frontier_ids),
        }
    )


def materialize_query(
    proposal: Mapping[str, Any],
    requirements: Sequence[Mapping[str, Any]],
    *,
    frontier_precondition_ids: Sequence[str] = (),
) -> dict[str, Any]:
    normalized_requirements = ordered(requirements)
    normalized_frontiers = ordered(frontier_precondition_ids)
    return {
        "kind": "LRProjectionQuery",
        "proposal": fresh(proposal),
        "fact_requirements": normalized_requirements,
        "frontier_precondition_ids": normalized_frontiers,
        "query_digest": _query_digest(proposal, normalized_requirements, normalized_frontiers),
    }


def materialize_query_batch(
    *,
    binding_profile: Mapping[str, Any],
    l_result: Mapping[str, Any],
    rule_bundle: Mapping[str, Any],
    r_profile: Mapping[str, Any],
    queries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    normalized_queries = ordered(queries)
    without = {
        "kind": "LRQueryBatch",
        "schema_version": LR_QUERY_SCHEMA,
        "contract_version": LR_CONTRACT,
        "binding_profile_digest": binding_profile["profile_digest"],
        "l_fixpoint_digest": l_result["fixpoint_digest"],
        "rule_bundle_digest": rule_bundle["rule_bundle_digest"],
        "r_profile_digest": r_profile["profile_digest"],
        "queries": normalized_queries,
    }
    preimage = {
        "kind": "LRQueryBatchPreimage",
        "contract_version": LR_CONTRACT,
        "binding_profile_digest": without["binding_profile_digest"],
        "l_fixpoint_digest": without["l_fixpoint_digest"],
        "rule_bundle_digest": without["rule_bundle_digest"],
        "r_profile_digest": without["r_profile_digest"],
        "ordered_queries": normalized_queries,
    }
    return {**without, "query_batch_digest": digest(preimage)}


def truth_fixture_inputs(logical_time: int = 7) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    atoms = {
        name: {"predicate": "lr_truth_probe", "subject": name}
        for name in ("true_only", "false_only", "both", "neither")
    }
    bundle = materialize_rule_bundle(query_atoms=list(atoms.values()))
    deltas = [
        fact_delta_input(atoms["true_only"], logical_time=logical_time, polarity="positive", derivation_id="derivation:lr:true"),
        fact_delta_input(atoms["false_only"], logical_time=logical_time, polarity="negative", derivation_id="derivation:lr:false"),
        fact_delta_input(atoms["both"], logical_time=logical_time, polarity="positive", derivation_id="derivation:lr:both-positive"),
        fact_delta_input(atoms["both"], logical_time=logical_time, polarity="negative", derivation_id="derivation:lr:both-negative"),
    ]
    return bundle, deltas, atoms


def actual_chain_inputs() -> tuple[
    dict[str, Any], list[dict[str, Any]], dict[str, Any],
    list[dict[str, Any]], list[str],
]:
    transition = json.loads(
        (ROOT / "fixtures/m1/golden/observe-with-effect.transition.json").read_text(
            encoding="utf-8"
        )
    )
    proposal = fresh(transition["effect_proposals"][0])
    observation = fresh(transition["fact_deltas"][0]["tuple"])
    requirements: list[dict[str, Any]] = []
    query_atoms: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = []
    fact_precondition_ids = ["constraint:artifact-ready"]
    frontier_precondition_ids = ["frontier:1"]
    if set(fact_precondition_ids) | set(frontier_precondition_ids) != set(proposal["preconditions"]):
        raise ValueError("M1 proposal precondition ownership changed")
    for index, precondition_id in enumerate(fact_precondition_ids):
        atom = {
            "predicate": "proposal_precondition_satisfied",
            "proposal_id": proposal["proposal_id"],
            "precondition_id": precondition_id,
        }
        query_atoms.append(atom)
        requirements.append(materialize_requirement(precondition_id, atom))
        rules.append(
            {
                "rule_id": f"rule:lr:m1:{index}",
                "stratum": 0,
                "head": literal(atom),
                "required_body": [literal(observation)],
                "default_not_positive_body": [],
            }
        )
    bundle = materialize_rule_bundle(
        query_atoms=query_atoms,
        rules=rules,
        rule_set_version="rules/0",
        dataflow_version="dataflow/0",
    )
    delta_input = {
        "kind": "LFactDeltaInput",
        "schema_version": "flrh-l-input/1",
        "polarity": "positive",
        "delta": fresh(transition["fact_deltas"][0]),
    }
    return bundle, [delta_input], proposal, requirements, frontier_precondition_ids


__all__ = [name for name in globals() if name.startswith("materialize_") or name in {
    "CASES_PATH", "ROOT", "actual_chain_inputs", "canonical_bytes", "digest", "fresh",
    "load_cases", "literal", "ordered", "truth_fixture_inputs", "fact_delta_input",
}]
