import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";

import { Effect } from "effect";
import * as z from "zod";

import {
  ActionReceiptSchema,
  EffectIntentSchema,
  type EffectIntent,
  type EffectObservation,
  type EffectPort,
  PortFailure,
  type VerificationPort,
  type VerificationReceipt,
  type VerificationRequest,
} from "./contracts.js";
import { canonicalDigest, canonicalJson, digestIntent } from "./pure.js";

const ArtifactBodySchema = z
  .object({
    schemaVersion: z.literal("flrh-synthetic-artifact/1"),
    intent: EffectIntentSchema,
    intentDigest: z.string().regex(/^sha256:[0-9a-f]{64}$/u),
  })
  .strict();

const ErrorCodeSchema = z.object({ code: z.string() }).passthrough();

export type LocalArtifactApplyMode =
  | "confirmed_success"
  | "unknown_after_write"
  | "unknown_after_write_unobservable"
  | "unknown_without_write";

export type LocalArtifactEffectOptions = {
  readonly directory: string;
  readonly componentId: string;
  readonly applyMode: LocalArtifactApplyMode;
};

const artifactIdFor = (intent: EffectIntent): string =>
  `artifact:${canonicalDigest(intent.idempotencyKey).slice("sha256:".length)}`;

const artifactPathFor = (directory: string, intent: EffectIntent): string =>
  join(directory, `${artifactIdFor(intent).slice("artifact:".length)}.json`);

const makeArtifactBody = (intent: EffectIntent) =>
  ArtifactBodySchema.parse({
    schemaVersion: "flrh-synthetic-artifact/1",
    intent,
    intentDigest: digestIntent(intent),
  });

const makeReceipt = (
  intent: EffectIntent,
  body: z.infer<typeof ArtifactBodySchema>,
  producerComponentId: string,
) =>
  ActionReceiptSchema.parse({
    kind: "action_receipt",
    intentId: intent.intentId,
    idempotencyKey: intent.idempotencyKey,
    artifactId: artifactIdFor(intent),
    artifactDigest: canonicalDigest(body),
    intentDigest: body.intentDigest,
    producerComponentId,
  });

const readArtifact = async (
  directory: string,
  intent: EffectIntent,
): Promise<z.infer<typeof ArtifactBodySchema> | undefined> => {
  try {
    const bytes = await readFile(artifactPathFor(directory, intent), "utf8");
    return ArtifactBodySchema.parse(JSON.parse(bytes));
  } catch (error: unknown) {
    const parsed = ErrorCodeSchema.safeParse(error);
    if (parsed.success && parsed.data.code === "ENOENT") return undefined;
    throw error;
  }
};

export class LocalArtifactEffectPort implements EffectPort {
  readonly componentId: string;
  readonly #directory: string;
  readonly #applyMode: LocalArtifactApplyMode;
  #applyCount = 0;
  #queryCount = 0;
  #confirmedMutationCount = 0;

  constructor(options: LocalArtifactEffectOptions) {
    this.componentId = z.string().min(1).parse(options.componentId);
    this.#directory = z.string().min(1).parse(options.directory);
    this.#applyMode = options.applyMode;
  }

  get applyCount(): number {
    return this.#applyCount;
  }

  get queryCount(): number {
    return this.#queryCount;
  }

  get confirmedMutationCount(): number {
    return this.#confirmedMutationCount;
  }

  apply(intent: EffectIntent): Effect.Effect<EffectObservation, PortFailure> {
    return Effect.tryPromise({
      try: async (signal) => {
        signal.throwIfAborted();
        this.#applyCount += 1;
        const decodedIntent = EffectIntentSchema.parse(intent);
        if (this.#applyMode === "unknown_without_write") {
          return {
            kind: "unknown",
            reason: "synthetic transport ambiguity",
          };
        }

        const body = makeArtifactBody(decodedIntent);
        await mkdir(this.#directory, { recursive: true });
        signal.throwIfAborted();
        try {
          await writeFile(
            artifactPathFor(this.#directory, decodedIntent),
            canonicalJson(body),
            { encoding: "utf8", flag: "wx" },
          );
          this.#confirmedMutationCount += 1;
        } catch (error: unknown) {
          const parsed = ErrorCodeSchema.safeParse(error);
          if (!parsed.success || parsed.data.code !== "EEXIST") throw error;
          const existing = await readArtifact(this.#directory, decodedIntent);
          if (
            existing === undefined ||
            canonicalJson(existing) !== canonicalJson(body)
          ) {
            return {
              kind: "confirmed_failure",
              reason: "idempotency key already belongs to a different intent",
            };
          }
        }

        if (
          this.#applyMode === "unknown_after_write" ||
          this.#applyMode === "unknown_after_write_unobservable"
        ) {
          return {
            kind: "unknown",
            reason: "artifact committed but acknowledgement was lost",
          };
        }
        return {
          kind: "confirmed_success",
          receipt: makeReceipt(decodedIntent, body, this.componentId),
        };
      },
      catch: () =>
        new PortFailure({
          operation: "apply",
          reason: "local artifact apply failed",
        }),
    });
  }

  query(intent: EffectIntent): Effect.Effect<EffectObservation, PortFailure> {
    return Effect.tryPromise({
      try: async (signal) => {
        signal.throwIfAborted();
        this.#queryCount += 1;
        const decodedIntent = EffectIntentSchema.parse(intent);
        if (this.#applyMode === "unknown_after_write_unobservable") {
          return {
            kind: "unknown",
            reason: "artifact destination is temporarily unobservable",
          };
        }
        const body = await readArtifact(this.#directory, decodedIntent);
        signal.throwIfAborted();
        if (body === undefined) {
          return { kind: "unknown", reason: "artifact is not observable" };
        }
        if (body.intentDigest !== digestIntent(decodedIntent)) {
          return {
            kind: "confirmed_failure",
            reason: "artifact belongs to a different intent",
          };
        }
        return {
          kind: "confirmed_success",
          receipt: makeReceipt(decodedIntent, body, this.componentId),
        };
      },
      catch: () =>
        new PortFailure({
          operation: "query",
          reason: "local artifact query failed",
        }),
    });
  }
}

export type LocalArtifactVerificationOptions = {
  readonly directory: string;
  readonly componentId: string;
};

export class LocalArtifactVerificationPort implements VerificationPort {
  readonly componentId: string;
  readonly #directory: string;

  constructor(options: LocalArtifactVerificationOptions) {
    this.componentId = z.string().min(1).parse(options.componentId);
    this.#directory = z.string().min(1).parse(options.directory);
  }

  verify(
    request: VerificationRequest,
  ): Effect.Effect<VerificationReceipt, PortFailure> {
    return Effect.tryPromise({
      try: async (signal) => {
        signal.throwIfAborted();
        const receipt = ActionReceiptSchema.parse(request.receipt);
        const body = await readArtifact(this.#directory, request.intent);
        signal.throwIfAborted();
        if (body === undefined) {
          return {
            kind: "rejected",
            verifierComponentId: this.componentId,
            reason: "artifact is absent",
          };
        }
        if (
          receipt.intentId !== request.intent.intentId ||
          receipt.idempotencyKey !== request.intent.idempotencyKey ||
          receipt.artifactId !== artifactIdFor(request.intent) ||
          receipt.artifactDigest !== canonicalDigest(body) ||
          receipt.intentDigest !== request.intentDigest ||
          body.intentDigest !== request.intentDigest
        ) {
          return {
            kind: "rejected",
            verifierComponentId: this.componentId,
            reason: "receipt does not match the independently observed artifact",
          };
        }
        return {
          kind: "verified",
          verifierComponentId: this.componentId,
          runId: request.runId,
          intentDigest: request.intentDigest,
          actionReceiptDigest: canonicalDigest(receipt),
          observedArtifactDigest: canonicalDigest(body),
          reason: "independent artifact digest matched",
        };
      },
      catch: () =>
        new PortFailure({
          operation: "verify",
          reason: "local artifact verification failed",
        }),
    });
  }
}
