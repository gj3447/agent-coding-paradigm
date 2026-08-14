import { Data, Effect } from "effect";
import * as z from "zod";

export const JsonObjectSchema = z.record(z.string(), z.json());

export const EffectIntentSchema = z
  .object({
    intentId: z.string().min(1),
    idempotencyKey: z.string().min(1),
    action: z.string().min(1),
    payload: JsonObjectSchema,
  })
  .strict();

export type EffectIntent = z.infer<typeof EffectIntentSchema>;

export const ApprovalPolicySchema = z
  .object({
    required: z.boolean(),
    deadlineAt: z.iso.datetime({ offset: true }),
  })
  .strict();

export const SyntheticRunInputSchema = z
  .object({
    schemaVersion: z.literal("flrh-langgraphjs-input/1"),
    profileVersion: z.literal("shared-accelerator-synthetic/1"),
    runId: z.string().min(1),
    availableHeadroom: z.number().nonnegative(),
    requiredHeadroom: z.number().positive(),
    timeoutMs: z.number().int().positive().max(300_000),
    approval: ApprovalPolicySchema,
    intent: EffectIntentSchema,
    priorIntent: EffectIntentSchema.optional(),
  })
  .strict();

export type SyntheticRunInput = z.infer<typeof SyntheticRunInputSchema>;

export const ActionReceiptSchema = z
  .object({
    kind: z.literal("action_receipt"),
    intentId: z.string().min(1),
    idempotencyKey: z.string().min(1),
    artifactId: z.string().min(1),
    artifactDigest: z.string().regex(/^sha256:[0-9a-f]{64}$/u),
    intentDigest: z.string().regex(/^sha256:[0-9a-f]{64}$/u),
    producerComponentId: z.string().min(1),
  })
  .strict();

export type ActionReceipt = z.infer<typeof ActionReceiptSchema>;

const ConfirmedSuccessObservationSchema = z
  .object({
    kind: z.literal("confirmed_success"),
    receipt: ActionReceiptSchema,
  })
  .strict();

const ConfirmedFailureObservationSchema = z
  .object({
    kind: z.literal("confirmed_failure"),
    reason: z.string().min(1),
  })
  .strict();

const UnknownEffectObservationSchema = z
  .object({
    kind: z.literal("unknown"),
    reason: z.string().min(1),
  })
  .strict();

export const EffectObservationSchema = z.discriminatedUnion("kind", [
  ConfirmedSuccessObservationSchema,
  ConfirmedFailureObservationSchema,
  UnknownEffectObservationSchema,
]);

const ResolvedEffectObservationSchema = z.discriminatedUnion("kind", [
  ConfirmedSuccessObservationSchema,
  ConfirmedFailureObservationSchema,
]);

export type EffectObservation = z.infer<typeof EffectObservationSchema>;

export const VerificationReceiptSchema = z.discriminatedUnion("kind", [
  z
    .object({
      kind: z.literal("verified"),
      verifierComponentId: z.string().min(1),
      runId: z.string().min(1),
      intentDigest: z.string().regex(/^sha256:[0-9a-f]{64}$/u),
      actionReceiptDigest: z.string().regex(/^sha256:[0-9a-f]{64}$/u),
      observedArtifactDigest: z.string().regex(/^sha256:[0-9a-f]{64}$/u),
      reason: z.string().min(1),
    })
    .strict(),
  z
    .object({
      kind: z.literal("rejected"),
      verifierComponentId: z.string().min(1),
      reason: z.string().min(1),
    })
    .strict(),
]);

export type VerificationReceipt = z.infer<typeof VerificationReceiptSchema>;

export const TerminalSchema = z.enum([
  "ACTIVE",
  "BLOCKED",
  "CANCELLED",
  "TIMED_OUT",
  "FAILED",
  "SUCCEEDED",
]);

export type SyntheticTerminal = z.infer<typeof TerminalSchema>;

export const SyntheticRunReceiptSchema = z
  .object({
    kind: z.literal("SyntheticRunReceipt"),
    schemaVersion: z.literal("flrh-langgraphjs-receipt/1"),
    profileVersion: z.literal("shared-accelerator-synthetic/1"),
    runId: z.string().min(1),
    intentDigest: z.string().regex(/^sha256:[0-9a-f]{64}$/u),
    terminal: TerminalSchema,
    route: z.array(z.string().min(1)),
    dispatchCount: z.number().int().nonnegative(),
    queryCount: z.number().int().nonnegative(),
    producerComponentId: z.string().min(1),
    verifierComponentId: z.string().min(1).nullable(),
    externalExactlyOnceClaim: z.literal(false),
    checkpointIsCompletionProof: z.literal(false),
  })
  .strict();

export type SyntheticRunReceipt = z.infer<typeof SyntheticRunReceiptSchema>;

export const ApprovalDecisionSchema = z.enum([
  "approve",
  "reject",
  "cancel",
  "timeout",
]);

export type ApprovalDecision = z.infer<typeof ApprovalDecisionSchema>;

export const ApprovalNonceSchema = z
  .string()
  .regex(/^approval:[0-9a-f]{64}$/u);

export const ApprovalResumeInputSchema = z
  .object({
    runId: z.string().min(1),
    intentDigest: z.string().regex(/^sha256:[0-9a-f]{64}$/u),
    approvalNonce: ApprovalNonceSchema,
    decision: ApprovalDecisionSchema,
  })
  .strict();

export type ApprovalResumeInput = z.infer<typeof ApprovalResumeInputSchema>;

export const ReconciliationDecisionSchema = z.discriminatedUnion("kind", [
  z
    .object({
      kind: z.literal("resolved"),
      observation: ResolvedEffectObservationSchema,
    })
    .strict(),
  z.object({ kind: z.literal("cancel") }).strict(),
  z.object({ kind: z.literal("timeout") }).strict(),
]);

export type ReconciliationDecision = z.infer<
  typeof ReconciliationDecisionSchema
>;

export const RuntimeInterruptSchema = z.discriminatedUnion("kind", [
  z
    .object({
      kind: z.literal("approval_required"),
      runId: z.string().min(1),
      intentId: z.string().min(1),
      intentDigest: z.string().regex(/^sha256:[0-9a-f]{64}$/u),
      approvalNonce: ApprovalNonceSchema,
      action: z.string().min(1),
      deadlineAt: z.iso.datetime({ offset: true }),
      allowedDecisions: z.tuple([
        z.literal("approve"),
        z.literal("reject"),
        z.literal("cancel"),
        z.literal("timeout"),
      ]),
    })
    .strict(),
  z
    .object({
      kind: z.literal("reconciliation_required"),
      runId: z.string().min(1),
      intentId: z.string().min(1),
      deadlineAt: z.iso.datetime({ offset: true }),
      allowedDecisions: z.tuple([
        z.literal("resolved"),
        z.literal("cancel"),
        z.literal("timeout"),
      ]),
    })
    .strict(),
]);

export type RuntimeInterrupt = z.infer<typeof RuntimeInterruptSchema>;

export type SyntheticInvocationResult =
  | {
      readonly kind: "interrupted";
      readonly interrupt: RuntimeInterrupt;
    }
  | {
      readonly kind: "settled";
      readonly receipt: SyntheticRunReceipt;
    };

export type PortOperation = "apply" | "query" | "verify";

export class PortFailure extends Data.TaggedError("PortFailure")<{
  readonly operation: PortOperation;
  readonly reason: string;
}> {}

export interface EffectPort {
  readonly componentId: string;
  apply(intent: EffectIntent): Effect.Effect<EffectObservation, PortFailure>;
  query(intent: EffectIntent): Effect.Effect<EffectObservation, PortFailure>;
}

export type VerificationRequest = {
  readonly runId: string;
  readonly intent: EffectIntent;
  readonly intentDigest: string;
  readonly receipt: ActionReceipt;
};

export interface VerificationPort {
  readonly componentId: string;
  verify(
    request: VerificationRequest,
  ): Effect.Effect<unknown, PortFailure>;
}
