import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { Effect } from "effect";

import {
  AgentPlanSchema,
  KnowledgeResultSchema,
  LocalArtifactEffectPort,
  LocalArtifactVerificationPort,
  canonicalDigest,
  createAgentCodingParadigm,
  createSyntheticConsumer,
  systemTrustedClock,
  toSyntheticRunInput,
  type KnowledgeGraphPort,
  type PlanningPort,
} from "./index.js";

const projectionBinding = {
  projectionId: "projection:synthetic-agent-coding-smoke",
  policyVersion: "public-research-admission/1" as const,
  manifestDigest: canonicalDigest({ fixture: "smoke-manifest" }),
  projectionDigest: canonicalDigest({ fixture: "smoke-projection" }),
  queryTemplateDigest: canonicalDigest({ fixture: "smoke-query" }),
};

const knowledge: KnowledgeGraphPort = {
  componentId: "knowledge:synthetic-neo4j-shape",
  search: (query) => {
    const evidence = [
      {
        evidenceId: "kg:synthetic:langgraph",
        title: "Synthetic LangGraph evidence",
        text: "Keep one outer graph and explicit effect boundaries.",
        score: 1,
        source: {
          kind: "neo4j" as const,
          scope: "public-research" as const,
          database: "synthetic",
          projectionId: projectionBinding.projectionId,
          labels: ["Method"],
          sourceRef: "https://example.invalid/research/synthetic-langgraph",
          revision: "fixture/1",
          contentDigest: canonicalDigest({ fixture: "synthetic-langgraph" }),
        },
      },
    ];
    return Effect.succeed(
      KnowledgeResultSchema.parse({
        kind: "knowledge_result",
        schemaVersion: "agent-coding-knowledge-result/1",
        componentId: "knowledge:synthetic-neo4j-shape",
        queryDigest: canonicalDigest(query),
        projection: projectionBinding,
        evidence,
        evidenceDigest: canonicalDigest(evidence),
        readOnly: true,
      }),
    );
  },
};

const planner: PlanningPort = {
  componentId: "planner:synthetic-langchain-openai-shape",
  draft: () =>
    Effect.succeed(
      AgentPlanSchema.parse({
        summary: "Compose a bounded agent-coding slice.",
        steps: [
          {
            stepId: "step:compose",
            objective: "Connect knowledge, planning, H, and verification.",
            evidenceIds: ["kg:synthetic:langgraph"],
            verification: "Run strict TypeScript and the focused test suite.",
          },
        ],
        risks: ["Synthetic adapters are not real platform evidence."],
        evidenceIds: ["kg:synthetic:langgraph"],
      }),
    ),
};

const directory = await mkdtemp(join(tmpdir(), "agent-coding-paradigm-"));
try {
  const proposal = await createAgentCodingParadigm({ knowledge, planner }).propose(
    {
      schemaVersion: "agent-coding-input/1",
      runId: "run:agent-coding-smoke",
      task: "Create the bounded agent-coding paradigm skeleton",
      knowledgeScope: "public-research",
      knowledgeLimit: 4,
      timeoutMs: 5_000,
    },
    { signal: AbortSignal.timeout(10_000) },
  );
  const executionInput = toSyntheticRunInput(proposal, {
    availableHeadroom: 8,
    requiredHeadroom: 4,
    timeoutMs: 5_000,
    approvalDeadlineAt: new Date(
      systemTrustedClock.nowEpochMilliseconds() + 300_000,
    ).toISOString(),
  });
  const effect = new LocalArtifactEffectPort({
    directory,
    componentId: "effect:agent-coding-smoke",
    applyMode: "confirmed_success",
  });
  const verifier = new LocalArtifactVerificationPort({
    directory,
    componentId: "verifier:agent-coding-smoke",
  });
  const h = createSyntheticConsumer({
    effect,
    verifier,
    clock: systemTrustedClock,
  });
  const paused = await h.run(executionInput, {
    signal: AbortSignal.timeout(10_000),
  });
  if (paused.kind !== "interrupted" || paused.interrupt.kind !== "approval_required") {
    throw new Error("agent-coding smoke expected an approval interrupt");
  }
  const completed = await h.resumeApproval(
    {
      runId: proposal.runId,
      intentDigest: paused.interrupt.intentDigest,
      approvalNonce: paused.interrupt.approvalNonce,
      decision: "approve",
    },
    { signal: AbortSignal.timeout(10_000) },
  );
  if (completed.kind !== "settled") {
    throw new Error("agent-coding smoke expected a settled H receipt");
  }
  console.log(
    JSON.stringify({
      kind: "AgentCodingParadigmSyntheticEvidence",
      proposalStatus: proposal.status,
      knowledgeReadOnly: proposal.knowledge.readOnly,
      modelOutputIsCompletionProof:
        proposal.planning.modelOutputIsCompletionProof,
      promptTokenCeiling: proposal.promptTokenCeiling,
      approvalObserved: true,
      terminal: completed.receipt.terminal,
      dispatchCount: completed.receipt.dispatchCount,
      queryCount: completed.receipt.queryCount,
      externalExactlyOnceClaim:
        completed.receipt.externalExactlyOnceClaim,
    }),
  );
} finally {
  await rm(directory, { recursive: true, force: true });
}
