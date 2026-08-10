/**
 * M1 pure functional kernel, ported from src/flrh_kernel/kernel.py.
 *
 * stepF owns no durable state and performs no I/O. It accepts explicit JSON
 * values (JsonValue model: bigint integers, Map objects) and returns a fresh
 * wire object — an FTransition or a typed FRejection. Validation order, JSON
 * Pointer paths, and digest preimages must match the Python reference exactly;
 * byte identity is enforced by the conformance suite.
 */

import {
  CanonicalizationError,
  INT64_MAX,
  canonicalBytes,
  canonicalDigest,
  compareBytes,
} from "../contracts/canonical";
import { type JsonObject, type JsonValue, jsonObject } from "../contracts/json-value";

export const CONTRACT_VERSION = "flrh-f-kernel/1";
export const SNAPSHOT_SCHEMA_VERSION = "flrh-f-snapshot/1";
export const RESULT_SCHEMA_VERSION = "flrh-f-result/1";
export const PAYLOAD_EVENT_TYPE = "flrh.m1.observation-recorded/1";
export const SUPPORTED_WORKFLOW = "flrh-workflow/0.1";
export const SUPPORTED_STATE_SCHEMA = "flrh-f-state/1";
export const SUPPORTED_EVENT_SCHEMA = "flrh-f-event/1";
export const SUPPORTED_CANONICALIZATION = "flrh-cjson/1";

const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:/-]*$/;
const VERSION_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:+/-]*$/;
const DATETIME_PATTERN =
  /^([0-9]{4})-([0-9]{2})-([0-9]{2})[Tt]([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.[0-9]+)?(?:[Zz]|[+-]([0-9]{2}):([0-9]{2}))$/;
const DIGEST_PATTERN = /^sha256:[0-9a-f]{64}$/;

const VERSION_KEYS = [
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
] as const;

const SNAPSHOT_KEYS = new Set([
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
]);
const EVENT_KEYS = new Set([
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
]);
const PAYLOAD_KEYS = new Set([
  "event_type",
  "aggregate_id",
  "expected_revision",
  "observation",
  "mark_complete",
  "effect_request",
]);
const EFFECT_REQUEST_KEYS = new Set([
  "effect_type",
  "action",
  "destination",
  "goal_id",
  "obligation_id",
  "declared_risk_hint",
  "preconditions",
]);
const RISK_HINTS = new Set(["read_only", "reversible", "high_risk_external", "unknown"]);

export type WireResult = JsonObject;

type VersionEntries = ReadonlyArray<readonly [string, string]>;

interface ParsedSnapshot {
  readonly aggregateId: string;
  readonly revision: bigint;
  readonly phase: string;
  readonly observationCount: bigint;
  readonly lastLogicalTime: bigint | null;
  readonly lastEventId: string | null;
  readonly lastObservationDigest: string | null;
  readonly versions: VersionEntries;
}

interface ParsedEffectRequest {
  readonly effectType: string;
  readonly actionDigest: string;
  readonly destinationDigest: string;
  readonly goalId: string;
  readonly obligationId: string;
  readonly declaredRiskHint: string;
  readonly preconditions: readonly string[];
}

interface ParsedEvent {
  readonly eventId: string;
  readonly logicalTime: bigint;
  readonly correlationId: string;
  readonly aggregateId: string;
  readonly expectedRevision: bigint;
  readonly observationDigest: string;
  readonly markComplete: boolean;
  readonly effectRequest: ParsedEffectRequest | null;
  readonly versions: VersionEntries;
}

interface Decision {
  readonly nextPhase: string;
  readonly factDeltas: readonly JsonObject[];
  readonly effectProposals: readonly JsonObject[];
}

type ContextValue = string | bigint | boolean | null;

const validId = (value: JsonValue | undefined): value is string =>
  typeof value === "string" && value.length >= 1 && value.length <= 128 && ID_PATTERN.test(value);

const validVersion = (value: JsonValue | undefined): value is string =>
  typeof value === "string" &&
  value.length >= 1 &&
  value.length <= 128 &&
  VERSION_PATTERN.test(value);

const validDatetime = (value: JsonValue | undefined): boolean => {
  if (typeof value !== "string") {
    return false;
  }
  const match = DATETIME_PATTERN.exec(value);
  if (match === null) {
    return false;
  }
  const [year, month, day, hour, minute, second] = match
    .slice(1, 7)
    .map((part) => Number.parseInt(part as string, 10)) as [
    number, number, number, number, number, number,
  ];
  if (year === 0 || month < 1 || month > 12 || hour > 23 || minute > 59 || second > 60) {
    return false;
  }
  const monthDays = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  let maximumDay = monthDays[month - 1] as number;
  if (month === 2 && (year % 400 === 0 || (year % 4 === 0 && year % 100 !== 0))) {
    maximumDay = 29;
  }
  if (day < 1 || day > maximumDay) {
    return false;
  }
  const offsetHour = match[7];
  const offsetMinute = match[8];
  if (
    offsetHour !== undefined &&
    (Number.parseInt(offsetHour, 10) > 23 || Number.parseInt(offsetMinute as string, 10) > 59)
  ) {
    return false;
  }
  return true;
};

const digestId = (prefix: string, domain: string, value: JsonObject): string => {
  const preimage = jsonObject([
    ["kind", "M1IdentityPreimage"],
    ["contract_version", CONTRACT_VERSION],
    ["domain", domain],
    ["value", new Map(value)],
  ]);
  const digest = canonicalDigest(preimage);
  return `${prefix}:${digest.slice("sha256:".length)}`;
};

const valueDigest = (domain: string, value: JsonObject): string =>
  canonicalDigest(
    jsonObject([
      ["kind", "M1ValueDigestPreimage"],
      ["contract_version", CONTRACT_VERSION],
      ["domain", domain],
      ["value", new Map(value)],
    ]),
  );

const safeEventId = (value: JsonValue): string | null => {
  if (value instanceof Map && validId(value.get("event_id"))) {
    return value.get("event_id") as string;
  }
  return null;
};

const safeRevision = (value: JsonValue): bigint | null => {
  if (value instanceof Map) {
    const revision = value.get("revision");
    if (typeof revision === "bigint" && revision >= 0n && revision <= INT64_MAX) {
      return revision;
    }
  }
  return null;
};

const reject = (
  code: string,
  path: string,
  snapshot: JsonValue,
  event: JsonValue,
  context?: ReadonlyArray<readonly [string, ContextValue]>,
): WireResult =>
  jsonObject([
    ["kind", "FRejection"],
    ["schema_version", RESULT_SCHEMA_VERSION],
    ["contract_version", CONTRACT_VERSION],
    ["code", code],
    ["path", path],
    ["event_id", safeEventId(event)],
    ["snapshot_revision", safeRevision(snapshot)],
    ["context", new Map(context ?? [])],
  ]);

const isRejection = (value: unknown): value is WireResult => value instanceof Map;

const keySetEquals = (value: JsonObject, keys: ReadonlySet<string>): boolean => {
  if (value.size !== keys.size) {
    return false;
  }
  for (const key of value.keys()) {
    if (!keys.has(key)) {
      return false;
    }
  }
  return true;
};

const validateVersions = (value: JsonValue | undefined): value is JsonObject => {
  if (!(value instanceof Map) || value.size !== VERSION_KEYS.length) {
    return false;
  }
  for (const key of VERSION_KEYS) {
    if (!value.has(key) || !validVersion(value.get(key))) {
      return false;
    }
  }
  return true;
};

const versionEntries = (value: JsonObject): VersionEntries =>
  VERSION_KEYS.map((key) => [key, value.get(key) as string] as const);

const versionsEqual = (a: VersionEntries, b: VersionEntries): boolean =>
  a.every(([key, value], index) => (b[index] as readonly [string, string])[0] === key
    && (b[index] as readonly [string, string])[1] === value);

const canonicalViolation = (value: JsonValue): CanonicalizationError | null => {
  try {
    canonicalBytes(value);
    return null;
  } catch (error) {
    if (error instanceof CanonicalizationError) {
      return error;
    }
    // Resource exhaustion (e.g. stack overflow on absurd nesting) must not be
    // laundered into a typed rejection the Python oracle can never produce.
    // eslint-disable-next-line no-restricted-syntax -- crash-propagation parity with the oracle, not a domain verdict
    throw error;
  }
};

const parseSnapshot = (value: JsonValue, event: JsonValue): ParsedSnapshot | WireResult => {
  const violation = canonicalViolation(value);
  if (violation !== null) {
    return reject(
      "CANONICALIZATION_VIOLATION",
      `/snapshot${violation.path === "/" ? "" : violation.path}`,
      value,
      event,
      [["canonical_code", violation.code]],
    );
  }
  if (!(value instanceof Map) || !keySetEquals(value, SNAPSHOT_KEYS)) {
    return reject("MALFORMED_SNAPSHOT", "/snapshot", value, event);
  }
  if (value.get("kind") !== "FStateSnapshot") {
    return reject("MALFORMED_SNAPSHOT", "/snapshot/kind", value, event);
  }
  if (value.get("schema_version") !== SNAPSHOT_SCHEMA_VERSION) {
    return reject("UNSUPPORTED_STATE_SCHEMA", "/snapshot/schema_version", value, event, [
      ["expected", SNAPSHOT_SCHEMA_VERSION],
    ]);
  }
  if (!validId(value.get("aggregate_id"))) {
    return reject("MALFORMED_SNAPSHOT", "/snapshot/aggregate_id", value, event);
  }
  const revision = value.get("revision");
  const count = value.get("observation_count");
  if (typeof revision !== "bigint" || revision < 0n) {
    return reject("MALFORMED_SNAPSHOT", "/snapshot/revision", value, event);
  }
  if (typeof count !== "bigint" || count < 0n) {
    return reject("MALFORMED_SNAPSHOT", "/snapshot/observation_count", value, event);
  }
  const phase = value.get("phase");
  if (phase !== "open" && phase !== "closed") {
    return reject("MALFORMED_SNAPSHOT", "/snapshot/phase", value, event);
  }
  const lastTime = value.get("last_logical_time") ?? null;
  if (lastTime !== null && (typeof lastTime !== "bigint" || lastTime < 0n)) {
    return reject("MALFORMED_SNAPSHOT", "/snapshot/last_logical_time", value, event);
  }
  const lastEventId = value.get("last_event_id") ?? null;
  if (lastEventId !== null && !validId(lastEventId)) {
    return reject("MALFORMED_SNAPSHOT", "/snapshot/last_event_id", value, event);
  }
  const lastDigest = value.get("last_observation_digest") ?? null;
  if (lastDigest !== null && !(typeof lastDigest === "string" && DIGEST_PATTERN.test(lastDigest))) {
    return reject("MALFORMED_SNAPSHOT", "/snapshot/last_observation_digest", value, event);
  }
  const versions = value.get("versions");
  if (!validateVersions(versions)) {
    return reject("MALFORMED_SNAPSHOT", "/snapshot/versions", value, event);
  }
  return {
    aggregateId: value.get("aggregate_id") as string,
    revision,
    phase,
    observationCount: count,
    lastLogicalTime: lastTime,
    lastEventId: lastEventId as string | null,
    lastObservationDigest: lastDigest,
    versions: versionEntries(versions),
  };
};

const parseEffectRequest = (
  value: JsonValue | undefined,
  snapshot: JsonValue,
  event: JsonValue,
): ParsedEffectRequest | null | WireResult => {
  if (value === null || value === undefined) {
    return null;
  }
  if (!(value instanceof Map) || !keySetEquals(value, EFFECT_REQUEST_KEYS)) {
    return reject(
      "MALFORMED_ACCEPTED_EVENT",
      "/accepted_event/payload/effect_request",
      snapshot,
      event,
    );
  }
  for (const field of ["effect_type", "goal_id", "obligation_id"]) {
    if (!validId(value.get(field))) {
      return reject(
        "MALFORMED_ACCEPTED_EVENT",
        `/accepted_event/payload/effect_request/${field}`,
        snapshot,
        event,
      );
    }
  }
  const action = value.get("action");
  if (!(action instanceof Map) || action.size === 0) {
    return reject(
      "MALFORMED_ACCEPTED_EVENT",
      "/accepted_event/payload/effect_request/action",
      snapshot,
      event,
    );
  }
  const destination = value.get("destination");
  if (!(destination instanceof Map) || destination.size === 0) {
    return reject(
      "MALFORMED_ACCEPTED_EVENT",
      "/accepted_event/payload/effect_request/destination",
      snapshot,
      event,
    );
  }
  const riskHint = value.get("declared_risk_hint");
  if (typeof riskHint !== "string" || !RISK_HINTS.has(riskHint)) {
    return reject(
      "MALFORMED_ACCEPTED_EVENT",
      "/accepted_event/payload/effect_request/declared_risk_hint",
      snapshot,
      event,
    );
  }
  const preconditions = value.get("preconditions");
  if (!Array.isArray(preconditions) || !preconditions.every((item) => validId(item))) {
    return reject(
      "MALFORMED_ACCEPTED_EVENT",
      "/accepted_event/payload/effect_request/preconditions",
      snapshot,
      event,
    );
  }
  const ids = preconditions as string[];
  if (new Set(ids).size !== ids.length) {
    return reject(
      "INVARIANT_VIOLATION",
      "/accepted_event/payload/effect_request/preconditions",
      snapshot,
      event,
      [["invariant", "unique_preconditions"]],
    );
  }
  const sortedPreconditions = ids
    .map((item) => ({ item, bytes: canonicalBytes(item) }))
    .sort((left, right) => compareBytes(left.bytes, right.bytes))
    .map((pair) => pair.item);
  return {
    effectType: value.get("effect_type") as string,
    actionDigest: valueDigest("effect-action", action),
    destinationDigest: valueDigest("effect-destination", destination),
    goalId: value.get("goal_id") as string,
    obligationId: value.get("obligation_id") as string,
    declaredRiskHint: riskHint,
    preconditions: sortedPreconditions,
  };
};

const parseEvent = (value: JsonValue, snapshotValue: JsonValue): ParsedEvent | WireResult => {
  const violation = canonicalViolation(value);
  if (violation !== null) {
    return reject(
      "CANONICALIZATION_VIOLATION",
      `/accepted_event${violation.path === "/" ? "" : violation.path}`,
      snapshotValue,
      value,
      [["canonical_code", violation.code]],
    );
  }
  if (!(value instanceof Map) || !keySetEquals(value, EVENT_KEYS)) {
    return reject("MALFORMED_ACCEPTED_EVENT", "/accepted_event", snapshotValue, value);
  }
  if (value.get("kind") !== "AcceptedEvent") {
    return reject("MALFORMED_ACCEPTED_EVENT", "/accepted_event/kind", snapshotValue, value);
  }
  for (const field of ["event_id", "correlation_id", "idempotency_key"]) {
    if (!validId(value.get(field))) {
      return reject("MALFORMED_ACCEPTED_EVENT", `/accepted_event/${field}`, snapshotValue, value);
    }
  }
  const causationId = value.get("causation_id") ?? null;
  if (causationId !== null && !validId(causationId)) {
    return reject("MALFORMED_ACCEPTED_EVENT", "/accepted_event/causation_id", snapshotValue, value);
  }
  const logicalTime = value.get("logical_time");
  if (typeof logicalTime !== "bigint" || logicalTime < 0n) {
    return reject("MALFORMED_ACCEPTED_EVENT", "/accepted_event/logical_time", snapshotValue, value);
  }
  for (const field of ["occurred_at", "received_at"]) {
    if (!validDatetime(value.get(field))) {
      return reject("MALFORMED_ACCEPTED_EVENT", `/accepted_event/${field}`, snapshotValue, value);
    }
  }
  const versions = value.get("versions");
  if (!validateVersions(versions)) {
    return reject("MALFORMED_ACCEPTED_EVENT", "/accepted_event/versions", snapshotValue, value);
  }
  const payload = value.get("payload");
  if (!(payload instanceof Map) || !keySetEquals(payload, PAYLOAD_KEYS)) {
    return reject("MALFORMED_ACCEPTED_EVENT", "/accepted_event/payload", snapshotValue, value);
  }
  if (payload.get("event_type") !== PAYLOAD_EVENT_TYPE) {
    return reject(
      "UNSUPPORTED_EVENT_PAYLOAD",
      "/accepted_event/payload/event_type",
      snapshotValue,
      value,
      [["expected", PAYLOAD_EVENT_TYPE]],
    );
  }
  if (!validId(payload.get("aggregate_id"))) {
    return reject(
      "MALFORMED_ACCEPTED_EVENT",
      "/accepted_event/payload/aggregate_id",
      snapshotValue,
      value,
    );
  }
  const expectedRevision = payload.get("expected_revision");
  if (typeof expectedRevision !== "bigint" || expectedRevision < 0n) {
    return reject(
      "MALFORMED_ACCEPTED_EVENT",
      "/accepted_event/payload/expected_revision",
      snapshotValue,
      value,
    );
  }
  const observation = payload.get("observation");
  if (!(observation instanceof Map) || observation.size === 0) {
    return reject(
      "MALFORMED_ACCEPTED_EVENT",
      "/accepted_event/payload/observation",
      snapshotValue,
      value,
    );
  }
  const markComplete = payload.get("mark_complete");
  if (typeof markComplete !== "boolean") {
    return reject(
      "MALFORMED_ACCEPTED_EVENT",
      "/accepted_event/payload/mark_complete",
      snapshotValue,
      value,
    );
  }
  const effectRequest = parseEffectRequest(payload.get("effect_request"), snapshotValue, value);
  if (effectRequest !== null && isRejection(effectRequest)) {
    return effectRequest;
  }
  return {
    eventId: value.get("event_id") as string,
    logicalTime,
    correlationId: value.get("correlation_id") as string,
    aggregateId: payload.get("aggregate_id") as string,
    expectedRevision,
    observationDigest: valueDigest("observation", observation),
    markComplete,
    effectRequest,
    versions: versionEntries(versions),
  };
};

const versionsMap = (versions: VersionEntries): JsonObject =>
  new Map(versions.map(([key, value]) => [key, value] as const));

const checkCompatibility = (
  snapshot: ParsedSnapshot,
  event: ParsedEvent,
  rawSnapshot: JsonValue,
  rawEvent: JsonValue,
): WireResult | null => {
  const snapshotVersions = new Map(snapshot.versions);
  const eventVersions = new Map(event.versions);
  if (
    snapshotVersions.get("workflow") !== SUPPORTED_WORKFLOW ||
    eventVersions.get("workflow") !== SUPPORTED_WORKFLOW
  ) {
    return reject("WORKFLOW_VERSION_MISMATCH", "/versions/workflow", rawSnapshot, rawEvent, [
      ["expected", SUPPORTED_WORKFLOW],
    ]);
  }
  if (snapshotVersions.get("state_schema") !== SUPPORTED_STATE_SCHEMA) {
    return reject(
      "UNSUPPORTED_STATE_SCHEMA",
      "/snapshot/versions/state_schema",
      rawSnapshot,
      rawEvent,
      [["expected", SUPPORTED_STATE_SCHEMA]],
    );
  }
  if (eventVersions.get("event_schema") !== SUPPORTED_EVENT_SCHEMA) {
    return reject(
      "UNSUPPORTED_EVENT_SCHEMA",
      "/accepted_event/versions/event_schema",
      rawSnapshot,
      rawEvent,
      [["expected", SUPPORTED_EVENT_SCHEMA]],
    );
  }
  if (
    snapshotVersions.get("canonicalization") !== SUPPORTED_CANONICALIZATION ||
    eventVersions.get("canonicalization") !== SUPPORTED_CANONICALIZATION
  ) {
    return reject(
      "UNSUPPORTED_CANONICALIZATION",
      "/versions/canonicalization",
      rawSnapshot,
      rawEvent,
      [["expected", SUPPORTED_CANONICALIZATION]],
    );
  }
  if (!versionsEqual(snapshot.versions, event.versions)) {
    return reject("VERSION_ENVELOPE_MISMATCH", "/versions", rawSnapshot, rawEvent);
  }
  if (snapshot.aggregateId !== event.aggregateId) {
    return reject(
      "SNAPSHOT_EVENT_MISMATCH",
      "/accepted_event/payload/aggregate_id",
      rawSnapshot,
      rawEvent,
    );
  }
  if (snapshot.revision !== event.expectedRevision) {
    return reject(
      "STALE_REVISION",
      "/accepted_event/payload/expected_revision",
      rawSnapshot,
      rawEvent,
      [["expected", snapshot.revision]],
    );
  }
  if (snapshot.lastLogicalTime !== null && event.logicalTime < snapshot.lastLogicalTime) {
    return reject("LOGICAL_TIME_REGRESSION", "/accepted_event/logical_time", rawSnapshot, rawEvent, [
      ["minimum", snapshot.lastLogicalTime],
    ]);
  }
  if (snapshot.phase === "closed") {
    return reject("DOMAIN_REJECTED", "/snapshot/phase", rawSnapshot, rawEvent, [
      ["phase", "closed"],
    ]);
  }
  if (snapshot.revision === INT64_MAX) {
    return reject("INVARIANT_VIOLATION", "/snapshot/revision", rawSnapshot, rawEvent, [
      ["invariant", "revision_increment_within_int64"],
    ]);
  }
  if (snapshot.observationCount === INT64_MAX) {
    return reject("INVARIANT_VIOLATION", "/snapshot/observation_count", rawSnapshot, rawEvent, [
      ["invariant", "observation_count_increment_within_int64"],
    ]);
  }
  return null;
};

const decide = (snapshot: ParsedSnapshot, event: ParsedEvent): Decision => {
  const versions = versionsMap(event.versions);
  const factIdentityEntries: ReadonlyArray<readonly [string, JsonValue]> = [
    ["kind", "FactDelta"],
    [
      "tuple",
      jsonObject([
        ["predicate", "observation_recorded"],
        ["subject", snapshot.aggregateId],
        ["object_digest", event.observationDigest],
      ]),
    ],
    ["logical_time", event.logicalTime],
    ["diff", 1n],
    ["causation_id", event.eventId],
    [
      "provenance_delta",
      jsonObject([
        ["source_event_id", event.eventId],
        ["observation_digest", event.observationDigest],
      ]),
    ],
    ["rule_set_version", versions.get("rule_set") as string],
    ["dataflow_version", versions.get("dataflow") as string],
  ];
  const factIdentity = jsonObject(factIdentityEntries);
  const factDelta = jsonObject(factIdentityEntries);
  factDelta.set(
    "derivation_id",
    digestId("derivation", "observation-fact-value", factIdentity),
  );
  const proposals: JsonObject[] = [];
  if (event.effectRequest !== null) {
    const request = event.effectRequest;
    const proposalValue = jsonObject([
      ["kind", "EffectProposal"],
      ["effect_type", request.effectType],
      ["action_digest", request.actionDigest],
      ["cause_id", event.eventId],
      ["correlation_id", event.correlationId],
      ["destination_digest", request.destinationDigest],
      ["goal_id", request.goalId],
      ["obligation_id", request.obligationId],
      ["declared_risk_hint", request.declaredRiskHint],
      ["preconditions", [...request.preconditions]],
      ["versions", versions],
    ]);
    const proposalId = digestId("proposal", "effect-proposal-value", proposalValue);
    const proposalDedupKey = digestId("proposal-dedup", "proposal-dedup-value", proposalValue);
    const proposal = new Map(proposalValue);
    proposal.set("proposal_id", proposalId);
    proposal.set("proposal_dedup_key", proposalDedupKey);
    proposals.push(proposal);
  }
  return {
    nextPhase: event.markComplete ? "closed" : snapshot.phase,
    factDeltas: [factDelta],
    effectProposals: proposals,
  };
};

const evolve = (snapshot: ParsedSnapshot, event: ParsedEvent, decision: Decision): JsonObject =>
  jsonObject([
    ["kind", "FStateSnapshot"],
    ["schema_version", SNAPSHOT_SCHEMA_VERSION],
    ["aggregate_id", snapshot.aggregateId],
    ["revision", snapshot.revision + 1n],
    ["phase", decision.nextPhase],
    ["observation_count", snapshot.observationCount + 1n],
    ["last_logical_time", event.logicalTime],
    ["last_event_id", event.eventId],
    ["last_observation_digest", event.observationDigest],
    ["versions", versionsMap(snapshot.versions)],
  ]);

const transitionDigest = (
  eventId: string,
  priorSnapshotDigest: string,
  nextSnapshot: JsonObject,
  factDeltas: readonly JsonObject[],
  effectProposals: readonly JsonObject[],
): string =>
  canonicalDigest(
    jsonObject([
      ["kind", "FTransitionDigestProjection"],
      ["contract_version", CONTRACT_VERSION],
      ["event_id", eventId],
      ["prior_snapshot_digest", priorSnapshotDigest],
      ["next_snapshot_digest", canonicalDigest(nextSnapshot)],
      ["ordered_fact_delta_digests", factDeltas.map((item) => canonicalDigest(item))],
      ["ordered_effect_proposal_digests", effectProposals.map((item) => canonicalDigest(item))],
    ]),
  );

const sortByCanonicalBytes = (items: readonly JsonObject[]): JsonObject[] =>
  items
    .map((item) => ({ item, bytes: canonicalBytes(item) }))
    .sort((left, right) => compareBytes(left.bytes, right.bytes))
    .map((pair) => pair.item);

/** Evaluate one pure F transition from explicit inputs.
 *
 * stepF never mutates the supplied values. It returns no callable, resource
 * handle, EffectIntent, authority, approval, or dispatch result.
 */
export const stepF = (snapshot: JsonValue, acceptedEvent: JsonValue): WireResult => {
  const parsedSnapshot = parseSnapshot(snapshot, acceptedEvent);
  if (isRejection(parsedSnapshot)) {
    return parsedSnapshot;
  }
  const parsedEvent = parseEvent(acceptedEvent, snapshot);
  if (isRejection(parsedEvent)) {
    return parsedEvent;
  }
  const incompatibility = checkCompatibility(parsedSnapshot, parsedEvent, snapshot, acceptedEvent);
  if (incompatibility !== null) {
    return incompatibility;
  }
  const decision = decide(parsedSnapshot, parsedEvent);
  const nextSnapshot = evolve(parsedSnapshot, parsedEvent, decision);
  const factDeltas = sortByCanonicalBytes(decision.factDeltas);
  const effectProposals = sortByCanonicalBytes(decision.effectProposals);
  const priorDigest = canonicalDigest(snapshot);
  return jsonObject([
    ["kind", "FTransition"],
    ["schema_version", RESULT_SCHEMA_VERSION],
    ["contract_version", CONTRACT_VERSION],
    ["event_id", parsedEvent.eventId],
    ["prior_snapshot_digest", priorDigest],
    ["next_snapshot", nextSnapshot],
    ["fact_deltas", factDeltas],
    ["effect_proposals", effectProposals],
    [
      "transition_digest",
      transitionDigest(parsedEvent.eventId, priorDigest, nextSnapshot, factDeltas, effectProposals),
    ],
  ]);
};
