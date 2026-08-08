"""M1 pure functional reference slice.

The module owns no durable state and performs no I/O.  Its only public state
transition accepts explicit JSON-compatible values and returns a fresh wire
object representing either a transition or a typed rejection.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple, Union

from .canonical import INT64_MAX, CanonicalizationError, canonical_bytes, canonical_digest


CONTRACT_VERSION = "flrh-f-kernel/1"
SNAPSHOT_SCHEMA_VERSION = "flrh-f-snapshot/1"
RESULT_SCHEMA_VERSION = "flrh-f-result/1"
PAYLOAD_EVENT_TYPE = "flrh.m1.observation-recorded/1"
SUPPORTED_WORKFLOW = "flrh-workflow/0.1"
SUPPORTED_STATE_SCHEMA = "flrh-f-state/1"
SUPPORTED_EVENT_SCHEMA = "flrh-f-event/1"
SUPPORTED_CANONICALIZATION = "flrh-cjson/1"

ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/-]*$")
DATETIME_PATTERN = re.compile(
    r"^([0-9]{4})-([0-9]{2})-([0-9]{2})T"
    r"([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.[0-9]+)?"
    r"(?:Z|[+-]([0-9]{2}):([0-9]{2}))$"
)
VERSION_KEYS = (
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
)
SNAPSHOT_KEYS = {
    "kind",
    "schema_version",
    "aggregate_id",
    "revision",
    "phase",
    "observation_count",
    "last_logical_time",
    "last_event_id",
    "last_observation_digest",
    "versions",
}
EVENT_KEYS = {
    "kind",
    "event_id",
    "payload",
    "occurred_at",
    "received_at",
    "logical_time",
    "correlation_id",
    "causation_id",
    "idempotency_key",
    "versions",
}
PAYLOAD_KEYS = {
    "event_type",
    "aggregate_id",
    "expected_revision",
    "observation",
    "mark_complete",
    "effect_request",
}
EFFECT_REQUEST_KEYS = {
    "effect_type",
    "action",
    "destination",
    "goal_id",
    "obligation_id",
    "declared_risk_hint",
    "preconditions",
}
RISK_HINTS = {"read_only", "reversible", "high_risk_external", "unknown"}


@dataclass(frozen=True)
class _Snapshot:
    aggregate_id: str
    revision: int
    phase: str
    observation_count: int
    last_logical_time: Optional[int]
    last_event_id: Optional[str]
    last_observation_digest: Optional[str]
    versions: Tuple[Tuple[str, str], ...]


@dataclass(frozen=True)
class _EffectRequest:
    effect_type: str
    action_digest: str
    destination_digest: str
    goal_id: str
    obligation_id: str
    declared_risk_hint: str
    preconditions: Tuple[str, ...]


@dataclass(frozen=True)
class _Event:
    event_id: str
    logical_time: int
    correlation_id: str
    aggregate_id: str
    expected_revision: int
    observation_digest: str
    mark_complete: bool
    effect_request: Optional[_EffectRequest]
    versions: Tuple[Tuple[str, str], ...]


@dataclass(frozen=True)
class _Decision:
    next_phase: str
    fact_deltas: Tuple[Dict[str, Any], ...]
    effect_proposals: Tuple[Dict[str, Any], ...]


WireResult = Dict[str, Any]


def _valid_id(value: Any) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= 128 and ID_PATTERN.fullmatch(value) is not None


def _valid_version(value: Any) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= 128 and VERSION_PATTERN.fullmatch(value) is not None


def _valid_datetime(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    match = DATETIME_PATTERN.fullmatch(value)
    if match is None:
        return False
    year, month, day, hour, minute, second = (int(part) for part in match.groups()[:6])
    if year == 0 or not 1 <= month <= 12 or hour > 23 or minute > 59 or second > 60:
        return False
    month_days = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    maximum_day = month_days[month - 1]
    if month == 2 and (year % 400 == 0 or (year % 4 == 0 and year % 100 != 0)):
        maximum_day = 29
    if not 1 <= day <= maximum_day:
        return False
    offset_hour, offset_minute = match.groups()[6:8]
    if offset_hour is not None and (int(offset_hour) > 23 or int(offset_minute) > 59):
        return False
    return True


def _digest_id(prefix: str, domain: str, value: Mapping[str, Any]) -> str:
    preimage = {
        "kind": "M1IdentityPreimage",
        "contract_version": CONTRACT_VERSION,
        "domain": domain,
        "value": dict(value),
    }
    raw = hashlib.sha256(canonical_bytes(preimage)).hexdigest()
    return f"{prefix}:{raw}"


def _value_digest(domain: str, value: Mapping[str, Any]) -> str:
    return canonical_digest(
        {
            "kind": "M1ValueDigestPreimage",
            "contract_version": CONTRACT_VERSION,
            "domain": domain,
            "value": dict(value),
        }
    )


def _safe_event_id(value: Any) -> Optional[str]:
    if isinstance(value, dict) and _valid_id(value.get("event_id")):
        return value["event_id"]
    return None


def _safe_revision(value: Any) -> Optional[int]:
    if isinstance(value, dict):
        revision = value.get("revision")
        if (
            isinstance(revision, int)
            and not isinstance(revision, bool)
            and 0 <= revision <= INT64_MAX
        ):
            return revision
    return None


def _reject(
    code: str,
    path: str,
    snapshot: Any,
    event: Any,
    context: Optional[Mapping[str, Union[str, int, bool, None]]] = None,
) -> WireResult:
    return {
        "kind": "FRejection",
        "schema_version": RESULT_SCHEMA_VERSION,
        "contract_version": CONTRACT_VERSION,
        "code": code,
        "path": path,
        "event_id": _safe_event_id(event),
        "snapshot_revision": _safe_revision(snapshot),
        "context": dict(context or {}),
    }


def _validate_versions(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == set(VERSION_KEYS)
        and all(_valid_version(value[key]) for key in VERSION_KEYS)
    )


def _parse_snapshot(value: Any, event: Any) -> Union[_Snapshot, WireResult]:
    try:
        canonical_bytes(value)
    except CanonicalizationError as error:
        return _reject(
            "CANONICALIZATION_VIOLATION",
            "/snapshot" + ("" if error.path == "/" else error.path),
            value,
            event,
            {"canonical_code": error.code},
        )
    if not isinstance(value, dict) or set(value) != SNAPSHOT_KEYS:
        return _reject("MALFORMED_SNAPSHOT", "/snapshot", value, event)
    if value.get("kind") != "FStateSnapshot":
        return _reject("MALFORMED_SNAPSHOT", "/snapshot/kind", value, event)
    if value.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        return _reject(
            "UNSUPPORTED_STATE_SCHEMA",
            "/snapshot/schema_version",
            value,
            event,
            {"expected": SNAPSHOT_SCHEMA_VERSION},
        )
    if not _valid_id(value.get("aggregate_id")):
        return _reject("MALFORMED_SNAPSHOT", "/snapshot/aggregate_id", value, event)
    revision = value.get("revision")
    count = value.get("observation_count")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        return _reject("MALFORMED_SNAPSHOT", "/snapshot/revision", value, event)
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        return _reject("MALFORMED_SNAPSHOT", "/snapshot/observation_count", value, event)
    if value.get("phase") not in {"open", "closed"}:
        return _reject("MALFORMED_SNAPSHOT", "/snapshot/phase", value, event)
    last_time = value.get("last_logical_time")
    if last_time is not None and (
        not isinstance(last_time, int) or isinstance(last_time, bool) or last_time < 0
    ):
        return _reject("MALFORMED_SNAPSHOT", "/snapshot/last_logical_time", value, event)
    if value.get("last_event_id") is not None and not _valid_id(value.get("last_event_id")):
        return _reject("MALFORMED_SNAPSHOT", "/snapshot/last_event_id", value, event)
    last_digest = value.get("last_observation_digest")
    if last_digest is not None and not (
        isinstance(last_digest, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", last_digest)
    ):
        return _reject("MALFORMED_SNAPSHOT", "/snapshot/last_observation_digest", value, event)
    if not _validate_versions(value.get("versions")):
        return _reject("MALFORMED_SNAPSHOT", "/snapshot/versions", value, event)
    return _Snapshot(
        aggregate_id=value["aggregate_id"],
        revision=revision,
        phase=value["phase"],
        observation_count=count,
        last_logical_time=last_time,
        last_event_id=value["last_event_id"],
        last_observation_digest=last_digest,
        versions=tuple((key, value["versions"][key]) for key in VERSION_KEYS),
    )


def _parse_effect_request(value: Any, snapshot: Any, event: Any) -> Union[Optional[_EffectRequest], WireResult]:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != EFFECT_REQUEST_KEYS:
        return _reject("MALFORMED_ACCEPTED_EVENT", "/accepted_event/payload/effect_request", snapshot, event)
    for field in ("effect_type", "goal_id", "obligation_id"):
        if not _valid_id(value.get(field)):
            return _reject(
                "MALFORMED_ACCEPTED_EVENT",
                f"/accepted_event/payload/effect_request/{field}",
                snapshot,
                event,
            )
    if not isinstance(value.get("action"), dict) or not value["action"]:
        return _reject("MALFORMED_ACCEPTED_EVENT", "/accepted_event/payload/effect_request/action", snapshot, event)
    if not isinstance(value.get("destination"), dict) or not value["destination"]:
        return _reject(
            "MALFORMED_ACCEPTED_EVENT",
            "/accepted_event/payload/effect_request/destination",
            snapshot,
            event,
        )
    if value.get("declared_risk_hint") not in RISK_HINTS:
        return _reject(
            "MALFORMED_ACCEPTED_EVENT",
            "/accepted_event/payload/effect_request/declared_risk_hint",
            snapshot,
            event,
        )
    preconditions = value.get("preconditions")
    if not isinstance(preconditions, list) or not all(_valid_id(item) for item in preconditions):
        return _reject(
            "MALFORMED_ACCEPTED_EVENT",
            "/accepted_event/payload/effect_request/preconditions",
            snapshot,
            event,
        )
    if len(preconditions) != len(set(preconditions)):
        return _reject(
            "INVARIANT_VIOLATION",
            "/accepted_event/payload/effect_request/preconditions",
            snapshot,
            event,
            {"invariant": "unique_preconditions"},
        )
    return _EffectRequest(
        effect_type=value["effect_type"],
        action_digest=_value_digest("effect-action", value["action"]),
        destination_digest=_value_digest("effect-destination", value["destination"]),
        goal_id=value["goal_id"],
        obligation_id=value["obligation_id"],
        declared_risk_hint=value["declared_risk_hint"],
        preconditions=tuple(sorted(preconditions, key=lambda item: canonical_bytes(item))),
    )


def _parse_event(value: Any, snapshot_value: Any) -> Union[_Event, WireResult]:
    try:
        canonical_bytes(value)
    except CanonicalizationError as error:
        return _reject(
            "CANONICALIZATION_VIOLATION",
            "/accepted_event" + ("" if error.path == "/" else error.path),
            snapshot_value,
            value,
            {"canonical_code": error.code},
        )
    if not isinstance(value, dict) or set(value) != EVENT_KEYS:
        return _reject("MALFORMED_ACCEPTED_EVENT", "/accepted_event", snapshot_value, value)
    if value.get("kind") != "AcceptedEvent":
        return _reject("MALFORMED_ACCEPTED_EVENT", "/accepted_event/kind", snapshot_value, value)
    for field in ("event_id", "correlation_id", "idempotency_key"):
        if not _valid_id(value.get(field)):
            return _reject("MALFORMED_ACCEPTED_EVENT", f"/accepted_event/{field}", snapshot_value, value)
    if value.get("causation_id") is not None and not _valid_id(value.get("causation_id")):
        return _reject("MALFORMED_ACCEPTED_EVENT", "/accepted_event/causation_id", snapshot_value, value)
    logical_time = value.get("logical_time")
    if not isinstance(logical_time, int) or isinstance(logical_time, bool) or logical_time < 0:
        return _reject("MALFORMED_ACCEPTED_EVENT", "/accepted_event/logical_time", snapshot_value, value)
    for field in ("occurred_at", "received_at"):
        if not _valid_datetime(value.get(field)):
            return _reject("MALFORMED_ACCEPTED_EVENT", f"/accepted_event/{field}", snapshot_value, value)
    if not _validate_versions(value.get("versions")):
        return _reject("MALFORMED_ACCEPTED_EVENT", "/accepted_event/versions", snapshot_value, value)
    payload = value.get("payload")
    if not isinstance(payload, dict) or set(payload) != PAYLOAD_KEYS:
        return _reject("MALFORMED_ACCEPTED_EVENT", "/accepted_event/payload", snapshot_value, value)
    if payload.get("event_type") != PAYLOAD_EVENT_TYPE:
        return _reject(
            "UNSUPPORTED_EVENT_PAYLOAD",
            "/accepted_event/payload/event_type",
            snapshot_value,
            value,
            {"expected": PAYLOAD_EVENT_TYPE},
        )
    if not _valid_id(payload.get("aggregate_id")):
        return _reject("MALFORMED_ACCEPTED_EVENT", "/accepted_event/payload/aggregate_id", snapshot_value, value)
    expected_revision = payload.get("expected_revision")
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0:
        return _reject(
            "MALFORMED_ACCEPTED_EVENT",
            "/accepted_event/payload/expected_revision",
            snapshot_value,
            value,
        )
    if not isinstance(payload.get("observation"), dict) or not payload["observation"]:
        return _reject("MALFORMED_ACCEPTED_EVENT", "/accepted_event/payload/observation", snapshot_value, value)
    if not isinstance(payload.get("mark_complete"), bool):
        return _reject("MALFORMED_ACCEPTED_EVENT", "/accepted_event/payload/mark_complete", snapshot_value, value)
    effect_request = _parse_effect_request(payload.get("effect_request"), snapshot_value, value)
    if isinstance(effect_request, dict):
        return effect_request
    return _Event(
        event_id=value["event_id"],
        logical_time=logical_time,
        correlation_id=value["correlation_id"],
        aggregate_id=payload["aggregate_id"],
        expected_revision=expected_revision,
        observation_digest=_value_digest("observation", payload["observation"]),
        mark_complete=payload["mark_complete"],
        effect_request=effect_request,
        versions=tuple((key, value["versions"][key]) for key in VERSION_KEYS),
    )


def _versions_dict(versions: Sequence[Tuple[str, str]]) -> Dict[str, str]:
    return {key: value for key, value in versions}


def _check_compatibility(snapshot: _Snapshot, event: _Event, raw_snapshot: Any, raw_event: Any) -> Optional[WireResult]:
    snapshot_versions = _versions_dict(snapshot.versions)
    event_versions = _versions_dict(event.versions)
    if snapshot_versions["workflow"] != SUPPORTED_WORKFLOW or event_versions["workflow"] != SUPPORTED_WORKFLOW:
        return _reject(
            "WORKFLOW_VERSION_MISMATCH",
            "/versions/workflow",
            raw_snapshot,
            raw_event,
            {"expected": SUPPORTED_WORKFLOW},
        )
    if snapshot_versions["state_schema"] != SUPPORTED_STATE_SCHEMA:
        return _reject(
            "UNSUPPORTED_STATE_SCHEMA",
            "/snapshot/versions/state_schema",
            raw_snapshot,
            raw_event,
            {"expected": SUPPORTED_STATE_SCHEMA},
        )
    if event_versions["event_schema"] != SUPPORTED_EVENT_SCHEMA:
        return _reject(
            "UNSUPPORTED_EVENT_SCHEMA",
            "/accepted_event/versions/event_schema",
            raw_snapshot,
            raw_event,
            {"expected": SUPPORTED_EVENT_SCHEMA},
        )
    if (
        snapshot_versions["canonicalization"] != SUPPORTED_CANONICALIZATION
        or event_versions["canonicalization"] != SUPPORTED_CANONICALIZATION
    ):
        return _reject(
            "UNSUPPORTED_CANONICALIZATION",
            "/versions/canonicalization",
            raw_snapshot,
            raw_event,
            {"expected": SUPPORTED_CANONICALIZATION},
        )
    if snapshot.versions != event.versions:
        return _reject("VERSION_ENVELOPE_MISMATCH", "/versions", raw_snapshot, raw_event)
    if snapshot.aggregate_id != event.aggregate_id:
        return _reject("SNAPSHOT_EVENT_MISMATCH", "/accepted_event/payload/aggregate_id", raw_snapshot, raw_event)
    if snapshot.revision != event.expected_revision:
        return _reject(
            "STALE_REVISION",
            "/accepted_event/payload/expected_revision",
            raw_snapshot,
            raw_event,
            {"expected": snapshot.revision},
        )
    if snapshot.last_logical_time is not None and event.logical_time < snapshot.last_logical_time:
        return _reject(
            "LOGICAL_TIME_REGRESSION",
            "/accepted_event/logical_time",
            raw_snapshot,
            raw_event,
            {"minimum": snapshot.last_logical_time},
        )
    if snapshot.phase == "closed":
        return _reject("DOMAIN_REJECTED", "/snapshot/phase", raw_snapshot, raw_event, {"phase": "closed"})
    if snapshot.revision == INT64_MAX:
        return _reject(
            "INVARIANT_VIOLATION",
            "/snapshot/revision",
            raw_snapshot,
            raw_event,
            {"invariant": "revision_increment_within_int64"},
        )
    if snapshot.observation_count == INT64_MAX:
        return _reject(
            "INVARIANT_VIOLATION",
            "/snapshot/observation_count",
            raw_snapshot,
            raw_event,
            {"invariant": "observation_count_increment_within_int64"},
        )
    return None


def _decide(snapshot: _Snapshot, event: _Event) -> _Decision:
    versions = _versions_dict(event.versions)
    fact_identity = {
        "kind": "FactDelta",
        "tuple": {
            "predicate": "observation_recorded",
            "subject": snapshot.aggregate_id,
            "object_digest": event.observation_digest,
        },
        "logical_time": event.logical_time,
        "diff": 1,
        "causation_id": event.event_id,
        "provenance_delta": {
            "source_event_id": event.event_id,
            "observation_digest": event.observation_digest,
        },
        "rule_set_version": versions["rule_set"],
        "dataflow_version": versions["dataflow"],
    }
    fact_delta = dict(fact_identity)
    fact_delta["derivation_id"] = _digest_id(
        "derivation",
        "observation-fact-value",
        fact_identity,
    )
    proposals = []
    if event.effect_request is not None:
        request = event.effect_request
        proposal_value = {
            "kind": "EffectProposal",
            "effect_type": request.effect_type,
            "action_digest": request.action_digest,
            "cause_id": event.event_id,
            "correlation_id": event.correlation_id,
            "destination_digest": request.destination_digest,
            "goal_id": request.goal_id,
            "obligation_id": request.obligation_id,
            "declared_risk_hint": request.declared_risk_hint,
            "preconditions": list(request.preconditions),
            "versions": versions,
        }
        proposal_id = _digest_id("proposal", "effect-proposal-value", proposal_value)
        proposal_dedup_key = _digest_id("proposal-dedup", "proposal-dedup-value", proposal_value)
        proposals.append(
            {
                **proposal_value,
                "proposal_id": proposal_id,
                "proposal_dedup_key": proposal_dedup_key,
            }
        )
    return _Decision(
        next_phase="closed" if event.mark_complete else snapshot.phase,
        fact_deltas=(fact_delta,),
        effect_proposals=tuple(proposals),
    )


def _evolve(snapshot: _Snapshot, event: _Event, decision: _Decision) -> Dict[str, Any]:
    return {
        "kind": "FStateSnapshot",
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "aggregate_id": snapshot.aggregate_id,
        "revision": snapshot.revision + 1,
        "phase": decision.next_phase,
        "observation_count": snapshot.observation_count + 1,
        "last_logical_time": event.logical_time,
        "last_event_id": event.event_id,
        "last_observation_digest": event.observation_digest,
        "versions": _versions_dict(snapshot.versions),
    }


def _transition_digest(
    event_id: str,
    prior_snapshot_digest: str,
    next_snapshot: Mapping[str, Any],
    fact_deltas: Sequence[Mapping[str, Any]],
    effect_proposals: Sequence[Mapping[str, Any]],
) -> str:
    projection = {
        "kind": "FTransitionDigestProjection",
        "contract_version": CONTRACT_VERSION,
        "event_id": event_id,
        "prior_snapshot_digest": prior_snapshot_digest,
        "next_snapshot_digest": canonical_digest(next_snapshot),
        "ordered_fact_delta_digests": [canonical_digest(item) for item in fact_deltas],
        "ordered_effect_proposal_digests": [canonical_digest(item) for item in effect_proposals],
    }
    return canonical_digest(projection)


def step_f(snapshot: Any, accepted_event: Any) -> WireResult:
    """Evaluate one pure F transition from explicit inputs.

    ``step_f`` never mutates the supplied objects.  It returns no callable,
    resource handle, ``EffectIntent``, authority, approval, or dispatch result.
    """

    parsed_snapshot = _parse_snapshot(snapshot, accepted_event)
    if isinstance(parsed_snapshot, dict):
        return parsed_snapshot
    parsed_event = _parse_event(accepted_event, snapshot)
    if isinstance(parsed_event, dict):
        return parsed_event
    incompatibility = _check_compatibility(parsed_snapshot, parsed_event, snapshot, accepted_event)
    if incompatibility is not None:
        return incompatibility
    decision = _decide(parsed_snapshot, parsed_event)
    next_snapshot = _evolve(parsed_snapshot, parsed_event, decision)
    fact_deltas = sorted(decision.fact_deltas, key=canonical_bytes)
    effect_proposals = sorted(decision.effect_proposals, key=canonical_bytes)
    prior_digest = canonical_digest(snapshot)
    return {
        "kind": "FTransition",
        "schema_version": RESULT_SCHEMA_VERSION,
        "contract_version": CONTRACT_VERSION,
        "event_id": parsed_event.event_id,
        "prior_snapshot_digest": prior_digest,
        "next_snapshot": next_snapshot,
        "fact_deltas": fact_deltas,
        "effect_proposals": effect_proposals,
        "transition_digest": _transition_digest(
            parsed_event.event_id,
            prior_digest,
            next_snapshot,
            fact_deltas,
            effect_proposals,
        ),
    }
