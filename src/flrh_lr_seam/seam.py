"""Pure, deterministic projection from a complete M2 fixpoint into M3 input.

The module deliberately owns no frontier, persistence, authority, or effect
semantics.  It validates explicit closed wires and returns one fresh JSON value.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .canonical import (
    INT64_MAX,
    CanonicalizationError,
    canonical_bytes,
    canonical_digest,
    diagnostic_order_key,
    thaw,
)


CONTRACT_VERSION = "flrh-lr-seam/1"
PROFILE_SCHEMA_VERSION = "flrh-lr-profile/1"
QUERY_SCHEMA_VERSION = "flrh-lr-query/1"
RESULT_SCHEMA_VERSION = "flrh-lr-result/1"
PROFILE_ID = "flrh-lr-four-valued/1"
CANONICALIZATION_VERSION = "flrh-cjson/1"

L_CONTRACT_VERSION = "flrh-l-kernel/1"
L_PROFILE_ID = "flrh-l-ground-stratified/1"
L_RULE_SCHEMA_VERSION = "flrh-l-rules/1"
L_MATERIALIZATION_SCHEMA_VERSION = "flrh-l-materialization/1"
L_RESULT_SCHEMA_VERSION = "flrh-l-result/1"
R_CONTRACT_VERSION = "flrh-r-kernel/1"
R_PROFILE_ID = "flrh-r-scalar-frontier/1"
R_PROFILE_SCHEMA_VERSION = "flrh-r-profile/1"
R_COMMAND_SCHEMA_VERSION = "flrh-r-command/1"
R_VALUE_DELTA_SCHEMA_VERSION = "flrh-r-value-delta/1"

ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/-]*$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")

RULE_BUNDLE_KEYS = frozenset(
    {
        "kind", "schema_version", "contract_version", "profile_id",
        "rule_set_version", "dataflow_version", "canonicalization_version",
        "limits", "query_atoms", "rules", "rule_bundle_digest",
    }
)
RULE_KEYS = frozenset(
    {"kind", "rule_id", "stratum", "head", "required_body",
     "default_not_positive_body", "rule_digest"}
)
LITERAL_KEYS = frozenset({"kind", "polarity", "atom"})
DEFAULT_KEYS = frozenset({"kind", "atom", "referenced_stratum"})
MATERIALIZATION_KEYS = frozenset(
    {"kind", "schema_version", "contract_version", "profile_id",
     "rule_bundle_digest", "rule_set_version", "dataflow_version",
     "canonicalization_version", "through_logical_time", "base_supports",
     "derived_supports", "fact_states", "conflicts", "stratum_digests",
     "materialization_digest"}
)
L_RESULT_KEYS = frozenset(
    {"kind", "schema_version", "contract_version", "logical_time",
     "rule_bundle_digest", "prior_materialization_digest", "input_delta_digests",
     "next_materialization", "derived_fact_deltas", "stats", "fixpoint_digest"}
)
BASE_SUPPORT_KEYS = frozenset(
    {"kind", "derivation_id", "support_content_digest", "literal",
     "provenance_delta", "rule_set_version", "dataflow_version"}
)
DERIVED_SUPPORT_KEYS = frozenset(
    {"kind", "derivation_id", "support_content_digest", "literal", "rule_id",
     "rule_digest", "premise_literal_keys", "default_absence_witnesses",
     "rule_set_version", "dataflow_version"}
)
FACT_STATE_KEYS = frozenset(
    {"kind", "fact_key", "atom", "state", "positive_support_ids",
     "negative_support_ids"}
)
CONFLICT_KEYS = frozenset(
    {"kind", "conflict_id", "fact_key", "atom", "positive_support_ids",
     "negative_support_ids"}
)
STRATUM_KEYS = frozenset({"kind", "stratum", "digest"})
L_FACT_DELTA_INPUT_KEYS = frozenset({"kind", "schema_version", "polarity", "delta"})
FACT_DELTA_KEYS = frozenset(
    {"kind", "tuple", "logical_time", "diff", "derivation_id", "causation_id",
     "provenance_delta", "rule_set_version", "dataflow_version"}
)

R_PROFILE_KEYS = frozenset(
    {"kind", "schema_version", "contract_version", "profile_id",
     "dataflow_version", "canonicalization_version", "source_ids",
     "late_event_policy", "overflow_policy", "limits", "profile_digest"}
)
R_LIMIT_KEYS = frozenset(
    {"max_deltas_per_command", "max_active_values", "max_open_epochs",
     "max_ready_batches", "max_demand_per_command", "max_outstanding_demand"}
)
R_LIMIT_CEILINGS = {
    "max_deltas_per_command": 10000, "max_active_values": 10000,
    "max_open_epochs": 1024, "max_ready_batches": 1024,
    "max_demand_per_command": 1024, "max_outstanding_demand": 10000,
}

BINDING_PROFILE_KEYS = frozenset(
    {"kind", "schema_version", "contract_version", "profile_id",
     "rule_set_version", "dataflow_version", "canonicalization_version",
     "proposal_source_id", "verdict_source_id", "neither_policy",
     "conflict_policy", "limits", "profile_digest"}
)
BINDING_LIMIT_KEYS = frozenset(
    {"max_queries", "max_fact_requirements_per_query"}
)
QUERY_BATCH_KEYS = frozenset(
    {"kind", "schema_version", "contract_version", "binding_profile_digest",
     "l_fixpoint_digest", "rule_bundle_digest", "r_profile_digest", "queries",
     "query_batch_digest"}
)
QUERY_KEYS = frozenset(
    {"kind", "proposal", "fact_requirements", "frontier_precondition_ids",
     "query_digest"}
)
REQUIREMENT_KEYS = frozenset({"kind", "precondition_id", "literal"})

VERSION_KEYS = frozenset(
    {"workflow", "state_schema", "event_schema", "graph_schema", "rule_set",
     "dataflow", "canonicalization", "tool", "model", "oracle", "gate",
     "resolver", "composition_profile"}
)
PROPOSAL_KEYS = frozenset(
    {"kind", "proposal_id", "effect_type", "action_digest", "cause_id",
     "correlation_id", "proposal_dedup_key", "destination_digest", "goal_id",
     "obligation_id", "declared_risk_hint", "preconditions", "versions"}
)

REJECTION_CONTEXT_KEYS = frozenset(
    {"expected", "actual", "invariant", "proposal_id", "precondition_id",
     "source_id", "truth_state", "limit", "observed"}
)

WireResult = Dict[str, Any]


class _Reject(Exception):
    def __init__(
        self, code: str, path: str, context: Optional[Mapping[str, Any]] = None
    ) -> None:
        super().__init__(code)
        self.code = code
        self.path = path
        supplied = dict(context or {})
        self.context = {key: supplied[key] for key in supplied if key in REJECTION_CONTEXT_KEYS}


def _valid_id(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) <= 128
        and ID_PATTERN.fullmatch(value) is not None
    )


def _valid_version(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) <= 128
        and VERSION_PATTERN.fullmatch(value) is not None
    )


def _valid_digest(value: Any) -> bool:
    return isinstance(value, str) and DIGEST_PATTERN.fullmatch(value) is not None


def _valid_time(value: Any) -> bool:
    return (
        isinstance(value, int) and not isinstance(value, bool)
        and 0 <= value <= INT64_MAX
    )


def _exact(value: Any, keys: frozenset[str], code: str, path: str) -> Dict[str, Any]:
    if not isinstance(value, dict) or frozenset(value) != keys:
        raise _Reject(code, path)
    return value


def _canonical_object(value: Any, code: str, path: str, nonempty: bool = False) -> Dict[str, Any]:
    if not isinstance(value, dict) or (nonempty and not value):
        raise _Reject(code, path)
    return thaw(value)


def _sorted_strings(values: Sequence[str]) -> List[str]:
    return sorted(values, key=canonical_bytes)


def _sorted_wires(values: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return [thaw(value) for value in sorted(values, key=canonical_bytes)]


def _diagnostic_query_key(value: Any) -> Tuple[Any, ...]:
    """Order a query independently of all of its declared set-like arrays.

    This order is used only to choose a rejection diagnostic.  Accepted wire
    identity continues to use the contract's canonical preimages below.
    """

    normalized = thaw(value)
    if not isinstance(normalized, dict):
        return diagnostic_order_key(normalized)
    proposal = normalized.get("proposal")
    if isinstance(proposal, dict) and isinstance(proposal.get("preconditions"), list):
        proposal["preconditions"] = sorted(
            proposal["preconditions"], key=diagnostic_order_key
        )
    requirements = normalized.get("fact_requirements")
    if isinstance(requirements, list):
        normalized["fact_requirements"] = sorted(
            requirements, key=diagnostic_order_key
        )
    frontier = normalized.get("frontier_precondition_ids")
    if isinstance(frontier, list):
        normalized["frontier_precondition_ids"] = sorted(
            frontier, key=diagnostic_order_key
        )
    return diagnostic_order_key(normalized)


def _literal(raw: Any, code: str, path: str) -> Dict[str, Any]:
    item = _exact(raw, LITERAL_KEYS, code, path)
    if item["kind"] != "LLiteral":
        raise _Reject(code, path + "/kind")
    if item["polarity"] not in {"positive", "negative"}:
        raise _Reject(code, path + "/polarity")
    atom = _canonical_object(item["atom"], code, path + "/atom", nonempty=True)
    return {"kind": "LLiteral", "polarity": item["polarity"], "atom": atom}


def _fact_key(atom: Mapping[str, Any]) -> str:
    return canonical_digest(
        {"kind": "M2FactKeyPreimage", "contract_version": L_CONTRACT_VERSION,
         "atom": thaw(atom)}
    )


def _project_fact_states(
    query_atoms: Sequence[Mapping[str, Any]],
    base_supports: Sequence[Mapping[str, Any]],
    derived_supports: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Independently reconstruct M2's complete fact-state projection."""

    atoms: Dict[bytes, Dict[str, Any]] = {
        canonical_bytes(atom): thaw(atom) for atom in query_atoms
    }
    positive: Dict[bytes, List[str]] = {}
    negative: Dict[bytes, List[str]] = {}
    for support in list(base_supports) + list(derived_supports):
        atom = thaw(support["literal"]["atom"])
        atom_key = canonical_bytes(atom)
        atoms[atom_key] = atom
        target = (
            positive
            if support["literal"]["polarity"] == "positive"
            else negative
        )
        target.setdefault(atom_key, []).append(support["derivation_id"])

    states: List[Dict[str, Any]] = []
    for atom_key in sorted(atoms):
        atom = atoms[atom_key]
        positive_ids = _sorted_strings(positive.get(atom_key, []))
        negative_ids = _sorted_strings(negative.get(atom_key, []))
        state = (
            "BOTH"
            if positive_ids and negative_ids
            else "TRUE_ONLY"
            if positive_ids
            else "FALSE_ONLY"
            if negative_ids
            else "NEITHER"
        )
        states.append(
            {
                "kind": "LFactState",
                "fact_key": _fact_key(atom),
                "atom": atom,
                "state": state,
                "positive_support_ids": positive_ids,
                "negative_support_ids": negative_ids,
            }
        )
    return _sorted_wires(states)


def _rule_preimage(rule: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "kind": "M2RulePreimage", "contract_version": L_CONTRACT_VERSION,
        "profile_id": L_PROFILE_ID, "rule_id": rule["rule_id"],
        "stratum": rule["stratum"], "head": rule["head"],
        "ordered_required_body": rule["required_body"],
        "ordered_default_not_positive_body": rule["default_not_positive_body"],
    }


def _parse_rule(raw: Any, path: str) -> Dict[str, Any]:
    item = _exact(raw, RULE_KEYS, "MALFORMED_RULE_BUNDLE", path)
    if item["kind"] != "LRule" or not _valid_id(item["rule_id"]):
        raise _Reject("MALFORMED_RULE_BUNDLE", path)
    if not _valid_time(item["stratum"]):
        raise _Reject("MALFORMED_RULE_BUNDLE", path + "/stratum")
    head = _literal(item["head"], "MALFORMED_RULE_BUNDLE", path + "/head")
    required_raw = item["required_body"]
    defaults_raw = item["default_not_positive_body"]
    if (not isinstance(required_raw, list) or len(required_raw) > 64
            or not isinstance(defaults_raw, list) or len(defaults_raw) > 64
            or not required_raw and not defaults_raw):
        raise _Reject("MALFORMED_RULE_BUNDLE", path)
    required = [
        _literal(value, "MALFORMED_RULE_BUNDLE", f"{path}/required_body/{index}")
        for index, value in enumerate(required_raw)
    ]
    required = _sorted_wires(required)
    defaults: List[Dict[str, Any]] = []
    for index, value in enumerate(defaults_raw):
        dpath = f"{path}/default_not_positive_body/{index}"
        default = _exact(value, DEFAULT_KEYS, "MALFORMED_RULE_BUNDLE", dpath)
        if default["kind"] != "LDefaultNotPositive" or not _valid_time(default["referenced_stratum"]):
            raise _Reject("MALFORMED_RULE_BUNDLE", dpath)
        defaults.append({"kind": "LDefaultNotPositive",
                         "atom": _canonical_object(default["atom"], "MALFORMED_RULE_BUNDLE", dpath + "/atom", True),
                         "referenced_stratum": default["referenced_stratum"]})
    defaults = _sorted_wires(defaults)
    if len({canonical_bytes(value) for value in required}) != len(required):
        raise _Reject("MALFORMED_RULE_BUNDLE", path + "/required_body")
    if len({canonical_bytes(value) for value in defaults}) != len(defaults):
        raise _Reject("MALFORMED_RULE_BUNDLE", path + "/default_not_positive_body")
    normalized = {"kind": "LRule", "rule_id": item["rule_id"],
                  "stratum": item["stratum"], "head": head,
                  "required_body": required,
                  "default_not_positive_body": defaults,
                  "rule_digest": item["rule_digest"]}
    expected = canonical_digest(_rule_preimage(normalized))
    if not _valid_digest(item["rule_digest"]) or item["rule_digest"] != expected:
        raise _Reject("DIGEST_MISMATCH", path + "/rule_digest",
                      {"expected": expected, "actual": item["rule_digest"]})
    return normalized


def _parse_rule_bundle(raw: Any) -> Tuple[Dict[str, Any], set[bytes]]:
    item = _exact(raw, RULE_BUNDLE_KEYS, "MALFORMED_RULE_BUNDLE", "/rule_bundle")
    if item["kind"] != "LRuleBundle":
        raise _Reject("MALFORMED_RULE_BUNDLE", "/rule_bundle/kind")
    if item["schema_version"] != L_RULE_SCHEMA_VERSION:
        raise _Reject("UNSUPPORTED_SCHEMA", "/rule_bundle/schema_version")
    if item["contract_version"] != L_CONTRACT_VERSION:
        raise _Reject("UNSUPPORTED_CONTRACT_VERSION", "/rule_bundle/contract_version")
    if item["profile_id"] != L_PROFILE_ID:
        raise _Reject("UNSUPPORTED_PROFILE", "/rule_bundle/profile_id")
    if item["canonicalization_version"] != CANONICALIZATION_VERSION:
        raise _Reject("UNSUPPORTED_CANONICALIZATION", "/rule_bundle/canonicalization_version")
    if not _valid_version(item["rule_set_version"]) or not _valid_version(item["dataflow_version"]):
        raise _Reject("MALFORMED_RULE_BUNDLE", "/rule_bundle")
    limits = _exact(item["limits"], frozenset({"max_rule_firings", "max_derivation_depth"}),
                    "MALFORMED_RULE_BUNDLE", "/rule_bundle/limits")
    if (not isinstance(limits["max_rule_firings"], int)
            or isinstance(limits["max_rule_firings"], bool)
            or not 1 <= limits["max_rule_firings"] <= 1000
            or not isinstance(limits["max_derivation_depth"], int)
            or isinstance(limits["max_derivation_depth"], bool)
            or not 1 <= limits["max_derivation_depth"] <= 8):
        raise _Reject("MALFORMED_RULE_BUNDLE", "/rule_bundle/limits")
    if not isinstance(item["query_atoms"], list) or len(item["query_atoms"]) > 1024:
        raise _Reject("MALFORMED_RULE_BUNDLE", "/rule_bundle/query_atoms")
    query_atoms = [
        _canonical_object(atom, "MALFORMED_RULE_BUNDLE", f"/rule_bundle/query_atoms/{index}", True)
        for index, atom in enumerate(item["query_atoms"])
    ]
    query_atoms = [thaw(atom) for atom in sorted(query_atoms, key=canonical_bytes)]
    query_keys = {canonical_bytes(atom) for atom in query_atoms}
    if len(query_keys) != len(query_atoms):
        raise _Reject("MALFORMED_RULE_BUNDLE", "/rule_bundle/query_atoms")
    if not isinstance(item["rules"], list) or len(item["rules"]) > 256:
        raise _Reject("MALFORMED_RULE_BUNDLE", "/rule_bundle/rules")
    rules = [_parse_rule(value, f"/rule_bundle/rules/{index}")
             for index, value in enumerate(item["rules"])]
    rules = _sorted_wires(rules)
    if len({rule["rule_id"] for rule in rules}) != len(rules):
        raise _Reject("MALFORMED_RULE_BUNDLE", "/rule_bundle/rules")
    if len({rule["rule_digest"] for rule in rules}) != len(rules):
        raise _Reject("MALFORMED_RULE_BUNDLE", "/rule_bundle/rules")
    preimage = {
        "kind": "M2RuleBundlePreimage", "contract_version": L_CONTRACT_VERSION,
        "profile_id": L_PROFILE_ID, "rule_set_version": item["rule_set_version"],
        "dataflow_version": item["dataflow_version"],
        "canonicalization_version": CANONICALIZATION_VERSION,
        "limits": dict(limits), "ordered_query_atoms": query_atoms,
        "ordered_rules": rules,
    }
    expected = canonical_digest(preimage)
    if not _valid_digest(item["rule_bundle_digest"]) or item["rule_bundle_digest"] != expected:
        raise _Reject("DIGEST_MISMATCH", "/rule_bundle/rule_bundle_digest",
                      {"expected": expected, "actual": item["rule_bundle_digest"]})
    normalized = {"kind": "LRuleBundle", "schema_version": L_RULE_SCHEMA_VERSION,
                  "contract_version": L_CONTRACT_VERSION, "profile_id": L_PROFILE_ID,
                  "rule_set_version": item["rule_set_version"],
                  "dataflow_version": item["dataflow_version"],
                  "canonicalization_version": CANONICALIZATION_VERSION,
                  "limits": dict(limits), "query_atoms": query_atoms, "rules": rules,
                  "rule_bundle_digest": expected}
    return normalized, query_keys


def _parse_support(
    raw: Any, path: str, rule_set_version: str, dataflow_version: str,
    rule_digests: Mapping[str, str], derived: bool,
) -> Dict[str, Any]:
    keys = DERIVED_SUPPORT_KEYS if derived else BASE_SUPPORT_KEYS
    item = _exact(raw, keys, "MALFORMED_L_RESULT", path)
    expected_kind = "LDerivedSupport" if derived else "LBaseSupport"
    if item["kind"] != expected_kind or not _valid_id(item["derivation_id"]):
        raise _Reject("MALFORMED_L_RESULT", path)
    if item["rule_set_version"] != rule_set_version or item["dataflow_version"] != dataflow_version:
        raise _Reject("VERSION_MISMATCH", path,
                      {"expected": f"{rule_set_version}|{dataflow_version}",
                       "actual": f"{item['rule_set_version']}|{item['dataflow_version']}"})
    literal = _literal(item["literal"], "MALFORMED_L_RESULT", path + "/literal")
    if derived:
        if not _valid_id(item["rule_id"]) or not _valid_digest(item["rule_digest"]):
            raise _Reject("MALFORMED_L_RESULT", path)
        if rule_digests.get(item["rule_id"]) != item["rule_digest"]:
            raise _Reject("INVARIANT_VIOLATION", path + "/rule_digest",
                          {"invariant": "derived_support_rule_binding"})
        premises = item["premise_literal_keys"]
        if (not isinstance(premises, list) or len(premises) > 64
                or any(not _valid_digest(value) for value in premises)
                or len(set(premises)) != len(premises)):
            raise _Reject("MALFORMED_L_RESULT", path + "/premise_literal_keys")
        premises = _sorted_strings(premises)
        witnesses_raw = item["default_absence_witnesses"]
        if not isinstance(witnesses_raw, list) or len(witnesses_raw) > 64:
            raise _Reject("MALFORMED_L_RESULT", path + "/default_absence_witnesses")
        witnesses: List[Dict[str, Any]] = []
        seen_witnesses: set[bytes] = set()
        witness_keys = frozenset({"kind", "fact_key", "atom", "referenced_stratum",
                                  "completed_stratum_digest", "witness_digest"})
        for index, value in enumerate(witnesses_raw):
            wpath = f"{path}/default_absence_witnesses/{index}"
            witness = _exact(value, witness_keys, "MALFORMED_L_RESULT", wpath)
            atom = _canonical_object(witness["atom"], "MALFORMED_L_RESULT", wpath + "/atom", True)
            if (witness["kind"] != "LAbsenceWitness"
                    or witness["fact_key"] != _fact_key(atom)
                    or not _valid_time(witness["referenced_stratum"])
                    or not _valid_digest(witness["completed_stratum_digest"])):
                raise _Reject("MALFORMED_L_RESULT", wpath)
            normalized_witness = {
                "kind": "LAbsenceWitness", "fact_key": witness["fact_key"],
                "atom": atom, "referenced_stratum": witness["referenced_stratum"],
                "completed_stratum_digest": witness["completed_stratum_digest"],
                "witness_digest": witness["witness_digest"],
            }
            expected_witness = canonical_digest(
                {"kind": "M2AbsenceWitnessPreimage", "contract_version": L_CONTRACT_VERSION,
                 "fact_key": witness["fact_key"], "atom": atom,
                 "referenced_stratum": witness["referenced_stratum"],
                 "completed_stratum_digest": witness["completed_stratum_digest"]}
            )
            if witness["witness_digest"] != expected_witness:
                raise _Reject("DIGEST_MISMATCH", wpath + "/witness_digest",
                              {"expected": expected_witness, "actual": witness["witness_digest"]})
            witness_key = canonical_bytes(normalized_witness)
            if witness_key in seen_witnesses:
                raise _Reject("MALFORMED_L_RESULT", wpath)
            seen_witnesses.add(witness_key)
            witnesses.append(normalized_witness)
        witnesses = _sorted_wires(witnesses)
        preimage = {
            "kind": "M2DerivedSupportContentPreimage", "contract_version": L_CONTRACT_VERSION,
            "profile_id": L_PROFILE_ID, "literal": literal, "rule_id": item["rule_id"],
            "rule_digest": item["rule_digest"], "ordered_premise_literal_keys": premises,
            "ordered_default_absence_witness_digests": [value["witness_digest"] for value in witnesses],
            "rule_set_version": rule_set_version, "dataflow_version": dataflow_version,
        }
        content_digest = canonical_digest(preimage)
        normalized = {
            "kind": expected_kind, "derivation_id": item["derivation_id"],
            "support_content_digest": item["support_content_digest"], "literal": literal,
            "rule_id": item["rule_id"], "rule_digest": item["rule_digest"],
            "premise_literal_keys": premises, "default_absence_witnesses": witnesses,
            "rule_set_version": rule_set_version, "dataflow_version": dataflow_version,
        }
    else:
        provenance = _canonical_object(item["provenance_delta"], "MALFORMED_L_RESULT",
                                       path + "/provenance_delta", True)
        content_digest = canonical_digest(
            {"kind": "M2BaseSupportContentPreimage", "contract_version": L_CONTRACT_VERSION,
             "profile_id": L_PROFILE_ID, "literal": literal,
             "provenance_delta": provenance, "rule_set_version": rule_set_version,
             "dataflow_version": dataflow_version}
        )
        normalized = {
            "kind": expected_kind, "derivation_id": item["derivation_id"],
            "support_content_digest": item["support_content_digest"], "literal": literal,
            "provenance_delta": provenance, "rule_set_version": rule_set_version,
            "dataflow_version": dataflow_version,
        }
    if item["support_content_digest"] != content_digest:
        raise _Reject("DIGEST_MISMATCH", path + "/support_content_digest",
                      {"expected": content_digest, "actual": item["support_content_digest"]})
    # Base identities are explicit caller support identities.  Only derived
    # supports use the content-addressed identity minted by M2.
    expected_id = "derivation:" + content_digest.split(":", 1)[1]
    if derived and item["derivation_id"] != expected_id:
        raise _Reject("DIGEST_MISMATCH", path + "/derivation_id",
                      {"expected": expected_id, "actual": item["derivation_id"]})
    return normalized


def _parse_materialization(
    raw: Any, bundle: Mapping[str, Any]
) -> Tuple[Dict[str, Any], Dict[bytes, Dict[str, Any]], set[bytes]]:
    path = "/l_result/next_materialization"
    item = _exact(raw, MATERIALIZATION_KEYS, "MALFORMED_L_RESULT", path)
    constants = {
        "kind": "LMaterialization", "schema_version": L_MATERIALIZATION_SCHEMA_VERSION,
        "contract_version": L_CONTRACT_VERSION, "profile_id": L_PROFILE_ID,
        "canonicalization_version": CANONICALIZATION_VERSION,
    }
    for key, expected in constants.items():
        if item[key] != expected:
            code = "UNSUPPORTED_SCHEMA" if key == "schema_version" else (
                "UNSUPPORTED_CONTRACT_VERSION" if key == "contract_version" else
                "UNSUPPORTED_PROFILE" if key == "profile_id" else
                "UNSUPPORTED_CANONICALIZATION" if key == "canonicalization_version" else
                "MALFORMED_L_RESULT"
            )
            raise _Reject(code, f"{path}/{key}")
    for key in ("rule_bundle_digest", "rule_set_version", "dataflow_version"):
        if item[key] != bundle[key]:
            raise _Reject("VERSION_MISMATCH" if key != "rule_bundle_digest" else "DIGEST_MISMATCH",
                          f"{path}/{key}", {"expected": bundle[key], "actual": item[key]})
    if item["through_logical_time"] is not None and not _valid_time(item["through_logical_time"]):
        raise _Reject("MALFORMED_L_RESULT", path + "/through_logical_time")
    rule_digests = {rule["rule_id"]: rule["rule_digest"] for rule in bundle["rules"]}
    if not isinstance(item["base_supports"], list) or not isinstance(item["derived_supports"], list):
        raise _Reject("MALFORMED_L_RESULT", path)
    base = [_parse_support(value, f"{path}/base_supports/{index}",
                           bundle["rule_set_version"], bundle["dataflow_version"],
                           rule_digests, False)
            for index, value in enumerate(item["base_supports"])]
    derived = [_parse_support(value, f"{path}/derived_supports/{index}",
                              bundle["rule_set_version"], bundle["dataflow_version"],
                              rule_digests, True)
               for index, value in enumerate(item["derived_supports"])]
    base, derived = _sorted_wires(base), _sorted_wires(derived)
    support_by_id: Dict[str, Tuple[bytes, str]] = {}
    for support in base + derived:
        identifier = support["derivation_id"]
        if identifier in support_by_id:
            raise _Reject("INVARIANT_VIOLATION", path,
                          {"invariant": "globally_unique_support_identity"})
        support_by_id[identifier] = (canonical_bytes(support["literal"]["atom"]),
                                     support["literal"]["polarity"])
    if not isinstance(item["fact_states"], list):
        raise _Reject("MALFORMED_L_RESULT", path + "/fact_states")
    facts: List[Dict[str, Any]] = []
    fact_by_atom: Dict[bytes, Dict[str, Any]] = {}
    seen_supports: set[str] = set()
    for index, value in enumerate(item["fact_states"]):
        fpath = f"{path}/fact_states/{index}"
        fact = _exact(value, FACT_STATE_KEYS, "MALFORMED_L_RESULT", fpath)
        atom = _canonical_object(fact["atom"], "MALFORMED_L_RESULT", fpath + "/atom", True)
        atom_key = canonical_bytes(atom)
        if fact["kind"] != "LFactState" or fact["fact_key"] != _fact_key(atom):
            raise _Reject("INVARIANT_VIOLATION", fpath, {"invariant": "fact_key_atom_binding"})
        positive, negative = fact["positive_support_ids"], fact["negative_support_ids"]
        if (not isinstance(positive, list) or not isinstance(negative, list)
                or any(not _valid_id(value) for value in positive + negative)
                or len(set(positive)) != len(positive) or len(set(negative)) != len(negative)):
            raise _Reject("MALFORMED_L_RESULT", fpath)
        positive, negative = _sorted_strings(positive), _sorted_strings(negative)
        expected_state = ("BOTH" if positive and negative else "TRUE_ONLY" if positive
                          else "FALSE_ONLY" if negative else "NEITHER")
        if fact["state"] != expected_state:
            raise _Reject("INVARIANT_VIOLATION", fpath + "/state",
                          {"expected": expected_state, "actual": fact["state"]})
        if atom_key in fact_by_atom:
            raise _Reject("INVARIANT_VIOLATION", fpath, {"invariant": "unique_fact_state_atom"})
        for support_id, polarity in [(value, "positive") for value in positive] + [(value, "negative") for value in negative]:
            if support_by_id.get(support_id) != (atom_key, polarity):
                raise _Reject("INVARIANT_VIOLATION", fpath,
                              {"invariant": "fact_state_support_binding"})
            seen_supports.add(support_id)
        normalized = {"kind": "LFactState", "fact_key": fact["fact_key"], "atom": atom,
                      "state": expected_state, "positive_support_ids": positive,
                      "negative_support_ids": negative}
        facts.append(normalized)
        fact_by_atom[atom_key] = normalized
    if seen_supports != set(support_by_id):
        raise _Reject("INVARIANT_VIOLATION", path + "/fact_states",
                      {"invariant": "all_supports_projected_once"})
    facts = _sorted_wires(facts)
    expected_final_facts = _project_fact_states(
        bundle["query_atoms"], base, derived
    )
    expected_fact_keys = {
        canonical_bytes(fact["atom"]) for fact in expected_final_facts
    }
    actual_fact_keys = set(fact_by_atom)
    if actual_fact_keys - expected_fact_keys:
        raise _Reject(
            "INVARIANT_VIOLATION",
            path + "/fact_states",
            {"invariant": "complete_fact_state_projection"},
        )
    missing_fact_keys = expected_fact_keys - actual_fact_keys
    if not isinstance(item["conflicts"], list):
        raise _Reject("MALFORMED_L_RESULT", path + "/conflicts")
    conflicts: List[Dict[str, Any]] = []
    seen_conflicts: set[bytes] = set()
    for index, value in enumerate(item["conflicts"]):
        cpath = f"{path}/conflicts/{index}"
        conflict = _exact(value, CONFLICT_KEYS, "MALFORMED_L_RESULT", cpath)
        atom = _canonical_object(conflict["atom"], "MALFORMED_L_RESULT", cpath + "/atom", True)
        for field in ("positive_support_ids", "negative_support_ids"):
            support_ids = conflict[field]
            if (not isinstance(support_ids, list) or not support_ids
                    or any(not _valid_id(support_id) for support_id in support_ids)
                    or len(set(support_ids)) != len(support_ids)):
                raise _Reject("MALFORMED_L_RESULT", f"{cpath}/{field}")
        fact = fact_by_atom.get(canonical_bytes(atom))
        if (conflict["kind"] != "LConflict" or fact is None or fact["state"] != "BOTH"
                or conflict["fact_key"] != fact["fact_key"]
                or _sorted_strings(conflict["positive_support_ids"]) != fact["positive_support_ids"]
                or _sorted_strings(conflict["negative_support_ids"]) != fact["negative_support_ids"]):
            raise _Reject("INVARIANT_VIOLATION", cpath, {"invariant": "conflict_fact_binding"})
        preimage = {"kind": "M2ConflictPreimage", "contract_version": L_CONTRACT_VERSION,
                    "fact_key": fact["fact_key"], "atom": atom,
                    "ordered_positive_support_ids": fact["positive_support_ids"],
                    "ordered_negative_support_ids": fact["negative_support_ids"]}
        expected_id = "conflict:" + canonical_digest(preimage).split(":", 1)[1]
        if conflict["conflict_id"] != expected_id:
            raise _Reject("DIGEST_MISMATCH", cpath + "/conflict_id",
                          {"expected": expected_id, "actual": conflict["conflict_id"]})
        normalized_conflict = {"kind": "LConflict", "conflict_id": expected_id,
                               "fact_key": fact["fact_key"], "atom": atom,
                               "positive_support_ids": fact["positive_support_ids"],
                               "negative_support_ids": fact["negative_support_ids"]}
        conflict_key = canonical_bytes(normalized_conflict)
        if conflict_key in seen_conflicts:
            raise _Reject("MALFORMED_L_RESULT", cpath)
        seen_conflicts.add(conflict_key)
        conflicts.append(normalized_conflict)
    if len(conflicts) != sum(1 for fact in facts if fact["state"] == "BOTH"):
        raise _Reject("INVARIANT_VIOLATION", path + "/conflicts",
                      {"invariant": "all_conflicts_projected_once"})
    conflicts = _sorted_wires(conflicts)
    if not isinstance(item["stratum_digests"], list):
        raise _Reject("MALFORMED_L_RESULT", path + "/stratum_digests")
    strata: List[Dict[str, Any]] = []
    seen_strata: set[int] = set()
    for index, value in enumerate(item["stratum_digests"]):
        spath = f"{path}/stratum_digests/{index}"
        stratum = _exact(value, STRATUM_KEYS, "MALFORMED_L_RESULT", spath)
        if stratum["kind"] != "LStratumDigest" or not _valid_time(stratum["stratum"]) or not _valid_digest(stratum["digest"]):
            raise _Reject("MALFORMED_L_RESULT", spath)
        normalized_stratum = dict(stratum)
        if normalized_stratum["stratum"] in seen_strata:
            raise _Reject("MALFORMED_L_RESULT", spath)
        seen_strata.add(normalized_stratum["stratum"])
        strata.append(normalized_stratum)
    strata = _sorted_wires(strata)
    declared_strata = sorted(
        {
            stratum
            for rule in bundle["rules"]
            for stratum in (
                [rule["stratum"]]
                + [
                    default["referenced_stratum"]
                    for default in rule["default_not_positive_body"]
                ]
            )
        }
    )
    if [entry["stratum"] for entry in strata] != declared_strata:
        raise _Reject("MALFORMED_L_RESULT", path + "/stratum_digests")
    rule_strata = {
        rule["rule_id"]: rule["stratum"] for rule in bundle["rules"]
    }
    completed_digest_by_stratum: Dict[int, str] = {}
    for index, entry in enumerate(strata):
        completed_derived = [
            support
            for support in derived
            if rule_strata[support["rule_id"]] <= entry["stratum"]
        ]
        completed_facts = _project_fact_states(
            bundle["query_atoms"], base, completed_derived
        )
        expected_stratum_digest = canonical_digest(
            {
                "kind": "M2StratumPreimage",
                "contract_version": L_CONTRACT_VERSION,
                "profile_id": L_PROFILE_ID,
                "rule_bundle_digest": bundle["rule_bundle_digest"],
                "stratum": entry["stratum"],
                "ordered_base_supports": base,
                "ordered_derived_supports": completed_derived,
                "ordered_fact_states": completed_facts,
            }
        )
        if entry["digest"] != expected_stratum_digest:
            raise _Reject(
                "DIGEST_MISMATCH",
                f"{path}/stratum_digests/{index}/digest",
                {"expected": expected_stratum_digest, "actual": entry["digest"]},
            )
        completed_digest_by_stratum[entry["stratum"]] = expected_stratum_digest
    for support_index, support in enumerate(derived):
        for witness_index, witness in enumerate(
            support["default_absence_witnesses"]
        ):
            expected_completed_digest = completed_digest_by_stratum.get(
                witness["referenced_stratum"]
            )
            if witness["completed_stratum_digest"] != expected_completed_digest:
                raise _Reject(
                    "DIGEST_MISMATCH",
                    (
                        f"{path}/derived_supports/{support_index}/"
                        f"default_absence_witnesses/{witness_index}/"
                        "completed_stratum_digest"
                    ),
                    {
                        "expected": expected_completed_digest,
                        "actual": witness["completed_stratum_digest"],
                    },
                )
    without_digest = {
        "kind": "LMaterialization", "schema_version": L_MATERIALIZATION_SCHEMA_VERSION,
        "contract_version": L_CONTRACT_VERSION, "profile_id": L_PROFILE_ID,
        "rule_bundle_digest": bundle["rule_bundle_digest"],
        "rule_set_version": bundle["rule_set_version"],
        "dataflow_version": bundle["dataflow_version"],
        "canonicalization_version": CANONICALIZATION_VERSION,
        "through_logical_time": item["through_logical_time"], "base_supports": base,
        "derived_supports": derived, "fact_states": facts, "conflicts": conflicts,
        "stratum_digests": strata,
    }
    expected = canonical_digest(
        {"kind": "M2MaterializationPreimage", "contract_version": L_CONTRACT_VERSION,
         "materialization_without_materialization_digest": without_digest}
    )
    if item["materialization_digest"] != expected:
        raise _Reject("DIGEST_MISMATCH", path + "/materialization_digest",
                      {"expected": expected, "actual": item["materialization_digest"]})
    normalized = dict(without_digest)
    normalized["materialization_digest"] = expected
    return normalized, fact_by_atom, missing_fact_keys


def _parse_l_result(
    raw: Any, bundle: Mapping[str, Any]
) -> Tuple[Dict[str, Any], Dict[bytes, Dict[str, Any]], set[bytes]]:
    item = _exact(raw, L_RESULT_KEYS, "MALFORMED_L_RESULT", "/l_result")
    if item["kind"] != "LFixpointResult":
        raise _Reject("MALFORMED_L_RESULT", "/l_result/kind")
    if item["schema_version"] != L_RESULT_SCHEMA_VERSION:
        raise _Reject("UNSUPPORTED_SCHEMA", "/l_result/schema_version")
    if item["contract_version"] != L_CONTRACT_VERSION:
        raise _Reject("UNSUPPORTED_CONTRACT_VERSION", "/l_result/contract_version")
    if not _valid_time(item["logical_time"]):
        raise _Reject("MALFORMED_L_RESULT", "/l_result/logical_time")
    if item["rule_bundle_digest"] != bundle["rule_bundle_digest"]:
        raise _Reject("DIGEST_MISMATCH", "/l_result/rule_bundle_digest",
                      {"expected": bundle["rule_bundle_digest"], "actual": item["rule_bundle_digest"]})
    if item["prior_materialization_digest"] is not None and not _valid_digest(item["prior_materialization_digest"]):
        raise _Reject("MALFORMED_L_RESULT", "/l_result/prior_materialization_digest")
    if (not isinstance(item["input_delta_digests"], list)
            or any(not _valid_digest(value) for value in item["input_delta_digests"])
            or len(set(item["input_delta_digests"])) != len(item["input_delta_digests"])):
        raise _Reject("MALFORMED_L_RESULT", "/l_result/input_delta_digests")
    materialization, facts, missing_fact_keys = _parse_materialization(
        item["next_materialization"], bundle
    )
    if materialization["through_logical_time"] != item["logical_time"]:
        raise _Reject("INVARIANT_VIOLATION", "/l_result/next_materialization/through_logical_time",
                      {"expected": item["logical_time"], "actual": materialization["through_logical_time"]})
    if not isinstance(item["derived_fact_deltas"], list):
        raise _Reject("MALFORMED_L_RESULT", "/l_result/derived_fact_deltas")
    derived_deltas: List[Dict[str, Any]] = []
    ordered_delta_inputs = sorted(item["derived_fact_deltas"], key=diagnostic_order_key)
    for index, value in enumerate(ordered_delta_inputs):
        dpath = f"/l_result/derived_fact_deltas/{index}"
        delta_input = _exact(value, L_FACT_DELTA_INPUT_KEYS, "MALFORMED_L_RESULT", dpath)
        if delta_input["kind"] != "LFactDeltaInput":
            raise _Reject("MALFORMED_L_RESULT", dpath + "/kind")
        if delta_input["schema_version"] != "flrh-l-input/1":
            raise _Reject("UNSUPPORTED_SCHEMA", dpath + "/schema_version")
        if delta_input["polarity"] not in {"positive", "negative"}:
            raise _Reject("MALFORMED_L_RESULT", dpath + "/polarity")
        delta = _exact(
            delta_input["delta"], FACT_DELTA_KEYS, "MALFORMED_L_RESULT",
            dpath + "/delta",
        )
        if delta["kind"] != "FactDelta":
            raise _Reject("MALFORMED_L_RESULT", dpath + "/delta/kind")
        if not _valid_time(delta["logical_time"]):
            raise _Reject("MALFORMED_L_RESULT", dpath + "/delta/logical_time")
        if delta["logical_time"] != item["logical_time"]:
            raise _Reject(
                "INVARIANT_VIOLATION", dpath + "/delta/logical_time",
                {"expected": item["logical_time"], "actual": delta["logical_time"]},
            )
        if delta["diff"] not in {-1, 1} or isinstance(delta["diff"], bool):
            raise _Reject("MALFORMED_L_RESULT", dpath + "/delta/diff")
        if not _valid_id(delta["derivation_id"]) or not _valid_id(delta["causation_id"]):
            raise _Reject("MALFORMED_L_RESULT", dpath + "/delta")
        tuple_value = _canonical_object(
            delta["tuple"], "MALFORMED_L_RESULT", dpath + "/delta/tuple", True
        )
        provenance = _canonical_object(
            delta["provenance_delta"], "MALFORMED_L_RESULT",
            dpath + "/delta/provenance_delta", True,
        )
        for key, expected_version in (
            ("rule_set_version", bundle["rule_set_version"]),
            ("dataflow_version", bundle["dataflow_version"]),
        ):
            if not _valid_version(delta[key]):
                raise _Reject("MALFORMED_L_RESULT", f"{dpath}/delta/{key}")
            if delta[key] != expected_version:
                raise _Reject(
                    "VERSION_MISMATCH", f"{dpath}/delta/{key}",
                    {"expected": expected_version, "actual": delta[key]},
                )
        derived_deltas.append({
            "kind": "LFactDeltaInput", "schema_version": "flrh-l-input/1",
            "polarity": delta_input["polarity"],
            "delta": {
                "kind": "FactDelta", "tuple": tuple_value,
                "logical_time": delta["logical_time"], "diff": delta["diff"],
                "derivation_id": delta["derivation_id"],
                "causation_id": delta["causation_id"],
                "provenance_delta": provenance,
                "rule_set_version": delta["rule_set_version"],
                "dataflow_version": delta["dataflow_version"],
            },
        })
    derived_deltas = _sorted_wires(derived_deltas)
    if len({canonical_bytes(value) for value in derived_deltas}) != len(derived_deltas):
        raise _Reject("MALFORMED_L_RESULT", "/l_result/derived_fact_deltas")
    stats_keys = frozenset({"evaluation_mode", "rule_evaluation_count", "rule_firing_count",
                            "worklist_pop_count", "max_derivation_depth"})
    stats = _exact(item["stats"], stats_keys, "MALFORMED_L_RESULT", "/l_result/stats")
    if stats["evaluation_mode"] != "full_recompute":
        raise _Reject("MALFORMED_L_RESULT", "/l_result/stats")
    for key in (
        "rule_evaluation_count", "rule_firing_count", "worklist_pop_count",
        "max_derivation_depth",
    ):
        if not isinstance(stats[key], int) or isinstance(stats[key], bool) or stats[key] < 0:
            raise _Reject("MALFORMED_L_RESULT", f"/l_result/stats/{key}")
    if stats["rule_firing_count"] > 1000:
        raise _Reject("MALFORMED_L_RESULT", "/l_result/stats/rule_firing_count")
    if stats["max_derivation_depth"] > 8:
        raise _Reject("MALFORMED_L_RESULT", "/l_result/stats/max_derivation_depth")
    without_digest = {
        "kind": "LFixpointResult", "schema_version": L_RESULT_SCHEMA_VERSION,
        "contract_version": L_CONTRACT_VERSION, "logical_time": item["logical_time"],
        "rule_bundle_digest": bundle["rule_bundle_digest"],
        "prior_materialization_digest": item["prior_materialization_digest"],
        "input_delta_digests": _sorted_strings(item["input_delta_digests"]),
        "next_materialization": materialization, "derived_fact_deltas": derived_deltas,
        "stats": dict(stats),
    }
    expected = canonical_digest(
        {"kind": "M2FixpointPreimage", "contract_version": L_CONTRACT_VERSION,
         "fixpoint_result_without_fixpoint_digest": without_digest}
    )
    if item["fixpoint_digest"] != expected:
        raise _Reject("DIGEST_MISMATCH", "/l_result/fixpoint_digest",
                      {"expected": expected, "actual": item["fixpoint_digest"]})
    normalized = dict(without_digest)
    normalized["fixpoint_digest"] = expected
    return normalized, facts, missing_fact_keys


def _parse_r_profile(raw: Any) -> Dict[str, Any]:
    item = _exact(raw, R_PROFILE_KEYS, "MALFORMED_R_PROFILE", "/r_profile")
    if item["kind"] != "RDataflowProfile":
        raise _Reject("MALFORMED_R_PROFILE", "/r_profile/kind")
    if item["schema_version"] != R_PROFILE_SCHEMA_VERSION:
        raise _Reject("UNSUPPORTED_SCHEMA", "/r_profile/schema_version")
    if item["contract_version"] != R_CONTRACT_VERSION:
        raise _Reject("UNSUPPORTED_CONTRACT_VERSION", "/r_profile/contract_version")
    if item["profile_id"] != R_PROFILE_ID:
        raise _Reject("UNSUPPORTED_PROFILE", "/r_profile/profile_id")
    if item["canonicalization_version"] != CANONICALIZATION_VERSION:
        raise _Reject("UNSUPPORTED_CANONICALIZATION", "/r_profile/canonicalization_version")
    if not _valid_version(item["dataflow_version"]):
        raise _Reject("MALFORMED_R_PROFILE", "/r_profile/dataflow_version")
    sources = item["source_ids"]
    if (not isinstance(sources, list) or not 1 <= len(sources) <= 256
            or any(not _valid_id(value) for value in sources)
            or len(set(sources)) != len(sources)):
        raise _Reject("MALFORMED_R_PROFILE", "/r_profile/source_ids")
    sources = _sorted_strings(sources)
    if item["late_event_policy"] != "reject" or item["overflow_policy"] != "reject_new":
        raise _Reject("UNSUPPORTED_PROFILE", "/r_profile")
    limits = _exact(item["limits"], R_LIMIT_KEYS, "MALFORMED_R_PROFILE", "/r_profile/limits")
    for key, ceiling in R_LIMIT_CEILINGS.items():
        value = limits[key]
        if (not isinstance(value, int) or isinstance(value, bool)
                or not 1 <= value <= ceiling):
            raise _Reject("MALFORMED_R_PROFILE", f"/r_profile/limits/{key}")
    normalized = {
        "kind": "RDataflowProfile", "schema_version": R_PROFILE_SCHEMA_VERSION,
        "contract_version": R_CONTRACT_VERSION, "profile_id": R_PROFILE_ID,
        "dataflow_version": item["dataflow_version"],
        "canonicalization_version": CANONICALIZATION_VERSION,
        "source_ids": sources, "late_event_policy": "reject",
        "overflow_policy": "reject_new", "limits": dict(limits),
        "profile_digest": item["profile_digest"],
    }
    preimage = {
        "kind": "M3ProfilePreimage", "contract_version": R_CONTRACT_VERSION,
        "profile_id": R_PROFILE_ID, "dataflow_version": item["dataflow_version"],
        "canonicalization_version": CANONICALIZATION_VERSION,
        "ordered_source_ids": sources, "late_event_policy": "reject",
        "overflow_policy": "reject_new", "limits": dict(limits),
    }
    expected = canonical_digest(preimage)
    if item["profile_digest"] != expected:
        raise _Reject("PROFILE_MISMATCH", "/r_profile/profile_digest",
                      {"expected": expected, "actual": item["profile_digest"]})
    return normalized


def _parse_binding_profile(raw: Any, bundle: Mapping[str, Any], r_profile: Mapping[str, Any]) -> Dict[str, Any]:
    item = _exact(raw, BINDING_PROFILE_KEYS, "MALFORMED_BINDING_PROFILE", "/binding_profile")
    if item["kind"] != "LRBindingProfile":
        raise _Reject("MALFORMED_BINDING_PROFILE", "/binding_profile/kind")
    if item["schema_version"] != PROFILE_SCHEMA_VERSION:
        raise _Reject("UNSUPPORTED_SCHEMA", "/binding_profile/schema_version")
    if item["contract_version"] != CONTRACT_VERSION:
        raise _Reject("UNSUPPORTED_CONTRACT_VERSION", "/binding_profile/contract_version")
    if item["profile_id"] != PROFILE_ID:
        raise _Reject("UNSUPPORTED_PROFILE", "/binding_profile/profile_id")
    if item["canonicalization_version"] != CANONICALIZATION_VERSION:
        raise _Reject("UNSUPPORTED_CANONICALIZATION", "/binding_profile/canonicalization_version")
    if item["rule_set_version"] != bundle["rule_set_version"]:
        raise _Reject("VERSION_MISMATCH", "/binding_profile/rule_set_version",
                      {"expected": bundle["rule_set_version"], "actual": item["rule_set_version"]})
    if item["dataflow_version"] != bundle["dataflow_version"] or item["dataflow_version"] != r_profile["dataflow_version"]:
        raise _Reject("VERSION_MISMATCH", "/binding_profile/dataflow_version",
                      {"expected": bundle["dataflow_version"], "actual": item["dataflow_version"]})
    for key in ("proposal_source_id", "verdict_source_id"):
        if not _valid_id(item[key]):
            raise _Reject("MALFORMED_BINDING_PROFILE", f"/binding_profile/{key}")
        if item[key] not in r_profile["source_ids"]:
            raise _Reject("PROFILE_MISMATCH", f"/binding_profile/{key}",
                          {"source_id": item[key], "invariant": "source_declared_by_r_profile"})
    if item["neither_policy"] != "deny_unproven" or item["conflict_policy"] != "emit_conflicted":
        raise _Reject("UNSUPPORTED_PROFILE", "/binding_profile")
    limits = _exact(item["limits"], BINDING_LIMIT_KEYS, "MALFORMED_BINDING_PROFILE",
                    "/binding_profile/limits")
    if (not isinstance(limits["max_queries"], int) or isinstance(limits["max_queries"], bool)
            or not 1 <= limits["max_queries"] <= 1024
            or not isinstance(limits["max_fact_requirements_per_query"], int)
            or isinstance(limits["max_fact_requirements_per_query"], bool)
            or not 1 <= limits["max_fact_requirements_per_query"] <= 64):
        raise _Reject("MALFORMED_BINDING_PROFILE", "/binding_profile/limits")
    preimage = {
        "kind": "LRProfilePreimage", "contract_version": CONTRACT_VERSION,
        "profile_id": PROFILE_ID, "rule_set_version": item["rule_set_version"],
        "dataflow_version": item["dataflow_version"],
        "canonicalization_version": CANONICALIZATION_VERSION,
        "proposal_source_id": item["proposal_source_id"],
        "verdict_source_id": item["verdict_source_id"],
        "neither_policy": "deny_unproven", "conflict_policy": "emit_conflicted",
        "limits": dict(limits),
    }
    expected = canonical_digest(preimage)
    if item["profile_digest"] != expected:
        raise _Reject("PROFILE_MISMATCH", "/binding_profile/profile_digest",
                      {"expected": expected, "actual": item["profile_digest"]})
    normalized = dict(item)
    normalized["limits"] = dict(limits)
    return thaw(normalized)


def _parse_proposal(raw: Any, path: str) -> Dict[str, Any]:
    item = _exact(raw, PROPOSAL_KEYS, "MALFORMED_QUERY_BATCH", path)
    if item["kind"] != "EffectProposal":
        raise _Reject("MALFORMED_QUERY_BATCH", path + "/kind")
    for key in ("proposal_id", "effect_type", "cause_id", "correlation_id",
                "proposal_dedup_key", "goal_id", "obligation_id"):
        if not _valid_id(item[key]):
            raise _Reject("MALFORMED_QUERY_BATCH", f"{path}/{key}")
    if not _valid_digest(item["action_digest"]) or not _valid_digest(item["destination_digest"]):
        raise _Reject("MALFORMED_QUERY_BATCH", path)
    if item["declared_risk_hint"] not in {"read_only", "reversible", "high_risk_external", "unknown"}:
        raise _Reject("MALFORMED_QUERY_BATCH", path + "/declared_risk_hint")
    preconditions = item["preconditions"]
    if (not isinstance(preconditions, list) or any(not _valid_id(value) for value in preconditions)
            or len(set(preconditions)) != len(preconditions)):
        raise _Reject("MALFORMED_QUERY_BATCH", path + "/preconditions")
    versions = _exact(item["versions"], VERSION_KEYS, "MALFORMED_QUERY_BATCH", path + "/versions")
    if any(not _valid_version(value) for value in versions.values()):
        raise _Reject("MALFORMED_QUERY_BATCH", path + "/versions")
    normalized = dict(item)
    normalized["preconditions"] = _sorted_strings(preconditions)
    normalized["versions"] = dict(versions)
    return thaw(normalized)


def _parse_query_batch(
    raw: Any, l_result: Mapping[str, Any], bundle: Mapping[str, Any],
    r_profile: Mapping[str, Any], binding: Mapping[str, Any], query_atoms: set[bytes],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    item = _exact(raw, QUERY_BATCH_KEYS, "MALFORMED_QUERY_BATCH", "/query_batch")
    if item["kind"] != "LRQueryBatch":
        raise _Reject("MALFORMED_QUERY_BATCH", "/query_batch/kind")
    if item["schema_version"] != QUERY_SCHEMA_VERSION:
        raise _Reject("UNSUPPORTED_SCHEMA", "/query_batch/schema_version")
    if item["contract_version"] != CONTRACT_VERSION:
        raise _Reject("UNSUPPORTED_CONTRACT_VERSION", "/query_batch/contract_version")
    bindings = (
        ("binding_profile_digest", binding["profile_digest"]),
        ("l_fixpoint_digest", l_result["fixpoint_digest"]),
        ("rule_bundle_digest", bundle["rule_bundle_digest"]),
        ("r_profile_digest", r_profile["profile_digest"]),
    )
    for key, expected in bindings:
        if item[key] != expected:
            raise _Reject("DIGEST_MISMATCH", f"/query_batch/{key}",
                          {"expected": expected, "actual": item[key]})
    queries_raw = item["queries"]
    if not isinstance(queries_raw, list):
        raise _Reject("MALFORMED_QUERY_BATCH", "/query_batch/queries")
    if len(queries_raw) > binding["limits"]["max_queries"]:
        raise _Reject("LIMIT_EXCEEDED", "/query_batch/queries",
                      {"limit": binding["limits"]["max_queries"], "observed": len(queries_raw)})
    # Query arrays are identity sets.  Choose diagnostics only after applying a
    # stable order that also ignores permutations in their nested set fields.
    queries_raw = sorted(queries_raw, key=_diagnostic_query_key)
    queries: List[Dict[str, Any]] = []
    proposal_ids: set[str] = set()
    for index, value in enumerate(queries_raw):
        qpath = f"/query_batch/queries/{index}"
        query = _exact(value, QUERY_KEYS, "MALFORMED_QUERY_BATCH", qpath)
        if query["kind"] != "LRProjectionQuery":
            raise _Reject("MALFORMED_QUERY_BATCH", qpath + "/kind")
        proposal = _parse_proposal(query["proposal"], qpath + "/proposal")
        proposal_id = proposal["proposal_id"]
        if proposal_id in proposal_ids:
            raise _Reject("DUPLICATE_PROPOSAL", qpath + "/proposal/proposal_id",
                          {"proposal_id": proposal_id})
        proposal_ids.add(proposal_id)
        if proposal["versions"]["rule_set"] != binding["rule_set_version"]:
            raise _Reject("VERSION_MISMATCH", qpath + "/proposal/versions/rule_set",
                          {"expected": binding["rule_set_version"],
                           "actual": proposal["versions"]["rule_set"], "proposal_id": proposal_id})
        if proposal["versions"]["dataflow"] != binding["dataflow_version"]:
            raise _Reject("VERSION_MISMATCH", qpath + "/proposal/versions/dataflow",
                          {"expected": binding["dataflow_version"],
                           "actual": proposal["versions"]["dataflow"], "proposal_id": proposal_id})
        if proposal["versions"]["canonicalization"] != CANONICALIZATION_VERSION:
            raise _Reject("UNSUPPORTED_CANONICALIZATION",
                          qpath + "/proposal/versions/canonicalization")
        requirements_raw = query["fact_requirements"]
        if not isinstance(requirements_raw, list):
            raise _Reject("MALFORMED_QUERY_BATCH", qpath + "/fact_requirements")
        limit = binding["limits"]["max_fact_requirements_per_query"]
        if len(requirements_raw) > limit:
            raise _Reject("LIMIT_EXCEEDED", qpath + "/fact_requirements",
                          {"limit": limit, "observed": len(requirements_raw),
                           "proposal_id": proposal_id})
        requirements_raw = sorted(requirements_raw, key=diagnostic_order_key)
        requirements: List[Dict[str, Any]] = []
        requirement_ids: List[str] = []
        for req_index, raw_requirement in enumerate(requirements_raw):
            rpath = f"{qpath}/fact_requirements/{req_index}"
            requirement = _exact(raw_requirement, REQUIREMENT_KEYS,
                                 "MALFORMED_QUERY_BATCH", rpath)
            if requirement["kind"] != "LRFactRequirement" or not _valid_id(requirement["precondition_id"]):
                raise _Reject("MALFORMED_QUERY_BATCH", rpath)
            literal = _literal(requirement["literal"], "MALFORMED_QUERY_BATCH", rpath + "/literal")
            if canonical_bytes(literal["atom"]) not in query_atoms:
                raise _Reject("QUERY_ATOM_NOT_DECLARED", rpath + "/literal/atom",
                              {"proposal_id": proposal_id,
                               "precondition_id": requirement["precondition_id"]})
            requirements.append({"kind": "LRFactRequirement",
                                 "precondition_id": requirement["precondition_id"],
                                 "literal": literal})
            requirement_ids.append(requirement["precondition_id"])
        requirements = _sorted_wires(requirements)
        if len(set(requirement_ids)) != len(requirement_ids):
            raise _Reject("PRECONDITION_BINDING_MISMATCH", qpath + "/fact_requirements",
                          {"proposal_id": proposal_id, "invariant": "unique_fact_precondition_id"})
        frontier = query["frontier_precondition_ids"]
        if (not isinstance(frontier, list) or len(frontier) > 64
                or any(not _valid_id(value) for value in frontier)
                or len(set(frontier)) != len(frontier)):
            raise _Reject("MALFORMED_QUERY_BATCH", qpath + "/frontier_precondition_ids")
        frontier = _sorted_strings(frontier)
        if set(requirement_ids).intersection(frontier):
            raise _Reject("PRECONDITION_BINDING_MISMATCH", qpath,
                          {"proposal_id": proposal_id, "invariant": "disjoint_precondition_bindings"})
        if set(requirement_ids).union(frontier) != set(proposal["preconditions"]):
            raise _Reject("PRECONDITION_BINDING_MISMATCH", qpath,
                          {"proposal_id": proposal_id, "invariant": "exact_precondition_partition"})
        without_digest = {"kind": "LRProjectionQuery", "proposal": proposal,
                          "fact_requirements": requirements,
                          "frontier_precondition_ids": frontier}
        expected = canonical_digest(
            {"kind": "LRQueryPreimage", "contract_version": CONTRACT_VERSION,
             "proposal": proposal, "ordered_fact_requirements": requirements,
             "ordered_frontier_precondition_ids": frontier}
        )
        if query["query_digest"] != expected:
            raise _Reject("DIGEST_MISMATCH", qpath + "/query_digest",
                          {"expected": expected, "actual": query["query_digest"],
                           "proposal_id": proposal_id})
        normalized = dict(without_digest)
        normalized["query_digest"] = expected
        queries.append(normalized)
    queries = _sorted_wires(queries)
    expected_batch = canonical_digest(
        {"kind": "LRQueryBatchPreimage", "contract_version": CONTRACT_VERSION,
         "binding_profile_digest": binding["profile_digest"],
         "l_fixpoint_digest": l_result["fixpoint_digest"],
         "rule_bundle_digest": bundle["rule_bundle_digest"],
         "r_profile_digest": r_profile["profile_digest"], "ordered_queries": queries}
    )
    if item["query_batch_digest"] != expected_batch:
        raise _Reject("DIGEST_MISMATCH", "/query_batch/query_batch_digest",
                      {"expected": expected_batch, "actual": item["query_batch_digest"]})
    normalized_batch = {"kind": "LRQueryBatch", "schema_version": QUERY_SCHEMA_VERSION,
                        "contract_version": CONTRACT_VERSION,
                        "binding_profile_digest": binding["profile_digest"],
                        "l_fixpoint_digest": l_result["fixpoint_digest"],
                        "rule_bundle_digest": bundle["rule_bundle_digest"],
                        "r_profile_digest": r_profile["profile_digest"],
                        "queries": queries, "query_batch_digest": expected_batch}
    return normalized_batch, queries


def _m3_value_digest(value_kind: str, value: Mapping[str, Any]) -> str:
    return canonical_digest(
        {"kind": "M3ValuePreimage", "contract_version": R_CONTRACT_VERSION,
         "value_kind": value_kind, "value": thaw(value)}
    )


def _m3_delivery_id(
    source_id: str, logical_time: int, dataflow_version: str,
    value_kind: str, value_digest: str,
) -> str:
    digest = canonical_digest(
        {"kind": "M3DeliveryPreimage", "contract_version": R_CONTRACT_VERSION,
         "source_id": source_id, "logical_time": logical_time,
         "dataflow_version": dataflow_version, "value_kind": value_kind,
         "value_digest": value_digest}
    )
    return "delivery:" + digest.split(":", 1)[1]


def _value_delta(
    source_id: str, logical_time: int, dataflow_version: str,
    value_kind: str, value: Mapping[str, Any],
) -> Dict[str, Any]:
    value_digest = _m3_value_digest(value_kind, value)
    return {
        "kind": "RValueDelta", "schema_version": R_VALUE_DELTA_SCHEMA_VERSION,
        "delivery_id": _m3_delivery_id(source_id, logical_time, dataflow_version,
                                        value_kind, value_digest),
        "source_id": source_id, "logical_time": logical_time, "diff": 1,
        "dataflow_version": dataflow_version, "value_kind": value_kind,
        "value_digest": value_digest, "value": thaw(value),
    }


def _project_query(
    query: Mapping[str, Any], facts: Mapping[bytes, Mapping[str, Any]],
    l_result: Mapping[str, Any], bundle: Mapping[str, Any],
    binding: Mapping[str, Any],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    proposal = query["proposal"]
    evidence_rows: List[Dict[str, Any]] = []
    supports: set[str] = set()
    all_satisfied = True
    any_conflict = False
    for requirement in query["fact_requirements"]:
        literal = requirement["literal"]
        fact = facts.get(canonical_bytes(literal["atom"]))
        if fact is None:
            raise _Reject("FACT_STATE_NOT_FOUND", "/query_batch/queries/fact_requirements/literal/atom",
                          {"proposal_id": proposal["proposal_id"],
                           "precondition_id": requirement["precondition_id"]})
        state = fact["state"]
        if state == "BOTH":
            satisfied = False
            conflict = True
            selected = set(fact["positive_support_ids"]).union(fact["negative_support_ids"])
        elif state == "NEITHER":
            satisfied = False
            conflict = False
            selected = set()
        elif literal["polarity"] == "positive":
            satisfied = state == "TRUE_ONLY"
            conflict = False
            selected = set(fact["positive_support_ids"] if satisfied
                           else fact["negative_support_ids"])
        else:
            satisfied = state == "FALSE_ONLY"
            conflict = False
            selected = set(fact["negative_support_ids"] if satisfied
                           else fact["positive_support_ids"])
        all_satisfied = all_satisfied and satisfied
        any_conflict = any_conflict or conflict
        supports.update(selected)
        evidence_rows.append(
            {"kind": "LRRequirementEvidence",
             "precondition_id": requirement["precondition_id"],
             "literal": literal, "fact_key": fact["fact_key"],
             "truth_state": state, "satisfied": satisfied,
             "evidence_derivation_ids": _sorted_strings(list(selected))}
        )
    evidence_rows = _sorted_wires(evidence_rows)
    status = "conflicted" if any_conflict else "eligible" if all_satisfied else "ineligible"
    support_ids = _sorted_strings(list(supports))
    proposal_digest = _m3_value_digest("effect_proposal", proposal)
    verdict_preimage = {
        "kind": "LRVerdictPreimage", "contract_version": CONTRACT_VERSION,
        "binding_profile_digest": binding["profile_digest"],
        "l_fixpoint_digest": l_result["fixpoint_digest"],
        "l_materialization_digest": l_result["next_materialization"]["materialization_digest"],
        "rule_bundle_digest": bundle["rule_bundle_digest"],
        "proposal_value_digest": proposal_digest, "query_digest": query["query_digest"],
        "ordered_requirement_evidence": evidence_rows, "status": status,
        "ordered_support_derivation_ids": support_ids,
        "rule_set_version": binding["rule_set_version"],
    }
    evidence_digest = canonical_digest(verdict_preimage)
    suffix = evidence_digest.split(":", 1)[1]
    verdict = {
        "kind": "EligibilityVerdict", "verdict_id": "verdict:lr:" + suffix,
        "proposal_id": proposal["proposal_id"], "status": status,
        "support_derivation_ids": support_ids, "cause_id": "cause:lr:" + suffix,
        "rule_set_version": binding["rule_set_version"],
    }
    deltas = [
        _value_delta(binding["proposal_source_id"], l_result["logical_time"],
                     binding["dataflow_version"], "effect_proposal", proposal),
        _value_delta(binding["verdict_source_id"], l_result["logical_time"],
                     binding["dataflow_version"], "eligibility_verdict", verdict),
    ]
    return thaw(verdict), deltas


def _projection(
    l_result: Mapping[str, Any], bundle: Mapping[str, Any],
    r_profile: Mapping[str, Any], binding: Mapping[str, Any],
    query_batch: Mapping[str, Any], queries: Sequence[Mapping[str, Any]],
    facts: Mapping[bytes, Mapping[str, Any]],
) -> Dict[str, Any]:
    verdicts: List[Dict[str, Any]] = []
    deltas: List[Dict[str, Any]] = []
    for query in queries:
        verdict, query_deltas = _project_query(query, facts, l_result, bundle, binding)
        verdicts.append(verdict)
        deltas.extend(query_deltas)
    verdicts = _sorted_wires(verdicts)
    deltas = _sorted_wires(deltas)
    if len(deltas) > r_profile["limits"]["max_deltas_per_command"]:
        raise _Reject("LIMIT_EXCEEDED", "/command/deltas",
                      {"limit": r_profile["limits"]["max_deltas_per_command"],
                       "observed": len(deltas)})
    command: Optional[Dict[str, Any]]
    if deltas:
        command = {
            "kind": "RApplyDeltaBatch", "schema_version": R_COMMAND_SCHEMA_VERSION,
            "profile_digest": r_profile["profile_digest"],
            "dataflow_version": binding["dataflow_version"], "deltas": deltas,
        }
    else:
        command = None
    without_digest = {
        "kind": "LRProjectionResult", "schema_version": RESULT_SCHEMA_VERSION,
        "contract_version": CONTRACT_VERSION, "logical_time": l_result["logical_time"],
        "binding_profile_digest": binding["profile_digest"],
        "l_fixpoint_digest": l_result["fixpoint_digest"],
        "l_materialization_digest": l_result["next_materialization"]["materialization_digest"],
        "query_batch_digest": query_batch["query_batch_digest"],
        "r_profile_digest": r_profile["profile_digest"], "verdicts": verdicts,
        "command": command,
    }
    projection_digest = canonical_digest(
        {"kind": "LRProjectionPreimage", "contract_version": CONTRACT_VERSION,
         "logical_time": l_result["logical_time"],
         "binding_profile_digest": binding["profile_digest"],
         "l_fixpoint_digest": l_result["fixpoint_digest"],
         "l_materialization_digest": l_result["next_materialization"]["materialization_digest"],
         "query_batch_digest": query_batch["query_batch_digest"],
         "r_profile_digest": r_profile["profile_digest"],
         "ordered_verdicts": verdicts, "command": command}
    )
    result = dict(without_digest)
    result["projection_digest"] = projection_digest
    return thaw(result)


def _rejection(
    rejection: _Reject, logical_time: Optional[int], binding_digest: Optional[str],
    l_digest: Optional[str], query_digest: Optional[str], r_digest: Optional[str],
) -> Dict[str, Any]:
    return thaw(
        {"kind": "LRProjectionRejection", "schema_version": RESULT_SCHEMA_VERSION,
         "contract_version": CONTRACT_VERSION, "code": rejection.code,
         "path": rejection.path, "logical_time": logical_time,
         "binding_profile_digest": binding_digest, "l_fixpoint_digest": l_digest,
         "query_batch_digest": query_digest, "r_profile_digest": r_digest,
         "context": rejection.context}
    )


def project_lr(
    l_result: Any, rule_bundle: Any, r_profile: Any,
    binding_profile: Any, query_batch: Any,
) -> WireResult:
    """Project one exact complete-L result into exact paired M3 insertion deltas."""

    logical_time: Optional[int] = None
    binding_digest: Optional[str] = None
    l_digest: Optional[str] = None
    query_digest: Optional[str] = None
    r_digest: Optional[str] = None
    try:
        # Reject non-canonical JSON domains before any digest or semantic parsing.
        for value in (l_result, rule_bundle, r_profile, binding_profile, query_batch):
            canonical_bytes(value)
        bundle, query_atoms = _parse_rule_bundle(rule_bundle)
        parsed_l, facts, missing_fact_keys = _parse_l_result(l_result, bundle)
        logical_time = parsed_l["logical_time"]
        l_digest = parsed_l["fixpoint_digest"]
        parsed_r = _parse_r_profile(r_profile)
        r_digest = parsed_r["profile_digest"]
        binding = _parse_binding_profile(binding_profile, bundle, parsed_r)
        binding_digest = binding["profile_digest"]
        parsed_batch, queries = _parse_query_batch(
            query_batch, parsed_l, bundle, parsed_r, binding, query_atoms
        )
        query_digest = parsed_batch["query_batch_digest"]
        # A query that names an omitted, otherwise expected L fact state keeps
        # the seam's precise FACT_STATE_NOT_FOUND classification.  Any
        # remaining omission is still an invalid incomplete materialization.
        for query in queries:
            for requirement in query["fact_requirements"]:
                if canonical_bytes(requirement["literal"]["atom"]) in missing_fact_keys:
                    raise _Reject(
                        "FACT_STATE_NOT_FOUND",
                        "/query_batch/queries/fact_requirements/literal/atom",
                        {
                            "proposal_id": query["proposal"]["proposal_id"],
                            "precondition_id": requirement["precondition_id"],
                        },
                    )
        if missing_fact_keys:
            # The complete-materialization invariant failed before any input
            # digest becomes a trusted rejection-envelope binding.  The
            # query-specific FACT_STATE_NOT_FOUND branch above is the sole
            # exception because that contract classification validates and
            # binds all five inputs before reporting the missing requirement.
            logical_time = None
            binding_digest = None
            l_digest = None
            query_digest = None
            r_digest = None
            raise _Reject(
                "INVARIANT_VIOLATION",
                "/l_result/next_materialization/fact_states",
                {"invariant": "complete_fact_state_projection"},
            )
        return _projection(parsed_l, bundle, parsed_r, binding, parsed_batch, queries, facts)
    except CanonicalizationError as error:
        return _rejection(
            _Reject("CANONICALIZATION_VIOLATION", error.path,
                    {"invariant": error.code}),
            logical_time, binding_digest, l_digest, query_digest, r_digest,
        )
    except _Reject as rejection:
        # Trust only already-validated digests; malformed inputs never echo a
        # caller-selected digest into the rejection envelope.
        return _rejection(rejection, logical_time, binding_digest, l_digest,
                          query_digest, r_digest)
    except Exception:
        return _rejection(
            _Reject("INVARIANT_VIOLATION", "", {"invariant": "closed_projection_failure"}),
            logical_time, binding_digest, l_digest, query_digest, r_digest,
        )
