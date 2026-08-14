import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { Effect } from "effect";
import * as z from "zod";

import {
  LocalArtifactEffectPort,
  LocalArtifactVerificationPort,
  canonicalJson,
  createSyntheticConsumer,
  systemTrustedClock,
  type LocalArtifactApplyMode,
  type SyntheticInvocationResult,
  type SyntheticRunInput,
  type VerificationPort,
} from "./index.js";

const VariantSchema = z.enum([
  "variant:happy-path",
  "variant:insufficient-headroom",
  "variant:unknown-after-dispatch",
  "variant:duplicate-intent-conflict",
  "variant:producer-self-report-only",
  "variant:cancel-while-unknown",
]);

type Variant = z.infer<typeof VariantSchema>;

const readVariant = (args: ReadonlyArray<string>): Variant => {
  const optionIndex = args.indexOf("--variant");
  const value = optionIndex < 0 ? undefined : args[optionIndex + 1];
  return VariantSchema.parse(value);
};

const makeInput = (variant: Variant): SyntheticRunInput => {
  const intent: SyntheticRunInput["intent"] = {
    intentId: "intent:public-synthetic-1",
    idempotencyKey: "idempotency:public-synthetic-1",
    action: "write_synthetic_analysis_artifact",
    payload: {
      marker: "SYNTHETIC",
      privateSourceIncluded: false,
    },
  };
  const base: SyntheticRunInput = {
    schemaVersion: "flrh-langgraphjs-input/1",
    profileVersion: "shared-accelerator-synthetic/1",
    runId: `run:${variant}`,
    availableHeadroom: 8,
    requiredHeadroom: 4,
    timeoutMs: 5_000,
    approval: {
      required: false,
      deadlineAt: "2026-08-11T17:00:00Z",
    },
    intent,
  };
  if (variant === "variant:insufficient-headroom") {
    return { ...base, availableHeadroom: 1 };
  }
  if (variant === "variant:duplicate-intent-conflict") {
    return {
      ...base,
      priorIntent: {
        ...intent,
        payload: {
          marker: "SYNTHETIC",
          privateSourceIncluded: false,
          result: "different",
        },
      },
    };
  }
  return base;
};

const applyModeFor = (variant: Variant): LocalArtifactApplyMode => {
  if (variant === "variant:unknown-after-dispatch") {
    return "unknown_after_write";
  }
  if (variant === "variant:cancel-while-unknown") {
    return "unknown_after_write_unobservable";
  }
  return "confirmed_success";
};

const settleCancellation = async (
  variant: Variant,
  initial: SyntheticInvocationResult,
  consumer: ReturnType<typeof createSyntheticConsumer>,
): Promise<SyntheticInvocationResult> => {
  if (variant !== "variant:cancel-while-unknown") return initial;
  if (
    initial.kind !== "interrupted" ||
    initial.interrupt.kind !== "reconciliation_required"
  ) {
    throw new TypeError("cancel variant did not reach reconciliation");
  }
  return consumer.resumeReconciliation(
    {
      runId: initial.kind === "interrupted" ? initial.interrupt.runId : "",
      decision: { kind: "cancel" },
    },
    { signal: AbortSignal.timeout(10_000) },
  );
};

const main = async (): Promise<void> => {
  const variant = readVariant(process.argv.slice(2));
  const directory = await mkdtemp(join(tmpdir(), "flrh-langgraphjs-smoke-"));
  try {
    const effect = new LocalArtifactEffectPort({
      directory,
      componentId: `effect:${variant}`,
      applyMode: applyModeFor(variant),
    });
    const independentVerifier = new LocalArtifactVerificationPort({
      directory,
      componentId: `verifier:${variant}`,
    });
    const verifier: VerificationPort =
      variant === "variant:producer-self-report-only"
        ? {
            componentId: `verifier:${variant}`,
            verify: () =>
              Effect.succeed({
                kind: "rejected",
                verifierComponentId: `verifier:${variant}`,
                reason: "independent destination evidence was withheld",
              }),
          }
        : independentVerifier;
    const consumer = createSyntheticConsumer({
      effect,
      verifier,
      clock: systemTrustedClock,
    });
    const initial = await consumer.run(makeInput(variant), {
      signal: AbortSignal.timeout(10_000),
    });
    const result = await settleCancellation(variant, initial, consumer);
    if (result.kind !== "settled") {
      throw new TypeError(`variant remained interrupted: ${result.interrupt.kind}`);
    }
    const evidence = {
      kind: "SyntheticLangGraphVariantEvidence",
      epistemicStatus: "PROPOSED",
      variantId: variant,
      receipt: result.receipt,
      effectCounts: {
        apply: effect.applyCount,
        query: effect.queryCount,
        confirmedMutation: effect.confirmedMutationCount,
      },
      evidenceBoundary: {
        publicSyntheticOnly: true,
        productionEvidence: false,
        enginePromotionEvidence: false,
      },
    };
    process.stdout.write(`${canonicalJson(evidence)}\n`);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
};

await main();
