import {
  Command,
  END,
  MemorySaver,
  ReducedValue,
  START,
  StateGraph,
  StateSchema,
  interrupt,
  isInterrupted,
} from "@langchain/langgraph";
import { Duration, Effect, Either } from "effect";
import * as z from "zod";

import {
  ApprovalNonceSchema,
  ApprovalResumeInputSchema,
  EffectObservationSchema,
  ReconciliationDecisionSchema,
  RuntimeInterruptSchema,
  SyntheticRunInputSchema,
  SyntheticRunReceiptSchema,
  VerificationReceiptSchema,
  type ApprovalDecision,
  type ApprovalResumeInput,
  type EffectObservation,
  type EffectPort,
  PortFailure,
  type ReconciliationDecision,
  type RuntimeInterrupt,
  type SyntheticInvocationResult,
  type VerificationPort,
  type VerificationReceipt,
} from "./contracts.js";
import {
  canonicalDigest,
  canonicalJson,
  decideIntent,
  deriveEligibility,
  digestIntent,
  hasExecutionPrerequisites,
  hasVerifiedCompletion,
} from "./pure.js";

const DecisionSchema = z.enum(["pending", "accepted", "conflict"]);
const EligibilitySchema = z.enum(["pending", "eligible", "blocked"]);
const ApprovalStatusSchema = z.enum([
  "pending",
  "not_required",
  "approved",
  "rejected",
  "cancelled",
  "timed_out",
]);
const ControlDispositionSchema = z.enum(["none", "cancelled", "timed_out"]);
const TrustedEpochMillisecondsSchema = z
  .number()
  .int()
  .nonnegative()
  .max(8_640_000_000_000_000);

const RuntimeState = new StateSchema({
  input: SyntheticRunInputSchema,
  intentDigest: z.string().default(""),
  decision: DecisionSchema.default("pending"),
  eligibility: EligibilitySchema.default("pending"),
  stable: z.boolean().default(false),
  intentCommitted: z.boolean().default(false),
  approvalNonce: ApprovalNonceSchema.nullable().default(null),
  approvalStatus: ApprovalStatusSchema.default("pending"),
  controlDisposition: ControlDispositionSchema.default("none"),
  effectObservation: EffectObservationSchema.nullable().default(null),
  verification: VerificationReceiptSchema.nullable().default(null),
  route: new ReducedValue(z.array(z.string()).default(() => []), {
    inputSchema: z.string(),
    reducer: (current, next) => [...current, next],
  }),
  dispatchCount: z.number().int().nonnegative().default(0),
  queryCount: z.number().int().nonnegative().default(0),
  terminal: z
    .enum(["ACTIVE", "BLOCKED", "CANCELLED", "TIMED_OUT", "FAILED", "SUCCEEDED"])
    .default("ACTIVE"),
  verifierComponentId: z.string().nullable().default(null),
});

type RuntimeStateValue = typeof RuntimeState.State;

export type CreateSyntheticConsumerOptions = {
  readonly effect: EffectPort;
  readonly verifier: VerificationPort;
  readonly clock: TrustedClock;
  readonly limits?: SyntheticConsumerRuntimeLimits;
};

export type SyntheticConsumerRuntimeLimits = Readonly<{
  readonly maxConcurrentRuns: number;
}>;

const SyntheticConsumerRuntimeLimitsSchema = z
  .object({
    maxConcurrentRuns: z.number().int().positive().max(64),
  })
  .strict();

const DEFAULT_SYNTHETIC_CONSUMER_RUNTIME_LIMITS =
  SyntheticConsumerRuntimeLimitsSchema.parse({ maxConcurrentRuns: 8 });

export interface TrustedClock {
  nowEpochMilliseconds(): number;
}

export const systemTrustedClock: TrustedClock = Object.freeze({
  nowEpochMilliseconds: () => Date.now(),
});

export type RunOptions = {
  readonly signal: AbortSignal;
};

export type ResumeOptions = {
  readonly signal: AbortSignal;
};

export type ResumeApprovalInput = ApprovalResumeInput;

export type ResumeReconciliationInput = {
  readonly runId: string;
  readonly decision: ReconciliationDecision;
};

export type RecoverAfterCancellationInput = {
  readonly runId: string;
};

const runPortEffect = <A>(
  operation: "apply" | "query" | "verify",
  program: Effect.Effect<A, PortFailure>,
  timeoutMs: number,
  signal: AbortSignal | undefined,
): Promise<Either.Either<A, PortFailure>> =>
  Effect.runPromise(
    program.pipe(
      Effect.timeoutFail({
        duration: Duration.millis(timeoutMs),
        onTimeout: () =>
          new PortFailure({
            operation,
            reason: `${operation} exceeded its bounded timeout`,
          }),
      }),
      Effect.either,
    ),
    signal === undefined ? undefined : { signal },
  );

const unknownFromError = (operation: string): EffectObservation => ({
  kind: "unknown",
  reason: `${operation} failed without a confirmed destination outcome`,
});

const bindEffectObservation = (
  observation: EffectObservation,
  intent: RuntimeStateValue["input"]["intent"],
  producerComponentId: string,
): EffectObservation => {
  if (observation.kind !== "confirmed_success") return observation;
  if (
    observation.receipt.intentId !== intent.intentId ||
    observation.receipt.idempotencyKey !== intent.idempotencyKey ||
    observation.receipt.intentDigest !== digestIntent(intent) ||
    observation.receipt.producerComponentId !== producerComponentId
  ) {
    return unknownFromError("receipt binding");
  }
  return observation;
};

const rejectedVerification = (
  verifierComponentId: string,
  reason: string,
): VerificationReceipt => ({
  kind: "rejected",
  verifierComponentId,
  reason,
});

const terminalFor = (
  state: RuntimeStateValue,
  effectComponentId: string,
  verifierComponentId: string,
): RuntimeStateValue["terminal"] => {
  if (state.decision === "conflict") return "ACTIVE";
  if (state.eligibility === "blocked") return "BLOCKED";
  if (state.controlDisposition === "cancelled") return "CANCELLED";
  if (state.controlDisposition === "timed_out") return "TIMED_OUT";
  if (state.approvalStatus === "rejected" || state.approvalStatus === "cancelled") {
    return "CANCELLED";
  }
  if (state.approvalStatus === "timed_out") return "TIMED_OUT";
  const completionFacts = {
    decision: state.decision,
    eligibility: state.eligibility,
    stable: state.stable,
    intentCommitted: state.intentCommitted,
    approvalStatus: state.approvalStatus,
    runId: state.input.runId,
    intent: state.input.intent,
    intentDigest: state.intentDigest,
    effectObservation: state.effectObservation,
    verification: state.verification,
    expectedProducerComponentId: effectComponentId,
    expectedVerifierComponentId: verifierComponentId,
  };
  if (!hasExecutionPrerequisites(completionFacts)) return "ACTIVE";
  if (state.effectObservation?.kind === "confirmed_failure") return "FAILED";
  if (hasVerifiedCompletion(completionFacts)) {
    return "SUCCEEDED";
  }
  return "ACTIVE";
};

const makeConfig = (options: { readonly threadId: string; readonly signal: AbortSignal }) => ({
  configurable: { thread_id: options.threadId },
  recursionLimit: 24,
  signal: options.signal,
});

const threadIdForRun = (runId: string): string =>
  `flrh-run:${canonicalDigest({ runId }).slice("sha256:".length)}`;

const approvalNonceFor = (input: {
  readonly runId: string;
  readonly intentDigest: string;
  readonly deadlineAt: string;
}): string =>
  `approval:${canonicalDigest({
    schemaVersion: "approval-nonce/1",
    runId: input.runId,
    intentDigest: input.intentDigest,
    deadlineAt: input.deadlineAt,
  }).slice("sha256:".length)}`;

const approvalDeadlineExpired = (
  nowEpochMilliseconds: number,
  deadlineAt: string,
): boolean => nowEpochMilliseconds >= Date.parse(deadlineAt);

export const createSyntheticConsumer = (
  options: CreateSyntheticConsumerOptions,
) => {
  const limits = SyntheticConsumerRuntimeLimitsSchema.parse(
    options.limits ?? DEFAULT_SYNTHETIC_CONSUMER_RUNTIME_LIMITS,
  );
  const effectComponentId = z.string().min(1).parse(options.effect.componentId);
  const verifierComponentId = z
    .string()
    .min(1)
    .parse(options.verifier.componentId);
  if (
    Object.is(options.effect, options.verifier) ||
    effectComponentId === verifierComponentId
  ) {
    throw new TypeError(
      "effect producer and completion verifier must be independent components",
    );
  }
  if (typeof options.clock?.nowEpochMilliseconds !== "function") {
    throw new TypeError("a trusted clock must be explicitly injected");
  }
  const readTrustedClock = (): number =>
    TrustedEpochMillisecondsSchema.parse(
      options.clock.nowEpochMilliseconds(),
    );

  const decide: typeof RuntimeState.Node = (state) => ({
    intentDigest: digestIntent(state.input.intent),
    decision: decideIntent(state.input),
    route: "decide",
  });

  const derive: typeof RuntimeState.Node = (state) => ({
    eligibility: deriveEligibility(state.input) ? "eligible" : "blocked",
    route: "derive_eligibility",
  });

  const stabilize: typeof RuntimeState.Node = () => ({
    stable: true,
    route: "stabilize",
  });

  const commitIntent: typeof RuntimeState.Node = (state) => ({
    intentCommitted: true,
    approvalNonce: state.input.approval.required
      ? approvalNonceFor({
          runId: state.input.runId,
          intentDigest: state.intentDigest,
          deadlineAt: state.input.approval.deadlineAt,
        })
      : null,
    route: "commit_intent",
  });

  const approval: typeof RuntimeState.Node = (state) => {
    if (!state.input.approval.required) {
      return { approvalStatus: "not_required" };
    }
    if (state.approvalNonce === null) {
      throw new TypeError("approval nonce was not committed");
    }
    const response = interrupt<RuntimeInterrupt, unknown>({
      kind: "approval_required",
      runId: state.input.runId,
      intentId: state.input.intent.intentId,
      intentDigest: state.intentDigest,
      approvalNonce: state.approvalNonce,
      action: state.input.intent.action,
      deadlineAt: state.input.approval.deadlineAt,
      allowedDecisions: ["approve", "reject", "cancel", "timeout"],
    });
    const decoded = ApprovalResumeInputSchema.parse(response);
    if (
      decoded.runId !== state.input.runId ||
      decoded.intentDigest !== state.intentDigest ||
      decoded.approvalNonce !== state.approvalNonce
    ) {
      throw new TypeError("approval binding mismatch");
    }
    const decision: ApprovalDecision = approvalDeadlineExpired(
      readTrustedClock(),
      state.input.approval.deadlineAt,
    )
      ? "timeout"
      : decoded.decision;
    const approvalStatus: Readonly<
      Record<ApprovalDecision, RuntimeStateValue["approvalStatus"]>
    > = {
      approve: "approved",
      reject: "rejected",
      cancel: "cancelled",
      timeout: "timed_out",
    };
    return { approvalStatus: approvalStatus[decision], route: "approval" };
  };

  const dispatch: typeof RuntimeState.Node = async (state, config) => {
    if (
      state.input.approval.required &&
      approvalDeadlineExpired(
        readTrustedClock(),
        state.input.approval.deadlineAt,
      )
    ) {
      return {
        approvalStatus: "timed_out",
        route: "approval_expired_before_dispatch",
      };
    }
    const outcome = await runPortEffect(
      "apply",
      options.effect.apply(state.input.intent),
      state.input.timeoutMs,
      config?.signal,
    );
    const decoded = Either.isRight(outcome)
      ? EffectObservationSchema.safeParse(outcome.right)
      : undefined;
    const observation =
      decoded?.success === true
        ? bindEffectObservation(
            decoded.data,
            state.input.intent,
            effectComponentId,
          )
        : unknownFromError("dispatch");
    return {
      effectObservation: observation,
      dispatchCount: state.dispatchCount + 1,
      route: "dispatch",
    };
  };

  const reconcile: typeof RuntimeState.Node = async (state, config) => {
    const outcome = await runPortEffect(
      "query",
      options.effect.query(state.input.intent),
      state.input.timeoutMs,
      config?.signal,
    );
    const decoded = Either.isRight(outcome)
      ? EffectObservationSchema.safeParse(outcome.right)
      : undefined;
    const observation =
      decoded?.success === true
        ? bindEffectObservation(
            decoded.data,
            state.input.intent,
            effectComponentId,
          )
        : unknownFromError("reconciliation query");
    return {
      effectObservation: observation,
      queryCount: state.queryCount + 1,
      route: "reconcile",
    };
  };

  const humanReconciliation: typeof RuntimeState.Node = (state) => {
    const response = interrupt<RuntimeInterrupt, unknown>({
      kind: "reconciliation_required",
      runId: state.input.runId,
      intentId: state.input.intent.intentId,
      deadlineAt: state.input.approval.deadlineAt,
      allowedDecisions: ["resolved", "cancel", "timeout"],
    });
    const decision = ReconciliationDecisionSchema.parse(response);
    if (decision.kind === "cancel") {
      return {
        controlDisposition: "cancelled",
        route: "human_reconciliation",
      };
    }
    if (decision.kind === "timeout") {
      return {
        controlDisposition: "timed_out",
        route: "human_reconciliation",
      };
    }
    const observation = bindEffectObservation(
      decision.observation,
      state.input.intent,
      effectComponentId,
    );
    if (observation.kind === "unknown") {
      throw new TypeError("resolved reconciliation receipt binding failed");
    }
    return {
      effectObservation: observation,
      route: "human_reconciliation",
    };
  };

  const verify: typeof RuntimeState.Node = async (state, config) => {
    if (state.effectObservation?.kind !== "confirmed_success") {
      return {
        verification: rejectedVerification(
          verifierComponentId,
          "no confirmed action receipt was available",
        ),
        verifierComponentId,
        route: "verify",
      };
    }
    const outcome = await runPortEffect(
      "verify",
      options.verifier.verify(
          {
            runId: state.input.runId,
            intent: state.input.intent,
            intentDigest: state.intentDigest,
            receipt: state.effectObservation.receipt,
          },
      ),
      state.input.timeoutMs,
      config?.signal,
    );
    const decoded = Either.isRight(outcome)
      ? VerificationReceiptSchema.safeParse(outcome.right)
      : undefined;
    let verification: VerificationReceipt =
      decoded?.success === true
        ? decoded.data
        : rejectedVerification(
            verifierComponentId,
            "independent verification failed closed",
          );
    if (verification.verifierComponentId !== verifierComponentId) {
      verification = rejectedVerification(
        verifierComponentId,
        "verification receipt named an unexpected component",
      );
    }
    if (
      verification.kind === "verified" &&
      (verification.runId !== state.input.runId ||
        verification.intentDigest !== state.intentDigest ||
        verification.actionReceiptDigest !==
          canonicalDigest(state.effectObservation.receipt) ||
        verification.observedArtifactDigest !==
          state.effectObservation.receipt.artifactDigest)
    ) {
      verification = rejectedVerification(
        verifierComponentId,
        "verification receipt was not bound to this run and action receipt",
      );
    }
    return { verification, verifierComponentId, route: "verify" };
  };

  const closeTerminal: typeof RuntimeState.Node = (state) => ({
    terminal: terminalFor(state, effectComponentId, verifierComponentId),
    route: "close_terminal",
  });

  const builder = new StateGraph(RuntimeState)
    .addNode("decide", decide)
    .addNode("derive_eligibility", derive)
    .addNode("stabilize", stabilize)
    .addNode("commit_intent", commitIntent)
    .addNode("approval", approval)
    .addNode("dispatch", dispatch, {
      retryPolicy: { maxAttempts: 1, jitter: false },
      timeout: 300_000,
    })
    .addNode("reconcile", reconcile, {
      retryPolicy: { maxAttempts: 1, jitter: false },
      timeout: 300_000,
    })
    .addNode("human_reconciliation", humanReconciliation)
    .addNode("verify", verify, {
      retryPolicy: { maxAttempts: 1, jitter: false },
      timeout: 300_000,
    })
    .addNode("close_terminal", closeTerminal)
    .addEdge(START, "decide")
    .addConditionalEdges("decide", (state) =>
      state.decision === "conflict" ? "close_terminal" : "derive_eligibility",
    )
    .addConditionalEdges("derive_eligibility", (state) =>
      state.eligibility === "blocked" ? "close_terminal" : "stabilize",
    )
    .addEdge("stabilize", "commit_intent")
    .addEdge("commit_intent", "approval")
    .addConditionalEdges("approval", (state) =>
      state.approvalStatus === "approved" ||
      state.approvalStatus === "not_required"
        ? "dispatch"
        : "close_terminal",
    )
    .addConditionalEdges("dispatch", (state) => {
      if (state.effectObservation?.kind === "unknown") return "reconcile";
      if (state.effectObservation?.kind === "confirmed_success") return "verify";
      return "close_terminal";
    })
    .addConditionalEdges("reconcile", (state) => {
      if (state.effectObservation?.kind === "unknown") {
        return "human_reconciliation";
      }
      if (state.effectObservation?.kind === "confirmed_success") return "verify";
      return "close_terminal";
    })
    .addConditionalEdges("human_reconciliation", (state) => {
      if (
        state.controlDisposition === "cancelled" ||
        state.controlDisposition === "timed_out"
      ) {
        return "close_terminal";
      }
      return state.effectObservation?.kind === "confirmed_success"
        ? "verify"
        : "close_terminal";
    })
    .addEdge("verify", "close_terminal")
    .addEdge("close_terminal", END);

  const graph = builder.compile({ checkpointer: new MemorySaver() });
  const activeThreadIds = new Set<string>();
  let activeInvocationCount = 0;

  const withThreadLease = async <A>(
    rawThreadId: string,
    operation: (threadId: string) => Promise<A>,
  ): Promise<A> => {
    const threadId = z.string().min(1).parse(rawThreadId);
    if (activeThreadIds.has(threadId)) {
      throw new TypeError("thread already has an invocation in progress");
    }
    if (activeInvocationCount >= limits.maxConcurrentRuns) {
      throw new TypeError("H runtime concurrency capacity is full");
    }
    activeThreadIds.add(threadId);
    activeInvocationCount += 1;
    try {
      return await operation(threadId);
    } finally {
      activeThreadIds.delete(threadId);
      activeInvocationCount -= 1;
    }
  };

  const toResult = (raw: RuntimeStateValue | unknown): SyntheticInvocationResult => {
    if (isInterrupted<unknown>(raw)) {
      const first = raw.__interrupt__.at(0);
      if (first === undefined) {
        throw new TypeError("LangGraph reported an empty interrupt set");
      }
      return {
        kind: "interrupted",
        interrupt: RuntimeInterruptSchema.parse(first.value),
      };
    }
    const state = RuntimeStateValueSchema.parse(raw);
    return {
      kind: "settled",
      receipt: SyntheticRunReceiptSchema.parse({
        kind: "SyntheticRunReceipt",
        schemaVersion: "flrh-langgraphjs-receipt/1",
        profileVersion: state.input.profileVersion,
        runId: state.input.runId,
        intentDigest: state.intentDigest,
        terminal: state.terminal,
        route: state.route,
        dispatchCount: state.dispatchCount,
        queryCount: state.queryCount,
        producerComponentId: effectComponentId,
        verifierComponentId: state.verifierComponentId,
        externalExactlyOnceClaim: false,
        checkpointIsCompletionProof: false,
      }),
    };
  };

  const run = async (
    input: unknown,
    runOptions: RunOptions,
  ): Promise<SyntheticInvocationResult> => {
    const decoded = SyntheticRunInputSchema.parse(input);
    return withThreadLease(threadIdForRun(decoded.runId), async (threadId) => {
      const config = makeConfig({ threadId, signal: runOptions.signal });
      const snapshot = await graph.getState(config);
      const existing = RuntimeStateValueSchema.safeParse(snapshot.values);
      if (existing.success) {
        if (canonicalJson(existing.data.input) !== canonicalJson(decoded)) {
          throw new TypeError(
            "run identity conflict: existing input bytes differ",
          );
        }
        if (snapshot.next.length === 0) {
          return toResult(existing.data);
        }
        throw new TypeError(
          "run already has an active checkpoint; use the typed resume API",
        );
      }
      const raw = await graph.invoke(
        { input: decoded },
        config,
      );
      return toResult(raw);
    });
  };

  const requireInterrupt = async (
    threadId: string,
    signal: AbortSignal,
    expectedKind: RuntimeInterrupt["kind"],
  ): Promise<RuntimeInterrupt> => {
    const snapshot = await graph.getState(makeConfig({ threadId, signal }));
    const state = RuntimeStateValueSchema.safeParse(snapshot.values);
    const decodedInterrupts: Array<RuntimeInterrupt> = [];
    for (const task of snapshot.tasks) {
      for (const item of task.interrupts) {
        const decoded = RuntimeInterruptSchema.safeParse(item.value);
        if (decoded.success) decodedInterrupts.push(decoded.data);
      }
    }
    const current = decodedInterrupts.length === 1
      ? decodedInterrupts.at(0)
      : undefined;
    if (
      !state.success ||
      current?.kind !== expectedKind ||
      current.runId !== state.data.input.runId ||
      current.intentId !== state.data.input.intent.intentId
    ) {
      throw new TypeError(`thread is not paused for ${expectedKind}`);
    }
    const interruptMatchesState = current.kind === "approval_required"
      ? current.intentDigest === state.data.intentDigest &&
        current.approvalNonce === state.data.approvalNonce &&
        current.action === state.data.input.intent.action &&
        current.deadlineAt === state.data.input.approval.deadlineAt
      : current.deadlineAt === state.data.input.approval.deadlineAt;
    if (!interruptMatchesState) {
      throw new TypeError(`thread is not paused for ${expectedKind}`);
    }
    return current;
  };

  const resumeApproval = async (
    input: ResumeApprovalInput,
    resumeOptions: ResumeOptions,
  ): Promise<SyntheticInvocationResult> => {
    const decoded = ApprovalResumeInputSchema.parse(input);
    return withThreadLease(threadIdForRun(decoded.runId), async (threadId) => {
      const current = await requireInterrupt(
        threadId,
        resumeOptions.signal,
        "approval_required",
      );
      if (current.kind !== "approval_required") {
        throw new TypeError("thread is not paused for approval_required");
      }
      if (
        decoded.intentDigest !== current.intentDigest ||
        decoded.approvalNonce !== current.approvalNonce
      ) {
        throw new TypeError("approval binding mismatch");
      }
      const resumeInput: ApprovalResumeInput = approvalDeadlineExpired(
        readTrustedClock(),
        current.deadlineAt,
      )
        ? { ...decoded, decision: "timeout" }
        : decoded;
      const raw = await graph.invoke(
        new Command({ resume: resumeInput }),
        makeConfig({ threadId, signal: resumeOptions.signal }),
      );
      return toResult(raw);
    });
  };

  const resumeReconciliation = async (
    input: ResumeReconciliationInput,
    resumeOptions: ResumeOptions,
  ): Promise<SyntheticInvocationResult> => {
    const decision = ReconciliationDecisionSchema.parse(input.decision);
    const runId = z.string().min(1).parse(input.runId);
    return withThreadLease(threadIdForRun(runId), async (threadId) => {
      const config = makeConfig({ threadId, signal: resumeOptions.signal });
      await requireInterrupt(
        threadId,
        resumeOptions.signal,
        "reconciliation_required",
      );
      if (decision.kind === "resolved") {
        const snapshot = await graph.getState(config);
        const state = RuntimeStateValueSchema.parse(snapshot.values);
        const bound = bindEffectObservation(
          decision.observation,
          state.input.intent,
          effectComponentId,
        );
        if (bound.kind === "unknown") {
          throw new TypeError("resolved reconciliation receipt binding failed");
        }
      }
      const raw = await graph.invoke(
        new Command({ resume: decision }),
        config,
      );
      return toResult(raw);
    });
  };

  const recoverAfterCancellation = async (
    input: RecoverAfterCancellationInput,
    resumeOptions: ResumeOptions,
  ): Promise<SyntheticInvocationResult> => {
    const runId = z.string().min(1).parse(input.runId);
    return withThreadLease(threadIdForRun(runId), async (threadId) => {
      const config = makeConfig({ threadId, signal: resumeOptions.signal });
      const snapshot = await graph.getState(config);
      const state = RuntimeStateValueSchema.safeParse(snapshot.values);
      const decodedInterrupts: Array<RuntimeInterrupt> = [];
      for (const task of snapshot.tasks) {
        for (const item of task.interrupts) {
          const decoded = RuntimeInterruptSchema.safeParse(item.value);
          if (decoded.success) decodedInterrupts.push(decoded.data);
        }
      }
      const currentInterrupt = decodedInterrupts.length === 1
        ? decodedInterrupts.at(0)
        : undefined;
      if (
        state.success &&
        currentInterrupt?.kind === "reconciliation_required" &&
        currentInterrupt.runId === runId &&
        currentInterrupt.intentId === state.data.input.intent.intentId
      ) {
        return { kind: "interrupted", interrupt: currentInterrupt };
      }
      const commonRecoveryState =
        state.success &&
        state.data.input.runId === runId &&
        state.data.intentCommitted &&
        decodedInterrupts.length === 0;
      const unrecordedDispatch =
        commonRecoveryState &&
        state.data.effectObservation === null &&
        state.data.dispatchCount === 0 &&
        snapshot.next.length === 1 &&
        snapshot.next.at(0) === "dispatch";
      const pendingReadOnlyQuery =
        commonRecoveryState &&
        state.data.effectObservation?.kind === "unknown" &&
        state.data.dispatchCount === 1 &&
        snapshot.next.length === 1 &&
        snapshot.next.at(0) === "reconcile";
      const pendingReadOnlyVerification =
        commonRecoveryState &&
        state.data.effectObservation?.kind === "confirmed_success" &&
        state.data.dispatchCount === 1 &&
        state.data.verification === null &&
        snapshot.next.length === 1 &&
        snapshot.next.at(0) === "verify";
      if (
        !unrecordedDispatch &&
        !pendingReadOnlyQuery &&
        !pendingReadOnlyVerification
      ) {
        throw new TypeError(
          "run is not at a recoverable cancellation boundary",
        );
      }
      if (unrecordedDispatch) {
        await graph.updateState(
          config,
          {
            effectObservation: unknownFromError("cancelled dispatch"),
            dispatchCount: 1,
            route: "dispatch_outcome_unknown",
          },
          "dispatch",
        );
      }
      const raw = await graph.invoke(null, config);
      return toResult(raw);
    });
  };

  return Object.freeze({
    run,
    resumeApproval,
    resumeReconciliation,
    recoverAfterCancellation,
  });
};

const RuntimeStateValueSchema = z
  .object({
    input: SyntheticRunInputSchema,
    intentDigest: z.string(),
    decision: DecisionSchema,
    eligibility: EligibilitySchema,
    stable: z.boolean(),
    intentCommitted: z.boolean(),
    approvalNonce: ApprovalNonceSchema.nullable(),
    approvalStatus: ApprovalStatusSchema,
    controlDisposition: ControlDispositionSchema,
    effectObservation: EffectObservationSchema.nullable(),
    verification: VerificationReceiptSchema.nullable(),
    route: z.array(z.string()),
    dispatchCount: z.number().int().nonnegative(),
    queryCount: z.number().int().nonnegative(),
    terminal: z.enum([
      "ACTIVE",
      "BLOCKED",
      "CANCELLED",
      "TIMED_OUT",
      "FAILED",
      "SUCCEEDED",
    ]),
    verifierComponentId: z.string().nullable(),
  })
  .passthrough();
