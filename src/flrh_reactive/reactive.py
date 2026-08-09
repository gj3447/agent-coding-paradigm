"""Bounded, deterministic scalar-frontier M3 reactive reference kernel."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from .canonical import (
    INT64_MAX,
    CanonicalizationError,
    canonical_bytes,
    canonical_digest,
    diagnostic_order_key,
    thaw,
)


CONTRACT_VERSION = "flrh-r-kernel/1"
PROFILE_ID = "flrh-r-scalar-frontier/1"
PROFILE_SCHEMA_VERSION = "flrh-r-profile/1"
STATE_SCHEMA_VERSION = "flrh-r-state/1"
COMMAND_SCHEMA_VERSION = "flrh-r-command/1"
VALUE_DELTA_SCHEMA_VERSION = "flrh-r-value-delta/1"
RESULT_SCHEMA_VERSION = "flrh-r-result/1"
CANONICALIZATION_VERSION = "flrh-cjson/1"

ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/-]*$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")

PROFILE_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "contract_version",
        "profile_id",
        "dataflow_version",
        "canonicalization_version",
        "source_ids",
        "late_event_policy",
        "overflow_policy",
        "limits",
        "profile_digest",
    }
)
LIMIT_KEYS = frozenset(
    {
        "max_deltas_per_command",
        "max_active_values",
        "max_open_epochs",
        "max_ready_batches",
        "max_demand_per_command",
        "max_outstanding_demand",
    }
)
LIMIT_CEILINGS = {
    "max_deltas_per_command": 10000,
    "max_active_values": 10000,
    "max_open_epochs": 1024,
    "max_ready_batches": 1024,
    "max_demand_per_command": 1024,
    "max_outstanding_demand": 10000,
}
STATE_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "contract_version",
        "profile_id",
        "profile_digest",
        "dataflow_version",
        "canonicalization_version",
        "source_frontiers",
        "global_low_watermark",
        "outstanding_demand",
        "open_epochs",
        "ready_batches",
        "state_digest",
    }
)
DELTA_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "delivery_id",
        "source_id",
        "logical_time",
        "diff",
        "dataflow_version",
        "value_kind",
        "value_digest",
        "value",
    }
)
STORED_KEYS = frozenset(
    {
        "kind",
        "delivery_id",
        "source_id",
        "logical_time",
        "value_kind",
        "value_digest",
        "value",
    }
)
VERSION_KEYS = frozenset(
    {
        "workflow",
        "state_schema",
        "event_schema",
        "graph_schema",
        "rule_set",
        "dataflow",
        "canonicalization",
        "tool",
        "model",
        "oracle",
        "gate",
        "resolver",
        "composition_profile",
    }
)
PROPOSAL_KEYS = frozenset(
    {
        "kind",
        "proposal_id",
        "effect_type",
        "action_digest",
        "cause_id",
        "correlation_id",
        "proposal_dedup_key",
        "destination_digest",
        "goal_id",
        "obligation_id",
        "declared_risk_hint",
        "preconditions",
        "versions",
    }
)
VERDICT_KEYS = frozenset(
    {
        "kind",
        "verdict_id",
        "proposal_id",
        "status",
        "support_derivation_ids",
        "cause_id",
        "rule_set_version",
    }
)

WireResult = Dict[str, Any]


class _Reject(Exception):
    def __init__(
        self,
        code: str,
        path: str,
        context: Optional[Mapping[str, Any]] = None,
        logical_time: Optional[int] = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.path = path
        self.context = dict(context or {})
        self.logical_time = logical_time


def _valid_id(value: Any) -> bool:
    return isinstance(value, str) and len(value) <= 128 and ID_PATTERN.fullmatch(value) is not None


def _valid_version(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= 128
        and VERSION_PATTERN.fullmatch(value) is not None
    )


def _valid_digest(value: Any) -> bool:
    return isinstance(value, str) and DIGEST_PATTERN.fullmatch(value) is not None


def _valid_time(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= INT64_MAX


def _exact(value: Any, keys: frozenset[str], code: str, path: str) -> Dict[str, Any]:
    if not isinstance(value, dict) or frozenset(value) != keys:
        raise _Reject(code, path)
    return value


def _sorted_strings(values: Sequence[str]) -> List[str]:
    return sorted(values, key=canonical_bytes)


def _sorted_wires(values: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return [thaw(value) for value in sorted(values, key=canonical_bytes)]


def _profile_preimage(profile: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "kind": "M3ProfilePreimage",
        "contract_version": CONTRACT_VERSION,
        "profile_id": profile["profile_id"],
        "dataflow_version": profile["dataflow_version"],
        "canonicalization_version": profile["canonicalization_version"],
        "ordered_source_ids": list(profile["source_ids"]),
        "late_event_policy": profile["late_event_policy"],
        "overflow_policy": profile["overflow_policy"],
        "limits": dict(profile["limits"]),
    }


def _parse_profile(raw: Any) -> Dict[str, Any]:
    profile = _exact(raw, PROFILE_KEYS, "MALFORMED_DATAFLOW_PROFILE", "/profile")
    if profile["kind"] != "RDataflowProfile":
        raise _Reject("MALFORMED_DATAFLOW_PROFILE", "/profile/kind")
    if profile["schema_version"] != PROFILE_SCHEMA_VERSION:
        raise _Reject("UNSUPPORTED_PROFILE_SCHEMA", "/profile/schema_version")
    if profile["contract_version"] != CONTRACT_VERSION:
        raise _Reject("UNSUPPORTED_CONTRACT_VERSION", "/profile/contract_version")
    if profile["profile_id"] != PROFILE_ID:
        raise _Reject("UNSUPPORTED_PROFILE", "/profile/profile_id")
    if profile["canonicalization_version"] != CANONICALIZATION_VERSION:
        raise _Reject("UNSUPPORTED_CANONICALIZATION", "/profile/canonicalization_version")
    if not _valid_version(profile["dataflow_version"]):
        raise _Reject("MALFORMED_DATAFLOW_PROFILE", "/profile/dataflow_version")
    source_ids = profile["source_ids"]
    if (
        not isinstance(source_ids, list)
        or not 1 <= len(source_ids) <= 256
        or any(not _valid_id(item) for item in source_ids)
        or len(set(source_ids)) != len(source_ids)
        or source_ids != _sorted_strings(source_ids)
    ):
        raise _Reject("MALFORMED_DATAFLOW_PROFILE", "/profile/source_ids")
    if profile["late_event_policy"] != "reject":
        raise _Reject("UNSUPPORTED_PROFILE", "/profile/late_event_policy")
    if profile["overflow_policy"] != "reject_new":
        raise _Reject("UNSUPPORTED_PROFILE", "/profile/overflow_policy")
    limits = _exact(profile["limits"], LIMIT_KEYS, "MALFORMED_DATAFLOW_PROFILE", "/profile/limits")
    for key, ceiling in LIMIT_CEILINGS.items():
        value = limits[key]
        if not _valid_time(value) or value < 1 or value > ceiling:
            raise _Reject("MALFORMED_DATAFLOW_PROFILE", f"/profile/limits/{key}")
    if not _valid_digest(profile["profile_digest"]):
        raise _Reject("MALFORMED_DATAFLOW_PROFILE", "/profile/profile_digest")
    normalized = thaw(profile)
    expected = canonical_digest(_profile_preimage(normalized))
    if normalized["profile_digest"] != expected:
        raise _Reject(
            "PROFILE_MISMATCH",
            "/profile/profile_digest",
            {"expected": expected, "actual": normalized["profile_digest"]},
        )
    return normalized


def _parse_versions(raw: Any, path: str) -> Dict[str, str]:
    versions = _exact(raw, VERSION_KEYS, "MALFORMED_VALUE_DELTA", path)
    if any(not _valid_version(value) for value in versions.values()):
        raise _Reject("MALFORMED_VALUE_DELTA", path)
    return dict(versions)


def _parse_protocol_value(raw: Any, value_kind: str, path: str) -> Dict[str, Any]:
    if value_kind == "effect_proposal":
        value = _exact(raw, PROPOSAL_KEYS, "MALFORMED_VALUE_DELTA", path)
        if value["kind"] != "EffectProposal":
            raise _Reject("MALFORMED_VALUE_DELTA", f"{path}/kind")
        id_fields = (
            "proposal_id",
            "effect_type",
            "cause_id",
            "correlation_id",
            "proposal_dedup_key",
            "goal_id",
            "obligation_id",
        )
        if any(not _valid_id(value[key]) for key in id_fields):
            raise _Reject("MALFORMED_VALUE_DELTA", path)
        if not _valid_digest(value["action_digest"]) or not _valid_digest(
            value["destination_digest"]
        ):
            raise _Reject("MALFORMED_VALUE_DELTA", path)
        if value["declared_risk_hint"] not in {
            "read_only",
            "reversible",
            "high_risk_external",
            "unknown",
        }:
            raise _Reject("MALFORMED_VALUE_DELTA", f"{path}/declared_risk_hint")
        preconditions = value["preconditions"]
        if (
            not isinstance(preconditions, list)
            or any(not _valid_id(item) for item in preconditions)
            or len(set(preconditions)) != len(preconditions)
        ):
            raise _Reject("MALFORMED_VALUE_DELTA", f"{path}/preconditions")
        _parse_versions(value["versions"], f"{path}/versions")
    elif value_kind == "eligibility_verdict":
        value = _exact(raw, VERDICT_KEYS, "MALFORMED_VALUE_DELTA", path)
        if value["kind"] != "EligibilityVerdict":
            raise _Reject("MALFORMED_VALUE_DELTA", f"{path}/kind")
        if any(
            not _valid_id(value[key])
            for key in ("verdict_id", "proposal_id", "cause_id")
        ):
            raise _Reject("MALFORMED_VALUE_DELTA", path)
        if value["status"] not in {"eligible", "ineligible", "conflicted"}:
            raise _Reject("MALFORMED_VALUE_DELTA", f"{path}/status")
        supports = value["support_derivation_ids"]
        if (
            not isinstance(supports, list)
            or any(not _valid_id(item) for item in supports)
            or len(set(supports)) != len(supports)
        ):
            raise _Reject("MALFORMED_VALUE_DELTA", f"{path}/support_derivation_ids")
        if not _valid_version(value["rule_set_version"]):
            raise _Reject("MALFORMED_VALUE_DELTA", f"{path}/rule_set_version")
    else:
        raise _Reject("MALFORMED_VALUE_DELTA", path)
    return thaw(value)


def _value_digest(value_kind: str, value: Mapping[str, Any]) -> str:
    return canonical_digest(
        {
            "kind": "M3ValuePreimage",
            "contract_version": CONTRACT_VERSION,
            "value_kind": value_kind,
            "value": thaw(value),
        }
    )


def _delivery_id(
    source_id: str,
    logical_time: int,
    dataflow_version: str,
    value_kind: str,
    value_digest: str,
) -> str:
    digest = canonical_digest(
        {
            "kind": "M3DeliveryPreimage",
            "contract_version": CONTRACT_VERSION,
            "source_id": source_id,
            "logical_time": logical_time,
            "dataflow_version": dataflow_version,
            "value_kind": value_kind,
            "value_digest": value_digest,
        }
    )
    return "delivery:" + digest.split(":", 1)[1]


def _parse_delta(
    raw: Any,
    profile: Mapping[str, Any],
    source_frontiers: Mapping[str, Optional[int]],
    path: str,
) -> Dict[str, Any]:
    delta = _exact(raw, DELTA_KEYS, "MALFORMED_VALUE_DELTA", path)
    if delta["kind"] != "RValueDelta":
        raise _Reject("MALFORMED_VALUE_DELTA", f"{path}/kind")
    if delta["schema_version"] != VALUE_DELTA_SCHEMA_VERSION:
        raise _Reject("UNSUPPORTED_VALUE_DELTA_SCHEMA", f"{path}/schema_version")
    if not _valid_id(delta["source_id"]) or delta["source_id"] not in source_frontiers:
        raise _Reject(
            "UNKNOWN_FRONTIER_SOURCE",
            f"{path}/source_id",
            {"source_id": delta["source_id"]} if _valid_id(delta["source_id"]) else {},
        )
    if not _valid_time(delta["logical_time"]):
        raise _Reject("MALFORMED_VALUE_DELTA", f"{path}/logical_time")
    if delta["diff"] not in (-1, 1) or isinstance(delta["diff"], bool):
        raise _Reject("MALFORMED_VALUE_DELTA", f"{path}/diff")
    if delta["dataflow_version"] != profile["dataflow_version"]:
        raise _Reject("DATAFLOW_VERSION_MISMATCH", f"{path}/dataflow_version")
    if delta["value_kind"] not in {"effect_proposal", "eligibility_verdict"}:
        raise _Reject("MALFORMED_VALUE_DELTA", f"{path}/value_kind")
    if not _valid_digest(delta["value_digest"]):
        raise _Reject("MALFORMED_VALUE_DELTA", f"{path}/value_digest")
    if not _valid_id(delta["delivery_id"]):
        raise _Reject("MALFORMED_VALUE_DELTA", f"{path}/delivery_id")
    value = _parse_protocol_value(delta["value"], delta["value_kind"], f"{path}/value")
    if (
        delta["value_kind"] == "effect_proposal"
        and value["versions"]["dataflow"] != profile["dataflow_version"]
    ):
        raise _Reject("DATAFLOW_VERSION_MISMATCH", f"{path}/value/versions/dataflow")
    expected_value_digest = _value_digest(delta["value_kind"], value)
    if delta["value_digest"] != expected_value_digest:
        raise _Reject(
            "VALUE_IDENTITY_CONFLICT",
            f"{path}/value_digest",
            {"expected": expected_value_digest, "actual": delta["value_digest"]},
            delta["logical_time"],
        )
    expected_delivery = _delivery_id(
        delta["source_id"],
        delta["logical_time"],
        delta["dataflow_version"],
        delta["value_kind"],
        expected_value_digest,
    )
    if delta["delivery_id"] != expected_delivery:
        raise _Reject(
            "VALUE_IDENTITY_CONFLICT",
            f"{path}/delivery_id",
            {"expected": expected_delivery, "actual": delta["delivery_id"]},
            delta["logical_time"],
        )
    # A source frontier is that source's assertion that no earlier value remains.
    source_frontier = source_frontiers[delta["source_id"]]
    if source_frontier is not None and delta["logical_time"] < source_frontier:
        raise _Reject(
            "LATE_DELTA",
            f"{path}/logical_time",
            {"source_id": delta["source_id"]},
            delta["logical_time"],
        )
    return {
        "kind": "RValueDelta",
        "schema_version": VALUE_DELTA_SCHEMA_VERSION,
        "delivery_id": expected_delivery,
        "source_id": delta["source_id"],
        "logical_time": delta["logical_time"],
        "diff": delta["diff"],
        "dataflow_version": profile["dataflow_version"],
        "value_kind": delta["value_kind"],
        "value_digest": expected_value_digest,
        "value": value,
    }


def _stored(delta: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "kind": "RStoredValue",
        "delivery_id": delta["delivery_id"],
        "source_id": delta["source_id"],
        "logical_time": delta["logical_time"],
        "value_kind": delta["value_kind"],
        "value_digest": delta["value_digest"],
        "value": thaw(delta["value"]),
    }


def _state_digest(without_digest: Mapping[str, Any]) -> str:
    return canonical_digest(
        {
            "kind": "M3StatePreimage",
            "contract_version": CONTRACT_VERSION,
            "state_without_state_digest": thaw(without_digest),
        }
    )


def _with_state_digest(without_digest: Mapping[str, Any]) -> Dict[str, Any]:
    state = thaw(without_digest)
    state["state_digest"] = _state_digest(state)
    return thaw(state)


def _initial_state(profile: Mapping[str, Any]) -> Dict[str, Any]:
    return _with_state_digest(
        {
            "kind": "RReactiveState",
            "schema_version": STATE_SCHEMA_VERSION,
            "contract_version": CONTRACT_VERSION,
            "profile_id": PROFILE_ID,
            "profile_digest": profile["profile_digest"],
            "dataflow_version": profile["dataflow_version"],
            "canonicalization_version": CANONICALIZATION_VERSION,
            "source_frontiers": [
                {"kind": "RSourceFrontier", "source_id": item, "low_watermark": None}
                for item in profile["source_ids"]
            ],
            "global_low_watermark": None,
            "outstanding_demand": 0,
            "open_epochs": [],
            "ready_batches": [],
        }
    )


def _published_digest(
    batch: Mapping[str, Any],
    proposals: Sequence[Mapping[str, Any]],
    verdicts: Sequence[Mapping[str, Any]],
) -> str:
    return canonical_digest(
        {
            "kind": "M3PublishedBatchPreimage",
            "contract_version": CONTRACT_VERSION,
            "batch": thaw(batch),
            "ordered_effect_proposals": _sorted_wires(proposals),
            "ordered_eligibility_verdicts": _sorted_wires(verdicts),
        }
    )


def _stable_batch_preimage(
    profile_digest: str,
    logical_time: int,
    low_watermark: int,
    proposal_ids: Sequence[str],
    verdict_ids: Sequence[str],
    dataflow_version: str,
) -> Dict[str, Any]:
    return {
        "kind": "M3StableBatchPreimage",
        "contract_version": CONTRACT_VERSION,
        "profile_digest": profile_digest,
        "logical_time": logical_time,
        "low_watermark": low_watermark,
        "ordered_proposal_ids": list(proposal_ids),
        "ordered_eligibility_verdict_ids": list(verdict_ids),
        "dataflow_version": dataflow_version,
    }


def _build_published_batch(
    profile: Mapping[str, Any], epoch: Mapping[str, Any], low_watermark: int
) -> Dict[str, Any]:
    proposals = [item["value"] for item in epoch["values"] if item["value_kind"] == "effect_proposal"]
    verdicts = [
        item["value"] for item in epoch["values"] if item["value_kind"] == "eligibility_verdict"
    ]
    proposal_by_id: Dict[str, Dict[str, Any]] = {}
    for proposal in proposals:
        proposal_id = proposal["proposal_id"]
        if proposal_id in proposal_by_id:
            raise _Reject(
                "UNRESOLVED_DEPENDENCY",
                "/prior_state/open_epochs",
                {"reason": "duplicate proposal_id"},
                epoch["logical_time"],
            )
        proposal_by_id[proposal_id] = proposal
    verdict_by_id: Dict[str, Dict[str, Any]] = {}
    verdict_by_proposal: Dict[str, List[Dict[str, Any]]] = {}
    for verdict in verdicts:
        if verdict["verdict_id"] in verdict_by_id:
            raise _Reject(
                "UNRESOLVED_DEPENDENCY",
                "/prior_state/open_epochs",
                {"reason": "duplicate verdict_id"},
                epoch["logical_time"],
            )
        verdict_by_id[verdict["verdict_id"]] = verdict
        verdict_by_proposal.setdefault(verdict["proposal_id"], []).append(verdict)
    if set(proposal_by_id) != set(verdict_by_proposal) or any(
        len(items) != 1 for items in verdict_by_proposal.values()
    ):
        raise _Reject(
            "UNRESOLVED_DEPENDENCY",
            "/prior_state/open_epochs",
            {"reason": "proposal verdict relation is not a total bijection"},
            epoch["logical_time"],
        )
    for proposal_id, proposal in proposal_by_id.items():
        verdict = verdict_by_proposal[proposal_id][0]
        if verdict["rule_set_version"] != proposal["versions"]["rule_set"]:
            raise _Reject(
                "RULE_SET_VERSION_MISMATCH",
                "/prior_state/open_epochs",
                {
                    "expected": proposal["versions"]["rule_set"],
                    "actual": verdict["rule_set_version"],
                },
                epoch["logical_time"],
            )
    ordered_proposals = _sorted_wires(proposals)
    ordered_verdicts = _sorted_wires(verdicts)
    proposal_ids = _sorted_strings([item["proposal_id"] for item in ordered_proposals])
    verdict_ids = _sorted_strings([item["verdict_id"] for item in ordered_verdicts])
    stable_preimage = _stable_batch_preimage(
        profile["profile_digest"],
        epoch["logical_time"],
        low_watermark,
        proposal_ids,
        verdict_ids,
        profile["dataflow_version"],
    )
    batch_digest = canonical_digest(stable_preimage)
    suffix = batch_digest.split(":", 1)[1]
    batch = {
        "kind": "StableProposalBatch",
        "batch_id": "batch:" + suffix,
        "logical_time": epoch["logical_time"],
        "low_watermark": low_watermark,
        "proposal_ids": proposal_ids,
        "eligibility_verdict_ids": verdict_ids,
        "batch_digest": batch_digest,
        "cause_id": "reaction:" + suffix,
        "dataflow_version": profile["dataflow_version"],
    }
    published = {
        "kind": "RPublishedBatch",
        "batch": batch,
        "effect_proposals": ordered_proposals,
        "eligibility_verdicts": ordered_verdicts,
    }
    published["published_batch_digest"] = _published_digest(
        batch, ordered_proposals, ordered_verdicts
    )
    return thaw(published)


def _parse_published(raw: Any, profile: Mapping[str, Any], path: str) -> Dict[str, Any]:
    published = _exact(
        raw,
        frozenset(
            {
                "kind",
                "batch",
                "effect_proposals",
                "eligibility_verdicts",
                "published_batch_digest",
            }
        ),
        "MALFORMED_REACTIVE_STATE",
        path,
    )
    if published["kind"] != "RPublishedBatch":
        raise _Reject("MALFORMED_REACTIVE_STATE", f"{path}/kind")
    if not isinstance(published["effect_proposals"], list) or not isinstance(
        published["eligibility_verdicts"], list
    ):
        raise _Reject("MALFORMED_REACTIVE_STATE", path)
    if not published["effect_proposals"] and not published["eligibility_verdicts"]:
        raise _Reject("MALFORMED_REACTIVE_STATE", path)
    try:
        proposals = [
            _parse_protocol_value(item, "effect_proposal", f"{path}/effect_proposals/{index}")
            for index, item in enumerate(published["effect_proposals"])
        ]
        verdicts = [
            _parse_protocol_value(item, "eligibility_verdict", f"{path}/eligibility_verdicts/{index}")
            for index, item in enumerate(published["eligibility_verdicts"])
        ]
    except _Reject as rejection:
        if rejection.code == "MALFORMED_VALUE_DELTA":
            raise _Reject("MALFORMED_REACTIVE_STATE", rejection.path) from None
        raise
    if (
        published["effect_proposals"] != proposals
        or published["eligibility_verdicts"] != verdicts
    ):
        raise _Reject("MALFORMED_REACTIVE_STATE", path)
    if proposals != _sorted_wires(proposals) or verdicts != _sorted_wires(verdicts):
        raise _Reject("MALFORMED_REACTIVE_STATE", path)
    proposal_by_id = {item["proposal_id"]: item for item in proposals}
    verdict_by_id = {item["verdict_id"]: item for item in verdicts}
    verdict_by_proposal: Dict[str, List[Dict[str, Any]]] = {}
    for verdict in verdicts:
        verdict_by_proposal.setdefault(verdict["proposal_id"], []).append(verdict)
    if (
        len(proposal_by_id) != len(proposals)
        or len(verdict_by_id) != len(verdicts)
        or set(proposal_by_id) != set(verdict_by_proposal)
        or any(len(items) != 1 for items in verdict_by_proposal.values())
    ):
        raise _Reject(
            "UNRESOLVED_DEPENDENCY",
            path,
            {"reason": "proposal verdict relation is not a total bijection"},
            published["batch"].get("logical_time")
            if isinstance(published["batch"], dict)
            and _valid_time(published["batch"].get("logical_time"))
            else None,
        )
    for proposal_id, proposal in proposal_by_id.items():
        if proposal["versions"]["dataflow"] != profile["dataflow_version"]:
            raise _Reject("DATAFLOW_VERSION_MISMATCH", f"{path}/effect_proposals")
        actual_rule_set = verdict_by_proposal[proposal_id][0]["rule_set_version"]
        if actual_rule_set != proposal["versions"]["rule_set"]:
            raise _Reject(
                "RULE_SET_VERSION_MISMATCH",
                path,
                {"expected": proposal["versions"]["rule_set"], "actual": actual_rule_set},
            )
    batch = published["batch"]
    batch_keys = frozenset(
        {
            "kind",
            "batch_id",
            "logical_time",
            "low_watermark",
            "proposal_ids",
            "eligibility_verdict_ids",
            "batch_digest",
            "cause_id",
            "dataflow_version",
        }
    )
    batch = _exact(batch, batch_keys, "MALFORMED_REACTIVE_STATE", f"{path}/batch")
    if (
        batch["kind"] != "StableProposalBatch"
        or not _valid_time(batch["logical_time"])
        or not _valid_time(batch["low_watermark"])
        or batch["low_watermark"] <= batch["logical_time"]
        or batch["dataflow_version"] != profile["dataflow_version"]
    ):
        raise _Reject("MALFORMED_REACTIVE_STATE", f"{path}/batch")
    proposal_ids = _sorted_strings([item["proposal_id"] for item in proposals])
    verdict_ids = _sorted_strings([item["verdict_id"] for item in verdicts])
    if batch["proposal_ids"] != proposal_ids or batch["eligibility_verdict_ids"] != verdict_ids:
        raise _Reject("MALFORMED_REACTIVE_STATE", f"{path}/batch")
    expected_batch_digest = canonical_digest(
        _stable_batch_preimage(
            profile["profile_digest"],
            batch["logical_time"],
            batch["low_watermark"],
            proposal_ids,
            verdict_ids,
            profile["dataflow_version"],
        )
    )
    suffix = expected_batch_digest.split(":", 1)[1]
    if (
        batch["batch_digest"] != expected_batch_digest
        or batch["batch_id"] != "batch:" + suffix
        or batch["cause_id"] != "reaction:" + suffix
    ):
        raise _Reject("MALFORMED_REACTIVE_STATE", f"{path}/batch/batch_digest")
    expected_published = _published_digest(batch, proposals, verdicts)
    if published["published_batch_digest"] != expected_published:
        raise _Reject("MALFORMED_REACTIVE_STATE", f"{path}/published_batch_digest")
    return {
        "kind": "RPublishedBatch",
        "batch": thaw(batch),
        "effect_proposals": proposals,
        "eligibility_verdicts": verdicts,
        "published_batch_digest": published["published_batch_digest"],
    }


def _parse_state(raw: Any, profile: Mapping[str, Any]) -> Dict[str, Any]:
    if raw is None:
        return _initial_state(profile)
    state = _exact(raw, STATE_KEYS, "MALFORMED_REACTIVE_STATE", "/prior_state")
    if state["kind"] != "RReactiveState":
        raise _Reject("MALFORMED_REACTIVE_STATE", "/prior_state/kind")
    if state["schema_version"] != STATE_SCHEMA_VERSION:
        raise _Reject("UNSUPPORTED_STATE_SCHEMA", "/prior_state/schema_version")
    if state["contract_version"] != CONTRACT_VERSION:
        raise _Reject("UNSUPPORTED_CONTRACT_VERSION", "/prior_state/contract_version")
    if state["profile_id"] != PROFILE_ID:
        raise _Reject("UNSUPPORTED_PROFILE", "/prior_state/profile_id")
    if state["canonicalization_version"] != CANONICALIZATION_VERSION:
        raise _Reject("UNSUPPORTED_CANONICALIZATION", "/prior_state/canonicalization_version")
    if state["profile_digest"] != profile["profile_digest"]:
        raise _Reject("PROFILE_MISMATCH", "/prior_state/profile_digest")
    if state["dataflow_version"] != profile["dataflow_version"]:
        raise _Reject("DATAFLOW_VERSION_MISMATCH", "/prior_state/dataflow_version")
    frontiers = state["source_frontiers"]
    if not isinstance(frontiers, list):
        raise _Reject("MALFORMED_REACTIVE_STATE", "/prior_state/source_frontiers")
    parsed_frontiers: List[Dict[str, Any]] = []
    for index, item in enumerate(frontiers):
        item = _exact(
            item,
            frozenset({"kind", "source_id", "low_watermark"}),
            "MALFORMED_REACTIVE_STATE",
            f"/prior_state/source_frontiers/{index}",
        )
        if (
            item["kind"] != "RSourceFrontier"
            or not _valid_id(item["source_id"])
            or (item["low_watermark"] is not None and not _valid_time(item["low_watermark"]))
        ):
            raise _Reject("MALFORMED_REACTIVE_STATE", f"/prior_state/source_frontiers/{index}")
        parsed_frontiers.append(dict(item))
    frontier_source_ids = [item["source_id"] for item in parsed_frontiers]
    if (
        len(set(frontier_source_ids)) != len(frontier_source_ids)
        or set(frontier_source_ids) != set(profile["source_ids"])
        or parsed_frontiers != _sorted_wires(parsed_frontiers)
    ):
        raise _Reject("MALFORMED_REACTIVE_STATE", "/prior_state/source_frontiers")
    watermarks = [item["low_watermark"] for item in parsed_frontiers]
    expected_global = None if any(item is None for item in watermarks) else min(watermarks)
    if state["global_low_watermark"] != expected_global:
        raise _Reject("MALFORMED_REACTIVE_STATE", "/prior_state/global_low_watermark")
    demand = state["outstanding_demand"]
    if (
        not _valid_time(demand)
        or demand > profile["limits"]["max_outstanding_demand"]
    ):
        raise _Reject("MALFORMED_REACTIVE_STATE", "/prior_state/outstanding_demand")
    if not isinstance(state["open_epochs"], list) or not isinstance(state["ready_batches"], list):
        raise _Reject("MALFORMED_REACTIVE_STATE", "/prior_state")
    epochs: List[Dict[str, Any]] = []
    seen_deliveries: set[str] = set()
    for epoch_index, epoch in enumerate(state["open_epochs"]):
        epoch = _exact(
            epoch,
            frozenset({"kind", "logical_time", "values"}),
            "MALFORMED_REACTIVE_STATE",
            f"/prior_state/open_epochs/{epoch_index}",
        )
        if (
            epoch["kind"] != "ROpenEpoch"
            or not _valid_time(epoch["logical_time"])
            or not isinstance(epoch["values"], list)
            or not epoch["values"]
            or (expected_global is not None and epoch["logical_time"] < expected_global)
        ):
            raise _Reject("MALFORMED_REACTIVE_STATE", f"/prior_state/open_epochs/{epoch_index}")
        values: List[Dict[str, Any]] = []
        for value_index, stored in enumerate(epoch["values"]):
            stored = _exact(
                stored,
                STORED_KEYS,
                "MALFORMED_REACTIVE_STATE",
                f"/prior_state/open_epochs/{epoch_index}/values/{value_index}",
            )
            if stored["kind"] != "RStoredValue" or stored["logical_time"] != epoch["logical_time"]:
                raise _Reject("MALFORMED_REACTIVE_STATE", f"/prior_state/open_epochs/{epoch_index}/values/{value_index}")
            if stored["source_id"] not in profile["source_ids"]:
                raise _Reject("UNKNOWN_FRONTIER_SOURCE", f"/prior_state/open_epochs/{epoch_index}/values/{value_index}/source_id")
            try:
                value = _parse_protocol_value(
                    stored["value"],
                    stored["value_kind"],
                    f"/prior_state/open_epochs/{epoch_index}/values/{value_index}/value",
                )
            except _Reject as rejection:
                if rejection.code == "MALFORMED_VALUE_DELTA":
                    raise _Reject("MALFORMED_REACTIVE_STATE", rejection.path) from None
                raise
            if (
                stored["value_kind"] == "effect_proposal"
                and value["versions"]["dataflow"] != profile["dataflow_version"]
            ):
                raise _Reject(
                    "DATAFLOW_VERSION_MISMATCH",
                    f"/prior_state/open_epochs/{epoch_index}/values/{value_index}/value/versions/dataflow",
                )
            expected_value = _value_digest(stored["value_kind"], value)
            expected_delivery = _delivery_id(
                stored["source_id"],
                stored["logical_time"],
                profile["dataflow_version"],
                stored["value_kind"],
                expected_value,
            )
            if stored["value_digest"] != expected_value or stored["delivery_id"] != expected_delivery:
                raise _Reject("MALFORMED_REACTIVE_STATE", f"/prior_state/open_epochs/{epoch_index}/values/{value_index}")
            normalized_stored = {
                "kind": "RStoredValue",
                "delivery_id": expected_delivery,
                "source_id": stored["source_id"],
                "logical_time": stored["logical_time"],
                "value_kind": stored["value_kind"],
                "value_digest": expected_value,
                "value": value,
            }
            if stored != normalized_stored:
                raise _Reject(
                    "MALFORMED_REACTIVE_STATE",
                    f"/prior_state/open_epochs/{epoch_index}/values/{value_index}",
                )
            if expected_delivery in seen_deliveries:
                raise _Reject("MALFORMED_REACTIVE_STATE", "/prior_state/open_epochs")
            seen_deliveries.add(expected_delivery)
            values.append(normalized_stored)
        if values != _sorted_wires(values):
            raise _Reject("MALFORMED_REACTIVE_STATE", f"/prior_state/open_epochs/{epoch_index}/values")
        epochs.append({"kind": "ROpenEpoch", "logical_time": epoch["logical_time"], "values": values})
    if epochs != sorted(epochs, key=lambda item: (item["logical_time"], canonical_bytes(item))):
        raise _Reject("MALFORMED_REACTIVE_STATE", "/prior_state/open_epochs")
    if len({item["logical_time"] for item in epochs}) != len(epochs):
        raise _Reject("MALFORMED_REACTIVE_STATE", "/prior_state/open_epochs")
    ready = [
        _parse_published(item, profile, f"/prior_state/ready_batches/{index}")
        for index, item in enumerate(state["ready_batches"])
    ]
    if ready != sorted(ready, key=lambda item: (item["batch"]["logical_time"], canonical_bytes(item))):
        raise _Reject("MALFORMED_REACTIVE_STATE", "/prior_state/ready_batches")
    if len({item["batch"]["logical_time"] for item in ready}) != len(ready):
        raise _Reject("MALFORMED_REACTIVE_STATE", "/prior_state/ready_batches")
    if ready and (
        expected_global is None
        or any(item["batch"]["low_watermark"] > expected_global for item in ready)
    ):
        raise _Reject("MALFORMED_REACTIVE_STATE", "/prior_state/ready_batches")
    ready_value_count = sum(
        len(item["effect_proposals"]) + len(item["eligibility_verdicts"])
        for item in ready
    )
    if len(epochs) > profile["limits"]["max_open_epochs"] or len(seen_deliveries) + ready_value_count > profile["limits"]["max_active_values"] or len(ready) > profile["limits"]["max_ready_batches"]:
        raise _Reject("MALFORMED_REACTIVE_STATE", "/prior_state")
    if demand and ready:
        raise _Reject("MALFORMED_REACTIVE_STATE", "/prior_state/ready_batches")
    without = {key: thaw(value) for key, value in state.items() if key != "state_digest"}
    if not _valid_digest(state["state_digest"]) or state["state_digest"] != _state_digest(without):
        raise _Reject("MALFORMED_REACTIVE_STATE", "/prior_state/state_digest")
    return thaw(state)


def _parse_command_base(raw: Any, profile: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise _Reject("MALFORMED_COMMAND", "/command")
    if raw.get("schema_version") != COMMAND_SCHEMA_VERSION:
        raise _Reject("UNSUPPORTED_COMMAND_SCHEMA", "/command/schema_version")
    if raw.get("profile_digest") != profile["profile_digest"]:
        raise _Reject("PROFILE_MISMATCH", "/command/profile_digest")
    if raw.get("dataflow_version") != profile["dataflow_version"]:
        raise _Reject("DATAFLOW_VERSION_MISMATCH", "/command/dataflow_version")
    return raw


def _command_digest(
    command: Mapping[str, Any], delta_digests: Optional[Sequence[str]] = None
) -> str:
    preimage: Dict[str, Any] = {
        "kind": "M3CommandPreimage",
        "contract_version": CONTRACT_VERSION,
        "command_kind": command["kind"],
        "profile_digest": command["profile_digest"],
        "dataflow_version": command["dataflow_version"],
    }
    if command["kind"] == "RApplyDeltaBatch":
        preimage["ordered_value_delta_digests"] = list(delta_digests or ())
    elif command["kind"] == "RAdvanceFrontier":
        preimage["source_id"] = command["source_id"]
        preimage["low_watermark"] = command["low_watermark"]
    else:
        preimage["batches"] = command["batches"]
    return canonical_digest(preimage)


def _state_parts(state: Mapping[str, Any]) -> Tuple[Dict[str, Optional[int]], Dict[int, Dict[str, Dict[str, Any]]], List[Dict[str, Any]]]:
    frontiers = {item["source_id"]: item["low_watermark"] for item in state["source_frontiers"]}
    epochs = {
        epoch["logical_time"]: {item["delivery_id"]: thaw(item) for item in epoch["values"]}
        for epoch in state["open_epochs"]
    }
    ready = [thaw(item) for item in state["ready_batches"]]
    return frontiers, epochs, ready


def _wire_state(
    profile: Mapping[str, Any],
    frontiers: Mapping[str, Optional[int]],
    demand: int,
    epochs: Mapping[int, Mapping[str, Mapping[str, Any]]],
    ready: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    watermark_values = list(frontiers.values())
    global_watermark = None if any(item is None for item in watermark_values) else min(watermark_values)
    open_epochs = [
        {
            "kind": "ROpenEpoch",
            "logical_time": logical_time,
            "values": _sorted_wires(list(values.values())),
        }
        for logical_time, values in epochs.items()
        if values
    ]
    open_epochs.sort(key=lambda item: (item["logical_time"], canonical_bytes(item)))
    ready_sorted = [thaw(item) for item in ready]
    ready_sorted.sort(key=lambda item: (item["batch"]["logical_time"], canonical_bytes(item)))
    return _with_state_digest(
        {
            "kind": "RReactiveState",
            "schema_version": STATE_SCHEMA_VERSION,
            "contract_version": CONTRACT_VERSION,
            "profile_id": PROFILE_ID,
            "profile_digest": profile["profile_digest"],
            "dataflow_version": profile["dataflow_version"],
            "canonicalization_version": CANONICALIZATION_VERSION,
            "source_frontiers": _sorted_wires(
                [
                    {"kind": "RSourceFrontier", "source_id": source_id, "low_watermark": watermark}
                    for source_id, watermark in frontiers.items()
                ]
            ),
            "global_low_watermark": global_watermark,
            "outstanding_demand": demand,
            "open_epochs": open_epochs,
            "ready_batches": ready_sorted,
        }
    )


def _drain(
    ready: List[Dict[str, Any]], demand: int
) -> Tuple[List[Dict[str, Any]], int, List[Dict[str, Any]]]:
    ready.sort(key=lambda item: (item["batch"]["logical_time"], canonical_bytes(item)))
    count = min(len(ready), demand)
    published = [thaw(item) for item in ready[:count]]
    return [thaw(item) for item in ready[count:]], demand - count, published


def _backpressure(state: Mapping[str, Any], limits: Mapping[str, Any]) -> Dict[str, Any]:
    ready_value_count = sum(
        len(item["effect_proposals"]) + len(item["eligibility_verdicts"])
        for item in state["ready_batches"]
    )
    return {
        "kind": "RBackpressure",
        "open_epoch_count": len(state["open_epochs"]),
        "active_value_count": sum(len(item["values"]) for item in state["open_epochs"])
        + ready_value_count,
        "ready_batch_count": len(state["ready_batches"]),
        "outstanding_demand": state["outstanding_demand"],
        "limits": dict(limits),
    }


def _transition(
    profile: Mapping[str, Any],
    prior_digest: str,
    command_digest: str,
    next_state: Mapping[str, Any],
    published: Sequence[Mapping[str, Any]],
    stats: Mapping[str, int],
) -> Dict[str, Any]:
    without = {
        "kind": "RTransition",
        "schema_version": RESULT_SCHEMA_VERSION,
        "contract_version": CONTRACT_VERSION,
        "profile_digest": profile["profile_digest"],
        "prior_state_digest": prior_digest,
        "command_digest": command_digest,
        "next_state": thaw(next_state),
        "published_batches": sorted(
            (thaw(item) for item in published),
            key=lambda item: (item["batch"]["logical_time"], canonical_bytes(item)),
        ),
        "backpressure": _backpressure(next_state, profile["limits"]),
        "stats": dict(stats),
    }
    result = thaw(without)
    result["transition_digest"] = canonical_digest(
        {
            "kind": "M3TransitionPreimage",
            "contract_version": CONTRACT_VERSION,
            "transition_without_transition_digest": without,
        }
    )
    return thaw(result)


def _rejection(
    rejection: _Reject, profile_digest: Optional[str]
) -> Dict[str, Any]:
    allowed = {
        "expected",
        "actual",
        "source_id",
        "delivery_id",
        "value_kind",
        "limit",
        "observed",
        "reason",
    }
    context = {key: value for key, value in rejection.context.items() if key in allowed}
    try:
        context = thaw(context)
    except (CanonicalizationError, TypeError, ValueError):
        context = {"reason": "closed rejection context"}
    return {
        "kind": "RRejection",
        "schema_version": RESULT_SCHEMA_VERSION,
        "contract_version": CONTRACT_VERSION,
        "code": rejection.code,
        "path": rejection.path,
        "logical_time": rejection.logical_time,
        "profile_digest": profile_digest,
        "context": context,
    }


def step_r(prior_state: Any, profile: Any, command: Any) -> WireResult:
    """Apply one pure bounded reactive command to explicit JSON state."""

    trusted_profile_digest: Optional[str] = None
    try:
        # Canonical-domain rejection is deterministic and precedes semantic parsing.
        canonical_bytes(profile)
        canonical_bytes(prior_state)
        canonical_bytes(command)
        parsed_profile = _parse_profile(profile)
        trusted_profile_digest = parsed_profile["profile_digest"]
        state = _parse_state(prior_state, parsed_profile)
        parsed_command = _parse_command_base(command, parsed_profile)
        frontiers, epochs, ready = _state_parts(state)
        demand = state["outstanding_demand"]
        stats = {
            "accepted_delta_count": 0,
            "retracted_delta_count": 0,
            "stabilized_epoch_count": 0,
            "published_batch_count": 0,
        }
        delta_digests: Optional[List[str]] = None

        if parsed_command.get("kind") == "RApplyDeltaBatch":
            _exact(
                parsed_command,
                frozenset({"kind", "schema_version", "profile_digest", "dataflow_version", "deltas"}),
                "MALFORMED_COMMAND",
                "/command",
            )
            raw_deltas = parsed_command["deltas"]
            if not isinstance(raw_deltas, list) or not raw_deltas:
                raise _Reject("MALFORMED_COMMAND", "/command/deltas")
            if len(raw_deltas) > parsed_profile["limits"]["max_deltas_per_command"]:
                raise _Reject(
                    "INPUT_LIMIT_EXCEEDED",
                    "/command/deltas",
                    {
                        "limit": parsed_profile["limits"]["max_deltas_per_command"],
                        "observed": len(raw_deltas),
                    },
                )
            # Canonical-domain admission is order-independent. Semantic JSON Pointers
            # retain the caller's original array index; accepted members are sorted
            # only after parsing and identity validation.
            for raw_delta in sorted(raw_deltas, key=diagnostic_order_key):
                canonical_bytes(raw_delta)
            parsed = [
                _parse_delta(raw, parsed_profile, frontiers, f"/command/deltas/{index}")
                for index, raw in enumerate(raw_deltas)
            ]
            grouped: Dict[str, List[Dict[str, Any]]] = {}
            for item in parsed:
                grouped.setdefault(item["delivery_id"], []).append(item)
            normalized: List[Dict[str, Any]] = []
            for delivery_id in sorted(grouped, key=canonical_bytes):
                group = grouped[delivery_id]
                additions = [item for item in group if item["diff"] == 1]
                removals = [item for item in group if item["diff"] == -1]
                if (additions and removals) or len(removals) > 1:
                    raise _Reject(
                        "AMBIGUOUS_DELTA_BATCH",
                        "/command/deltas",
                        {"delivery_id": delivery_id},
                        group[0]["logical_time"],
                    )
                stable = {canonical_bytes(_stored(item)) for item in group}
                if len(stable) != 1:
                    raise _Reject(
                        "VALUE_IDENTITY_CONFLICT",
                        "/command/deltas",
                        {"delivery_id": delivery_id},
                        group[0]["logical_time"],
                    )
                normalized.append(group[0])
            delta_digests = _sorted_strings([canonical_digest(item) for item in normalized])

            existing = {
                delivery_id: stored
                for values in epochs.values()
                for delivery_id, stored in values.items()
            }
            for item in normalized:
                prior = existing.get(item["delivery_id"])
                expected = _stored(item)
                if item["diff"] == -1:
                    if prior is None:
                        raise _Reject(
                            "UNKNOWN_DELIVERY",
                            "/command/deltas",
                            {"delivery_id": item["delivery_id"]},
                            item["logical_time"],
                        )
                    if canonical_bytes(prior) != canonical_bytes(expected):
                        raise _Reject(
                            "VALUE_IDENTITY_CONFLICT",
                            "/command/deltas",
                            {"delivery_id": item["delivery_id"]},
                            item["logical_time"],
                        )
                elif prior is not None and canonical_bytes(prior) != canonical_bytes(expected):
                    raise _Reject(
                        "VALUE_IDENTITY_CONFLICT",
                        "/command/deltas",
                        {"delivery_id": item["delivery_id"]},
                        item["logical_time"],
                    )

            next_epochs = {
                logical_time: {key: thaw(value) for key, value in values.items()}
                for logical_time, values in epochs.items()
            }
            for item in normalized:
                values = next_epochs.setdefault(item["logical_time"], {})
                if item["diff"] == -1:
                    del values[item["delivery_id"]]
                    stats["retracted_delta_count"] += 1
                elif item["delivery_id"] not in values:
                    values[item["delivery_id"]] = _stored(item)
                    stats["accepted_delta_count"] += 1
            next_epochs = {key: value for key, value in next_epochs.items() if value}
            ready_value_count = sum(
                len(item["effect_proposals"]) + len(item["eligibility_verdicts"])
                for item in ready
            )
            active_count = sum(len(values) for values in next_epochs.values()) + ready_value_count
            if active_count > parsed_profile["limits"]["max_active_values"]:
                raise _Reject(
                    "QUEUE_CAPACITY_EXCEEDED",
                    "/command/deltas",
                    {"limit": parsed_profile["limits"]["max_active_values"], "observed": active_count},
                )
            if len(next_epochs) > parsed_profile["limits"]["max_open_epochs"]:
                raise _Reject(
                    "QUEUE_CAPACITY_EXCEEDED",
                    "/command/deltas",
                    {"limit": parsed_profile["limits"]["max_open_epochs"], "observed": len(next_epochs)},
                )
            epochs = next_epochs

        elif parsed_command.get("kind") == "RAdvanceFrontier":
            _exact(
                parsed_command,
                frozenset(
                    {"kind", "schema_version", "profile_digest", "dataflow_version", "source_id", "low_watermark"}
                ),
                "MALFORMED_COMMAND",
                "/command",
            )
            source_id = parsed_command["source_id"]
            if not _valid_id(source_id) or source_id not in frontiers:
                raise _Reject(
                    "UNKNOWN_FRONTIER_SOURCE",
                    "/command/source_id",
                    {"source_id": source_id} if _valid_id(source_id) else {},
                )
            watermark = parsed_command["low_watermark"]
            if not _valid_time(watermark):
                raise _Reject("MALFORMED_COMMAND", "/command/low_watermark")
            old = frontiers[source_id]
            if old is not None and watermark < old:
                raise _Reject(
                    "FRONTIER_REGRESSION",
                    "/command/low_watermark",
                    {"expected": old, "actual": watermark, "source_id": source_id},
                )
            next_frontiers = dict(frontiers)
            next_frontiers[source_id] = watermark
            values = list(next_frontiers.values())
            next_global = None if any(item is None for item in values) else min(values)
            closing = [] if next_global is None else sorted(
                (time for time in epochs if time < next_global), key=lambda item: item
            )
            created = [
                _build_published_batch(
                    parsed_profile,
                    {
                        "kind": "ROpenEpoch",
                        "logical_time": logical_time,
                        "values": _sorted_wires(list(epochs[logical_time].values())),
                    },
                    next_global,
                )
                for logical_time in closing
            ]
            candidate_ready = ready + created
            candidate_ready, candidate_demand, published = _drain(candidate_ready, demand)
            if len(candidate_ready) > parsed_profile["limits"]["max_ready_batches"]:
                raise _Reject(
                    "QUEUE_CAPACITY_EXCEEDED",
                    "/prior_state/ready_batches",
                    {
                        "limit": parsed_profile["limits"]["max_ready_batches"],
                        "observed": len(candidate_ready),
                    },
                )
            for logical_time in closing:
                del epochs[logical_time]
            frontiers = next_frontiers
            ready = candidate_ready
            demand = candidate_demand
            stats["stabilized_epoch_count"] = len(closing)
            stats["published_batch_count"] = len(published)

        elif parsed_command.get("kind") == "RGrantDemand":
            _exact(
                parsed_command,
                frozenset({"kind", "schema_version", "profile_digest", "dataflow_version", "batches"}),
                "MALFORMED_COMMAND",
                "/command",
            )
            batches = parsed_command["batches"]
            if not _valid_time(batches) or batches < 1:
                raise _Reject("MALFORMED_COMMAND", "/command/batches")
            if batches > parsed_profile["limits"]["max_demand_per_command"]:
                raise _Reject(
                    "DEMAND_LIMIT_EXCEEDED",
                    "/command/batches",
                    {"limit": parsed_profile["limits"]["max_demand_per_command"], "observed": batches},
                )
            granted = demand + batches
            if granted > parsed_profile["limits"]["max_outstanding_demand"]:
                raise _Reject(
                    "DEMAND_LIMIT_EXCEEDED",
                    "/command/batches",
                    {
                        "limit": parsed_profile["limits"]["max_outstanding_demand"],
                        "observed": granted,
                    },
                )
            ready, demand, published = _drain(ready, granted)
            stats["published_batch_count"] = len(published)
        else:
            raise _Reject("MALFORMED_COMMAND", "/command/kind")

        if parsed_command["kind"] != "RAdvanceFrontier" and parsed_command["kind"] != "RGrantDemand":
            published = []
        next_state = _wire_state(parsed_profile, frontiers, demand, epochs, ready)
        command_digest = _command_digest(parsed_command, delta_digests)
        return _transition(
            parsed_profile,
            state["state_digest"],
            command_digest,
            next_state,
            published,
            stats,
        )
    except _Reject as rejection:
        return _rejection(rejection, trusted_profile_digest)
    except CanonicalizationError:
        return _rejection(
            _Reject("CANONICALIZATION_VIOLATION", "", {"reason": "canonical JSON domain"}),
            trusted_profile_digest,
        )
    except Exception:
        return _rejection(
            _Reject("INVARIANT_VIOLATION", "", {"reason": "closed kernel failure"}),
            trusted_profile_digest,
        )
