import { Data, Effect, Schema } from "effect";

import authoritativeProfileJson from "../../../spec/run-fsm.v1.json" with {
  type: "json",
};

export type JsonValue =
  | null | boolean | number | string
  | ReadonlyArray<JsonValue>
  | { readonly [key: string]: JsonValue };

const Id = Schema.String.pipe(
  Schema.pattern(/^[A-Za-z0-9][A-Za-z0-9._:/-]*$/u),
);
const AuthorityId = Schema.String.pipe(
  Schema.pattern(/^[a-z][a-z0-9_.]*$/u),
);
const EventType = Schema.String.pipe(Schema.pattern(/^[A-Z][A-Z0-9_]*$/u));
const CommandName = Schema.Literal(
  "PersistControlTransition",
  "PersistPendingInterrupt",
  "AuditInvalidTransition",
);
const JsonValueSchema: Schema.Schema<JsonValue> = Schema.Union(
  Schema.Null,
  Schema.Boolean,
  Schema.JsonNumber,
  Schema.String,
  Schema.Array(Schema.suspend(() => JsonValueSchema)),
  Schema.Record({ key: Schema.String, value: Schema.suspend(() => JsonValueSchema) }),
);
const Authority = Schema.Struct({ actor_role: AuthorityId, capability: AuthorityId });
const Transition = Schema.Struct({
  id: Id,
  from: Id,
  event: EventType,
  to: Id,
  guard: Schema.optional(Id),
  effects: Schema.Array(CommandName),
  evidence_required: Schema.Array(Id),
});
const Machine = Schema.Struct({
  id: Schema.Literal("control"),
  initial: Id,
  states: Schema.Array(Schema.Struct({ id: Id, kind: Schema.Literal("atomic", "final") })),
  invalid_event_policy: Schema.Struct({
    effect: Schema.Literal("AuditInvalidTransition"),
  }),
  transitions: Schema.Array(Transition),
});

/** Structural decoder for the repository-owned profile, not a second FSM contract. */
export const RunFsmProfileSchema = Schema.Struct({
  schema_version: Schema.Literal("flrh-run-fsm/v1"),
  authority: Schema.Literal("sole-authoritative-outer-control-fsm"),
  context_schema: Schema.Struct({
    required: Schema.Array(Id),
    properties: Schema.Record({
      key: Id,
      value: Schema.Struct({ type: Schema.Literal("boolean") }),
    }),
  }),
  guards: Schema.Record({
    key: Id,
    value: Schema.Struct({
      reads: Schema.Array(Id),
      operator: Schema.optional(Schema.Literal("all_true")),
    }),
  }),
  event_authority: Schema.Record({ key: EventType, value: Schema.Array(Authority) }),
  machines: Schema.Tuple(Machine),
  global_interrupts: Schema.Array(Schema.Struct({
    event: EventType,
    to: Id,
    deferred_in_states: Schema.Array(Id),
    deferred_effect: Schema.Literal("PersistPendingInterrupt"),
  })),
});
export const ControlEventSchema = Schema.Struct({
  type: EventType,
  actor_role: AuthorityId,
  capability: AuthorityId,
  event_id: Id,
  payload: Schema.Record({ key: Schema.String, value: JsonValueSchema }),
});
const ControlContextSchema = Schema.Record({ key: Id, value: Schema.Boolean });
const BoundaryEnvelope = Schema.Struct({
  state: Schema.Unknown,
  event: Schema.Unknown,
  context: Schema.Unknown,
});

export type RunFsmProfile = Schema.Schema.Type<typeof RunFsmProfileSchema>;
export type ControlEvent = Schema.Schema.Type<typeof ControlEventSchema>;
export type ControlContext = Schema.Schema.Type<typeof ControlContextSchema>;
export type ControlState = string;
export type ControlEventType = string;
export type DecodedControlStep = Readonly<{
  state: ControlState;
  event: ControlEvent;
  context: ControlContext;
}>;

export class ControlBoundaryError extends Data.TaggedError("ControlBoundaryError")<{
  readonly boundary: "envelope" | "state" | "event" | "context";
  readonly reason: string;
}> {}

export const authoritativeControlProfile = Schema.decodeUnknownSync(
  RunFsmProfileSchema,
)(authoritativeProfileJson);
const machine = authoritativeControlProfile.machines[0];
const states = new Set(machine.states.map((state) => state.id));
const events = new Set(Object.keys(authoritativeControlProfile.event_authority));
const contextKeys = Object.keys(authoritativeControlProfile.context_schema.properties).sort();
const exact = { errors: "all", onExcessProperty: "error" } as const;
const boundaryError =
  (boundary: ControlBoundaryError["boundary"]) => (error: unknown) =>
    new ControlBoundaryError({ boundary, reason: String(error) });

/** Decodes unknown step input; the repository profile is decoded once above. */
export const decodeControlStep = (
  input: unknown,
): Effect.Effect<DecodedControlStep, ControlBoundaryError> =>
  Effect.gen(function* () {
    const envelope = yield* Schema.decodeUnknown(BoundaryEnvelope, exact)(input).pipe(
      Effect.mapError(boundaryError("envelope")),
    );
    const state = yield* Schema.decodeUnknown(Schema.String)(envelope.state).pipe(
      Effect.filterOrFail(
        (value) => states.has(value),
        () => new ControlBoundaryError({ boundary: "state", reason: "unknown state" }),
      ),
      Effect.mapError((error) =>
        error instanceof ControlBoundaryError ? error : boundaryError("state")(error),
      ),
    );
    const event = yield* Schema.decodeUnknown(ControlEventSchema, exact)(envelope.event).pipe(
      Effect.filterOrFail(
        (value) => events.has(value.type),
        () => new ControlBoundaryError({ boundary: "event", reason: "unknown event type" }),
      ),
      Effect.mapError((error) =>
        error instanceof ControlBoundaryError ? error : boundaryError("event")(error),
      ),
    );
    const context = yield* Schema.decodeUnknown(ControlContextSchema, exact)(envelope.context).pipe(
      Effect.filterOrFail(
        (value) =>
          Object.keys(value).sort().join("\n") === contextKeys.join("\n") &&
          authoritativeControlProfile.context_schema.required.every((key) => key in value),
        () => new ControlBoundaryError({
          boundary: "context",
          reason: "context keys do not match the authoritative profile",
        }),
      ),
      Effect.mapError((error) =>
        error instanceof ControlBoundaryError ? error : boundaryError("context")(error),
      ),
    );
    return Object.freeze({ state, event, context });
  });

export type ControlRejectionReason =
  | "authority_invalid" | "terminal_state" | "invalid_transition"
  | "guard_false" | "guard_missing" | "evidence_missing";
export type ControlCommand = Readonly<{
  kind: "PersistControlTransition" | "PersistPendingInterrupt" | "AuditInvalidTransition";
  payload: Readonly<Record<string, string>>;
}>;
type DecisionBase = Readonly<{
  source_state: ControlState;
  target_state: ControlState;
  event_id: string;
  effects: ReadonlyArray<ControlCommand>;
}>;
export type ControlDecision =
  | (DecisionBase & Readonly<{ kind: "accepted"; accepted: true; transition_id: string }>)
  | (DecisionBase & Readonly<{
      kind: "rejected";
      accepted: false;
      transition_id: null;
      reason: ControlRejectionReason;
      missing_evidence: ReadonlyArray<string>;
    }>);

const command = (
  kind: ControlCommand["kind"],
  event: ControlEvent,
  extra: Readonly<Record<string, string>> = {},
): ControlCommand => Object.freeze({
  kind,
  payload: Object.freeze({ event_id: event.event_id, ...extra }),
});
const reject = (
  state: ControlState,
  event: ControlEvent,
  reason: ControlRejectionReason,
  missing: ReadonlyArray<string> = [],
): ControlDecision => Object.freeze({
  kind: "rejected",
  accepted: false,
  source_state: state,
  target_state: state,
  transition_id: null,
  event_id: event.event_id,
  reason,
  missing_evidence: Object.freeze([...missing].sort()),
  effects: Object.freeze([command("AuditInvalidTransition", event, {
    state, event: event.type, actor_role: event.actor_role, reason,
  })]),
});
const accept = (
  state: ControlState,
  target: ControlState,
  transitionId: string,
  event: ControlEvent,
  effects: ReadonlyArray<ControlCommand>,
): ControlDecision => Object.freeze({
  kind: "accepted",
  accepted: true,
  source_state: state,
  target_state: target,
  transition_id: transitionId,
  event_id: event.event_id,
  effects: Object.freeze([...effects]),
});

/** Pure, total reducer over a previously decoded profile and invocation. */
export const decideControlStep = (
  input: DecodedControlStep,
): ControlDecision => {
  const profile = authoritativeControlProfile;
  const { state, event, context } = input;
  const control = profile.machines[0];
  const allowed = profile.event_authority[event.type] ?? [];
  if (!allowed.some((entry) =>
    entry.actor_role === event.actor_role && entry.capability === event.capability
  )) return reject(state, event, "authority_invalid");
  if (control.states.some((item) => item.id === state && item.kind === "final")) {
    return reject(state, event, "terminal_state");
  }
  const interrupt = profile.global_interrupts.find((item) => item.event === event.type);
  if (interrupt !== undefined) {
    const deferred = interrupt.deferred_in_states.includes(state);
    return accept(
      state,
      deferred ? state : interrupt.to,
      `global-interrupt:${interrupt.event}${deferred ? ":deferred" : ""}`,
      event,
      [command(
        deferred ? "PersistPendingInterrupt" : "PersistControlTransition",
        event,
        deferred ? { interrupt: interrupt.event } : {},
      )],
    );
  }
  const transition = control.transitions.find(
    (item) => item.from === state && item.event === event.type,
  );
  if (transition === undefined) return reject(state, event, "invalid_transition");
  if (transition.guard !== undefined) {
    const definition = profile.guards[transition.guard];
    const values = definition === undefined
      ? undefined
      : definition.reads.map((key) => context[key]);
    const value = definition === undefined ||
      values === undefined || values.some((item) => item === undefined)
      ? undefined
      : definition.operator === "all_true"
      ? values.every((item) => item === true)
      : values.length === 1
      ? values[0]
      : undefined;
    if (value === undefined) return reject(state, event, "guard_missing");
    if (!value) return reject(state, event, "guard_false");
  }
  const missing = transition.evidence_required.filter(
    (name) => event.payload[name] === undefined || event.payload[name] === null,
  );
  if (missing.length > 0) return reject(state, event, "evidence_missing", missing);
  return accept(
    state,
    transition.to,
    transition.id,
    event,
    transition.effects.map((kind) => command(kind, event)),
  );
};
