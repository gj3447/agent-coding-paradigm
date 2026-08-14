import { Data, Effect } from "effect";
import * as z from "zod";

import { EffectIntentSchema, JsonObjectSchema } from "./contracts.js";

const DigestSchema = z.string().regex(/^sha256:[0-9a-f]{64}$/u);

export const KnowledgeQuerySchema = z
  .object({
    schemaVersion: z.literal("agent-coding-knowledge-query/1"),
    runId: z.string().min(1),
    scope: z.literal("public-research"),
    text: z.string().min(1),
    limit: z.number().int().positive().max(25),
  })
  .strict();

export type KnowledgeQuery = z.infer<typeof KnowledgeQuerySchema>;

export const KnowledgeSourceSchema = z
  .object({
    kind: z.literal("neo4j"),
    database: z.string().min(1),
    scope: z.literal("public-research"),
    projectionId: z.string().min(1),
    labels: z.array(z.string().min(1)).min(1),
    sourceRef: z.string().min(1),
    revision: z.string().min(1),
    contentDigest: DigestSchema,
  })
  .strict();

export const KnowledgeEvidenceSchema = z
  .object({
    evidenceId: z.string().min(1),
    title: z.string().min(1),
    text: z.string(),
    score: z.number().finite().nonnegative(),
    source: KnowledgeSourceSchema,
  })
  .strict();

export type KnowledgeEvidence = z.infer<typeof KnowledgeEvidenceSchema>;

export const KnowledgeProjectionBindingSchema = z
  .object({
    projectionId: z.string().min(1),
    policyVersion: z.literal("public-research-admission/1"),
    manifestDigest: DigestSchema,
    projectionDigest: DigestSchema,
    queryTemplateDigest: DigestSchema,
  })
  .strict();

export const KnowledgeResultSchema = z
  .object({
    kind: z.literal("knowledge_result"),
    schemaVersion: z.literal("agent-coding-knowledge-result/1"),
    componentId: z.string().min(1),
    queryDigest: DigestSchema,
    projection: KnowledgeProjectionBindingSchema,
    evidence: z.array(KnowledgeEvidenceSchema).max(25),
    evidenceDigest: DigestSchema,
    readOnly: z.literal(true),
  })
  .strict();

export type KnowledgeResult = z.infer<typeof KnowledgeResultSchema>;

export const AgentPlanStepSchema = z
  .object({
    stepId: z.string().min(1),
    objective: z.string().min(1),
    evidenceIds: z.array(z.string().min(1)).max(25),
    verification: z.string().min(1),
  })
  .strict();

export const AgentPlanSchema = z
  .object({
    summary: z.string().min(1),
    steps: z.array(AgentPlanStepSchema).min(1).max(12),
    risks: z.array(z.string().min(1)).max(12),
    evidenceIds: z.array(z.string().min(1)).max(25),
  })
  .strict();

export type AgentPlan = z.infer<typeof AgentPlanSchema>;

export const PlanningRequestSchema = z
  .object({
    schemaVersion: z.literal("agent-coding-planning-request/1"),
    runId: z.string().min(1),
    task: z.string().min(1),
    knowledge: KnowledgeResultSchema,
  })
  .strict();

export type PlanningRequest = z.infer<typeof PlanningRequestSchema>;

export const PlanningReceiptSchema = z
  .object({
    kind: z.literal("planning_receipt"),
    schemaVersion: z.literal("agent-coding-planning-receipt/1"),
    componentId: z.string().min(1),
    requestDigest: DigestSchema,
    plan: AgentPlanSchema,
    planDigest: DigestSchema,
    structuredOutput: z.literal(true),
    modelOutputIsCompletionProof: z.literal(false),
  })
  .strict();

export type PlanningReceipt = z.infer<typeof PlanningReceiptSchema>;

export const AgentCodingInputSchema = z
  .object({
    schemaVersion: z.literal("agent-coding-input/1"),
    runId: z.string().min(1),
    task: z.string().min(1),
    knowledgeScope: z.literal("public-research"),
    knowledgeLimit: z.number().int().positive().max(25),
    timeoutMs: z.number().int().positive().max(300_000),
  })
  .strict();

export type AgentCodingInput = z.infer<typeof AgentCodingInputSchema>;

export const AgentCodingProposalSchema = z
  .object({
    kind: z.literal("AgentCodingProposal"),
    schemaVersion: z.literal("agent-coding-proposal/1"),
    status: z.literal("PROPOSED"),
    runId: z.string().min(1),
    input: AgentCodingInputSchema,
    inputDigest: DigestSchema,
    route: z.tuple([
      z.literal("retrieve_knowledge"),
      z.literal("draft_plan"),
      z.literal("emit_proposal"),
    ]),
    knowledge: KnowledgeResultSchema,
    planning: PlanningReceiptSchema,
    proposedIntent: EffectIntentSchema,
    proposalDigest: DigestSchema,
    completionClaim: z.literal(false),
    promptTokenCeiling: z.literal(false),
  })
  .strict();

export type AgentCodingProposal = z.infer<typeof AgentCodingProposalSchema>;

export const AgentExecutionOptionsSchema = z
  .object({
    availableHeadroom: z.number().nonnegative(),
    requiredHeadroom: z.number().positive(),
    timeoutMs: z.number().int().positive().max(300_000),
    approvalDeadlineAt: z.iso.datetime({ offset: true }),
  })
  .strict();

export type AgentExecutionOptions = z.infer<
  typeof AgentExecutionOptionsSchema
>;

export class KnowledgeFailure extends Data.TaggedError("KnowledgeFailure")<{
  readonly reason: string;
}> {}

export class PlanningFailure extends Data.TaggedError("PlanningFailure")<{
  readonly reason: string;
}> {}

export class AgentCodingFailure extends Data.TaggedError(
  "AgentCodingFailure",
)<{
  readonly stage: "knowledge" | "planning" | "proposal";
  readonly reason: string;
}> {}

export interface KnowledgeGraphPort {
  readonly componentId: string;
  search(query: KnowledgeQuery): Effect.Effect<unknown, KnowledgeFailure>;
}

export interface PlanningPort {
  readonly componentId: string;
  draft(request: PlanningRequest): Effect.Effect<unknown, PlanningFailure>;
}

export const AgentCodingJsonObjectSchema = JsonObjectSchema;
