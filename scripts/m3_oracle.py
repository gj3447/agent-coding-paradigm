#!/usr/bin/env python3
"""Independent full-history oracle for the bounded M3 scalar-frontier profile.

This module deliberately imports no production ``flrh_reactive`` code and no
project canonicalization helper.  It recomputes state from the explicit prior
wire value using a small, direct model intended only for the frozen corpus.
"""

from __future__ import annotations

import copy
import hashlib
import json
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any


INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1
CONTRACT_VERSION = "flrh-r-kernel/1"
PROFILE_ID = "flrh-r-scalar-frontier/1"


class OracleReject(Exception):
    def __init__(
        self,
        code: str,
        path: str,
        *,
        logical_time: int | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.path = path
        self.logical_time = logical_time
        self.context = dict(context or {})


def _validate_json(value: Any) -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        if not INT64_MIN <= value <= INT64_MAX:
            raise ValueError("integer outside signed 64-bit")
        return
    if isinstance(value, float):
        raise ValueError("floating-point values are outside flrh-cjson/1")
    if isinstance(value, str):
        if unicodedata.normalize("NFC", value) != value:
            raise ValueError("non-NFC string")
        value.encode("utf-8")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json(item)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("non-string object key")
            _validate_json(key)
            _validate_json(item)
        return
    raise ValueError("non-JSON value")


def _normalize_sets(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize_sets(item) for item in value]
    if not isinstance(value, Mapping):
        return value
    result = {key: _normalize_sets(item) for key, item in value.items()}
    kind = result.get("kind")
    set_fields = {
        "EffectProposal": ("preconditions",),
        "EligibilityVerdict": ("support_derivation_ids",),
        "StableProposalBatch": ("proposal_ids", "eligibility_verdict_ids"),
    }.get(kind, ())
    for field in set_fields:
        if field in result:
            items = result[field]
            encoded = [canonical_bytes(item) for item in items]
            if len(encoded) != len(set(encoded)):
                raise ValueError(f"duplicate set member: {kind}.{field}")
            result[field] = [item for _, item in sorted(zip(encoded, items), key=lambda pair: pair[0])]
    return result


def canonical_bytes(value: Any) -> bytes:
    """Small independent implementation of the frozen JSON profile."""

    _validate_json(value)
    normalized = _normalize_sets(copy.deepcopy(value))
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def profile_digest(profile: Mapping[str, Any]) -> str:
    return digest(
        {
            "kind": "M3ProfilePreimage",
            "contract_version": CONTRACT_VERSION,
            "profile_id": profile["profile_id"],
            "dataflow_version": profile["dataflow_version"],
            "canonicalization_version": profile["canonicalization_version"],
            "ordered_source_ids": sorted(profile["source_ids"], key=canonical_bytes),
            "late_event_policy": profile["late_event_policy"],
            "overflow_policy": profile["overflow_policy"],
            "limits": profile["limits"],
        }
    )


def value_digest(value_kind: str, value: Mapping[str, Any]) -> str:
    return digest(
        {
            "kind": "M3ValuePreimage",
            "contract_version": CONTRACT_VERSION,
            "value_kind": value_kind,
            "value": value,
        }
    )


def delivery_id(
    source_id: str,
    logical_time: int,
    dataflow_version: str,
    value_kind: str,
    bound_value_digest: str,
) -> str:
    bound = digest(
        {
            "kind": "M3DeliveryPreimage",
            "contract_version": CONTRACT_VERSION,
            "source_id": source_id,
            "logical_time": logical_time,
            "dataflow_version": dataflow_version,
            "value_kind": value_kind,
            "value_digest": bound_value_digest,
        }
    )
    return "delivery:" + bound.split(":", 1)[1]


def delta_digest(delta: Mapping[str, Any]) -> str:
    """Digest one exact delta for normalized ApplyDeltaBatch command identity."""

    return digest(delta)


def command_digest(command: Mapping[str, Any]) -> str:
    preimage: dict[str, Any] = {
        "kind": "M3CommandPreimage",
        "contract_version": CONTRACT_VERSION,
        "command_kind": command["kind"],
        "profile_digest": command["profile_digest"],
        "dataflow_version": command["dataflow_version"],
    }
    if command["kind"] == "RApplyDeltaBatch":
        unique = {delta_digest(item) for item in command["deltas"]}
        preimage["ordered_value_delta_digests"] = sorted(unique, key=canonical_bytes)
    elif command["kind"] == "RAdvanceFrontier":
        preimage["source_id"] = command["source_id"]
        preimage["low_watermark"] = command["low_watermark"]
    elif command["kind"] == "RGrantDemand":
        preimage["batches"] = command["batches"]
    return digest(preimage)


def _state_with_digest(state: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(state))
    result.pop("state_digest", None)
    result["state_digest"] = digest(
        {
            "kind": "M3StatePreimage",
            "contract_version": CONTRACT_VERSION,
            "state_without_state_digest": result,
        }
    )
    return result


def initial_state(profile: Mapping[str, Any]) -> dict[str, Any]:
    state = {
        "kind": "RReactiveState",
        "schema_version": "flrh-r-state/1",
        "contract_version": CONTRACT_VERSION,
        "profile_id": PROFILE_ID,
        "profile_digest": profile["profile_digest"],
        "dataflow_version": profile["dataflow_version"],
        "canonicalization_version": "flrh-cjson/1",
        "source_frontiers": sorted([
            {"kind": "RSourceFrontier", "source_id": item, "low_watermark": None}
            for item in sorted(profile["source_ids"], key=canonical_bytes)
        ], key=canonical_bytes),
        "global_low_watermark": None,
        "outstanding_demand": 0,
        "open_epochs": [],
        "ready_batches": [],
    }
    return _state_with_digest(state)


def _stored(delta: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "kind": "RStoredValue",
        "delivery_id": delta["delivery_id"],
        "source_id": delta["source_id"],
        "logical_time": delta["logical_time"],
        "value_kind": delta["value_kind"],
        "value_digest": delta["value_digest"],
        "value": json.loads(canonical_bytes(delta["value"]).decode("utf-8")),
    }


def _open_stored(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for epoch in state["open_epochs"]:
        values.extend(copy.deepcopy(epoch["values"]))
    return values


def _ready_value_count(state: Mapping[str, Any]) -> int:
    return sum(
        len(item["effect_proposals"]) + len(item["eligibility_verdicts"])
        for item in state["ready_batches"]
    )


def _published(epoch: Mapping[str, Any], state: Mapping[str, Any]) -> dict[str, Any]:
    proposals = sorted(
        [item["value"] for item in epoch["values"] if item["value_kind"] == "effect_proposal"],
        key=canonical_bytes,
    )
    verdicts = sorted(
        [item["value"] for item in epoch["values"] if item["value_kind"] == "eligibility_verdict"],
        key=canonical_bytes,
    )
    proposal_ids = sorted([item["proposal_id"] for item in proposals], key=canonical_bytes)
    verdict_ids = sorted([item["verdict_id"] for item in verdicts], key=canonical_bytes)
    preimage = {
        "kind": "M3StableBatchPreimage",
        "contract_version": CONTRACT_VERSION,
        "profile_digest": state["profile_digest"],
        "logical_time": epoch["logical_time"],
        "low_watermark": state["global_low_watermark"],
        "ordered_proposal_ids": proposal_ids,
        "ordered_eligibility_verdict_ids": verdict_ids,
        "dataflow_version": state["dataflow_version"],
    }
    stable_digest = digest(preimage)
    suffix = stable_digest.split(":", 1)[1]
    batch = {
        "kind": "StableProposalBatch",
        "batch_id": "batch:" + suffix,
        "logical_time": epoch["logical_time"],
        "low_watermark": state["global_low_watermark"],
        "proposal_ids": proposal_ids,
        "eligibility_verdict_ids": verdict_ids,
        "batch_digest": stable_digest,
        "cause_id": "reaction:" + suffix,
        "dataflow_version": state["dataflow_version"],
    }
    result = {
        "kind": "RPublishedBatch",
        "batch": batch,
        "effect_proposals": proposals,
        "eligibility_verdicts": verdicts,
    }
    result["published_batch_digest"] = digest(
        {
            "kind": "M3PublishedBatchPreimage",
            "contract_version": CONTRACT_VERSION,
            "batch": batch,
            "ordered_effect_proposals": proposals,
            "ordered_eligibility_verdicts": verdicts,
        }
    )
    return result


def _backpressure(state: Mapping[str, Any], profile: Mapping[str, Any]) -> dict[str, Any]:
    active = sum(len(item["values"]) for item in state["open_epochs"])
    active += sum(
        len(item["effect_proposals"]) + len(item["eligibility_verdicts"])
        for item in state["ready_batches"]
    )
    return {
        "kind": "RBackpressure",
        "open_epoch_count": len(state["open_epochs"]),
        "active_value_count": active,
        "ready_batch_count": len(state["ready_batches"]),
        "outstanding_demand": state["outstanding_demand"],
        "limits": copy.deepcopy(profile["limits"]),
    }


def _reject(
    error: OracleReject, profile: Mapping[str, Any] | None
) -> dict[str, Any]:
    return {
        "kind": "RRejection",
        "schema_version": "flrh-r-result/1",
        "contract_version": CONTRACT_VERSION,
        "code": error.code,
        "path": error.path,
        "logical_time": error.logical_time,
        "profile_digest": profile.get("profile_digest") if profile else None,
        "context": copy.deepcopy(error.context),
    }


def _drain(state: dict[str, Any]) -> list[dict[str, Any]]:
    state["ready_batches"].sort(
        key=lambda item: (item["batch"]["logical_time"], canonical_bytes(item["batch"]))
    )
    count = min(state["outstanding_demand"], len(state["ready_batches"]))
    published = copy.deepcopy(state["ready_batches"][:count])
    state["ready_batches"] = state["ready_batches"][count:]
    state["outstanding_demand"] -= count
    return published


def step_expected(
    prior_state: Mapping[str, Any] | None,
    profile: Mapping[str, Any],
    command: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate one valid frozen-profile command by direct full-state scans."""

    try:
        if profile.get("profile_digest") != profile_digest(profile):
            raise OracleReject("MALFORMED_DATAFLOW_PROFILE", "/profile/profile_digest")
        state = initial_state(profile) if prior_state is None else copy.deepcopy(dict(prior_state))
        if command.get("profile_digest") != profile["profile_digest"]:
            raise OracleReject("PROFILE_MISMATCH", "/command/profile_digest")
        if command.get("dataflow_version") != profile["dataflow_version"]:
            raise OracleReject("DATAFLOW_VERSION_MISMATCH", "/command/dataflow_version")

        stats = {
            "accepted_delta_count": 0,
            "retracted_delta_count": 0,
            "stabilized_epoch_count": 0,
            "published_batch_count": 0,
        }
        kind = command["kind"]
        if kind == "RApplyDeltaBatch":
            deltas = copy.deepcopy(command["deltas"])
            limit = profile["limits"]["max_deltas_per_command"]
            if len(deltas) > limit:
                raise OracleReject(
                    "INPUT_LIMIT_EXCEEDED",
                    "/command/deltas",
                    context={"limit": limit, "observed": len(deltas)},
                )
            source_watermarks = {
                item["source_id"]: item["low_watermark"] for item in state["source_frontiers"]
            }
            for index, delta in enumerate(deltas):
                source_watermark = source_watermarks.get(delta.get("source_id"))
                if source_watermark is not None and delta["logical_time"] < source_watermark:
                    raise OracleReject(
                        "LATE_DELTA",
                        f"/command/deltas/{index}/logical_time",
                        logical_time=delta["logical_time"],
                        context={"source_id": delta["source_id"]},
                    )
            groups: dict[str, list[dict[str, Any]]] = {}
            for delta in deltas:
                groups.setdefault(delta["delivery_id"], []).append(delta)
            active = {item["delivery_id"]: item for item in _open_stored(state)}
            for delivery_key in sorted(groups, key=canonical_bytes):
                group = groups[delivery_key]
                plus = [item for item in group if item["diff"] == 1]
                minus = [item for item in group if item["diff"] == -1]
                stable = {canonical_bytes({key: value for key, value in item.items() if key != "diff"}) for item in group}
                if (plus and minus) or len(minus) > 1:
                    raise OracleReject(
                        "AMBIGUOUS_DELTA_BATCH",
                        "/command/deltas",
                        context={"delivery_id": delivery_key},
                    )
                if len(stable) > 1:
                    raise OracleReject(
                        "VALUE_IDENTITY_CONFLICT",
                        "/command/deltas",
                        context={"delivery_id": delivery_key},
                    )
                item = group[0]
                if item["dataflow_version"] != profile["dataflow_version"]:
                    raise OracleReject(
                        "DATAFLOW_VERSION_MISMATCH",
                        "/command/deltas",
                        logical_time=item["logical_time"],
                        context={"expected": profile["dataflow_version"], "actual": item["dataflow_version"]},
                    )
                if item["source_id"] not in profile["source_ids"]:
                    raise OracleReject(
                        "UNKNOWN_FRONTIER_SOURCE",
                        "/command/deltas",
                        logical_time=item["logical_time"],
                        context={"source_id": item["source_id"], "delivery_id": delivery_key},
                    )
                if item["value_digest"] != value_digest(item["value_kind"], item["value"]):
                    raise OracleReject(
                        "VALUE_IDENTITY_CONFLICT",
                        "/command/deltas",
                        logical_time=item["logical_time"],
                        context={"delivery_id": delivery_key},
                    )
                expected_delivery_id = delivery_id(
                    item["source_id"],
                    item["logical_time"],
                    item["dataflow_version"],
                    item["value_kind"],
                    item["value_digest"],
                )
                if delivery_key != expected_delivery_id:
                    raise OracleReject(
                        "VALUE_IDENTITY_CONFLICT",
                        "/command/deltas",
                        logical_time=item["logical_time"],
                        context={"delivery_id": delivery_key, "expected": expected_delivery_id},
                    )
                if (
                    item["value_kind"] == "effect_proposal"
                    and item["value"]["versions"]["dataflow"] != profile["dataflow_version"]
                ):
                    raise OracleReject(
                        "DATAFLOW_VERSION_MISMATCH",
                        "/command/deltas",
                        logical_time=item["logical_time"],
                        context={
                            "expected": profile["dataflow_version"],
                            "actual": item["value"]["versions"]["dataflow"],
                        },
                    )
                existing = active.get(delivery_key)
                if minus:
                    if existing is None:
                        raise OracleReject(
                            "UNKNOWN_DELIVERY",
                            "/command/deltas",
                            logical_time=item["logical_time"],
                            context={"delivery_id": delivery_key},
                        )
                    active.pop(delivery_key)
                    stats["retracted_delta_count"] += 1
                elif existing is None:
                    active[delivery_key] = _stored(item)
                    stats["accepted_delta_count"] += 1
                elif canonical_bytes(existing) != canonical_bytes(_stored(item)):
                    raise OracleReject(
                        "VALUE_IDENTITY_CONFLICT",
                        "/command/deltas",
                        logical_time=item["logical_time"],
                        context={"delivery_id": delivery_key},
                    )
            total_active = len(active) + _ready_value_count(state)
            if total_active > profile["limits"]["max_active_values"]:
                limit = profile["limits"]["max_active_values"]
                raise OracleReject(
                    "QUEUE_CAPACITY_EXCEEDED",
                    "/command/deltas",
                    context={"limit": limit, "observed": total_active},
                )
            # Apply only to open epochs; ready values cannot be targeted by an
            # on-time command after strict frontier stabilization.
            open_values = list(active.values())
            by_epoch: dict[int, list[dict[str, Any]]] = {}
            for item in open_values:
                by_epoch.setdefault(item["logical_time"], []).append(item)
            if len(by_epoch) > profile["limits"]["max_open_epochs"]:
                limit = profile["limits"]["max_open_epochs"]
                raise OracleReject(
                    "QUEUE_CAPACITY_EXCEEDED",
                    "/command/deltas",
                    context={"limit": limit, "observed": len(by_epoch)},
                )
            state["open_epochs"] = [
                {
                    "kind": "ROpenEpoch",
                    "logical_time": epoch,
                    "values": sorted(values, key=canonical_bytes),
                }
                for epoch, values in sorted(by_epoch.items())
            ]
        elif kind == "RAdvanceFrontier":
            source = command["source_id"]
            frontiers = {item["source_id"]: item["low_watermark"] for item in state["source_frontiers"]}
            if source not in frontiers:
                raise OracleReject(
                    "UNKNOWN_FRONTIER_SOURCE",
                    "/command/source_id",
                    context={"source_id": source},
                )
            prior = frontiers[source]
            if prior is not None and command["low_watermark"] < prior:
                raise OracleReject(
                    "FRONTIER_REGRESSION",
                    "/command/low_watermark",
                    context={"source_id": source, "expected": prior, "actual": command["low_watermark"]},
                )
            frontiers[source] = command["low_watermark"]
            state["source_frontiers"] = sorted([
                {"kind": "RSourceFrontier", "source_id": item, "low_watermark": frontiers[item]}
                for item in sorted(frontiers, key=canonical_bytes)
            ], key=canonical_bytes)
            state["global_low_watermark"] = (
                min(frontiers.values()) if all(item is not None for item in frontiers.values()) else None
            )
            if state["global_low_watermark"] is not None:
                stable = [item for item in state["open_epochs"] if item["logical_time"] < state["global_low_watermark"]]
                still_open = [item for item in state["open_epochs"] if item["logical_time"] >= state["global_low_watermark"]]
                ready = copy.deepcopy(state["ready_batches"])
                for epoch in stable:
                    proposals = [
                        item for item in epoch["values"] if item["value_kind"] == "effect_proposal"
                    ]
                    verdicts = [
                        item for item in epoch["values"] if item["value_kind"] == "eligibility_verdict"
                    ]
                    proposal_counts: dict[str, int] = {}
                    verdict_counts: dict[str, int] = {}
                    verdict_id_counts: dict[str, int] = {}
                    for item in proposals:
                        proposal_id = item["value"]["proposal_id"]
                        proposal_counts[proposal_id] = proposal_counts.get(proposal_id, 0) + 1
                    for item in verdicts:
                        proposal_id = item["value"]["proposal_id"]
                        verdict_counts[proposal_id] = verdict_counts.get(proposal_id, 0) + 1
                        verdict_id = item["value"]["verdict_id"]
                        verdict_id_counts[verdict_id] = verdict_id_counts.get(verdict_id, 0) + 1
                    if (
                        set(proposal_counts) != set(verdict_counts)
                        or any(count != 1 for count in proposal_counts.values())
                        or any(count != 1 for count in verdict_counts.values())
                        or any(count != 1 for count in verdict_id_counts.values())
                    ):
                        raise OracleReject(
                            "UNRESOLVED_DEPENDENCY",
                            "/prior_state/open_epochs",
                            logical_time=epoch["logical_time"],
                            context={"reason": "proposal_verdict_bijection"},
                        )
                    proposal_by_id = {
                        item["value"]["proposal_id"]: item["value"] for item in proposals
                    }
                    for item in verdicts:
                        verdict = item["value"]
                        proposal = proposal_by_id[verdict["proposal_id"]]
                        if verdict["rule_set_version"] != proposal["versions"]["rule_set"]:
                            raise OracleReject(
                                "RULE_SET_VERSION_MISMATCH",
                                "/prior_state/open_epochs",
                                logical_time=epoch["logical_time"],
                                context={
                                    "expected": proposal["versions"]["rule_set"],
                                    "actual": verdict["rule_set_version"],
                                    "delivery_id": item["delivery_id"],
                                },
                            )
                    ready.append(_published(epoch, state))
                state["open_epochs"] = still_open
                state["ready_batches"] = ready
                stats["stabilized_epoch_count"] = len(stable)
        elif kind == "RGrantDemand":
            batches = command["batches"]
            command_limit = profile["limits"]["max_demand_per_command"]
            if batches > command_limit:
                raise OracleReject(
                    "DEMAND_LIMIT_EXCEEDED",
                    "/command/batches",
                    context={"limit": command_limit, "observed": batches},
                )
            next_demand = state["outstanding_demand"] + batches
            total_limit = profile["limits"]["max_outstanding_demand"]
            if next_demand > total_limit:
                raise OracleReject(
                    "DEMAND_LIMIT_EXCEEDED",
                    "/command/batches",
                    context={"limit": total_limit, "observed": next_demand},
                )
            state["outstanding_demand"] = next_demand
        else:
            raise OracleReject("MALFORMED_COMMAND", "/command/kind")

        published = _drain(state)
        if len(state["ready_batches"]) > profile["limits"]["max_ready_batches"]:
            limit = profile["limits"]["max_ready_batches"]
            raise OracleReject(
                "QUEUE_CAPACITY_EXCEEDED",
                "/prior_state/ready_batches",
                context={"limit": limit, "observed": len(state["ready_batches"])},
            )
        stats["published_batch_count"] = len(published)
        next_state = _state_with_digest(state)
        without_digest = {
            "kind": "RTransition",
            "schema_version": "flrh-r-result/1",
            "contract_version": CONTRACT_VERSION,
            "profile_digest": profile["profile_digest"],
            "prior_state_digest": (prior_state or initial_state(profile))["state_digest"],
            "command_digest": command_digest(command),
            "next_state": next_state,
            "published_batches": published,
            "backpressure": _backpressure(next_state, profile),
            "stats": stats,
        }
        result = copy.deepcopy(without_digest)
        result["transition_digest"] = digest(
            {
                "kind": "M3TransitionPreimage",
                "contract_version": CONTRACT_VERSION,
                "transition_without_transition_digest": without_digest,
            }
        )
        return result
    except OracleReject as error:
        return _reject(error, profile)


def run_sequence(
    prior_state: Mapping[str, Any] | None,
    profile: Mapping[str, Any],
    commands: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    state = copy.deepcopy(prior_state)
    for command in commands:
        result = step_expected(state, profile, command)
        results.append(result)
        if result["kind"] == "RRejection":
            break
        state = result["next_state"]
    return results


__all__ = [
    "canonical_bytes",
    "command_digest",
    "delivery_id",
    "delta_digest",
    "digest",
    "initial_state",
    "profile_digest",
    "run_sequence",
    "step_expected",
    "value_digest",
]
