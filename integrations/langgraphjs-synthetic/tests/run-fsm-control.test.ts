import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { Effect, Exit, Schema } from "effect";

import controlProfileJson from "../../../spec/run-fsm.v1.json" with {
  type: "json",
};
import controlTracesJson from "../../../spec/run-fsm-traces.v1.json" with {
  type: "json",
};
import {
  RunFsmProfileSchema,
  authoritativeControlProfile,
  decideControlStep,
  decodeControlStep,
  type ControlEvent,
  type ControlContext,
  type DecodedControlStep,
} from "../src/run-fsm-control.js";

const profile = authoritativeControlProfile;
const machine = profile.machines[0];
const emptyContext: ControlContext = Object.fromEntries(
  profile.context_schema.required.map((key) => [key, false]),
);

const event = (state: string, type: string, sequence: number): ControlEvent => {
  const authority = profile.event_authority[type]?.[0];
  assert.ok(authority, `missing authority for ${type}`);
  const transition = machine.transitions.find(
    (item) => item.from === state && item.event === type,
  );
  return {
    type,
    actor_role: authority.actor_role,
    capability: authority.capability,
    event_id: `control:test:${sequence}`,
    payload: Object.fromEntries(
      (transition?.evidence_required ?? []).map((name) => [
        name,
        { kind: "ControlTestEvidence", name },
      ]),
    ),
  };
};

const input = (
  state: string,
  type: string,
  sequence: number,
  context: ControlContext = emptyContext,
): DecodedControlStep => ({
  state,
  event: event(state, type, sequence),
  context,
});

const contextFromGuardResults = (
  results: Readonly<Record<string, boolean>>,
): ControlContext => {
  const context = { ...emptyContext };
  for (const [name, value] of Object.entries(results)) {
    const guard = profile.guards[name];
    assert.ok(guard, `missing guard ${name}`);
    for (const key of guard.reads) context[key] = value;
  }
  return context;
};

describe("Effect Schema run-FSM control kernel", () => {
  it("replays the existing authoritative conformance traces deterministically", async () => {
    for (const fixture of controlTracesJson.cases) {
      let state = machine.initial;
      for (const step of fixture.steps) {
        const transition = machine.transitions.find(
          (item) => item.from === state && item.event === step.event.type,
        );
        const value = {
          state,
          event: {
            ...step.event,
            payload: Object.fromEntries(
              (transition?.evidence_required ?? []).map((name) => [name, { name }]),
            ),
          },
          context: contextFromGuardResults(step.guard_results),
        };
        const decoded = await Effect.runPromise(decodeControlStep(value));
        const first = decideControlStep(decoded);
        assert.deepEqual(first, decideControlStep(decoded), fixture.id);
        assert.equal(first.target_state, step.expected_state, fixture.id);
        assert.deepEqual(first.effects.map((effect) => effect.kind), step.expected_effects);
        assert.ok(Object.isFrozen(first));
        state = first.target_state;
      }
    }
  });

  it("fails closed on authority, guard, evidence, and terminal violations", async () => {
    const start = await Effect.runPromise(decodeControlStep(input("INIT", "START", 20)));
    const unauthorized = decideControlStep({
      ...start,
      event: { ...start.event, actor_role: "model" },
    });
    assert.equal(unauthorized.kind, "rejected");
    if (unauthorized.kind === "rejected") {
      assert.equal(unauthorized.reason, "authority_invalid");
    }

    const missingEvidence = decideControlStep({
      state: "INIT",
      event: { ...start.event, event_id: "control:test:21", payload: {} },
      context: emptyContext,
    });
    assert.equal(missingEvidence.kind, "rejected");
    if (missingEvidence.kind === "rejected") {
      assert.equal(missingEvidence.reason, "evidence_missing");
    }

    const stable = await Effect.runPromise(
      decodeControlStep(input("STABILIZE", "EPOCH_STABLE", 22)),
    );
    const guardRejected = decideControlStep(stable);
    assert.equal(guardRejected.kind, "rejected");

    const completion = await Effect.runPromise(
      decodeControlStep(input("VERIFY_COMPLETION", "VERIFIED_COMPLETE", 23)),
    );
    const rejectedCompletion = decideControlStep({
      ...completion,
      context: {
        ...emptyContext,
        independent_receipt_closed: true,
        no_unknown_effects: false,
      },
    });
    assert.equal(rejectedCompletion.kind, "rejected");
    assert.equal(rejectedCompletion.target_state, "VERIFY_COMPLETION");
    const terminal = decideControlStep({
      state: "SUCCEEDED",
      event: start.event,
      context: emptyContext,
    });
    assert.equal(terminal.kind, "rejected");
  });

  it("decodes the repository profile and every unknown invocation boundary", async () => {
    assert.deepEqual(
      profile,
      await Effect.runPromise(
        Schema.decodeUnknown(RunFsmProfileSchema)(controlProfileJson),
      ),
    );
    const valid = input("INIT", "START", 30);
    const invalid: ReadonlyArray<readonly [string, unknown]> = [
      ["state", { ...valid, state: "NOT_A_CONTROL_STATE" }],
      ["event", { ...valid, event: { ...valid.event, capability: undefined } }],
      ["context", { ...valid, context: { ...emptyContext, frontier_passed: "yes" } }],
      ["context", { ...valid, context: { ...emptyContext, extra: false } }],
    ];
    for (const [boundary, value] of invalid) {
      const error = await Effect.runPromise(decodeControlStep(value).pipe(Effect.flip));
      assert.equal(error.boundary, boundary);
    }
    assert.ok(
      Exit.isFailure(
        await Effect.runPromiseExit(Schema.decodeUnknown(RunFsmProfileSchema)({})),
      ),
    );
  });
});
