import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { Effect } from "effect";

import {
  AgentPlanSchema,
  AgentCodingFailure,
  KnowledgeResultSchema,
  LocalArtifactEffectPort,
  LocalArtifactVerificationPort,
  canonicalDigest,
  createAgentCodingParadigm,
  createSyntheticConsumer,
  toSyntheticRunInput,
  type AgentCodingInput,
  type KnowledgeGraphPort,
  type KnowledgeQuery,
  type PlanningPort,
  type PlanningRequest,
} from "../src/index.js";

const input: AgentCodingInput = {
  schemaVersion: "agent-coding-input/1",
  runId: "run:agent-coding-1",
  task: "Design a bounded TypeScript implementation plan",
  knowledgeScope: "public-research",
  knowledgeLimit: 4,
  timeoutMs: 2_000,
};

const projectionBinding = {
  projectionId: "projection:synthetic-agent-coding-tests",
  policyVersion: "public-research-admission/1" as const,
  manifestDigest: canonicalDigest({ fixture: "agent-coding-manifest" }),
  projectionDigest: canonicalDigest({ fixture: "agent-coding-projection" }),
  queryTemplateDigest: canonicalDigest({ fixture: "agent-coding-query" }),
};

const evidence = [
  {
    evidenceId: "kg:method:langgraph",
    title: "LangGraph orchestration",
    text: "Use a state graph for bounded orchestration.",
    score: 4.2,
    source: {
      kind: "neo4j" as const,
      database: "neo4j",
      scope: "public-research" as const,
      projectionId: projectionBinding.projectionId,
      labels: ["Method"],
      sourceRef: "https://example.invalid/research/langgraph",
      revision: "2026-08-11",
      contentDigest: canonicalDigest({ fixture: "kg:method:langgraph" }),
    },
  },
];

const knowledgeResult = (query: KnowledgeQuery) =>
  KnowledgeResultSchema.parse({
    kind: "knowledge_result",
    schemaVersion: "agent-coding-knowledge-result/1",
    componentId: "knowledge:neo4j-test",
    queryDigest: canonicalDigest(query),
    projection: projectionBinding,
    evidence,
    evidenceDigest: canonicalDigest(evidence),
    readOnly: true,
  });

const plan = AgentPlanSchema.parse({
  summary: "Build one outer graph with typed ports.",
  steps: [
    {
      stepId: "step:1",
      objective: "Compose the KG and model nodes.",
      evidenceIds: ["kg:method:langgraph"],
      verification: "Run strict typecheck and focused tests.",
    },
  ],
  risks: ["A model response is not completion evidence."],
  evidenceIds: ["kg:method:langgraph"],
});

describe("Agent Coding Paradigm composition", () => {
  it("routes Neo4j evidence through one planner call and emits an approval-bound H intent", async () => {
    let knowledgeCalls = 0;
    let planningCalls = 0;
    const knowledge: KnowledgeGraphPort = {
      componentId: "knowledge:neo4j-test",
      search: (query) =>
        Effect.sync(() => {
          knowledgeCalls += 1;
          return knowledgeResult(query);
        }),
    };
    const planner: PlanningPort = {
      componentId: "planner:langchain-openai-test",
      draft: () =>
        Effect.sync(() => {
          planningCalls += 1;
          return plan;
        }),
    };
    const paradigm = createAgentCodingParadigm({ knowledge, planner });

    const proposal = await paradigm.propose(input, {
      signal: AbortSignal.timeout(5_000),
    });

    assert.equal(knowledgeCalls, 1);
    assert.equal(planningCalls, 1);
    assert.deepEqual(proposal.route, [
      "retrieve_knowledge",
      "draft_plan",
      "emit_proposal",
    ]);
    assert.equal(proposal.status, "PROPOSED");
    assert.equal(proposal.completionClaim, false);
    assert.equal(proposal.promptTokenCeiling, false);
    assert.equal(proposal.knowledge.readOnly, true);
    assert.equal(proposal.planning.modelOutputIsCompletionProof, false);

    const execution = toSyntheticRunInput(proposal, {
      availableHeadroom: 8,
      requiredHeadroom: 4,
      timeoutMs: 5_000,
      approvalDeadlineAt: "2026-08-12T00:00:00Z",
    });
    assert.equal(execution.approval.required, true);
    assert.equal(execution.intent.action, "write_agent_coding_plan");
    assert.equal(
      execution.intent.payload["planDigest"],
      proposal.planning.planDigest,
    );

    const directory = await mkdtemp(join(tmpdir(), "agent-coding-plan-"));
    try {
      const effect = new LocalArtifactEffectPort({
        directory,
        componentId: "effect:agent-coding-plan",
        applyMode: "confirmed_success",
      });
      const verifier = new LocalArtifactVerificationPort({
        directory,
        componentId: "verifier:agent-coding-plan",
      });
      const h = createSyntheticConsumer({
        effect,
        verifier,
        clock: {
          nowEpochMilliseconds: () => Date.parse("2026-08-11T12:00:00Z"),
        },
      });
      const paused = await h.run(execution, {
        signal: AbortSignal.timeout(5_000),
      });
      assert.equal(paused.kind, "interrupted");
      if (paused.kind !== "interrupted") return;
      assert.equal(paused.interrupt.kind, "approval_required");
      assert.equal(effect.applyCount, 0);

      const completed = await h.resumeApproval(
        {
          runId: proposal.runId,
          intentDigest: paused.interrupt.intentDigest,
          approvalNonce: paused.interrupt.approvalNonce,
          decision: "approve",
        },
        { signal: AbortSignal.timeout(5_000) },
      );
      assert.equal(completed.kind, "settled");
      if (completed.kind !== "settled") return;
      assert.equal(completed.receipt.terminal, "SUCCEEDED");
      assert.equal(completed.receipt.dispatchCount, 1);
      assert.equal(completed.receipt.verifierComponentId, verifier.componentId);
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  });

  it("fails closed when a plan cites evidence that was not retrieved", async () => {
    const knowledge: KnowledgeGraphPort = {
      componentId: "knowledge:closed",
      search: (query) =>
        Effect.succeed(
          KnowledgeResultSchema.parse({
            ...knowledgeResult(query),
            componentId: "knowledge:closed",
          }),
        ),
    };
    const planner: PlanningPort = {
      componentId: "planner:closed",
      draft: () =>
        Effect.succeed({
          ...plan,
          evidenceIds: ["kg:not-retrieved"],
        }),
    };

    await assert.rejects(
      createAgentCodingParadigm({ knowledge, planner }).propose(input, {
        signal: AbortSignal.timeout(5_000),
      }),
      (error) =>
        error instanceof AgentCodingFailure &&
        /not retrieved/u.test(error.reason),
    );
  });

  it("rejects duplicate evidence identity with different canonical bytes", async () => {
    const knowledge: KnowledgeGraphPort = {
      componentId: "knowledge:duplicate",
      search: (query) =>
        Effect.succeed(
          KnowledgeResultSchema.parse({
            kind: "knowledge_result",
            schemaVersion: "agent-coding-knowledge-result/1",
            componentId: "knowledge:duplicate",
            queryDigest: canonicalDigest(query),
            projection: projectionBinding,
            evidence: [evidence[0], { ...evidence[0], title: "Different" }],
            evidenceDigest: canonicalDigest([
              evidence[0],
              { ...evidence[0], title: "Different" },
            ]),
            readOnly: true,
          }),
        ),
    };
    let planningCalls = 0;
    const planner: PlanningPort = {
      componentId: "planner:duplicate",
      draft: () =>
        Effect.sync(() => {
          planningCalls += 1;
          return plan;
        }),
    };

    await assert.rejects(
      createAgentCodingParadigm({ knowledge, planner }).propose(input, {
        signal: AbortSignal.timeout(5_000),
      }),
      (error) =>
        error instanceof AgentCodingFailure &&
        /duplicate evidence identity/u.test(error.reason),
    );
    assert.equal(planningCalls, 0);
  });

  it("rejects a knowledge port that changes the query bytes it was given", async () => {
    const knowledge: KnowledgeGraphPort = {
      componentId: "knowledge:query-mutation",
      search: (query) =>
        Effect.sync(() => {
          query.text = "mutated private query";
          return KnowledgeResultSchema.parse({
            ...knowledgeResult(query),
            componentId: "knowledge:query-mutation",
          });
        }),
    };
    const planner: PlanningPort = {
      componentId: "planner:query-mutation",
      draft: () => Effect.succeed(plan),
    };

    await assert.rejects(
      createAgentCodingParadigm({ knowledge, planner }).propose(input, {
        signal: AbortSignal.timeout(5_000),
      }),
      (error) =>
        error instanceof AgentCodingFailure &&
        /not bound to this query/u.test(error.reason),
    );
  });

  it("does not let a planner mutate the request used for its receipt digest", async () => {
    const knowledge: KnowledgeGraphPort = {
      componentId: "knowledge:request-mutation",
      search: (query) =>
        Effect.succeed(
          KnowledgeResultSchema.parse({
            ...knowledgeResult(query),
            componentId: "knowledge:request-mutation",
          }),
        ),
    };
    const planner: PlanningPort = {
      componentId: "planner:request-mutation",
      draft: (request) =>
        Effect.sync(() => {
          request.task = "mutated private task";
          return plan;
        }),
    };
    const proposal = await createAgentCodingParadigm({ knowledge, planner }).propose(
      input,
      { signal: AbortSignal.timeout(5_000) },
    );

    assert.doesNotThrow(() =>
      toSyntheticRunInput(proposal, {
        availableHeadroom: 8,
        requiredHeadroom: 4,
        timeoutMs: 5_000,
        approvalDeadlineAt: "2026-08-12T00:00:00Z",
      }),
    );
  });

  it("propagates cancellation and never starts the planner after a cancelled KG read", async () => {
    let planningCalls = 0;
    const knowledge: KnowledgeGraphPort = {
      componentId: "knowledge:cancel",
      search: () => Effect.never,
    };
    const planner: PlanningPort = {
      componentId: "planner:cancel",
      draft: (_request: PlanningRequest) =>
        Effect.sync(() => {
          planningCalls += 1;
          return plan;
        }),
    };
    const controller = new AbortController();
    const pending = createAgentCodingParadigm({ knowledge, planner }).propose(
      input,
      { signal: controller.signal },
    );

    controller.abort(new Error("cancelled by caller"));
    await assert.rejects(pending);
    assert.equal(planningCalls, 0);
  });

  it("rejects model attempts to inject authority fields into the strict plan", async () => {
    const knowledge: KnowledgeGraphPort = {
      componentId: "knowledge:authority-injection",
      search: (query) => Effect.succeed(knowledgeResult(query)),
    };
    const planner: PlanningPort = {
      componentId: "planner:authority-injection",
      draft: () =>
        Effect.succeed({
          ...plan,
          terminal: "SUCCEEDED",
          verified: true,
          effectIntent: { action: "delete_everything" },
          cypher: "MATCH (n) DETACH DELETE n",
        }),
    };

    await assert.rejects(
      createAgentCodingParadigm({ knowledge, planner }).propose(input, {
        signal: AbortSignal.timeout(5_000),
      }),
    );
  });

  it("replays an exact completed proposal without re-reading KG or recalling the model", async () => {
    let knowledgeCalls = 0;
    let planningCalls = 0;
    const knowledge: KnowledgeGraphPort = {
      componentId: "knowledge:idempotent",
      search: (query) =>
        Effect.sync(() => {
          knowledgeCalls += 1;
          return KnowledgeResultSchema.parse({
            ...knowledgeResult(query),
            componentId: "knowledge:idempotent",
          });
        }),
    };
    const planner: PlanningPort = {
      componentId: "planner:idempotent",
      draft: () =>
        Effect.sync(() => {
          planningCalls += 1;
          return plan;
        }),
    };
    const paradigm = createAgentCodingParadigm({ knowledge, planner });

    const first = await paradigm.propose(input, {
      signal: AbortSignal.timeout(5_000),
    });
    const second = await paradigm.propose(input, {
      signal: AbortSignal.timeout(5_000),
    });

    assert.deepEqual(second, first);
    assert.equal(knowledgeCalls, 1);
    assert.equal(planningCalls, 1);
    assert.deepEqual(Object.keys(paradigm), ["propose"]);
  });

  it("fails fast when the configured cross-run concurrency bound is full", async () => {
    let knowledgeCalls = 0;
    let releaseFirst: (() => void) | undefined;
    const firstGate = new Promise<void>((resolve) => {
      releaseFirst = resolve;
    });
    const knowledge: KnowledgeGraphPort = {
      componentId: "knowledge:bounded-concurrency",
      search: (query) =>
        Effect.gen(function* () {
          knowledgeCalls += 1;
          if (knowledgeCalls === 1) yield* Effect.promise(() => firstGate);
          return KnowledgeResultSchema.parse({
            ...knowledgeResult(query),
            componentId: "knowledge:bounded-concurrency",
          });
        }),
    };
    const planner: PlanningPort = {
      componentId: "planner:bounded-concurrency",
      draft: () => Effect.succeed(plan),
    };
    const boundedOptions = {
      knowledge,
      planner,
      limits: { maxConcurrentRuns: 1, runRecordCapacity: 4 },
    };
    const paradigm = createAgentCodingParadigm(boundedOptions);
    const first = paradigm.propose(input, {
      signal: AbortSignal.timeout(5_000),
    });
    await new Promise<void>((resolve) => setImmediate(resolve));

    try {
      await assert.rejects(
        paradigm.propose(
          { ...input, runId: "run:agent-coding-capacity-2" },
          { signal: AbortSignal.timeout(5_000) },
        ),
        /concurrency capacity/u,
      );
    } finally {
      releaseFirst?.();
      await first;
    }
    assert.equal(knowledgeCalls, 1);
  });

  it("evicts the oldest process-local replay record at the configured bound", async () => {
    let knowledgeCalls = 0;
    const knowledge: KnowledgeGraphPort = {
      componentId: "knowledge:bounded-records",
      search: (query) =>
        Effect.sync(() => {
          knowledgeCalls += 1;
          return KnowledgeResultSchema.parse({
            ...knowledgeResult(query),
            componentId: "knowledge:bounded-records",
          });
        }),
    };
    const planner: PlanningPort = {
      componentId: "planner:bounded-records",
      draft: () => Effect.succeed(plan),
    };
    const boundedOptions = {
      knowledge,
      planner,
      limits: { maxConcurrentRuns: 2, runRecordCapacity: 1 },
    };
    const paradigm = createAgentCodingParadigm(boundedOptions);
    const secondInput = { ...input, runId: "run:agent-coding-record-2" };

    await paradigm.propose(input, { signal: AbortSignal.timeout(5_000) });
    await paradigm.propose(secondInput, { signal: AbortSignal.timeout(5_000) });
    await paradigm.propose(input, { signal: AbortSignal.timeout(5_000) });

    assert.equal(knowledgeCalls, 3);
  });

  it("does not implicitly retry a failed logical run", async () => {
    let knowledgeCalls = 0;
    const knowledge: KnowledgeGraphPort = {
      componentId: "knowledge:failed-run",
      search: () =>
        Effect.sync(() => {
          knowledgeCalls += 1;
          throw new Error("synthetic KG failure");
        }),
    };
    const planner: PlanningPort = {
      componentId: "planner:failed-run",
      draft: () => Effect.succeed(plan),
    };
    const paradigm = createAgentCodingParadigm({ knowledge, planner });

    await assert.rejects(
      paradigm.propose(input, { signal: AbortSignal.timeout(5_000) }),
    );
    await assert.rejects(
      paradigm.propose(input, { signal: AbortSignal.timeout(5_000) }),
      /already attempted/u,
    );
    assert.equal(knowledgeCalls, 1);
  });

  it("rejects different bytes for a completed agent-coding run identity", async () => {
    const knowledge: KnowledgeGraphPort = {
      componentId: "knowledge:identity",
      search: (query) =>
        Effect.succeed(
          KnowledgeResultSchema.parse({
            ...knowledgeResult(query),
            componentId: "knowledge:identity",
          }),
        ),
    };
    const planner: PlanningPort = {
      componentId: "planner:identity",
      draft: () => Effect.succeed(plan),
    };
    const paradigm = createAgentCodingParadigm({ knowledge, planner });
    await paradigm.propose(input, { signal: AbortSignal.timeout(5_000) });

    await assert.rejects(
      paradigm.propose(
        { ...input, task: "Different task bytes" },
        { signal: AbortSignal.timeout(5_000) },
      ),
      /run identity conflict/u,
    );
  });

  it("rejects a proposal whose digest-bound plan bytes were changed", async () => {
    const knowledge: KnowledgeGraphPort = {
      componentId: "knowledge:proposal-binding",
      search: (query) =>
        Effect.succeed(
          KnowledgeResultSchema.parse({
            ...knowledgeResult(query),
            componentId: "knowledge:proposal-binding",
          }),
        ),
    };
    const planner: PlanningPort = {
      componentId: "planner:proposal-binding",
      draft: () => Effect.succeed(plan),
    };
    const proposal = await createAgentCodingParadigm({ knowledge, planner }).propose(
      input,
      { signal: AbortSignal.timeout(5_000) },
    );
    const mutated = {
      ...proposal,
      planning: {
        ...proposal.planning,
        plan: {
          ...proposal.planning.plan,
          summary: "mutated after proposal issuance",
        },
      },
    };

    assert.throws(
      () =>
        toSyntheticRunInput(mutated, {
          availableHeadroom: 8,
          requiredHeadroom: 4,
          timeoutMs: 5_000,
          approvalDeadlineAt: "2026-08-12T00:00:00Z",
        }),
      /proposal binding/u,
    );
  });

  it("does not reuse external effect identity for different intent bytes", async () => {
    const makeParadigm = () => {
      const knowledge: KnowledgeGraphPort = {
        componentId: "knowledge:external-identity",
        search: (query) =>
          Effect.succeed(
            KnowledgeResultSchema.parse({
              ...knowledgeResult(query),
              componentId: "knowledge:external-identity",
            }),
          ),
      };
      const planner: PlanningPort = {
        componentId: "planner:external-identity",
        draft: () => Effect.succeed(plan),
      };
      return createAgentCodingParadigm({ knowledge, planner });
    };
    const first = await makeParadigm().propose(input, {
      signal: AbortSignal.timeout(5_000),
    });
    const second = await makeParadigm().propose(
      { ...input, task: "Different task with the same retrieved evidence and plan" },
      { signal: AbortSignal.timeout(5_000) },
    );

    assert.notEqual(
      first.proposedIntent.intentId,
      second.proposedIntent.intentId,
    );
    assert.notEqual(
      first.proposedIntent.idempotencyKey,
      second.proposedIntent.idempotencyKey,
    );
  });
});
