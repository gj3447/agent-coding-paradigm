import {
  END,
  ReducedValue,
  START,
  StateGraph,
  StateSchema,
} from "@langchain/langgraph";
import { Duration, Effect } from "effect";
import * as z from "zod";

import {
  AgentCodingFailure,
  AgentCodingInputSchema,
  AgentCodingProposalSchema,
  AgentExecutionOptionsSchema,
  AgentPlanSchema,
  KnowledgeFailure,
  KnowledgeQuerySchema,
  KnowledgeResultSchema,
  PlanningFailure,
  PlanningReceiptSchema,
  PlanningRequestSchema,
  type AgentCodingInput,
  type AgentCodingProposal,
  type AgentExecutionOptions,
  type KnowledgeEvidence,
  type KnowledgeGraphPort,
  type PlanningPort,
} from "./agent-coding-contracts.js";
import {
  SyntheticRunInputSchema,
  type SyntheticRunInput,
} from "./contracts.js";
import { canonicalDigest, canonicalJson } from "./pure.js";

const AgentCodingState = new StateSchema({
  input: AgentCodingInputSchema,
  knowledge: KnowledgeResultSchema.nullable().default(null),
  planning: PlanningReceiptSchema.nullable().default(null),
  route: new ReducedValue(z.array(z.string()).default(() => []), {
    inputSchema: z.string(),
    reducer: (current, next) => [...current, next],
  }),
});

type AgentCodingStateValue = typeof AgentCodingState.State;

const AgentCodingStateValueSchema = z
  .object({
    input: AgentCodingInputSchema,
    knowledge: KnowledgeResultSchema.nullable(),
    planning: PlanningReceiptSchema.nullable(),
    route: z.array(z.string()),
  })
  .passthrough();

export type CreateAgentCodingParadigmOptions = {
  readonly knowledge: KnowledgeGraphPort;
  readonly planner: PlanningPort;
  readonly limits?: AgentCodingRuntimeLimits;
};

export type AgentCodingRuntimeLimits = Readonly<{
  readonly maxConcurrentRuns: number;
  readonly runRecordCapacity: number;
}>;

export type AgentCodingRunOptions = {
  readonly signal: AbortSignal;
};

const AgentCodingRuntimeLimitsSchema = z
  .object({
    maxConcurrentRuns: z.number().int().positive().max(64),
    runRecordCapacity: z.number().int().positive().max(4_096),
  })
  .strict();

const DEFAULT_RUNTIME_LIMITS = AgentCodingRuntimeLimitsSchema.parse({
  maxConcurrentRuns: 8,
  runRecordCapacity: 128,
});

const compareCodeUnits = (left: string, right: string): number => {
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
};

const normalizeEvidence = (
  evidence: ReadonlyArray<KnowledgeEvidence>,
): ReadonlyArray<KnowledgeEvidence> => {
  const byIdentity = new Map<string, KnowledgeEvidence>();
  for (const item of evidence) {
    const prior = byIdentity.get(item.evidenceId);
    if (
      prior !== undefined &&
      canonicalJson(prior) !== canonicalJson(item)
    ) {
      throw new AgentCodingFailure({
        stage: "knowledge",
        reason: `duplicate evidence identity changed bytes: ${item.evidenceId}`,
      });
    }
    byIdentity.set(item.evidenceId, item);
  }
  return [...byIdentity.values()].sort((left, right) =>
    compareCodeUnits(left.evidenceId, right.evidenceId),
  );
};

const validateKnowledge = (
  raw: unknown,
  query: z.infer<typeof KnowledgeQuerySchema>,
  componentId: string,
) => {
  const decoded = KnowledgeResultSchema.parse(raw);
  if (decoded.componentId !== componentId) {
    throw new AgentCodingFailure({
      stage: "knowledge",
      reason: "knowledge receipt named an unexpected component",
    });
  }
  if (decoded.queryDigest !== canonicalDigest(query)) {
    throw new AgentCodingFailure({
      stage: "knowledge",
      reason: "knowledge receipt was not bound to this query",
    });
  }
  if (decoded.evidenceDigest !== canonicalDigest(decoded.evidence)) {
    throw new AgentCodingFailure({
      stage: "knowledge",
      reason: "knowledge evidence digest did not match its canonical bytes",
    });
  }
  if (decoded.evidence.length > query.limit) {
    throw new AgentCodingFailure({
      stage: "knowledge",
      reason: "knowledge result exceeded the declared record bound",
    });
  }
  const evidence = normalizeEvidence(decoded.evidence);
  return KnowledgeResultSchema.parse({
    ...decoded,
    evidence,
    evidenceDigest: canonicalDigest(evidence),
  });
};

const validatePlanCitations = (
  rawPlan: unknown,
  evidence: ReadonlyArray<KnowledgeEvidence>,
) => {
  const plan = AgentPlanSchema.parse(rawPlan);
  const available = new Set(evidence.map((item) => item.evidenceId));
  const cited = [
    ...plan.evidenceIds,
    ...plan.steps.flatMap((step) => step.evidenceIds),
  ];
  const missing = cited.find((evidenceId) => !available.has(evidenceId));
  if (missing !== undefined) {
    throw new AgentCodingFailure({
      stage: "planning",
      reason: `plan cited evidence that was not retrieved: ${missing}`,
    });
  }
  return plan;
};

const makeProposedIntent = (
  input: AgentCodingInput,
  knowledgeDigest: string,
  planDigest: string,
  plan: z.infer<typeof AgentPlanSchema>,
) => {
  const action = "write_agent_coding_plan" as const;
  const payload = {
    runId: input.runId,
    task: input.task,
    knowledgeDigest,
    planDigest,
    plan,
  };
  // External effect identity is derived from every action byte it identifies.
  // A shared run/evidence/plan tuple must not alias a different task payload.
  const identityDigest = canonicalDigest({ action, payload });
  return {
    intentId: `intent:agent-coding:${identityDigest.slice("sha256:".length)}`,
    idempotencyKey: `idempotency:agent-coding:${identityDigest.slice("sha256:".length)}`,
    action,
    payload,
  };
};

const makeProposal = (state: AgentCodingStateValue): AgentCodingProposal => {
  if (state.knowledge === null || state.planning === null) {
    throw new AgentCodingFailure({
      stage: "proposal",
      reason: "proposal requires bound knowledge and planning receipts",
    });
  }
  const inputDigest = canonicalDigest(state.input);
  const proposedIntent = makeProposedIntent(
    state.input,
    state.knowledge.evidenceDigest,
    state.planning.planDigest,
    state.planning.plan,
  );
  const preimage = {
    kind: "AgentCodingProposal" as const,
    schemaVersion: "agent-coding-proposal/1" as const,
    status: "PROPOSED" as const,
    runId: state.input.runId,
    input: state.input,
    inputDigest,
    route: [
      "retrieve_knowledge",
      "draft_plan",
      "emit_proposal",
    ] as const,
    knowledge: state.knowledge,
    planning: state.planning,
    proposedIntent,
    completionClaim: false as const,
    promptTokenCeiling: false as const,
  };
  return AgentCodingProposalSchema.parse({
    ...preimage,
    proposalDigest: canonicalDigest(preimage),
  });
};

export const createAgentCodingParadigm = (
  options: CreateAgentCodingParadigmOptions,
) => {
  const limits = AgentCodingRuntimeLimitsSchema.parse(
    options.limits ?? DEFAULT_RUNTIME_LIMITS,
  );
  const knowledgeComponentId = z
    .string()
    .min(1)
    .parse(options.knowledge.componentId);
  const plannerComponentId = z
    .string()
    .min(1)
    .parse(options.planner.componentId);
  if (
    knowledgeComponentId === plannerComponentId ||
    Object.is(options.knowledge, options.planner)
  ) {
    throw new TypeError("knowledge and planning ports must be distinct components");
  }

  const retrieveKnowledge: typeof AgentCodingState.Node = async (
    state,
    config,
  ) => {
    const query = KnowledgeQuerySchema.parse({
      schemaVersion: "agent-coding-knowledge-query/1",
      runId: state.input.runId,
      scope: state.input.knowledgeScope,
      text: state.input.task,
      limit: state.input.knowledgeLimit,
    });
    const queryForPort = KnowledgeQuerySchema.parse(
      JSON.parse(canonicalJson(query)),
    );
    const raw = await Effect.runPromise(
      options.knowledge.search(queryForPort).pipe(
        Effect.timeoutFail({
          duration: Duration.millis(state.input.timeoutMs),
          onTimeout: () =>
            new KnowledgeFailure({
              reason: "knowledge read exceeded its bounded timeout",
            }),
        }),
        Effect.mapError(
          (failure) =>
            new AgentCodingFailure({
              stage: "knowledge",
              reason: failure.reason,
            }),
        ),
      ),
      config?.signal === undefined ? undefined : { signal: config.signal },
    );
    return {
      knowledge: validateKnowledge(raw, query, knowledgeComponentId),
      route: "retrieve_knowledge",
    };
  };

  const draftPlan: typeof AgentCodingState.Node = async (state, config) => {
    if (state.knowledge === null) {
      throw new AgentCodingFailure({
        stage: "planning",
        reason: "planning cannot start before knowledge is committed",
      });
    }
    const request = PlanningRequestSchema.parse({
      schemaVersion: "agent-coding-planning-request/1",
      runId: state.input.runId,
      task: state.input.task,
      knowledge: state.knowledge,
    });
    const requestForPort = PlanningRequestSchema.parse(
      JSON.parse(canonicalJson(request)),
    );
    const rawPlan = await Effect.runPromise(
      options.planner.draft(requestForPort).pipe(
        Effect.timeoutFail({
          duration: Duration.millis(state.input.timeoutMs),
          onTimeout: () =>
            new PlanningFailure({
              reason: "planning call exceeded its bounded timeout",
            }),
        }),
        Effect.mapError(
          (failure) =>
            new AgentCodingFailure({
              stage: "planning",
              reason: failure.reason,
            }),
        ),
      ),
      config?.signal === undefined ? undefined : { signal: config.signal },
    );
    const plan = validatePlanCitations(rawPlan, state.knowledge.evidence);
    return {
      planning: PlanningReceiptSchema.parse({
        kind: "planning_receipt",
        schemaVersion: "agent-coding-planning-receipt/1",
        componentId: plannerComponentId,
        requestDigest: canonicalDigest(request),
        plan,
        planDigest: canonicalDigest(plan),
        structuredOutput: true,
        modelOutputIsCompletionProof: false,
      }),
      route: "draft_plan",
    };
  };

  const emitProposal: typeof AgentCodingState.Node = () => ({
    route: "emit_proposal",
  });

  const graph = new StateGraph(AgentCodingState)
    .addNode("retrieve_knowledge", retrieveKnowledge, {
      retryPolicy: { maxAttempts: 1, jitter: false },
      timeout: 300_000,
    })
    .addNode("draft_plan", draftPlan, {
      retryPolicy: { maxAttempts: 1, jitter: false },
      timeout: 300_000,
    })
    .addNode("emit_proposal", emitProposal)
    .addEdge(START, "retrieve_knowledge")
    .addEdge("retrieve_knowledge", "draft_plan")
    .addEdge("draft_plan", "emit_proposal")
    .addEdge("emit_proposal", END)
    .compile();

  const activeRunIds = new Set<string>();
  const runRecords = new Map<
    string,
    | Readonly<{
        inputJson: string;
        outcome: "completed";
        proposalJson: string;
      }>
    | Readonly<{ inputJson: string; outcome: "failed" }>
  >();

  const rememberRun = (
    runId: string,
    record:
      | Readonly<{
          inputJson: string;
          outcome: "completed";
          proposalJson: string;
        }>
      | Readonly<{ inputJson: string; outcome: "failed" }>,
  ): void => {
    runRecords.delete(runId);
    runRecords.set(runId, record);
    while (runRecords.size > limits.runRecordCapacity) {
      const oldestRunId = runRecords.keys().next().value;
      if (oldestRunId === undefined) break;
      runRecords.delete(oldestRunId);
    }
  };

  const propose = async (
    rawInput: unknown,
    runOptions: AgentCodingRunOptions,
  ): Promise<AgentCodingProposal> => {
    const input = AgentCodingInputSchema.parse(rawInput);
    const inputJson = canonicalJson(input);
    const prior = runRecords.get(input.runId);
    if (prior !== undefined) {
      if (prior.inputJson !== inputJson) {
        throw new TypeError("agent-coding run identity conflict");
      }
      rememberRun(input.runId, prior);
      if (prior.outcome === "failed") {
        throw new TypeError(
          "agent-coding run already attempted; use a new run identity",
        );
      }
      return AgentCodingProposalSchema.parse(JSON.parse(prior.proposalJson));
    }
    if (activeRunIds.has(input.runId)) {
      throw new TypeError("agent-coding run already has an invocation in progress");
    }
    if (activeRunIds.size >= limits.maxConcurrentRuns) {
      throw new TypeError("agent-coding concurrency capacity is full");
    }
    activeRunIds.add(input.runId);
    try {
      const rawState = await graph.invoke(
        { input },
        {
          recursionLimit: 8,
          signal: runOptions.signal,
        },
      );
      const state = AgentCodingStateValueSchema.parse(rawState);
      const proposal = makeProposal(state);
      rememberRun(input.runId, {
        inputJson,
        outcome: "completed",
        proposalJson: canonicalJson(proposal),
      });
      return proposal;
    } catch (error) {
      rememberRun(input.runId, { inputJson, outcome: "failed" });
      throw error;
    } finally {
      activeRunIds.delete(input.runId);
    }
  };

  return Object.freeze({ propose });
};

export const toSyntheticRunInput = (
  rawProposal: unknown,
  rawOptions: AgentExecutionOptions,
): SyntheticRunInput => {
  const proposal = AgentCodingProposalSchema.parse(rawProposal);
  validateProposalBindings(proposal);
  const options = AgentExecutionOptionsSchema.parse(rawOptions);
  return SyntheticRunInputSchema.parse({
    schemaVersion: "flrh-langgraphjs-input/1",
    profileVersion: "shared-accelerator-synthetic/1",
    runId: proposal.runId,
    availableHeadroom: options.availableHeadroom,
    requiredHeadroom: options.requiredHeadroom,
    timeoutMs: options.timeoutMs,
    approval: {
      required: true,
      deadlineAt: options.approvalDeadlineAt,
    },
    intent: proposal.proposedIntent,
  });
};

const validateProposalBindings = (proposal: AgentCodingProposal): void => {
  const query = KnowledgeQuerySchema.parse({
    schemaVersion: "agent-coding-knowledge-query/1",
    runId: proposal.input.runId,
    scope: proposal.input.knowledgeScope,
    text: proposal.input.task,
    limit: proposal.input.knowledgeLimit,
  });
  const request = PlanningRequestSchema.parse({
    schemaVersion: "agent-coding-planning-request/1",
    runId: proposal.input.runId,
    task: proposal.input.task,
    knowledge: proposal.knowledge,
  });
  const expectedIntent = makeProposedIntent(
    proposal.input,
    proposal.knowledge.evidenceDigest,
    proposal.planning.planDigest,
    proposal.planning.plan,
  );
  const preimage = {
    kind: proposal.kind,
    schemaVersion: proposal.schemaVersion,
    status: proposal.status,
    runId: proposal.runId,
    input: proposal.input,
    inputDigest: proposal.inputDigest,
    route: proposal.route,
    knowledge: proposal.knowledge,
    planning: proposal.planning,
    proposedIntent: proposal.proposedIntent,
    completionClaim: proposal.completionClaim,
    promptTokenCeiling: proposal.promptTokenCeiling,
  };
  const citedPlan = validatePlanCitations(
    proposal.planning.plan,
    proposal.knowledge.evidence,
  );
  const valid =
    proposal.runId === proposal.input.runId &&
    proposal.inputDigest === canonicalDigest(proposal.input) &&
    proposal.knowledge.queryDigest === canonicalDigest(query) &&
    proposal.knowledge.evidenceDigest ===
      canonicalDigest(proposal.knowledge.evidence) &&
    proposal.planning.requestDigest === canonicalDigest(request) &&
    proposal.planning.planDigest === canonicalDigest(citedPlan) &&
    canonicalJson(proposal.proposedIntent) === canonicalJson(expectedIntent) &&
    proposal.proposalDigest === canonicalDigest(preimage);
  if (!valid) {
    throw new TypeError("agent-coding proposal binding failed");
  }
};
