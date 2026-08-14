import { createHash } from "node:crypto";

import type {
  EffectIntent,
  EffectObservation,
  SyntheticRunInput,
  VerificationReceipt,
} from "./contracts.js";
import { JsonObjectSchema } from "./contracts.js";

type CanonicalJson =
  | null
  | boolean
  | number
  | string
  | ReadonlyArray<CanonicalJson>
  | { readonly [key: string]: CanonicalJson };

const requireNfc = (value: string): string => {
  if (value.normalize("NFC") !== value) {
    throw new TypeError("canonical JSON requires NFC strings and keys");
  }
  return value;
};

const compareCodeUnits = (left: string, right: string): number => {
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
};

const canonicalize = (value: unknown): CanonicalJson => {
  if (
    value === null ||
    typeof value === "boolean"
  ) {
    return value;
  }
  if (typeof value === "string") return requireNfc(value);
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new TypeError("canonical JSON rejects non-finite numbers");
    }
    return value;
  }
  if (Array.isArray(value)) {
    return value.map(canonicalize);
  }

  const record = JsonObjectSchema.parse(value);
  return Object.fromEntries(
    Object.entries(record)
      .map(
        ([key, item]): readonly [string, unknown] => [requireNfc(key), item],
      )
      .sort(([left], [right]) => compareCodeUnits(left, right))
      .map(([key, item]) => [key, canonicalize(item)]),
  );
};

export const canonicalJson = (value: unknown): string =>
  JSON.stringify(canonicalize(value));

export const canonicalDigest = (value: unknown): string =>
  `sha256:${createHash("sha256").update(canonicalJson(value)).digest("hex")}`;

export const digestIntent = (intent: EffectIntent): string =>
  canonicalDigest(intent);

export type IntentDecision = "accepted" | "conflict";

export const decideIntent = (input: SyntheticRunInput): IntentDecision => {
  const prior = input.priorIntent;
  if (prior === undefined) return "accepted";
  const sharesExternalIdentity =
    prior.intentId === input.intent.intentId ||
    prior.idempotencyKey === input.intent.idempotencyKey;
  if (!sharesExternalIdentity) return "accepted";
  return canonicalJson(prior) === canonicalJson(input.intent)
    ? "accepted"
    : "conflict";
};

export const deriveEligibility = (input: SyntheticRunInput): boolean =>
  input.availableHeadroom >= input.requiredHeadroom;

export type CompletionFacts = Readonly<{
  decision: "pending" | "accepted" | "conflict";
  eligibility: "pending" | "eligible" | "blocked";
  stable: boolean;
  intentCommitted: boolean;
  approvalStatus:
    | "pending"
    | "not_required"
    | "approved"
    | "rejected"
    | "cancelled"
    | "timed_out";
  runId: string;
  intent: EffectIntent;
  intentDigest: string;
  effectObservation: EffectObservation | null;
  verification: VerificationReceipt | null;
  expectedProducerComponentId: string;
  expectedVerifierComponentId: string;
}>;

export const hasExecutionPrerequisites = (
  facts: CompletionFacts,
): boolean =>
  facts.decision === "accepted" &&
  facts.eligibility === "eligible" &&
  facts.stable &&
  facts.intentCommitted &&
  (facts.approvalStatus === "approved" ||
    facts.approvalStatus === "not_required");

export const hasVerifiedCompletion = (facts: CompletionFacts): boolean => {
  if (!hasExecutionPrerequisites(facts)) return false;
  if (facts.effectObservation?.kind !== "confirmed_success") return false;
  if (facts.verification?.kind !== "verified") return false;
  const receipt = facts.effectObservation.receipt;
  return (
    receipt.intentId === facts.intent.intentId &&
    receipt.idempotencyKey === facts.intent.idempotencyKey &&
    receipt.intentDigest === facts.intentDigest &&
    receipt.producerComponentId === facts.expectedProducerComponentId &&
    facts.verification.verifierComponentId ===
      facts.expectedVerifierComponentId &&
    facts.verification.runId === facts.runId &&
    facts.verification.intentDigest === facts.intentDigest &&
    facts.verification.actionReceiptDigest === canonicalDigest(receipt) &&
    facts.verification.observedArtifactDigest === receipt.artifactDigest
  );
};
