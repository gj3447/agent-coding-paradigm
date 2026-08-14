import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { Effect } from "effect";

import {
  LocalArtifactEffectPort,
  LocalArtifactVerificationPort,
  canonicalDigest,
  createSyntheticConsumer as createSyntheticConsumerWithClock,
  digestIntent,
  type CreateSyntheticConsumerOptions,
  type EffectPort,
  type EffectObservation,
  type TrustedClock,
  type VerificationPort,
  type VerificationReceipt,
  type SyntheticRunInput,
} from "../src/index.js";

const temporaryDirectories: Array<string> = [];
const fixedTestClock: TrustedClock = Object.freeze({
  nowEpochMilliseconds: () => Date.parse("2026-08-11T15:00:00Z"),
});

type TestConsumerOptions = Omit<CreateSyntheticConsumerOptions, "clock"> & {
  readonly clock?: TrustedClock;
};

const createSyntheticConsumer = (options: TestConsumerOptions) =>
  createSyntheticConsumerWithClock({
    ...options,
    clock: options.clock ?? fixedTestClock,
  });

const makeTemporaryDirectory = async (): Promise<string> => {
  const directory = await mkdtemp(join(tmpdir(), "flrh-langgraphjs-"));
  temporaryDirectories.push(directory);
  return directory;
};

const makeInput = (
  overrides: Partial<SyntheticRunInput> = {},
): SyntheticRunInput => ({
  schemaVersion: "flrh-langgraphjs-input/1",
  profileVersion: "shared-accelerator-synthetic/1",
  runId: "run:synthetic-1",
  availableHeadroom: 8,
  requiredHeadroom: 4,
  timeoutMs: 5_000,
  approval: {
    required: false,
    deadlineAt: "2026-08-11T16:00:00Z",
  },
  intent: {
    intentId: "intent:analysis-1",
    idempotencyKey: "idempotency:analysis-1",
    action: "write_synthetic_analysis_artifact",
    payload: {
      marker: "SYNTHETIC",
      result: "eligible",
    },
  },
  ...overrides,
});

afterEach(async () => {
  await Promise.all(
    temporaryDirectories.splice(0).map((directory) =>
      rm(directory, { recursive: true, force: true }),
    ),
  );
});

describe("LangGraph.js synthetic FLR-H consumer", () => {
  it("runs the happy path through an independent verifier", async () => {
    const directory = await makeTemporaryDirectory();
    const effect = new LocalArtifactEffectPort({
      directory,
      componentId: "effect:local-artifact",
      applyMode: "confirmed_success",
    });
    const verifier = new LocalArtifactVerificationPort({
      directory,
      componentId: "verifier:local-artifact",
    });
    const consumer = createSyntheticConsumer({ effect, verifier });

    const result = await consumer.run(makeInput(), {
      signal: AbortSignal.timeout(10_000),
    });

    assert.equal(result.kind, "settled");
    if (result.kind !== "settled") return;
    assert.equal(result.receipt.terminal, "SUCCEEDED");
    assert.equal(result.receipt.dispatchCount, 1);
    assert.equal(result.receipt.queryCount, 0);
    assert.equal(effect.confirmedMutationCount, 1);
    assert.equal(result.receipt.verifierComponentId, verifier.componentId);
    assert.deepEqual(result.receipt.route, [
      "decide",
      "derive_eligibility",
      "stabilize",
      "commit_intent",
      "dispatch",
      "verify",
      "close_terminal",
    ]);
  });

  it("reconciles an unknown result without dispatching twice", async () => {
    const directory = await makeTemporaryDirectory();
    const effect = new LocalArtifactEffectPort({
      directory,
      componentId: "effect:unknown-after-write",
      applyMode: "unknown_after_write",
    });
    const verifier = new LocalArtifactVerificationPort({
      directory,
      componentId: "verifier:local-artifact",
    });
    const consumer = createSyntheticConsumer({ effect, verifier });

    const result = await consumer.run(makeInput(), {
      signal: AbortSignal.timeout(10_000),
    });

    assert.equal(result.kind, "settled");
    if (result.kind !== "settled") return;
    assert.equal(result.receipt.terminal, "SUCCEEDED");
    assert.equal(result.receipt.dispatchCount, 1);
    assert.equal(result.receipt.queryCount, 1);
    assert.deepEqual(result.receipt.route.slice(-4), [
      "dispatch",
      "reconcile",
      "verify",
      "close_terminal",
    ]);
  });

  it("interrupts for approval before touching the effect boundary", async () => {
    const directory = await makeTemporaryDirectory();
    const effect = new LocalArtifactEffectPort({
      directory,
      componentId: "effect:approval",
      applyMode: "confirmed_success",
    });
    const verifier = new LocalArtifactVerificationPort({
      directory,
      componentId: "verifier:approval",
    });
    const consumer = createSyntheticConsumer({ effect, verifier });

    const paused = await consumer.run(
      makeInput({
        approval: {
          required: true,
          deadlineAt: "2026-08-11T16:00:00Z",
        },
      }),
      {
        signal: AbortSignal.timeout(10_000),
      },
    );

    assert.equal(paused.kind, "interrupted");
    if (paused.kind !== "interrupted") return;
    assert.equal(paused.interrupt.kind, "approval_required");
    if (paused.interrupt.kind !== "approval_required") return;
    assert.equal(effect.applyCount, 0);

    const rejected = await consumer.resumeApproval(
      {
        runId: "run:synthetic-1",
        intentDigest: paused.interrupt.intentDigest,
        approvalNonce: paused.interrupt.approvalNonce,
        decision: "reject",
      },
      { signal: AbortSignal.timeout(10_000) },
    );
    assert.equal(rejected.kind, "settled");
    if (rejected.kind !== "settled") return;
    assert.equal(rejected.receipt.terminal, "CANCELLED");
    assert.equal(rejected.receipt.dispatchCount, 0);
    assert.equal(effect.applyCount, 0);
  });

  it("does not dispatch when approval arrives after its trusted deadline", async () => {
    const directory = await makeTemporaryDirectory();
    const effect = new LocalArtifactEffectPort({
      directory,
      componentId: "effect:expired-approval",
      applyMode: "confirmed_success",
    });
    const verifier = new LocalArtifactVerificationPort({
      directory,
      componentId: "verifier:expired-approval",
    });
    const consumer = createSyntheticConsumer({
      effect,
      verifier,
      clock: {
        nowEpochMilliseconds: () =>
          Date.parse("2026-08-11T16:00:00.001Z"),
      },
    });
    const input = makeInput({
      runId: "run:expired-approval",
      approval: {
        required: true,
        deadlineAt: "2026-08-11T16:00:00.000Z",
      },
    });

    const paused = await consumer.run(input, {
      signal: AbortSignal.timeout(10_000),
    });
    assert.equal(paused.kind, "interrupted");
    if (paused.kind !== "interrupted") return;
    assert.equal(paused.interrupt.kind, "approval_required");
    if (paused.interrupt.kind !== "approval_required") return;

    const result = await consumer.resumeApproval(
      {
        runId: input.runId,
        intentDigest: paused.interrupt.intentDigest,
        approvalNonce: paused.interrupt.approvalNonce,
        decision: "approve",
      },
      { signal: AbortSignal.timeout(10_000) },
    );

    assert.equal(result.kind, "settled");
    if (result.kind !== "settled") return;
    assert.equal(result.receipt.terminal, "TIMED_OUT");
    assert.equal(result.receipt.dispatchCount, 0);
    assert.equal(effect.applyCount, 0);
  });

  it("does not let stale approval content authorize a different intent", async () => {
    const directory = await makeTemporaryDirectory();
    const effect = new LocalArtifactEffectPort({
      directory,
      componentId: "effect:approval-binding",
      applyMode: "confirmed_success",
    });
    const verifier = new LocalArtifactVerificationPort({
      directory,
      componentId: "verifier:approval-binding",
    });
    const consumer = createSyntheticConsumer({
      effect,
      verifier,
      clock: {
        nowEpochMilliseconds: () => Date.parse("2026-08-11T15:00:00Z"),
      },
    });
    const firstInput = makeInput({
      runId: "run:first-approval",
      approval: {
        required: true,
        deadlineAt: "2026-08-11T16:00:00Z",
      },
    });
    const secondInput = makeInput({
      runId: "run:second-approval",
      approval: {
        required: true,
        deadlineAt: "2026-08-11T16:00:00Z",
      },
      intent: {
        ...makeInput().intent,
        intentId: "intent:second-approval",
        idempotencyKey: "idempotency:second-approval",
        payload: { marker: "SYNTHETIC", result: "different-intent" },
      },
    });

    const firstPaused = await consumer.run(firstInput, {
      signal: AbortSignal.timeout(10_000),
    });
    const secondPaused = await consumer.run(secondInput, {
      signal: AbortSignal.timeout(10_000),
    });
    assert.equal(firstPaused.kind, "interrupted");
    assert.equal(secondPaused.kind, "interrupted");
    if (
      firstPaused.kind !== "interrupted" ||
      firstPaused.interrupt.kind !== "approval_required" ||
      secondPaused.kind !== "interrupted" ||
      secondPaused.interrupt.kind !== "approval_required"
    ) {
      return;
    }
    await assert.rejects(
      consumer.resumeApproval(
        {
          runId: secondInput.runId,
          intentDigest: firstPaused.interrupt.intentDigest,
          approvalNonce: firstPaused.interrupt.approvalNonce,
          decision: "approve",
        },
        { signal: AbortSignal.timeout(10_000) },
      ),
      /approval binding mismatch/u,
    );
    assert.equal(effect.applyCount, 0);

    const accepted = await consumer.resumeApproval(
      {
        runId: secondInput.runId,
        intentDigest: secondPaused.interrupt.intentDigest,
        approvalNonce: secondPaused.interrupt.approvalNonce,
        decision: "approve",
      },
      { signal: AbortSignal.timeout(10_000) },
    );
    assert.equal(accepted.kind, "settled");
    assert.equal(effect.applyCount, 1);

    await assert.rejects(
      consumer.resumeApproval(
        {
          runId: secondInput.runId,
          intentDigest: secondPaused.interrupt.intentDigest,
          approvalNonce: secondPaused.interrupt.approvalNonce,
          decision: "approve",
        },
        { signal: AbortSignal.timeout(10_000) },
      ),
      /not paused for approval_required/u,
    );
    assert.equal(effect.applyCount, 1);
  });

  it("fails closed when the effect producer is also the verifier", async () => {
    const directory = await makeTemporaryDirectory();
    const aliased = Object.assign(
      new LocalArtifactEffectPort({
        directory,
        componentId: "component:aliased",
        applyMode: "confirmed_success",
      }),
      {
        verify: (): Effect.Effect<VerificationReceipt> =>
          Effect.succeed({
            kind: "rejected",
            verifierComponentId: "component:aliased",
            reason: "self report",
          }),
      },
    );

    assert.throws(
      () => createSyntheticConsumer({ effect: aliased, verifier: aliased }),
      /independent/,
    );
  });

  it("blocks insufficient headroom before committing an effect", async () => {
    const directory = await makeTemporaryDirectory();
    const effect = new LocalArtifactEffectPort({
      directory,
      componentId: "effect:blocked",
      applyMode: "confirmed_success",
    });
    const verifier = new LocalArtifactVerificationPort({
      directory,
      componentId: "verifier:blocked",
    });
    const consumer = createSyntheticConsumer({ effect, verifier });

    const result = await consumer.run(
      makeInput({ availableHeadroom: 1, requiredHeadroom: 4 }),
      {
        signal: AbortSignal.timeout(10_000),
      },
    );

    assert.equal(result.kind, "settled");
    if (result.kind !== "settled") return;
    assert.equal(result.receipt.terminal, "BLOCKED");
    assert.equal(result.receipt.dispatchCount, 0);
    assert.equal(result.receipt.queryCount, 0);
    assert.deepEqual(result.receipt.route, [
      "decide",
      "derive_eligibility",
      "close_terminal",
    ]);
  });

  it("routes duplicate identity with different intent to conflict", async () => {
    const directory = await makeTemporaryDirectory();
    const effect = new LocalArtifactEffectPort({
      directory,
      componentId: "effect:conflict",
      applyMode: "confirmed_success",
    });
    const verifier = new LocalArtifactVerificationPort({
      directory,
      componentId: "verifier:conflict",
    });
    const consumer = createSyntheticConsumer({ effect, verifier });
    const input = makeInput();

    const result = await consumer.run(
      makeInput({
        priorIntent: {
          ...input.intent,
          payload: { marker: "SYNTHETIC", result: "different" },
        },
      }),
      {
        signal: AbortSignal.timeout(10_000),
      },
    );

    assert.equal(result.kind, "settled");
    if (result.kind !== "settled") return;
    assert.equal(result.receipt.terminal, "ACTIVE");
    assert.equal(result.receipt.dispatchCount, 0);
    assert.deepEqual(result.receipt.route, ["decide", "close_terminal"]);
  });

  it("does not accept producer success when independent verification rejects", async () => {
    const directory = await makeTemporaryDirectory();
    const effect = new LocalArtifactEffectPort({
      directory,
      componentId: "effect:self-report",
      applyMode: "confirmed_success",
    });
    const verifier: VerificationPort = {
      componentId: "verifier:rejecting",
      verify: () => Effect.succeed({
        kind: "rejected",
        verifierComponentId: "verifier:rejecting",
        reason: "independent evidence is absent",
      }),
    };
    const consumer = createSyntheticConsumer({ effect, verifier });

    const result = await consumer.run(makeInput(), {
      signal: AbortSignal.timeout(10_000),
    });

    assert.equal(result.kind, "settled");
    if (result.kind !== "settled") return;
    assert.equal(result.receipt.terminal, "ACTIVE");
    assert.equal(result.receipt.dispatchCount, 1);
    assert.deepEqual(result.receipt.route.slice(-2), [
      "verify",
      "close_terminal",
    ]);
  });

  it("does not accept an unbound cached verifier self-report", async () => {
    const directory = await makeTemporaryDirectory();
    const effect = new LocalArtifactEffectPort({
      directory,
      componentId: "effect:cached-self-report",
      applyMode: "confirmed_success",
    });
    const verifier: VerificationPort = {
      componentId: "verifier:cached-self-report-wrapper",
      verify: () =>
        Effect.succeed({
          kind: "verified",
          verifierComponentId: "verifier:cached-self-report-wrapper",
          reason: "cached producer assertion",
        }),
    };
    const consumer = createSyntheticConsumer({ effect, verifier });

    const result = await consumer.run(makeInput(), {
      signal: AbortSignal.timeout(10_000),
    });

    assert.equal(result.kind, "settled");
    if (result.kind !== "settled") return;
    assert.equal(result.receipt.terminal, "ACTIVE");
    assert.equal(result.receipt.queryCount, 0);
    assert.deepEqual(result.receipt.route.slice(-2), [
      "verify",
      "close_terminal",
    ]);
  });

  it("queries before accepting a success receipt whose identity was not bound", async () => {
    const directory = await makeTemporaryDirectory();
    const base = new LocalArtifactEffectPort({
      directory,
      componentId: "effect:receipt-binding",
      applyMode: "confirmed_success",
    });
    const effect: EffectPort = {
      componentId: base.componentId,
      apply: (intent) =>
        base.apply(intent).pipe(
          Effect.map((observation): EffectObservation => {
            if (observation.kind !== "confirmed_success") return observation;
            return {
              kind: "confirmed_success",
              receipt: {
                ...observation.receipt,
                intentId: "intent:wrong",
                idempotencyKey: "idempotency:wrong",
                producerComponentId: "effect:wrong",
              },
            };
          }),
        ),
      query: (intent) => base.query(intent),
    };
    const verifier = new LocalArtifactVerificationPort({
      directory,
      componentId: "verifier:receipt-binding",
    });
    const consumer = createSyntheticConsumer({ effect, verifier });

    const result = await consumer.run(makeInput(), {
      signal: AbortSignal.timeout(10_000),
    });

    assert.equal(result.kind, "settled");
    if (result.kind !== "settled") return;
    assert.equal(result.receipt.terminal, "SUCCEEDED");
    assert.equal(result.receipt.dispatchCount, 1);
    assert.equal(result.receipt.queryCount, 1);
    assert.deepEqual(result.receipt.route.slice(-4), [
      "dispatch",
      "reconcile",
      "verify",
      "close_terminal",
    ]);
  });

  it("reconciles before honoring cancellation while the outcome is unknown", async () => {
    const directory = await makeTemporaryDirectory();
    const effect = new LocalArtifactEffectPort({
      directory,
      componentId: "effect:unresolved",
      applyMode: "unknown_after_write_unobservable",
    });
    const verifier = new LocalArtifactVerificationPort({
      directory,
      componentId: "verifier:unresolved",
    });
    const consumer = createSyntheticConsumer({ effect, verifier });

    const paused = await consumer.run(makeInput(), {
      signal: AbortSignal.timeout(10_000),
    });
    assert.equal(paused.kind, "interrupted");
    if (paused.kind !== "interrupted") return;
    assert.equal(paused.interrupt.kind, "reconciliation_required");
    assert.equal(effect.applyCount, 1);
    assert.equal(effect.queryCount, 1);
    assert.equal(effect.confirmedMutationCount, 1);

    const cancelled = await consumer.resumeReconciliation(
      {
        runId: "run:synthetic-1",
        decision: { kind: "cancel" },
      },
      { signal: AbortSignal.timeout(10_000) },
    );
    assert.equal(cancelled.kind, "settled");
    if (cancelled.kind !== "settled") return;
    assert.equal(cancelled.receipt.terminal, "CANCELLED");
    assert.equal(cancelled.receipt.dispatchCount, 1);
    assert.equal(cancelled.receipt.queryCount, 1);
    assert.deepEqual(cancelled.receipt.route.slice(-3), [
      "reconcile",
      "human_reconciliation",
      "close_terminal",
    ]);
  });

  it("does not accept an unknown observation as a resolved reconciliation", async () => {
    const directory = await makeTemporaryDirectory();
    const effect = new LocalArtifactEffectPort({
      directory,
      componentId: "effect:still-unknown",
      applyMode: "unknown_after_write_unobservable",
    });
    const verifier = new LocalArtifactVerificationPort({
      directory,
      componentId: "verifier:still-unknown",
    });
    const consumer = createSyntheticConsumer({ effect, verifier });
    const paused = await consumer.run(makeInput(), {
      signal: AbortSignal.timeout(10_000),
    });
    assert.equal(paused.kind, "interrupted");

    await assert.rejects(
      consumer.resumeReconciliation(
        {
          runId: "run:synthetic-1",
          decision: {
            kind: "resolved",
            observation: {
              kind: "unknown",
              reason: "the external outcome is still unknown",
            },
          } as never,
        },
        { signal: AbortSignal.timeout(10_000) },
      ),
    );

    const cancelled = await consumer.resumeReconciliation(
      { runId: "run:synthetic-1", decision: { kind: "cancel" } },
      { signal: AbortSignal.timeout(10_000) },
    );
    assert.equal(cancelled.kind, "settled");
    if (cancelled.kind !== "settled") return;
    assert.equal(cancelled.receipt.terminal, "CANCELLED");
  });

  it("keeps reconciliation open when a human success receipt is not bound", async () => {
    const directory = await makeTemporaryDirectory();
    const effect = new LocalArtifactEffectPort({
      directory,
      componentId: "effect:unbound-human-receipt",
      applyMode: "unknown_after_write_unobservable",
    });
    const verifier = new LocalArtifactVerificationPort({
      directory,
      componentId: "verifier:unbound-human-receipt",
    });
    const input = makeInput({ runId: "run:unbound-human-receipt" });
    const consumer = createSyntheticConsumer({ effect, verifier });
    const paused = await consumer.run(input, {
      signal: AbortSignal.timeout(10_000),
    });
    assert.equal(paused.kind, "interrupted");

    await assert.rejects(
      consumer.resumeReconciliation(
        {
          runId: input.runId,
          decision: {
            kind: "resolved",
            observation: {
              kind: "confirmed_success",
              receipt: {
                kind: "action_receipt",
                intentId: "intent:wrong",
                idempotencyKey: "idempotency:wrong",
                artifactId: "artifact:wrong",
                artifactDigest: canonicalDigest({ artifact: "wrong" }),
                intentDigest: digestIntent(input.intent),
                producerComponentId: effect.componentId,
              },
            },
          },
        },
        { signal: AbortSignal.timeout(10_000) },
      ),
      /binding/u,
    );

    const cancelled = await consumer.resumeReconciliation(
      { runId: input.runId, decision: { kind: "cancel" } },
      { signal: AbortSignal.timeout(10_000) },
    );
    assert.equal(cancelled.kind, "settled");
    if (cancelled.kind !== "settled") return;
    assert.equal(cancelled.receipt.terminal, "CANCELLED");
    assert.equal(effect.applyCount, 1);
    assert.equal(effect.queryCount, 1);
    assert.equal(
      cancelled.receipt.route.filter(
        (step) => step === "human_reconciliation",
      ).length,
      1,
    );
  });

  it("keeps Effect port construction lazy until the boundary is executed", async () => {
    const directory = await makeTemporaryDirectory();
    const effect = new LocalArtifactEffectPort({
      directory,
      componentId: "effect:lazy",
      applyMode: "confirmed_success",
    });
    const program = effect.apply(makeInput().intent);

    assert.equal(effect.applyCount, 0);
    assert.equal(effect.confirmedMutationCount, 0);

    await Effect.runPromise(program);

    assert.equal(effect.applyCount, 1);
    assert.equal(effect.confirmedMutationCount, 1);
  });

  it("propagates caller cancellation instead of reclassifying it as unknown", async () => {
    const effect: EffectPort = {
      componentId: "effect:never",
      apply: () => Effect.never,
      query: () => Effect.never,
    };
    const verifier: VerificationPort = {
      componentId: "verifier:never",
      verify: () =>
        Effect.succeed({
          kind: "rejected",
          verifierComponentId: "verifier:never",
          reason: "no receipt",
        }),
    };
    const consumer = createSyntheticConsumer({ effect, verifier });
    const controller = new AbortController();

    const pending = consumer.run(makeInput({ timeoutMs: 5_000 }), {
      signal: controller.signal,
    });
    setTimeout(() => controller.abort(new Error("caller cancelled")), 25);

    await assert.rejects(pending);
  });

  it("turns a bounded Effect timeout into reconciliation without retrying apply", async () => {
    let applyCount = 0;
    let queryCount = 0;
    const effect: EffectPort = {
      componentId: "effect:timeout",
      apply: () =>
        Effect.sync(() => {
          applyCount += 1;
        }).pipe(Effect.zipRight(Effect.never)),
      query: () =>
        Effect.sync(() => {
          queryCount += 1;
        }).pipe(Effect.zipRight(Effect.never)),
    };
    const verifier: VerificationPort = {
      componentId: "verifier:timeout",
      verify: () =>
        Effect.succeed({
          kind: "rejected",
          verifierComponentId: "verifier:timeout",
          reason: "no receipt",
        }),
    };
    const consumer = createSyntheticConsumer({ effect, verifier });

    const result = await consumer.run(makeInput({ timeoutMs: 20 }), {
      signal: AbortSignal.timeout(2_000),
    });

    assert.equal(result.kind, "interrupted");
    if (result.kind !== "interrupted") return;
    assert.equal(result.interrupt.kind, "reconciliation_required");
    assert.equal(applyCount, 1);
    assert.equal(queryCount, 1);
  });

  it("returns a completed thread idempotently without executing its effect again", async () => {
    const directory = await makeTemporaryDirectory();
    const effect = new LocalArtifactEffectPort({
      directory,
      componentId: "effect:thread-replay",
      applyMode: "confirmed_success",
    });
    const verifier = new LocalArtifactVerificationPort({
      directory,
      componentId: "verifier:thread-replay",
    });
    const consumer = createSyntheticConsumer({ effect, verifier });
    const options = {
      signal: AbortSignal.timeout(10_000),
    };

    const first = await consumer.run(makeInput(), options);
    const second = await consumer.run(makeInput(), options);

    assert.deepEqual(second, first);
    assert.equal(effect.applyCount, 1);
    assert.equal(effect.confirmedMutationCount, 1);
  });

  it("rejects different input bytes for an existing run identity", async () => {
    const directory = await makeTemporaryDirectory();
    const effect = new LocalArtifactEffectPort({
      directory,
      componentId: "effect:thread-conflict",
      applyMode: "confirmed_success",
    });
    const verifier = new LocalArtifactVerificationPort({
      directory,
      componentId: "verifier:thread-conflict",
    });
    const consumer = createSyntheticConsumer({ effect, verifier });
    const options = {
      signal: AbortSignal.timeout(10_000),
    };
    const original = makeInput();
    await consumer.run(original, options);

    await assert.rejects(
      consumer.run(
        {
          ...original,
          intent: {
            ...original.intent,
            payload: { marker: "SYNTHETIC", result: "different" },
          },
        },
        options,
      ),
      /run identity conflict/u,
    );
    assert.equal(effect.applyCount, 1);
  });

  it("serializes concurrent invocations for one run identity", async () => {
    const directory = await makeTemporaryDirectory();
    const effect = new LocalArtifactEffectPort({
      directory,
      componentId: "effect:thread-concurrency",
      applyMode: "confirmed_success",
    });
    const verifier = new LocalArtifactVerificationPort({
      directory,
      componentId: "verifier:thread-concurrency",
    });
    const consumer = createSyntheticConsumer({ effect, verifier });
    const run = () =>
      consumer.run(makeInput(), {
        signal: AbortSignal.timeout(10_000),
      });

    const results = await Promise.allSettled([run(), run()]);

    assert.equal(
      results.filter((result) => result.status === "fulfilled").length,
      1,
    );
    assert.equal(
      results.filter((result) => result.status === "rejected").length,
      1,
    );
    assert.equal(effect.applyCount, 1);
    assert.equal(effect.confirmedMutationCount, 1);
  });

  it("fails fast when the H cross-run concurrency bound is full", async () => {
    let applyCount = 0;
    let announceFirstApply: (() => void) | undefined;
    let releaseFirstApply: (() => void) | undefined;
    const firstApplyStarted = new Promise<void>((resolve) => {
      announceFirstApply = resolve;
    });
    const firstApplyGate = new Promise<void>((resolve) => {
      releaseFirstApply = resolve;
    });
    const effect: EffectPort = {
      componentId: "effect:bounded-cross-run",
      apply: () =>
        Effect.gen(function* () {
          applyCount += 1;
          if (applyCount === 1) {
            announceFirstApply?.();
            yield* Effect.promise(() => firstApplyGate);
          }
          return {
            kind: "confirmed_failure" as const,
            reason: "bounded admission fixture",
          };
        }),
      query: () =>
        Effect.succeed({
          kind: "confirmed_failure" as const,
          reason: "query is not expected",
        }),
    };
    const verifier: VerificationPort = {
      componentId: "verifier:bounded-cross-run",
      verify: () =>
        Effect.succeed({
          kind: "rejected",
          verifierComponentId: "verifier:bounded-cross-run",
          reason: "no successful receipt is expected",
        }),
    };
    const consumer = createSyntheticConsumer({
      effect,
      verifier,
      limits: { maxConcurrentRuns: 1 },
    });
    const first = consumer.run(
      makeInput({ runId: "run:bounded-cross-run-1" }),
      { signal: AbortSignal.timeout(10_000) },
    );
    await firstApplyStarted;

    try {
      await assert.rejects(
        consumer.run(
          makeInput({ runId: "run:bounded-cross-run-2" }),
          { signal: AbortSignal.timeout(10_000) },
        ),
        /concurrency capacity/u,
      );
    } finally {
      releaseFirstApply?.();
      await first;
    }
    assert.equal(applyCount, 1);
  });

  it("does not expose the raw graph around the authority wrapper", async () => {
    const directory = await makeTemporaryDirectory();
    const consumer = createSyntheticConsumer({
      effect: new LocalArtifactEffectPort({
        directory,
        componentId: "effect:closed-surface",
        applyMode: "confirmed_success",
      }),
      verifier: new LocalArtifactVerificationPort({
        directory,
        componentId: "verifier:closed-surface",
      }),
    });

    assert.deepEqual(Object.keys(consumer).sort(), [
      "recoverAfterCancellation",
      "resumeApproval",
      "resumeReconciliation",
      "run",
    ]);
  });

  it("recovers a cancelled dispatch through query without a second apply", async () => {
    const input = makeInput({ timeoutMs: 5_000 });
    let applyCount = 0;
    let queryCount = 0;
    let announceDispatch: (() => void) | undefined;
    let announceQuery: (() => void) | undefined;
    const dispatchStarted = new Promise<void>((resolve) => {
      announceDispatch = resolve;
    });
    const firstQueryStarted = new Promise<void>((resolve) => {
      announceQuery = resolve;
    });
    const receipt = {
      kind: "action_receipt" as const,
      intentId: input.intent.intentId,
      idempotencyKey: input.intent.idempotencyKey,
      artifactId: "artifact:abort-window",
      artifactDigest: canonicalDigest({ artifact: "abort-window" }),
      intentDigest: digestIntent(input.intent),
      producerComponentId: "effect:abort-window",
    };
    const effect: EffectPort = {
      componentId: receipt.producerComponentId,
      apply: () =>
        Effect.sync(() => {
          applyCount += 1;
          announceDispatch?.();
        }).pipe(
          Effect.zipRight(Effect.sleep("100 millis")),
          Effect.as({ kind: "confirmed_success" as const, receipt }),
        ),
      query: () =>
        Effect.gen(function* () {
          queryCount += 1;
          if (queryCount === 1) {
            announceQuery?.();
            yield* Effect.sleep("100 millis");
          }
          return {
            kind: "unknown" as const,
            reason: "the cancelled dispatch outcome requires an operator",
          };
        }),
    };
    const verifier: VerificationPort = {
      componentId: "verifier:abort-window",
      verify: (request) =>
        Effect.succeed({
          kind: "verified",
          verifierComponentId: "verifier:abort-window",
          runId: request.runId,
          intentDigest: request.intentDigest,
          actionReceiptDigest: canonicalDigest(request.receipt),
          observedArtifactDigest: request.receipt.artifactDigest,
          reason: "bounded test verifier",
        }),
    };
    const consumer = createSyntheticConsumer({ effect, verifier });
    const controller = new AbortController();
    const pending = consumer.run(input, {
      signal: controller.signal,
    });

    await dispatchStarted;
    controller.abort(new Error("test cancellation after dispatch began"));
    await assert.rejects(pending);
    await assert.rejects(
      consumer.resumeReconciliation(
        {
          runId: input.runId,
          decision: { kind: "cancel" },
        },
        { signal: AbortSignal.timeout(2_000) },
      ),
      /not paused for reconciliation_required/u,
    );
    assert.equal(applyCount, 1);

    const recoveryController = new AbortController();
    const firstRecovery = consumer.recoverAfterCancellation(
      { runId: input.runId },
      { signal: recoveryController.signal },
    );
    await firstQueryStarted;
    recoveryController.abort(new Error("test cancellation during query"));
    await assert.rejects(firstRecovery);
    assert.equal(applyCount, 1);
    assert.equal(queryCount, 1);

    const recovered = await consumer.recoverAfterCancellation(
      { runId: input.runId },
      { signal: AbortSignal.timeout(2_000) },
    );
    assert.deepEqual(recovered, {
      kind: "interrupted",
      interrupt: {
        kind: "reconciliation_required",
        runId: input.runId,
        intentId: input.intent.intentId,
        deadlineAt: input.approval.deadlineAt,
        allowedDecisions: ["resolved", "cancel", "timeout"],
      },
    });
    assert.equal(applyCount, 1);
    assert.equal(queryCount, 2);

    const cancelled = await consumer.resumeReconciliation(
      { runId: input.runId, decision: { kind: "cancel" } },
      { signal: AbortSignal.timeout(2_000) },
    );
    assert.equal(cancelled.kind, "settled");
    if (cancelled.kind !== "settled") return;
    assert.equal(cancelled.receipt.terminal, "CANCELLED");
    assert.equal(cancelled.receipt.dispatchCount, 1);
    assert.equal(cancelled.receipt.queryCount, 1);
    assert.equal(applyCount, 1);
  });

  it("repeats only independent verification after cancellation in verify", async () => {
    const input = makeInput({
      runId: "run:verify-cancellation",
      intent: {
        ...makeInput().intent,
        intentId: "intent:verify-cancellation",
        idempotencyKey: "idempotency:verify-cancellation",
      },
    });
    let applyCount = 0;
    let verifyCount = 0;
    let announceVerify: (() => void) | undefined;
    const firstVerificationStarted = new Promise<void>((resolve) => {
      announceVerify = resolve;
    });
    const receipt = {
      kind: "action_receipt" as const,
      intentId: input.intent.intentId,
      idempotencyKey: input.intent.idempotencyKey,
      artifactId: "artifact:verify-cancellation",
      artifactDigest: canonicalDigest({ artifact: "verify-cancellation" }),
      intentDigest: digestIntent(input.intent),
      producerComponentId: "effect:verify-cancellation",
    };
    const effect: EffectPort = {
      componentId: receipt.producerComponentId,
      apply: () =>
        Effect.sync(() => {
          applyCount += 1;
          return { kind: "confirmed_success" as const, receipt };
        }),
      query: () =>
        Effect.succeed({
          kind: "confirmed_success",
          receipt,
        }),
    };
    const verifier: VerificationPort = {
      componentId: "verifier:verify-cancellation",
      verify: (request) =>
        Effect.gen(function* () {
          verifyCount += 1;
          if (verifyCount === 1) {
            announceVerify?.();
            yield* Effect.sleep("100 millis");
          }
          return {
            kind: "verified" as const,
            verifierComponentId: "verifier:verify-cancellation",
            runId: request.runId,
            intentDigest: request.intentDigest,
            actionReceiptDigest: canonicalDigest(request.receipt),
            observedArtifactDigest: request.receipt.artifactDigest,
            reason: "independent test observation matched",
          };
        }),
    };
    const consumer = createSyntheticConsumer({ effect, verifier });
    const controller = new AbortController();
    const pending = consumer.run(input, { signal: controller.signal });

    await firstVerificationStarted;
    controller.abort(new Error("test cancellation during verification"));
    await assert.rejects(pending);
    const recovered = await consumer.recoverAfterCancellation(
      { runId: input.runId },
      { signal: AbortSignal.timeout(2_000) },
    );
    assert.equal(applyCount, 1);
    assert.equal(verifyCount, 2);
    assert.deepEqual(recovered, {
      kind: "settled",
      receipt: {
        kind: "SyntheticRunReceipt",
        schemaVersion: "flrh-langgraphjs-receipt/1",
        profileVersion: input.profileVersion,
        runId: input.runId,
        intentDigest: digestIntent(input.intent),
        terminal: "SUCCEEDED",
        route: [
          "decide",
          "derive_eligibility",
          "stabilize",
          "commit_intent",
          "dispatch",
          "verify",
          "close_terminal",
        ],
        dispatchCount: 1,
        queryCount: 0,
        producerComponentId: effect.componentId,
        verifierComponentId: verifier.componentId,
        externalExactlyOnceClaim: false,
        checkpointIsCompletionProof: false,
      },
    });
  });
});
