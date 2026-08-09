#!/usr/bin/env python3
"""Stdlib-only independent oracle for the frozen direct L-to-R seam.

This module deliberately imports no production FLRH package.  It materializes
the normative truth projection and M3 wire identities from complete JSON
documents supplied by the fixture corpus.
"""

from __future__ import annotations

import copy
import hashlib
import json
import unicodedata
from typing import Any, Mapping, Sequence


LR_CONTRACT = "flrh-lr-seam/1"
RESULT_SCHEMA = "flrh-lr-result/1"
R_CONTRACT = "flrh-r-kernel/1"


def _normalize(value: Any, path: str = "", set_paths: frozenset[str] = frozenset()) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        if not -(2**63) <= value <= 2**63 - 1:
            raise ValueError(f"INTEGER_OUTSIDE_INT64:{path or '/'}")
        return value
    if isinstance(value, float):
        raise ValueError(f"FLOAT_FORBIDDEN:{path or '/'}")
    if isinstance(value, str):
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise ValueError(f"NON_UNICODE_SCALAR:{path or '/'}")
        if unicodedata.normalize("NFC", value) != value:
            raise ValueError(f"NON_NFC_STRING:{path or '/'}")
        return value
    if isinstance(value, list):
        normalized = [_normalize(item, f"{path}/{index}", set_paths) for index, item in enumerate(value)]
        if path in set_paths:
            encoded = [_encode(item) for item in normalized]
            if len(encoded) != len(set(encoded)):
                raise ValueError(f"DUPLICATE_SET_ELEMENT:{path or '/'}")
            normalized = [item for _, item in sorted(zip(encoded, normalized), key=lambda pair: pair[0])]
        return normalized
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError(f"NON_STRING_OBJECT_KEY:{path or '/'}")
        result = {}
        for key in sorted(value):
            if unicodedata.normalize("NFC", key) != key:
                raise ValueError(f"NON_NFC_OBJECT_KEY:{path or '/'}")
            escaped = key.replace("~", "~0").replace("/", "~1")
            result[key] = _normalize(value[key], f"{path}/{escaped}", set_paths)
        return result
    raise ValueError(f"UNSUPPORTED_JSON_TYPE:{path or '/'}")


def _encode(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def canonical_bytes(value: Any) -> bytes:
    kind = value.get("kind") if isinstance(value, dict) else None
    set_paths = {
        "EffectProposal": frozenset({"/preconditions"}),
        "EligibilityVerdict": frozenset({"/support_derivation_ids"}),
    }.get(kind, frozenset())
    return _encode(_normalize(value, set_paths=set_paths))


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def ordered(values: Sequence[Any]) -> list[Any]:
    return [copy.deepcopy(value) for value in sorted(values, key=canonical_bytes)]


def _value_digest(value_kind: str, value: Mapping[str, Any]) -> str:
    return digest({"kind": "M3ValuePreimage", "contract_version": R_CONTRACT,
                   "value_kind": value_kind, "value": copy.deepcopy(value)})


def _delta(source_id: str, logical_time: int, dataflow_version: str,
           value_kind: str, value: Mapping[str, Any]) -> dict[str, Any]:
    value_digest = _value_digest(value_kind, value)
    delivery_digest = digest(
        {"kind": "M3DeliveryPreimage", "contract_version": R_CONTRACT,
         "source_id": source_id, "logical_time": logical_time,
         "dataflow_version": dataflow_version, "value_kind": value_kind,
         "value_digest": value_digest}
    )
    return {
        "kind": "RValueDelta", "schema_version": "flrh-r-value-delta/1",
        "delivery_id": "delivery:" + delivery_digest.split(":", 1)[1],
        "source_id": source_id, "logical_time": logical_time, "diff": 1,
        "dataflow_version": dataflow_version, "value_kind": value_kind,
        "value_digest": value_digest, "value": copy.deepcopy(value),
    }


class OracleReject(Exception):
    def __init__(self, code: str, path: str, context: Mapping[str, Any] | None = None):
        super().__init__(code)
        self.code = code
        self.path = path
        self.context = dict(context or {})


def rejection(code: str, path: str, *, logical_time: int | None,
              binding_profile_digest: str | None, l_fixpoint_digest: str | None,
              query_batch_digest: str | None, r_profile_digest: str | None,
              context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "kind": "LRProjectionRejection", "schema_version": RESULT_SCHEMA,
        "contract_version": LR_CONTRACT, "code": code, "path": path,
        "logical_time": logical_time,
        "binding_profile_digest": binding_profile_digest,
        "l_fixpoint_digest": l_fixpoint_digest,
        "query_batch_digest": query_batch_digest,
        "r_profile_digest": r_profile_digest, "context": dict(context or {}),
    }


def _project_query(query: Mapping[str, Any], facts: Mapping[bytes, Mapping[str, Any]],
                   l_result: Mapping[str, Any], rule_bundle: Mapping[str, Any],
                   binding_profile: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    proposal = copy.deepcopy(query["proposal"])
    proposal["preconditions"] = sorted(proposal["preconditions"])
    supports: set[str] = set()
    evidence_rows: list[dict[str, Any]] = []
    all_satisfied = True
    any_conflict = False
    for requirement in ordered(query["fact_requirements"]):
        literal = requirement["literal"]
        fact = facts.get(canonical_bytes(literal["atom"]))
        if fact is None:
            raise OracleReject(
                "FACT_STATE_NOT_FOUND", "/query_batch/queries/fact_requirements/literal/atom",
                {"proposal_id": proposal["proposal_id"],
                 "precondition_id": requirement["precondition_id"]},
            )
        state = fact["state"]
        if state == "BOTH":
            satisfied, conflict = False, True
            selected = set(fact["positive_support_ids"]) | set(fact["negative_support_ids"])
        elif state == "NEITHER":
            satisfied, conflict, selected = False, False, set()
        elif literal["polarity"] == "positive":
            satisfied, conflict = state == "TRUE_ONLY", False
            selected = set(fact["positive_support_ids"] if satisfied else fact["negative_support_ids"])
        else:
            satisfied, conflict = state == "FALSE_ONLY", False
            selected = set(fact["negative_support_ids"] if satisfied else fact["positive_support_ids"])
        all_satisfied = all_satisfied and satisfied
        any_conflict = any_conflict or conflict
        supports.update(selected)
        evidence_rows.append({
            "kind": "LRRequirementEvidence",
            "precondition_id": requirement["precondition_id"], "literal": copy.deepcopy(literal),
            "fact_key": fact["fact_key"], "truth_state": state, "satisfied": satisfied,
            "evidence_derivation_ids": sorted(selected),
        })
    evidence_rows = ordered(evidence_rows)
    status = "conflicted" if any_conflict else "eligible" if all_satisfied else "ineligible"
    support_ids = sorted(supports)
    verdict_preimage = {
        "kind": "LRVerdictPreimage", "contract_version": LR_CONTRACT,
        "binding_profile_digest": binding_profile["profile_digest"],
        "l_fixpoint_digest": l_result["fixpoint_digest"],
        "l_materialization_digest": l_result["next_materialization"]["materialization_digest"],
        "rule_bundle_digest": rule_bundle["rule_bundle_digest"],
        "proposal_value_digest": _value_digest("effect_proposal", proposal),
        "query_digest": query["query_digest"], "ordered_requirement_evidence": evidence_rows,
        "status": status, "ordered_support_derivation_ids": support_ids,
        "rule_set_version": binding_profile["rule_set_version"],
    }
    suffix = digest(verdict_preimage).split(":", 1)[1]
    verdict = {
        "kind": "EligibilityVerdict", "verdict_id": "verdict:lr:" + suffix,
        "proposal_id": proposal["proposal_id"], "status": status,
        "support_derivation_ids": support_ids, "cause_id": "cause:lr:" + suffix,
        "rule_set_version": binding_profile["rule_set_version"],
    }
    deltas = [
        _delta(binding_profile["proposal_source_id"], l_result["logical_time"],
               binding_profile["dataflow_version"], "effect_proposal", proposal),
        _delta(binding_profile["verdict_source_id"], l_result["logical_time"],
               binding_profile["dataflow_version"], "eligibility_verdict", verdict),
    ]
    return verdict, deltas


def project_expected(l_result: Mapping[str, Any], rule_bundle: Mapping[str, Any],
                     r_profile: Mapping[str, Any], binding_profile: Mapping[str, Any],
                     query_batch: Mapping[str, Any]) -> dict[str, Any]:
    """Return the normative projection for a complete, independently validated input."""

    facts = {canonical_bytes(item["atom"]): item
             for item in l_result["next_materialization"]["fact_states"]}
    verdicts: list[dict[str, Any]] = []
    deltas: list[dict[str, Any]] = []
    normalized_queries = []
    for raw_query in query_batch["queries"]:
        query = copy.deepcopy(raw_query)
        query["proposal"]["preconditions"] = sorted(query["proposal"]["preconditions"])
        query["fact_requirements"] = ordered(query["fact_requirements"])
        query["frontier_precondition_ids"] = sorted(query["frontier_precondition_ids"])
        normalized_queries.append(query)
    for query in ordered(normalized_queries):
        verdict, pair = _project_query(query, facts, l_result, rule_bundle, binding_profile)
        verdicts.append(verdict)
        deltas.extend(pair)
    verdicts = ordered(verdicts)
    deltas = ordered(deltas)
    if len(deltas) > r_profile["limits"]["max_deltas_per_command"]:
        raise OracleReject("LIMIT_EXCEEDED", "/command/deltas",
                           {"limit": r_profile["limits"]["max_deltas_per_command"],
                            "observed": len(deltas)})
    command = None if not deltas else {
        "kind": "RApplyDeltaBatch", "schema_version": "flrh-r-command/1",
        "profile_digest": r_profile["profile_digest"],
        "dataflow_version": binding_profile["dataflow_version"], "deltas": deltas,
    }
    without = {
        "kind": "LRProjectionResult", "schema_version": RESULT_SCHEMA,
        "contract_version": LR_CONTRACT, "logical_time": l_result["logical_time"],
        "binding_profile_digest": binding_profile["profile_digest"],
        "l_fixpoint_digest": l_result["fixpoint_digest"],
        "l_materialization_digest": l_result["next_materialization"]["materialization_digest"],
        "query_batch_digest": query_batch["query_batch_digest"],
        "r_profile_digest": r_profile["profile_digest"], "verdicts": verdicts,
        "command": command,
    }
    preimage = {
        "kind": "LRProjectionPreimage", "contract_version": LR_CONTRACT,
        "logical_time": without["logical_time"],
        "binding_profile_digest": without["binding_profile_digest"],
        "l_fixpoint_digest": without["l_fixpoint_digest"],
        "l_materialization_digest": without["l_materialization_digest"],
        "query_batch_digest": without["query_batch_digest"],
        "r_profile_digest": without["r_profile_digest"],
        "ordered_verdicts": verdicts, "command": command,
    }
    return {**without, "projection_digest": digest(preimage)}


__all__ = ["OracleReject", "canonical_bytes", "digest", "ordered", "project_expected", "rejection"]
