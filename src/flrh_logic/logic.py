"""M2 pure ground stratified-logic reference module.

``solve_l`` consumes only explicit JSON values and returns a fresh closed JSON
result.  It owns neither persistence nor reactive publication nor effects.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from .canonical import (
    INT64_MAX,
    CanonicalizationError,
    canonical_bytes,
    canonical_digest,
    diagnostic_order_key,
)


CONTRACT_VERSION = "flrh-l-kernel/1"
PROFILE_ID = "flrh-l-ground-stratified/1"
RULE_SCHEMA_VERSION = "flrh-l-rules/1"
INPUT_SCHEMA_VERSION = "flrh-l-input/1"
MATERIALIZATION_SCHEMA_VERSION = "flrh-l-materialization/1"
RESULT_SCHEMA_VERSION = "flrh-l-result/1"
CANONICALIZATION_VERSION = "flrh-cjson/1"
MAX_RULE_FIRINGS_CEILING = 1000
MAX_DERIVATION_DEPTH_CEILING = 8
MAX_FACT_DELTA_INPUTS = 10000

POLARITIES = frozenset(("positive", "negative"))
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/-]*$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")

RULE_BUNDLE_KEYS = frozenset(
    (
        "kind",
        "schema_version",
        "contract_version",
        "profile_id",
        "rule_set_version",
        "dataflow_version",
        "canonicalization_version",
        "limits",
        "query_atoms",
        "rules",
        "rule_bundle_digest",
    )
)
RULE_KEYS = frozenset(
    (
        "kind",
        "rule_id",
        "stratum",
        "head",
        "required_body",
        "default_not_positive_body",
        "rule_digest",
    )
)
LITERAL_KEYS = frozenset(("kind", "polarity", "atom"))
DEFAULT_KEYS = frozenset(("kind", "atom", "referenced_stratum"))
INPUT_KEYS = frozenset(("kind", "schema_version", "polarity", "delta"))
FACT_DELTA_KEYS = frozenset(
    (
        "kind",
        "tuple",
        "logical_time",
        "diff",
        "derivation_id",
        "causation_id",
        "provenance_delta",
        "rule_set_version",
        "dataflow_version",
    )
)
MATERIALIZATION_KEYS = frozenset(
    (
        "kind",
        "schema_version",
        "contract_version",
        "profile_id",
        "rule_bundle_digest",
        "rule_set_version",
        "dataflow_version",
        "canonicalization_version",
        "through_logical_time",
        "base_supports",
        "derived_supports",
        "fact_states",
        "conflicts",
        "stratum_digests",
        "materialization_digest",
    )
)
BASE_SUPPORT_KEYS = frozenset(
    (
        "kind",
        "derivation_id",
        "support_content_digest",
        "literal",
        "provenance_delta",
        "rule_set_version",
        "dataflow_version",
    )
)
DERIVED_SUPPORT_KEYS = frozenset(
    (
        "kind",
        "derivation_id",
        "support_content_digest",
        "literal",
        "rule_id",
        "rule_digest",
        "premise_literal_keys",
        "default_absence_witnesses",
        "rule_set_version",
        "dataflow_version",
    )
)
ABSENCE_WITNESS_KEYS = frozenset(
    (
        "kind",
        "fact_key",
        "atom",
        "referenced_stratum",
        "completed_stratum_digest",
        "witness_digest",
    )
)
FACT_STATE_KEYS = frozenset(
    (
        "kind",
        "fact_key",
        "atom",
        "state",
        "positive_support_ids",
        "negative_support_ids",
    )
)
CONFLICT_KEYS = frozenset(
    (
        "kind",
        "conflict_id",
        "fact_key",
        "atom",
        "positive_support_ids",
        "negative_support_ids",
    )
)
STRATUM_DIGEST_KEYS = frozenset(("kind", "stratum", "digest"))


WireResult = Dict[str, Any]


class _KernelReject(Exception):
    def __init__(
        self,
        code: str,
        path: str,
        context: Optional[Mapping[str, Union[str, int, bool, None]]] = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.path = path
        self.context = dict(context or {})


@dataclass(frozen=True)
class _Literal:
    polarity: str
    atom_bytes: bytes


@dataclass(frozen=True)
class _DefaultNotPositive:
    atom_bytes: bytes
    referenced_stratum: int


@dataclass(frozen=True)
class _Rule:
    rule_id: str
    stratum: int
    head: _Literal
    required_body: Tuple[_Literal, ...]
    default_not_positive_body: Tuple[_DefaultNotPositive, ...]
    rule_digest: str


@dataclass(frozen=True)
class _Bundle:
    profile_id: str
    rule_set_version: str
    dataflow_version: str
    max_rule_firings: int
    max_derivation_depth: int
    query_atoms: Tuple[bytes, ...]
    rules: Tuple[_Rule, ...]
    digest: str


@dataclass(frozen=True)
class _BaseSupport:
    derivation_id: str
    support_content_digest: str
    literal: _Literal
    provenance_bytes: bytes
    rule_set_version: str
    dataflow_version: str


@dataclass(frozen=True)
class _AbsenceWitness:
    fact_key: str
    atom_bytes: bytes
    referenced_stratum: int
    completed_stratum_digest: str
    witness_digest: str


@dataclass(frozen=True)
class _DerivedSupport:
    derivation_id: str
    support_content_digest: str
    literal: _Literal
    rule_id: str
    rule_digest: str
    premise_literal_keys: Tuple[str, ...]
    default_absence_witnesses: Tuple[_AbsenceWitness, ...]
    rule_set_version: str
    dataflow_version: str


@dataclass(frozen=True)
class _ParsedInput:
    index: int
    polarity: str
    diff: int
    derivation_id: str
    support: _BaseSupport
    normalized_wire_bytes: bytes
    input_digest: str


@dataclass(frozen=True)
class _Derivation:
    derived: Tuple[_DerivedSupport, ...]
    fact_states: Tuple[Dict[str, Any], ...]
    conflicts: Tuple[Dict[str, Any], ...]
    stratum_digests: Tuple[Dict[str, Any], ...]
    rule_evaluation_count: int
    rule_firing_count: int
    worklist_pop_count: int
    max_derivation_depth: int


@dataclass(frozen=True)
class _Prior:
    through_logical_time: Optional[int]
    materialization_digest: str
    base: Tuple[_BaseSupport, ...]
    derived: Tuple[_DerivedSupport, ...]


def _valid_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 128
        and ID_PATTERN.fullmatch(value) is not None
    )


def _valid_version(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 128
        and VERSION_PATTERN.fullmatch(value) is not None
    )


def _valid_digest(value: Any) -> bool:
    return isinstance(value, str) and DIGEST_PATTERN.fullmatch(value) is not None


def _valid_nonnegative_int(value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= INT64_MAX
    )


def _thaw(value_bytes: bytes) -> Any:
    return json.loads(value_bytes.decode("utf-8"))


def _freeze(value: Any) -> bytes:
    return canonical_bytes(value)


def _sort_wires(values: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(values, key=canonical_bytes)


def _sort_strings(values: Sequence[str]) -> List[str]:
    return sorted(values, key=canonical_bytes)


def _reject_canonical(value: Any, path: str) -> None:
    try:
        canonical_bytes(value)
    except CanonicalizationError as error:
        suffix = "" if error.path == "/" else error.path
        raise _KernelReject(
            "CANONICALIZATION_VIOLATION",
            path + suffix,
            {"invariant": error.code},
        )


def _ordered_rule_bundle_view(value: Any) -> Any:
    """Copy only set-like rule collections into deterministic validation order."""

    if not isinstance(value, dict):
        return value
    ordered = dict(value)
    raw_queries = ordered.get("query_atoms")
    if isinstance(raw_queries, list):
        ordered["query_atoms"] = sorted(raw_queries, key=diagnostic_order_key)
    raw_rules = ordered.get("rules")
    if isinstance(raw_rules, list):
        normalized_rules: List[Any] = []
        for raw_rule in sorted(raw_rules, key=diagnostic_order_key):
            if not isinstance(raw_rule, dict):
                normalized_rules.append(raw_rule)
                continue
            rule = dict(raw_rule)
            for field in ("required_body", "default_not_positive_body"):
                body = rule.get(field)
                if isinstance(body, list):
                    rule[field] = sorted(body, key=diagnostic_order_key)
            normalized_rules.append(rule)
        ordered["rules"] = sorted(
            normalized_rules, key=diagnostic_order_key
        )
    return ordered


def _ordered_materialization_view(value: Any) -> Any:
    """Copy set-like materialization collections for stable rejection."""

    if not isinstance(value, dict):
        return value
    ordered = dict(value)
    nested_set_fields = {
        "derived_supports": (
            "premise_literal_keys",
            "default_absence_witnesses",
        ),
        "fact_states": ("positive_support_ids", "negative_support_ids"),
        "conflicts": ("positive_support_ids", "negative_support_ids"),
    }
    for field in (
        "base_supports",
        "derived_supports",
        "fact_states",
        "conflicts",
        "stratum_digests",
    ):
        collection = ordered.get(field)
        if isinstance(collection, list):
            normalized_collection: List[Any] = []
            for raw in collection:
                if not isinstance(raw, dict):
                    normalized_collection.append(raw)
                    continue
                item = dict(raw)
                for nested_field in nested_set_fields.get(field, ()):
                    nested = item.get(nested_field)
                    if isinstance(nested, list):
                        item[nested_field] = sorted(
                            nested, key=diagnostic_order_key
                        )
                normalized_collection.append(item)
            ordered[field] = sorted(
                normalized_collection, key=diagnostic_order_key
            )
    return ordered


def _require_exact_object(value: Any, keys: frozenset, code: str, path: str) -> Dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise _KernelReject(code, path)
    return value


def _sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _literal_wire(literal: _Literal) -> Dict[str, Any]:
    return {
        "kind": "LLiteral",
        "polarity": literal.polarity,
        "atom": _thaw(literal.atom_bytes),
    }


def _default_wire(default: _DefaultNotPositive) -> Dict[str, Any]:
    return {
        "kind": "LDefaultNotPositive",
        "atom": _thaw(default.atom_bytes),
        "referenced_stratum": default.referenced_stratum,
    }


def _rule_wire(rule: _Rule) -> Dict[str, Any]:
    return {
        "kind": "LRule",
        "rule_id": rule.rule_id,
        "stratum": rule.stratum,
        "head": _literal_wire(rule.head),
        "required_body": [_literal_wire(item) for item in rule.required_body],
        "default_not_positive_body": [
            _default_wire(item) for item in rule.default_not_positive_body
        ],
        "rule_digest": rule.rule_digest,
    }


def _fact_key(atom_bytes: bytes) -> str:
    return canonical_digest(
        {
            "kind": "M2FactKeyPreimage",
            "contract_version": CONTRACT_VERSION,
            "atom": _thaw(atom_bytes),
        }
    )


def _literal_key(literal: _Literal) -> str:
    return canonical_digest(
        {
            "kind": "M2LiteralKeyPreimage",
            "contract_version": CONTRACT_VERSION,
            "literal": _literal_wire(literal),
        }
    )


def _parse_atom(value: Any, code: str, path: str) -> bytes:
    if not isinstance(value, dict) or not value:
        raise _KernelReject(code, path)
    return _freeze(value)


def _parse_literal(value: Any, code: str, path: str) -> _Literal:
    item = _require_exact_object(value, LITERAL_KEYS, code, path)
    if item.get("kind") != "LLiteral":
        raise _KernelReject(code, path + "/kind")
    polarity = item.get("polarity")
    if polarity not in POLARITIES:
        raise _KernelReject(code, path + "/polarity")
    return _Literal(
        polarity=polarity,
        atom_bytes=_parse_atom(item.get("atom"), code, path + "/atom"),
    )


def _parse_default(value: Any, path: str) -> _DefaultNotPositive:
    item = _require_exact_object(value, DEFAULT_KEYS, "MALFORMED_RULE_BUNDLE", path)
    if item.get("kind") != "LDefaultNotPositive":
        raise _KernelReject("MALFORMED_RULE_BUNDLE", path + "/kind")
    referenced = item.get("referenced_stratum")
    if not _valid_nonnegative_int(referenced):
        raise _KernelReject("MALFORMED_RULE_BUNDLE", path + "/referenced_stratum")
    return _DefaultNotPositive(
        atom_bytes=_parse_atom(item.get("atom"), "MALFORMED_RULE_BUNDLE", path + "/atom"),
        referenced_stratum=referenced,
    )


def _rule_preimage(
    rule_id: str,
    stratum: int,
    head: _Literal,
    required: Sequence[_Literal],
    defaults: Sequence[_DefaultNotPositive],
) -> Dict[str, Any]:
    return {
        "kind": "M2RulePreimage",
        "contract_version": CONTRACT_VERSION,
        "profile_id": PROFILE_ID,
        "rule_id": rule_id,
        "stratum": stratum,
        "head": _literal_wire(head),
        "ordered_required_body": [_literal_wire(item) for item in required],
        "ordered_default_not_positive_body": [_default_wire(item) for item in defaults],
    }


def _parse_rule(value: Any, index: int) -> _Rule:
    path = f"/rule_bundle/rules/{index}"
    item = _require_exact_object(value, RULE_KEYS, "MALFORMED_RULE_BUNDLE", path)
    if item.get("kind") != "LRule":
        raise _KernelReject("MALFORMED_RULE_BUNDLE", path + "/kind")
    rule_id = item.get("rule_id")
    if not _valid_id(rule_id):
        raise _KernelReject("MALFORMED_RULE_BUNDLE", path + "/rule_id")
    stratum = item.get("stratum")
    if not _valid_nonnegative_int(stratum):
        raise _KernelReject("MALFORMED_RULE_BUNDLE", path + "/stratum")
    head = _parse_literal(item.get("head"), "MALFORMED_RULE_BUNDLE", path + "/head")
    raw_required = item.get("required_body")
    raw_defaults = item.get("default_not_positive_body")
    if not isinstance(raw_required, list) or len(raw_required) > 64:
        raise _KernelReject("MALFORMED_RULE_BUNDLE", path + "/required_body")
    if not isinstance(raw_defaults, list) or len(raw_defaults) > 64:
        raise _KernelReject(
            "MALFORMED_RULE_BUNDLE", path + "/default_not_positive_body"
        )
    if not raw_required and not raw_defaults:
        raise _KernelReject(
            "MALFORMED_RULE_BUNDLE",
            path,
            {"invariant": "rule_requires_evidence_or_completed_absence_root"},
        )
    ordered_required = sorted(raw_required, key=diagnostic_order_key)
    ordered_defaults = sorted(raw_defaults, key=diagnostic_order_key)
    required = tuple(
        sorted(
            (
                _parse_literal(
                    raw,
                    "MALFORMED_RULE_BUNDLE",
                    f"{path}/required_body/{body_index}",
                )
                for body_index, raw in enumerate(ordered_required)
            ),
            key=lambda literal: canonical_bytes(_literal_wire(literal)),
        )
    )
    defaults = tuple(
        sorted(
            (
                _parse_default(raw, f"{path}/default_not_positive_body/{body_index}")
                for body_index, raw in enumerate(ordered_defaults)
            ),
            key=lambda default: canonical_bytes(_default_wire(default)),
        )
    )
    required_bytes = [canonical_bytes(_literal_wire(literal)) for literal in required]
    default_bytes = [canonical_bytes(_default_wire(default)) for default in defaults]
    if len(required_bytes) != len(set(required_bytes)):
        raise _KernelReject(
            "MALFORMED_RULE_BUNDLE",
            path + "/required_body",
            {"invariant": "unique_required_body_literals"},
        )
    if len(default_bytes) != len(set(default_bytes)):
        raise _KernelReject(
            "MALFORMED_RULE_BUNDLE",
            path + "/default_not_positive_body",
            {"invariant": "unique_default_not_positive_body"},
        )
    expected_digest = canonical_digest(
        _rule_preimage(rule_id, stratum, head, required, defaults)
    )
    supplied_digest = item.get("rule_digest")
    if not _valid_digest(supplied_digest) or supplied_digest != expected_digest:
        raise _KernelReject(
            "PROVENANCE_INTEGRITY_VIOLATION",
            path + "/rule_digest",
            {"expected": expected_digest, "actual": supplied_digest, "rule_id": rule_id},
        )
    return _Rule(
        rule_id=rule_id,
        stratum=stratum,
        head=head,
        required_body=required,
        default_not_positive_body=defaults,
        rule_digest=expected_digest,
    )


def _bundle_preimage(
    rule_set_version: str,
    dataflow_version: str,
    max_rule_firings: int,
    max_derivation_depth: int,
    query_atoms: Sequence[bytes],
    rules: Sequence[_Rule],
) -> Dict[str, Any]:
    return {
        "kind": "M2RuleBundlePreimage",
        "contract_version": CONTRACT_VERSION,
        "profile_id": PROFILE_ID,
        "rule_set_version": rule_set_version,
        "dataflow_version": dataflow_version,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "limits": {
            "max_rule_firings": max_rule_firings,
            "max_derivation_depth": max_derivation_depth,
        },
        "ordered_query_atoms": [_thaw(atom) for atom in query_atoms],
        "ordered_rules": [_rule_wire(rule) for rule in rules],
    }


def _validate_stratification(rules: Sequence[_Rule]) -> None:
    producers: Dict[str, set] = {}
    for rule in rules:
        producers.setdefault(_literal_key(rule.head), set()).add(rule.stratum)
    for key in sorted(producers):
        strata = producers[key]
        if len(strata) > 1:
            ordered = sorted(strata)
            raise _KernelReject(
                "INVALID_STRATIFICATION",
                "/rule_bundle/rules",
                {
                    "invariant": "one_producer_stratum_per_literal",
                    "source_stratum": ordered[0],
                    "target_stratum": ordered[-1],
                },
            )
    for rule in rules:
        for literal in rule.required_body:
            source_strata = producers.get(_literal_key(literal), set())
            if source_strata and max(source_strata) > rule.stratum:
                raise _KernelReject(
                    "INVALID_STRATIFICATION",
                    "/rule_bundle/rules",
                    {
                        "rule_id": rule.rule_id,
                        "source_stratum": max(source_strata),
                        "target_stratum": rule.stratum,
                    },
                )
        for default in rule.default_not_positive_body:
            if default.referenced_stratum >= rule.stratum:
                raise _KernelReject(
                    "OUTSIDE_V0_NEGATIVE_RECURSION",
                    "/rule_bundle/rules",
                    {
                        "rule_id": rule.rule_id,
                        "source_stratum": default.referenced_stratum,
                        "target_stratum": rule.stratum,
                    },
                )
            positive = _Literal("positive", default.atom_bytes)
            source_strata = producers.get(_literal_key(positive), set())
            if source_strata and max(source_strata) > default.referenced_stratum:
                raise _KernelReject(
                    "INVALID_STRATIFICATION",
                    "/rule_bundle/rules",
                    {
                        "rule_id": rule.rule_id,
                        "source_stratum": max(source_strata),
                        "target_stratum": default.referenced_stratum,
                    },
                )


def _parse_bundle(value: Any) -> _Bundle:
    value = _ordered_rule_bundle_view(value)
    _reject_canonical(value, "/rule_bundle")
    item = _require_exact_object(
        value, RULE_BUNDLE_KEYS, "MALFORMED_RULE_BUNDLE", "/rule_bundle"
    )
    if item.get("kind") != "LRuleBundle":
        raise _KernelReject("MALFORMED_RULE_BUNDLE", "/rule_bundle/kind")
    if item.get("schema_version") != RULE_SCHEMA_VERSION:
        raise _KernelReject("UNSUPPORTED_RULE_SCHEMA", "/rule_bundle/schema_version")
    if item.get("contract_version") != CONTRACT_VERSION:
        raise _KernelReject(
            "UNSUPPORTED_CONTRACT_VERSION", "/rule_bundle/contract_version"
        )
    if item.get("profile_id") != PROFILE_ID:
        raise _KernelReject("UNSUPPORTED_PROFILE", "/rule_bundle/profile_id")
    if item.get("canonicalization_version") != CANONICALIZATION_VERSION:
        raise _KernelReject(
            "UNSUPPORTED_CANONICALIZATION",
            "/rule_bundle/canonicalization_version",
        )
    rule_set_version = item.get("rule_set_version")
    dataflow_version = item.get("dataflow_version")
    if not _valid_version(rule_set_version):
        raise _KernelReject("MALFORMED_RULE_BUNDLE", "/rule_bundle/rule_set_version")
    if not _valid_version(dataflow_version):
        raise _KernelReject("MALFORMED_RULE_BUNDLE", "/rule_bundle/dataflow_version")
    limits = _require_exact_object(
        item.get("limits"),
        frozenset(("max_rule_firings", "max_derivation_depth")),
        "MALFORMED_RULE_BUNDLE",
        "/rule_bundle/limits",
    )
    max_firings = limits.get("max_rule_firings")
    max_depth = limits.get("max_derivation_depth")
    if not (
        isinstance(max_firings, int)
        and not isinstance(max_firings, bool)
        and 1 <= max_firings <= MAX_RULE_FIRINGS_CEILING
    ):
        raise _KernelReject(
            "MALFORMED_RULE_BUNDLE", "/rule_bundle/limits/max_rule_firings"
        )
    if not (
        isinstance(max_depth, int)
        and not isinstance(max_depth, bool)
        and 1 <= max_depth <= MAX_DERIVATION_DEPTH_CEILING
    ):
        raise _KernelReject(
            "MALFORMED_RULE_BUNDLE", "/rule_bundle/limits/max_derivation_depth"
        )
    raw_queries = item.get("query_atoms")
    raw_rules = item.get("rules")
    if not isinstance(raw_queries, list) or len(raw_queries) > 1024:
        raise _KernelReject("MALFORMED_RULE_BUNDLE", "/rule_bundle/query_atoms")
    if not isinstance(raw_rules, list) or len(raw_rules) > 256:
        raise _KernelReject("MALFORMED_RULE_BUNDLE", "/rule_bundle/rules")
    ordered_queries = sorted(raw_queries, key=diagnostic_order_key)
    ordered_rules = sorted(raw_rules, key=diagnostic_order_key)
    query_atoms = tuple(
        sorted(
            (
                _parse_atom(
                    atom, "MALFORMED_RULE_BUNDLE", f"/rule_bundle/query_atoms/{index}"
                )
                for index, atom in enumerate(ordered_queries)
            )
        )
    )
    if len(query_atoms) != len(set(query_atoms)):
        raise _KernelReject(
            "MALFORMED_RULE_BUNDLE",
            "/rule_bundle/query_atoms",
            {"invariant": "unique_query_atoms"},
        )
    rules = tuple(
        sorted(
            (_parse_rule(rule, index) for index, rule in enumerate(ordered_rules)),
            key=lambda rule: canonical_bytes(_rule_wire(rule)),
        )
    )
    by_id: Dict[str, bytes] = {}
    for rule in rules:
        encoded = canonical_bytes(_rule_wire(rule))
        previous = by_id.get(rule.rule_id)
        if previous is not None:
            raise _KernelReject(
                "MALFORMED_RULE_BUNDLE",
                "/rule_bundle/rules",
                {"rule_id": rule.rule_id, "invariant": "unique_rule_id"},
            )
        by_id[rule.rule_id] = encoded
    digests = [rule.rule_digest for rule in rules]
    if len(digests) != len(set(digests)):
        raise _KernelReject(
            "MALFORMED_RULE_BUNDLE",
            "/rule_bundle/rules",
            {"invariant": "unique_rule_digest"},
        )
    expected_digest = canonical_digest(
        _bundle_preimage(
            rule_set_version,
            dataflow_version,
            max_firings,
            max_depth,
            query_atoms,
            rules,
        )
    )
    supplied_digest = item.get("rule_bundle_digest")
    if not _valid_digest(supplied_digest) or supplied_digest != expected_digest:
        raise _KernelReject(
            "RULE_BUNDLE_MISMATCH",
            "/rule_bundle/rule_bundle_digest",
            {"expected": expected_digest, "actual": supplied_digest},
        )
    bundle = _Bundle(
        profile_id=PROFILE_ID,
        rule_set_version=rule_set_version,
        dataflow_version=dataflow_version,
        max_rule_firings=max_firings,
        max_derivation_depth=max_depth,
        query_atoms=query_atoms,
        rules=rules,
        digest=expected_digest,
    )
    try:
        _validate_stratification(rules)
    except _KernelReject as rejection:
        rejection.trusted_rule_bundle_digest = expected_digest
        raise
    return bundle


def _base_support_preimage(
    literal: _Literal,
    provenance_bytes: bytes,
    rule_set_version: str,
    dataflow_version: str,
) -> Dict[str, Any]:
    return {
        "kind": "M2BaseSupportContentPreimage",
        "contract_version": CONTRACT_VERSION,
        "profile_id": PROFILE_ID,
        "literal": _literal_wire(literal),
        "provenance_delta": _thaw(provenance_bytes),
        "rule_set_version": rule_set_version,
        "dataflow_version": dataflow_version,
    }


def _base_support_wire(support: _BaseSupport) -> Dict[str, Any]:
    return {
        "kind": "LBaseSupport",
        "derivation_id": support.derivation_id,
        "support_content_digest": support.support_content_digest,
        "literal": _literal_wire(support.literal),
        "provenance_delta": _thaw(support.provenance_bytes),
        "rule_set_version": support.rule_set_version,
        "dataflow_version": support.dataflow_version,
    }


def _absence_witness_wire(witness: _AbsenceWitness) -> Dict[str, Any]:
    return {
        "kind": "LAbsenceWitness",
        "fact_key": witness.fact_key,
        "atom": _thaw(witness.atom_bytes),
        "referenced_stratum": witness.referenced_stratum,
        "completed_stratum_digest": witness.completed_stratum_digest,
        "witness_digest": witness.witness_digest,
    }


def _absence_witness(atom_bytes: bytes, stratum: int, digest: str) -> _AbsenceWitness:
    fact_key = _fact_key(atom_bytes)
    preimage = {
        "kind": "M2AbsenceWitnessPreimage",
        "contract_version": CONTRACT_VERSION,
        "fact_key": fact_key,
        "atom": _thaw(atom_bytes),
        "referenced_stratum": stratum,
        "completed_stratum_digest": digest,
    }
    return _AbsenceWitness(
        fact_key=fact_key,
        atom_bytes=atom_bytes,
        referenced_stratum=stratum,
        completed_stratum_digest=digest,
        witness_digest=canonical_digest(preimage),
    )


def _derived_support_preimage(
    literal: _Literal,
    rule_id: str,
    rule_digest: str,
    premise_literal_keys: Sequence[str],
    witnesses: Sequence[_AbsenceWitness],
    rule_set_version: str,
    dataflow_version: str,
) -> Dict[str, Any]:
    return {
        "kind": "M2DerivedSupportContentPreimage",
        "contract_version": CONTRACT_VERSION,
        "profile_id": PROFILE_ID,
        "literal": _literal_wire(literal),
        "rule_id": rule_id,
        "rule_digest": rule_digest,
        "ordered_premise_literal_keys": list(premise_literal_keys),
        "ordered_default_absence_witness_digests": [
            witness.witness_digest for witness in witnesses
        ],
        "rule_set_version": rule_set_version,
        "dataflow_version": dataflow_version,
    }


def _derived_support_for_rule(
    rule: _Rule,
    witnesses: Sequence[_AbsenceWitness],
    bundle: _Bundle,
) -> _DerivedSupport:
    premise_keys = tuple(
        _sort_strings([_literal_key(literal) for literal in rule.required_body])
    )
    ordered_witnesses = tuple(
        sorted(witnesses, key=lambda item: canonical_bytes(_absence_witness_wire(item)))
    )
    content_digest = canonical_digest(
        _derived_support_preimage(
            rule.head,
            rule.rule_id,
            rule.rule_digest,
            premise_keys,
            ordered_witnesses,
            bundle.rule_set_version,
            bundle.dataflow_version,
        )
    )
    return _DerivedSupport(
        derivation_id="derivation:" + content_digest.split(":", 1)[1],
        support_content_digest=content_digest,
        literal=rule.head,
        rule_id=rule.rule_id,
        rule_digest=rule.rule_digest,
        premise_literal_keys=premise_keys,
        default_absence_witnesses=ordered_witnesses,
        rule_set_version=bundle.rule_set_version,
        dataflow_version=bundle.dataflow_version,
    )


def _derived_support_wire(support: _DerivedSupport) -> Dict[str, Any]:
    return {
        "kind": "LDerivedSupport",
        "derivation_id": support.derivation_id,
        "support_content_digest": support.support_content_digest,
        "literal": _literal_wire(support.literal),
        "rule_id": support.rule_id,
        "rule_digest": support.rule_digest,
        "premise_literal_keys": list(support.premise_literal_keys),
        "default_absence_witnesses": [
            _absence_witness_wire(witness)
            for witness in support.default_absence_witnesses
        ],
        "rule_set_version": support.rule_set_version,
        "dataflow_version": support.dataflow_version,
    }


def _parse_fact_delta_input(
    value: Any,
    index: int,
    logical_time: int,
    bundle: _Bundle,
) -> _ParsedInput:
    path = f"/fact_delta_inputs/{index}"
    _reject_canonical(value, path)
    item = _require_exact_object(
        value, INPUT_KEYS, "MALFORMED_FACT_DELTA_INPUT", path
    )
    if item.get("kind") != "LFactDeltaInput":
        raise _KernelReject("MALFORMED_FACT_DELTA_INPUT", path + "/kind")
    if item.get("schema_version") != INPUT_SCHEMA_VERSION:
        raise _KernelReject("UNSUPPORTED_INPUT_SCHEMA", path + "/schema_version")
    polarity = item.get("polarity")
    if polarity not in POLARITIES:
        raise _KernelReject("MALFORMED_FACT_DELTA_INPUT", path + "/polarity")
    delta_path = path + "/delta"
    delta = _require_exact_object(
        item.get("delta"), FACT_DELTA_KEYS, "MALFORMED_FACT_DELTA_INPUT", delta_path
    )
    if delta.get("kind") != "FactDelta":
        raise _KernelReject("MALFORMED_FACT_DELTA_INPUT", delta_path + "/kind")
    atom_bytes = _parse_atom(
        delta.get("tuple"), "MALFORMED_FACT_DELTA_INPUT", delta_path + "/tuple"
    )
    delta_time = delta.get("logical_time")
    if not _valid_nonnegative_int(delta_time):
        raise _KernelReject(
            "MALFORMED_FACT_DELTA_INPUT", delta_path + "/logical_time"
        )
    if delta_time != logical_time:
        raise _KernelReject(
            "LOGICAL_TIME_MISMATCH",
            delta_path + "/logical_time",
            {"expected": logical_time, "actual": delta_time},
        )
    diff = delta.get("diff")
    if not isinstance(diff, int) or isinstance(diff, bool) or diff not in (-1, 1):
        raise _KernelReject("MALFORMED_FACT_DELTA_INPUT", delta_path + "/diff")
    derivation_id = delta.get("derivation_id")
    causation_id = delta.get("causation_id")
    if not _valid_id(derivation_id):
        raise _KernelReject(
            "MALFORMED_FACT_DELTA_INPUT", delta_path + "/derivation_id"
        )
    if not _valid_id(causation_id):
        raise _KernelReject(
            "MALFORMED_FACT_DELTA_INPUT", delta_path + "/causation_id"
        )
    provenance = delta.get("provenance_delta")
    if not isinstance(provenance, dict) or not provenance:
        raise _KernelReject(
            "MALFORMED_FACT_DELTA_INPUT", delta_path + "/provenance_delta"
        )
    provenance_bytes = _freeze(provenance)
    rule_set_version = delta.get("rule_set_version")
    dataflow_version = delta.get("dataflow_version")
    if not _valid_version(rule_set_version):
        raise _KernelReject(
            "MALFORMED_FACT_DELTA_INPUT", delta_path + "/rule_set_version"
        )
    if not _valid_version(dataflow_version):
        raise _KernelReject(
            "MALFORMED_FACT_DELTA_INPUT", delta_path + "/dataflow_version"
        )
    if rule_set_version != bundle.rule_set_version:
        raise _KernelReject(
            "RULE_SET_VERSION_MISMATCH",
            delta_path + "/rule_set_version",
            {"expected": bundle.rule_set_version, "actual": rule_set_version},
        )
    if dataflow_version != bundle.dataflow_version:
        raise _KernelReject(
            "DATAFLOW_VERSION_MISMATCH",
            delta_path + "/dataflow_version",
            {"expected": bundle.dataflow_version, "actual": dataflow_version},
        )
    literal = _Literal(polarity=polarity, atom_bytes=atom_bytes)
    content_digest = canonical_digest(
        _base_support_preimage(
            literal,
            provenance_bytes,
            rule_set_version,
            dataflow_version,
        )
    )
    support = _BaseSupport(
        derivation_id=derivation_id,
        support_content_digest=content_digest,
        literal=literal,
        provenance_bytes=provenance_bytes,
        rule_set_version=rule_set_version,
        dataflow_version=dataflow_version,
    )
    normalized_wire = {
        "kind": "LFactDeltaInput",
        "schema_version": INPUT_SCHEMA_VERSION,
        "polarity": polarity,
        "delta": {
            "kind": "FactDelta",
            "tuple": _thaw(atom_bytes),
            "logical_time": delta_time,
            "diff": diff,
            "derivation_id": derivation_id,
            "causation_id": causation_id,
            "provenance_delta": _thaw(provenance_bytes),
            "rule_set_version": rule_set_version,
            "dataflow_version": dataflow_version,
        },
    }
    normalized_bytes = canonical_bytes(normalized_wire)
    input_digest = canonical_digest(
        {
            "kind": "M2InputDeltaPreimage",
            "contract_version": CONTRACT_VERSION,
            "fact_delta_input": normalized_wire,
        }
    )
    return _ParsedInput(
        index=index,
        polarity=polarity,
        diff=diff,
        derivation_id=derivation_id,
        support=support,
        normalized_wire_bytes=normalized_bytes,
        input_digest=input_digest,
    )


def _project_facts(
    bundle: _Bundle,
    base_supports: Sequence[_BaseSupport],
    derived_supports: Sequence[_DerivedSupport],
) -> Tuple[Tuple[Dict[str, Any], ...], Tuple[Dict[str, Any], ...]]:
    atoms: Dict[bytes, None] = {atom: None for atom in bundle.query_atoms}
    positive: Dict[bytes, List[str]] = {}
    negative: Dict[bytes, List[str]] = {}
    for support in list(base_supports) + list(derived_supports):
        atom = support.literal.atom_bytes
        atoms[atom] = None
        target = positive if support.literal.polarity == "positive" else negative
        target.setdefault(atom, []).append(support.derivation_id)
    states: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []
    for atom in sorted(atoms):
        positive_ids = _sort_strings(positive.get(atom, []))
        negative_ids = _sort_strings(negative.get(atom, []))
        if len(positive_ids) != len(set(positive_ids)) or len(negative_ids) != len(
            set(negative_ids)
        ):
            raise _KernelReject(
                "INVARIANT_VIOLATION",
                "/next_materialization",
                {"invariant": "unique_support_identity_per_fact_polarity"},
            )
        if positive_ids and negative_ids:
            state_name = "BOTH"
        elif positive_ids:
            state_name = "TRUE_ONLY"
        elif negative_ids:
            state_name = "FALSE_ONLY"
        else:
            state_name = "NEITHER"
        fact_key = _fact_key(atom)
        state = {
            "kind": "LFactState",
            "fact_key": fact_key,
            "atom": _thaw(atom),
            "state": state_name,
            "positive_support_ids": positive_ids,
            "negative_support_ids": negative_ids,
        }
        states.append(state)
        if state_name == "BOTH":
            conflict_preimage = {
                "kind": "M2ConflictPreimage",
                "contract_version": CONTRACT_VERSION,
                "fact_key": fact_key,
                "atom": _thaw(atom),
                "ordered_positive_support_ids": positive_ids,
                "ordered_negative_support_ids": negative_ids,
            }
            conflict_hex = canonical_digest(conflict_preimage).split(":", 1)[1]
            conflicts.append(
                {
                    "kind": "LConflict",
                    "conflict_id": "conflict:" + conflict_hex,
                    "fact_key": fact_key,
                    "atom": _thaw(atom),
                    "positive_support_ids": positive_ids,
                    "negative_support_ids": negative_ids,
                }
            )
    return (
        tuple(_sort_wires(states)),
        tuple(_sort_wires(conflicts)),
    )


def _completed_stratum_digest(
    stratum: int,
    bundle: _Bundle,
    base_supports: Sequence[_BaseSupport],
    derived_supports: Sequence[_DerivedSupport],
) -> str:
    states, _ = _project_facts(bundle, base_supports, derived_supports)
    base_wires = _sort_wires([_base_support_wire(item) for item in base_supports])
    derived_wires = _sort_wires(
        [_derived_support_wire(item) for item in derived_supports]
    )
    return canonical_digest(
        {
            "kind": "M2StratumPreimage",
            "contract_version": CONTRACT_VERSION,
            "profile_id": PROFILE_ID,
            "rule_bundle_digest": bundle.digest,
            "stratum": stratum,
            "ordered_base_supports": base_wires,
            "ordered_derived_supports": derived_wires,
            "ordered_fact_states": list(states),
        }
    )


def _derive(bundle: _Bundle, base_supports: Sequence[_BaseSupport]) -> _Derivation:
    ordered_base = tuple(
        sorted(base_supports, key=lambda item: canonical_bytes(_base_support_wire(item)))
    )
    base_ids = [item.derivation_id for item in ordered_base]
    if len(base_ids) != len(set(base_ids)):
        raise _KernelReject(
            "INVARIANT_VIOLATION",
            "/next_materialization/base_supports",
            {"invariant": "unique_base_support_identity"},
        )

    present: Dict[str, _Literal] = {}
    literal_depths: Dict[str, int] = {}
    for support in ordered_base:
        key = _literal_key(support.literal)
        present[key] = support.literal
        literal_depths[key] = 0

    strata_values = set(rule.stratum for rule in bundle.rules)
    for rule in bundle.rules:
        strata_values.update(
            item.referenced_stratum for item in rule.default_not_positive_body
        )
    strata = sorted(strata_values)
    rules_by_stratum: Dict[int, List[_Rule]] = {}
    for rule in bundle.rules:
        rules_by_stratum.setdefault(rule.stratum, []).append(rule)
    for stratum in rules_by_stratum:
        rules_by_stratum[stratum].sort(key=lambda item: canonical_bytes(_rule_wire(item)))

    derived_by_rule: Dict[str, _DerivedSupport] = {}
    derived_depths: Dict[str, int] = {}
    completed_digests: Dict[int, str] = {}
    completed_presence: Dict[int, frozenset] = {}
    stratum_wires: List[Dict[str, Any]] = []
    rule_evaluations = 0
    rule_firings = 0
    worklist_pops = 0

    for stratum in strata:
        current_rules = rules_by_stratum.get(stratum, [])
        required_index: Dict[str, List[_Rule]] = {}
        default_only: List[_Rule] = []
        for rule in current_rules:
            if rule.required_body:
                for literal in rule.required_body:
                    required_index.setdefault(_literal_key(literal), []).append(rule)
            else:
                default_only.append(rule)
        for key in required_index:
            required_index[key].sort(key=lambda item: canonical_bytes(_rule_wire(item)))

        queue = _sort_strings(list(present))
        queued = set(queue)

        def enqueue(key: str) -> None:
            if key not in queued:
                queue.append(key)
                queue.sort(key=canonical_bytes)
                queued.add(key)

        def evaluate(rule: _Rule) -> None:
            nonlocal rule_evaluations, rule_firings
            rule_evaluations += 1
            premise_keys = [_literal_key(item) for item in rule.required_body]
            if any(key not in present for key in premise_keys):
                return
            witnesses: List[_AbsenceWitness] = []
            for default in rule.default_not_positive_body:
                completed = completed_presence.get(default.referenced_stratum)
                completed_digest = completed_digests.get(default.referenced_stratum)
                if completed is None or completed_digest is None:
                    raise _KernelReject(
                        "INVARIANT_VIOLATION",
                        "/rule_bundle/rules",
                        {
                            "rule_id": rule.rule_id,
                            "invariant": "referenced_stratum_must_be_completed",
                        },
                    )
                positive_key = _literal_key(
                    _Literal("positive", default.atom_bytes)
                )
                if positive_key in completed:
                    return
                witnesses.append(
                    _absence_witness(
                        default.atom_bytes,
                        default.referenced_stratum,
                        completed_digest,
                    )
                )

            depth = 1
            if premise_keys:
                depth += max(literal_depths[key] for key in premise_keys)
            existing = derived_by_rule.get(rule.rule_id)
            if existing is None:
                support = _derived_support_for_rule(rule, witnesses, bundle)
                if support.derivation_id in set(base_ids):
                    raise _KernelReject(
                        "DERIVED_SUPPORT_TARGET",
                        "/fact_delta_inputs",
                        {"derivation_id": support.derivation_id},
                    )
                derived_by_rule[rule.rule_id] = support
                derived_depths[rule.rule_id] = depth
                rule_firings += 1
                if rule_firings > bundle.max_rule_firings:
                    raise _KernelReject(
                        "RULE_BUDGET_EXHAUSTED",
                        "/rule_bundle/limits/max_rule_firings",
                        {
                            "limit": bundle.max_rule_firings,
                            "observed": rule_firings,
                        },
                    )
                head_key = _literal_key(rule.head)
                old_depth = literal_depths.get(head_key)
                present[head_key] = rule.head
                if old_depth is None or depth < old_depth:
                    literal_depths[head_key] = depth
                    enqueue(head_key)
            else:
                old_support_depth = derived_depths[rule.rule_id]
                if depth < old_support_depth:
                    derived_depths[rule.rule_id] = depth
                    head_key = _literal_key(rule.head)
                    old_depth = literal_depths.get(head_key)
                    if old_depth is None or depth < old_depth:
                        literal_depths[head_key] = depth
                        enqueue(head_key)

        for rule in default_only:
            evaluate(rule)
        while queue:
            key = queue.pop(0)
            queued.remove(key)
            worklist_pops += 1
            for rule in required_index.get(key, []):
                evaluate(rule)

        current_derived = tuple(
            sorted(
                derived_by_rule.values(),
                key=lambda item: canonical_bytes(_derived_support_wire(item)),
            )
        )
        digest = _completed_stratum_digest(
            stratum, bundle, ordered_base, current_derived
        )
        completed_digests[stratum] = digest
        completed_presence[stratum] = frozenset(present)
        stratum_wires.append(
            {"kind": "LStratumDigest", "stratum": stratum, "digest": digest}
        )

    derived = tuple(
        sorted(
            derived_by_rule.values(),
            key=lambda item: canonical_bytes(_derived_support_wire(item)),
        )
    )
    derived_ids = [item.derivation_id for item in derived]
    if len(derived_ids) != len(set(derived_ids)) or set(base_ids).intersection(
        derived_ids
    ):
        raise _KernelReject(
            "INVARIANT_VIOLATION",
            "/next_materialization/derived_supports",
            {"invariant": "globally_unique_support_identity"},
        )
    maximum_depth = max(derived_depths.values(), default=0)
    if maximum_depth > bundle.max_derivation_depth:
        raise _KernelReject(
            "DERIVATION_DEPTH_EXCEEDED",
            "/rule_bundle/limits/max_derivation_depth",
            {"limit": bundle.max_derivation_depth, "observed": maximum_depth},
        )
    fact_states, conflicts = _project_facts(bundle, ordered_base, derived)
    return _Derivation(
        derived=derived,
        fact_states=fact_states,
        conflicts=conflicts,
        stratum_digests=tuple(_sort_wires(stratum_wires)),
        rule_evaluation_count=rule_evaluations,
        rule_firing_count=rule_firings,
        worklist_pop_count=worklist_pops,
        max_derivation_depth=maximum_depth,
    )


def _materialization_wire(
    bundle: _Bundle,
    through_logical_time: Optional[int],
    base_supports: Sequence[_BaseSupport],
    derivation: _Derivation,
) -> Dict[str, Any]:
    base_wires = _sort_wires([_base_support_wire(item) for item in base_supports])
    derived_wires = _sort_wires(
        [_derived_support_wire(item) for item in derivation.derived]
    )
    without_digest: Dict[str, Any] = {
        "kind": "LMaterialization",
        "schema_version": MATERIALIZATION_SCHEMA_VERSION,
        "contract_version": CONTRACT_VERSION,
        "profile_id": PROFILE_ID,
        "rule_bundle_digest": bundle.digest,
        "rule_set_version": bundle.rule_set_version,
        "dataflow_version": bundle.dataflow_version,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "through_logical_time": through_logical_time,
        "base_supports": base_wires,
        "derived_supports": derived_wires,
        "fact_states": list(derivation.fact_states),
        "conflicts": list(derivation.conflicts),
        "stratum_digests": list(derivation.stratum_digests),
    }
    materialization_digest = canonical_digest(
        {
            "kind": "M2MaterializationPreimage",
            "contract_version": CONTRACT_VERSION,
            "materialization_without_materialization_digest": without_digest,
        }
    )
    result = dict(without_digest)
    result["materialization_digest"] = materialization_digest
    return result


def _parse_base_support(value: Any, index: int, bundle: _Bundle) -> _BaseSupport:
    path = f"/prior_materialization/base_supports/{index}"
    item = _require_exact_object(
        value, BASE_SUPPORT_KEYS, "MALFORMED_MATERIALIZATION", path
    )
    if item.get("kind") != "LBaseSupport":
        raise _KernelReject("MALFORMED_MATERIALIZATION", path + "/kind")
    derivation_id = item.get("derivation_id")
    if not _valid_id(derivation_id):
        raise _KernelReject("MALFORMED_MATERIALIZATION", path + "/derivation_id")
    literal = _parse_literal(
        item.get("literal"), "MALFORMED_MATERIALIZATION", path + "/literal"
    )
    provenance = item.get("provenance_delta")
    if not isinstance(provenance, dict) or not provenance:
        raise _KernelReject(
            "MALFORMED_MATERIALIZATION", path + "/provenance_delta"
        )
    provenance_bytes = _freeze(provenance)
    rule_set_version = item.get("rule_set_version")
    dataflow_version = item.get("dataflow_version")
    if rule_set_version != bundle.rule_set_version:
        raise _KernelReject(
            "RULE_SET_VERSION_MISMATCH",
            path + "/rule_set_version",
            {"expected": bundle.rule_set_version, "actual": rule_set_version},
        )
    if dataflow_version != bundle.dataflow_version:
        raise _KernelReject(
            "DATAFLOW_VERSION_MISMATCH",
            path + "/dataflow_version",
            {"expected": bundle.dataflow_version, "actual": dataflow_version},
        )
    expected_digest = canonical_digest(
        _base_support_preimage(
            literal,
            provenance_bytes,
            rule_set_version,
            dataflow_version,
        )
    )
    supplied_digest = item.get("support_content_digest")
    if not _valid_digest(supplied_digest) or supplied_digest != expected_digest:
        raise _KernelReject(
            "PROVENANCE_INTEGRITY_VIOLATION",
            path + "/support_content_digest",
            {
                "derivation_id": derivation_id,
                "expected": expected_digest,
                "actual": supplied_digest,
            },
        )
    return _BaseSupport(
        derivation_id=derivation_id,
        support_content_digest=expected_digest,
        literal=literal,
        provenance_bytes=provenance_bytes,
        rule_set_version=rule_set_version,
        dataflow_version=dataflow_version,
    )


def _parse_prior(
    value: Any,
    logical_time: int,
    bundle: _Bundle,
) -> Optional[_Prior]:
    if value is None:
        return None
    path = "/prior_materialization"
    value = _ordered_materialization_view(value)
    _reject_canonical(value, path)
    item = _require_exact_object(
        value, MATERIALIZATION_KEYS, "MALFORMED_MATERIALIZATION", path
    )
    if item.get("kind") != "LMaterialization":
        raise _KernelReject("MALFORMED_MATERIALIZATION", path + "/kind")
    if item.get("schema_version") != MATERIALIZATION_SCHEMA_VERSION:
        raise _KernelReject(
            "UNSUPPORTED_MATERIALIZATION_SCHEMA", path + "/schema_version"
        )
    if item.get("contract_version") != CONTRACT_VERSION:
        raise _KernelReject("UNSUPPORTED_CONTRACT_VERSION", path + "/contract_version")
    if item.get("profile_id") != PROFILE_ID:
        raise _KernelReject("UNSUPPORTED_PROFILE", path + "/profile_id")
    if item.get("canonicalization_version") != CANONICALIZATION_VERSION:
        raise _KernelReject(
            "UNSUPPORTED_CANONICALIZATION", path + "/canonicalization_version"
        )
    if item.get("rule_bundle_digest") != bundle.digest:
        raise _KernelReject(
            "RULE_BUNDLE_MISMATCH",
            path + "/rule_bundle_digest",
            {"expected": bundle.digest, "actual": item.get("rule_bundle_digest")},
        )
    if item.get("rule_set_version") != bundle.rule_set_version:
        raise _KernelReject(
            "RULE_SET_VERSION_MISMATCH",
            path + "/rule_set_version",
            {
                "expected": bundle.rule_set_version,
                "actual": item.get("rule_set_version"),
            },
        )
    if item.get("dataflow_version") != bundle.dataflow_version:
        raise _KernelReject(
            "DATAFLOW_VERSION_MISMATCH",
            path + "/dataflow_version",
            {
                "expected": bundle.dataflow_version,
                "actual": item.get("dataflow_version"),
            },
        )
    through = item.get("through_logical_time")
    if through is not None and not _valid_nonnegative_int(through):
        raise _KernelReject("MALFORMED_MATERIALIZATION", path + "/through_logical_time")
    if through is not None and through > logical_time:
        raise _KernelReject(
            "LOGICAL_TIME_REGRESSION",
            path + "/through_logical_time",
            {"expected": logical_time, "actual": through},
        )
    raw_base = item.get("base_supports")
    if not isinstance(raw_base, list):
        raise _KernelReject("MALFORMED_MATERIALIZATION", path + "/base_supports")
    ordered_base = sorted(raw_base, key=diagnostic_order_key)
    base = tuple(
        sorted(
            (
                _parse_base_support(raw, index, bundle)
                for index, raw in enumerate(ordered_base)
            ),
            key=lambda support: canonical_bytes(_base_support_wire(support)),
        )
    )
    base_ids = [support.derivation_id for support in base]
    if len(base_ids) != len(set(base_ids)):
        raise _KernelReject(
            "PROVENANCE_INTEGRITY_VIOLATION",
            path + "/base_supports",
            {"invariant": "unique_base_support_identity"},
        )
    supplied_materialization_digest = item.get("materialization_digest")
    without_digest = {
        key: item[key] for key in item if key != "materialization_digest"
    }
    expected_supplied_digest = canonical_digest(
        {
            "kind": "M2MaterializationPreimage",
            "contract_version": CONTRACT_VERSION,
            "materialization_without_materialization_digest": without_digest,
        }
    )
    if (
        not _valid_digest(supplied_materialization_digest)
        or supplied_materialization_digest != expected_supplied_digest
    ):
        raise _KernelReject(
            "PROVENANCE_INTEGRITY_VIOLATION",
            path + "/materialization_digest",
            {
                "expected": expected_supplied_digest,
                "actual": supplied_materialization_digest,
            },
        )
    derivation = _derive(bundle, base)
    expected_wire = _materialization_wire(bundle, through, base, derivation)
    if canonical_bytes(item) != canonical_bytes(expected_wire):
        raise _KernelReject(
            "PROVENANCE_INTEGRITY_VIOLATION",
            path,
            {"invariant": "materialization_equals_clean_projection"},
        )
    return _Prior(
        through_logical_time=through,
        materialization_digest=supplied_materialization_digest,
        base=base,
        derived=derivation.derived,
    )


def _apply_inputs(
    parsed_inputs: Sequence[_ParsedInput],
    prior: Optional[_Prior],
) -> Tuple[Tuple[_BaseSupport, ...], Tuple[str, ...], bool]:
    prior_base = {item.derivation_id: item for item in (prior.base if prior else ())}
    prior_derived_ids = {item.derivation_id for item in (prior.derived if prior else ())}
    grouped: Dict[str, List[_ParsedInput]] = {}
    for item in parsed_inputs:
        grouped.setdefault(item.derivation_id, []).append(item)

    for derivation_id in sorted(grouped, key=canonical_bytes):
        group = grouped[derivation_id]
        additions = [item for item in group if item.diff == 1]
        retractions = [item for item in group if item.diff == -1]
        if (additions and retractions) or len(retractions) > 1:
            raise _KernelReject(
                "AMBIGUOUS_BATCH_DELTA",
                "/fact_delta_inputs",
                {"derivation_id": derivation_id},
            )
        stable_digests = {item.support.support_content_digest for item in group}
        if len(stable_digests) > 1:
            raise _KernelReject(
                "DERIVATION_IDENTITY_CONFLICT",
                "/fact_delta_inputs",
                {"derivation_id": derivation_id},
            )
        if derivation_id in prior_derived_ids:
            raise _KernelReject(
                "DERIVED_SUPPORT_TARGET",
                "/fact_delta_inputs",
                {"derivation_id": derivation_id},
            )
        existing = prior_base.get(derivation_id)
        support = group[0].support
        if retractions:
            if existing is None:
                raise _KernelReject(
                    "UNKNOWN_DERIVATION",
                    "/fact_delta_inputs",
                    {"derivation_id": derivation_id},
                )
            if existing.support_content_digest != support.support_content_digest:
                raise _KernelReject(
                    "DERIVATION_IDENTITY_CONFLICT",
                    "/fact_delta_inputs",
                    {"derivation_id": derivation_id},
                )
        elif existing is not None and (
            existing.support_content_digest != support.support_content_digest
        ):
            raise _KernelReject(
                "DERIVATION_IDENTITY_CONFLICT",
                "/fact_delta_inputs",
                {"derivation_id": derivation_id},
            )

    next_base = dict(prior_base)
    has_retraction = False
    for derivation_id in sorted(grouped, key=canonical_bytes):
        group = grouped[derivation_id]
        if group[0].diff == -1:
            has_retraction = True
            del next_base[derivation_id]
        else:
            next_base.setdefault(derivation_id, group[0].support)
    ordered_base = tuple(
        sorted(next_base.values(), key=lambda item: canonical_bytes(_base_support_wire(item)))
    )
    input_digests = tuple(_sort_strings(list({item.input_digest for item in parsed_inputs})))
    return ordered_base, input_digests, has_retraction


def _invocation_causation_id(
    logical_time: int,
    bundle_digest: str,
    prior_materialization_digest: Optional[str],
    input_delta_digests: Sequence[str],
) -> str:
    digest = canonical_digest(
        {
            "kind": "M2InvocationPreimage",
            "contract_version": CONTRACT_VERSION,
            "logical_time": logical_time,
            "rule_bundle_digest": bundle_digest,
            "prior_materialization_digest": prior_materialization_digest,
            "ordered_input_delta_digests": list(input_delta_digests),
        }
    )
    return "logic:" + digest.split(":", 1)[1]


def _derived_delta_wire(
    support: _DerivedSupport,
    diff: int,
    logical_time: int,
    causation_id: str,
) -> Dict[str, Any]:
    witness_digests = _sort_strings(
        [item.witness_digest for item in support.default_absence_witnesses]
    )
    provenance = {
        "kind": "LDerivedProvenanceDelta",
        "rule_id": support.rule_id,
        "rule_digest": support.rule_digest,
        "premise_literal_keys": list(support.premise_literal_keys),
        "default_absence_witness_digests": witness_digests,
        "support_content_digest": support.support_content_digest,
    }
    return {
        "kind": "LFactDeltaInput",
        "schema_version": INPUT_SCHEMA_VERSION,
        "polarity": support.literal.polarity,
        "delta": {
            "kind": "FactDelta",
            "tuple": _thaw(support.literal.atom_bytes),
            "logical_time": logical_time,
            "diff": diff,
            "derivation_id": support.derivation_id,
            "causation_id": causation_id,
            "provenance_delta": provenance,
            "rule_set_version": support.rule_set_version,
            "dataflow_version": support.dataflow_version,
        },
    }


def _derived_delta_projection(
    prior_derived: Sequence[_DerivedSupport],
    next_derived: Sequence[_DerivedSupport],
    logical_time: int,
    causation_id: str,
) -> Tuple[Dict[str, Any], ...]:
    old = {item.derivation_id: item for item in prior_derived}
    new = {item.derivation_id: item for item in next_derived}
    for derivation_id in sorted(set(old).intersection(new), key=canonical_bytes):
        if canonical_bytes(_derived_support_wire(old[derivation_id])) != canonical_bytes(
            _derived_support_wire(new[derivation_id])
        ):
            raise _KernelReject(
                "INVARIANT_VIOLATION",
                "/next_materialization/derived_supports",
                {
                    "derivation_id": derivation_id,
                    "invariant": "stable_derived_identity_content",
                },
            )
    deltas: List[Dict[str, Any]] = []
    for derivation_id in sorted(set(old) - set(new), key=canonical_bytes):
        deltas.append(
            _derived_delta_wire(old[derivation_id], -1, logical_time, causation_id)
        )
    for derivation_id in sorted(set(new) - set(old), key=canonical_bytes):
        deltas.append(
            _derived_delta_wire(new[derivation_id], 1, logical_time, causation_id)
        )
    return tuple(_sort_wires(deltas))


def _rejection_wire(
    rejection: _KernelReject,
    logical_time: Optional[int],
    rule_bundle_digest: Optional[str],
) -> Dict[str, Any]:
    context = {
        key: value
        for key, value in rejection.context.items()
        if key
        in {
            "expected",
            "actual",
            "derivation_id",
            "rule_id",
            "invariant",
            "limit",
            "observed",
            "source_stratum",
            "target_stratum",
            "support_content_digest",
        }
    }
    try:
        context = _thaw(canonical_bytes(context))
    except (CanonicalizationError, TypeError, ValueError):
        context = {"invariant": "closed_rejection_context"}
    return {
        "kind": "LRejection",
        "schema_version": RESULT_SCHEMA_VERSION,
        "contract_version": CONTRACT_VERSION,
        "code": rejection.code,
        "path": rejection.path,
        "logical_time": logical_time,
        "rule_bundle_digest": rule_bundle_digest,
        "context": context,
    }


def solve_l(
    prior_materialization: Any,
    rule_bundle: Any,
    fact_delta_inputs: Any,
    logical_time: Any,
) -> WireResult:
    """Compute one bounded pure-L fixpoint over explicit JSON values."""

    trusted_time: Optional[int] = None
    trusted_bundle_digest: Optional[str] = None
    try:
        if not _valid_nonnegative_int(logical_time):
            raise _KernelReject(
                "LOGICAL_TIME_MISMATCH",
                "/logical_time",
                {"invariant": "nonnegative_int64_logical_time"},
            )
        trusted_time = logical_time
        bundle = _parse_bundle(rule_bundle)
        trusted_bundle_digest = bundle.digest
        if not isinstance(fact_delta_inputs, list):
            raise _KernelReject(
                "MALFORMED_FACT_DELTA_INPUT", "/fact_delta_inputs"
            )
        if len(fact_delta_inputs) > MAX_FACT_DELTA_INPUTS:
            raise _KernelReject(
                "MALFORMED_FACT_DELTA_INPUT",
                "/fact_delta_inputs",
                {"limit": MAX_FACT_DELTA_INPUTS, "observed": len(fact_delta_inputs)},
            )
        prior = _parse_prior(prior_materialization, logical_time, bundle)
        validation_order = sorted(fact_delta_inputs, key=diagnostic_order_key)
        for index, raw in enumerate(validation_order):
            _reject_canonical(raw, f"/fact_delta_inputs/{index}")
        normalized_raw_inputs = sorted(fact_delta_inputs, key=canonical_bytes)
        parsed_inputs = tuple(
            _parse_fact_delta_input(raw, index, logical_time, bundle)
            for index, raw in enumerate(normalized_raw_inputs)
        )
        next_base, input_digests, _has_retraction = _apply_inputs(
            parsed_inputs, prior
        )
        derivation = _derive(bundle, next_base)
        next_materialization = _materialization_wire(
            bundle, logical_time, next_base, derivation
        )
        prior_digest = prior.materialization_digest if prior else None
        causation_id = _invocation_causation_id(
            logical_time,
            bundle.digest,
            prior_digest,
            input_digests,
        )
        derived_deltas = _derived_delta_projection(
            prior.derived if prior else (),
            derivation.derived,
            logical_time,
            causation_id,
        )
        without_digest: Dict[str, Any] = {
            "kind": "LFixpointResult",
            "schema_version": RESULT_SCHEMA_VERSION,
            "contract_version": CONTRACT_VERSION,
            "logical_time": logical_time,
            "rule_bundle_digest": bundle.digest,
            "prior_materialization_digest": prior_digest,
            "input_delta_digests": list(input_digests),
            "next_materialization": next_materialization,
            "derived_fact_deltas": list(derived_deltas),
            "stats": {
                "evaluation_mode": "full_recompute",
                "rule_evaluation_count": derivation.rule_evaluation_count,
                "rule_firing_count": derivation.rule_firing_count,
                "worklist_pop_count": derivation.worklist_pop_count,
                "max_derivation_depth": derivation.max_derivation_depth,
            },
        }
        fixpoint_digest = canonical_digest(
            {
                "kind": "M2FixpointPreimage",
                "contract_version": CONTRACT_VERSION,
                "fixpoint_result_without_fixpoint_digest": without_digest,
            }
        )
        result = dict(without_digest)
        result["fixpoint_digest"] = fixpoint_digest
        return _thaw(canonical_bytes(result))
    except _KernelReject as rejection:
        return _rejection_wire(
            rejection,
            trusted_time,
            getattr(
                rejection, "trusted_rule_bundle_digest", trusted_bundle_digest
            ),
        )
    except CanonicalizationError:
        return _rejection_wire(
            _KernelReject(
                "CANONICALIZATION_VIOLATION",
                "",
                {"invariant": "canonical_json_domain"},
            ),
            trusted_time,
            trusted_bundle_digest,
        )
    except Exception:
        return _rejection_wire(
            _KernelReject(
                "INVARIANT_VIOLATION",
                "",
                {"invariant": "closed_kernel_failure"},
            ),
            trusted_time,
            trusted_bundle_digest,
        )
