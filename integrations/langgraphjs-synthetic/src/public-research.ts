import * as z from "zod";

import { canonicalDigest, canonicalJson } from "./pure.js";

const DigestSchema = z.string().regex(/^sha256:[0-9a-f]{64}$/u);

export const PUBLIC_RESEARCH_SEMANTIC_LABELS = [
  "Claim",
  "Concept",
  "Data",
  "Method",
  "Pattern",
  "Service",
  "Structure",
  "Technology",
  "Theory",
  "Tool",
  "Work",
] as const;

export const REPOSITORY_OWNED_PUBLIC_RESEARCH_MANIFEST_PIN = Object.freeze({
  projectionId: "projection:synthetic-agent-coding-foundations-v1",
  manifestDigest:
    "sha256:290a5c10cfd0fd799923d7e6db05a7faf92d4f8ce5516d4bcae7d5408269f8b2",
} as const);

const PublicResearchSemanticLabelSchema = z.enum(
  PUBLIC_RESEARCH_SEMANTIC_LABELS,
);

const PublicResearchRevisionSchema = z
  .string()
  .min(1)
  .refine((revision) => revision !== "unknown", {
    message: "public research revision must be explicit",
  });

export const PublicResearchSourceSchema = z
  .object({
    sourceId: z.string().min(1),
    uri: z
      .string()
      .url()
      .refine((uri) => uri.startsWith("https://"), {
        message: "public research sources require HTTPS",
      }),
    publisher: z.string().min(1).max(200),
    revision: PublicResearchRevisionSchema,
    disposition: z.enum([
      "original-synthetic",
      "public-reference-summary",
    ]),
  })
  .strict();

const PublicResearchEntryContentSchema = z
  .object({
    evidenceId: z.string().min(1),
    sourceId: z.string().min(1),
    title: z.string().min(1).max(200),
    summary: z.string().min(1).max(4_096),
    semanticLabels: z
      .array(PublicResearchSemanticLabelSchema)
      .min(1)
      .max(4),
    revision: PublicResearchRevisionSchema,
  })
  .strict();

export const PublicResearchEntrySchema =
  PublicResearchEntryContentSchema.extend({
    contentDigest: DigestSchema,
  });

const PublicResearchLimitsSchema = z
  .object({
    maxEntries: z.literal(25),
    maxSummaryUtf8Bytes: z.literal(4_096),
    maxTotalUtf8Bytes: z.literal(65_536),
  })
  .strict();

export const PublicResearchProjectionManifestSchema = z
  .object({
    kind: z.literal("PublicResearchProjectionManifest"),
    schemaVersion: z.literal("public-research-projection-manifest/1"),
    status: z.literal("PROPOSED"),
    projectionId: z.string().min(1),
    scope: z.literal("public-research"),
    policyVersion: z.literal("public-research-admission/1"),
    limits: PublicResearchLimitsSchema,
    sources: z.array(PublicResearchSourceSchema).max(25),
    entries: z.array(PublicResearchEntrySchema).max(25),
  })
  .strict();

export const PublicResearchProjectionSchema = z
  .object({
    kind: z.literal("PublicResearchProjection"),
    schemaVersion: z.literal("public-research-projection/1"),
    status: z.literal("PROPOSED"),
    projectionId: z.string().min(1),
    scope: z.literal("public-research"),
    policyVersion: z.literal("public-research-admission/1"),
    sources: z.array(PublicResearchSourceSchema).max(25),
    entries: z.array(PublicResearchEntrySchema).max(25),
    projectionDigest: DigestSchema,
  })
  .strict();

export const PublicResearchDryRunReceiptSchema = z
  .object({
    kind: z.literal("PublicResearchDryRunReceipt"),
    schemaVersion: z.literal("public-research-dry-run-receipt/1"),
    status: z.literal("PROPOSED"),
    mode: z.literal("offline-dry-run"),
    projectionId: z.string().min(1),
    scope: z.literal("public-research"),
    policyVersion: z.literal("public-research-admission/1"),
    manifestDigest: DigestSchema,
    projectionDigest: DigestSchema,
    inputSourceCount: z.number().int().nonnegative(),
    admittedSourceCount: z.number().int().nonnegative().max(25),
    duplicateSourceCount: z.number().int().nonnegative(),
    inputEntryCount: z.number().int().nonnegative(),
    admittedEntryCount: z.number().int().nonnegative().max(25),
    duplicateEntryCount: z.number().int().nonnegative(),
    rejectedEntryCount: z.literal(0),
    liveNeo4jReadCount: z.literal(0),
    liveNeo4jWriteCount: z.literal(0),
    modelCallCount: z.literal(0),
    modelContextAdmission: z.literal(false),
    completionClaim: z.literal(false),
  })
  .strict();

export type PublicResearchProjectionManifest = z.infer<
  typeof PublicResearchProjectionManifestSchema
>;
type PublicResearchEntryContent = z.infer<
  typeof PublicResearchEntryContentSchema
>;
export type PublicResearchEntry = z.infer<typeof PublicResearchEntrySchema>;
export type PublicResearchProjection = z.infer<
  typeof PublicResearchProjectionSchema
>;
export type PublicResearchDryRunReceipt = z.infer<
  typeof PublicResearchDryRunReceiptSchema
>;

export type PublicResearchAdmissionFailureCode =
  | "INVALID_MANIFEST"
  | "NON_CANONICAL_TEXT"
  | "DUPLICATE_SOURCE_CONFLICT"
  | "DUPLICATE_EVIDENCE_CONFLICT"
  | "ENTRY_DIGEST_MISMATCH"
  | "SOURCE_NOT_FOUND"
  | "REVISION_MISMATCH"
  | "NON_CANONICAL_LABELS"
  | "UNUSED_SOURCE"
  | "BYTE_LIMIT_EXCEEDED"
  | "OWNED_PROJECTION_ID_MISMATCH"
  | "OWNED_MANIFEST_DIGEST_MISMATCH";

export class PublicResearchAdmissionFailure extends Error {
  readonly code: PublicResearchAdmissionFailureCode;

  constructor(code: PublicResearchAdmissionFailureCode, message: string) {
    super(message);
    this.name = "PublicResearchAdmissionFailure";
    this.code = code;
  }
}

const fail = (
  code: PublicResearchAdmissionFailureCode,
  message: string,
): never => {
  throw new PublicResearchAdmissionFailure(code, message);
};

const compareCodeUnits = (left: string, right: string): number => {
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
};

const entryContent = (entry: PublicResearchEntryContent) => ({
  evidenceId: entry.evidenceId,
  sourceId: entry.sourceId,
  title: entry.title,
  summary: entry.summary,
  semanticLabels: entry.semanticLabels,
  revision: entry.revision,
});

export const digestPublicResearchEntry = (
  entry: PublicResearchEntryContent,
): string => canonicalDigest(entryContent(entry));

const decodeManifest = (raw: unknown): PublicResearchProjectionManifest => {
  const decoded = PublicResearchProjectionManifestSchema.safeParse(raw);
  if (!decoded.success) {
    return fail("INVALID_MANIFEST", "public research manifest is invalid");
  }
  try {
    canonicalJson(decoded.data);
  } catch {
    return fail(
      "NON_CANONICAL_TEXT",
      "public research manifest requires NFC canonical text",
    );
  }
  return decoded.data;
};

const normalizeSources = (
  sources: PublicResearchProjectionManifest["sources"],
) => {
  const byId = new Map<string, PublicResearchProjectionManifest["sources"][number]>();
  let duplicateCount = 0;
  for (const source of sources) {
    const prior = byId.get(source.sourceId);
    if (prior === undefined) {
      byId.set(source.sourceId, source);
      continue;
    }
    if (canonicalJson(prior) !== canonicalJson(source)) {
      return fail(
        "DUPLICATE_SOURCE_CONFLICT",
        `source identity changed bytes: ${source.sourceId}`,
      );
    }
    duplicateCount += 1;
  }
  const normalized = [...byId.values()].sort((left, right) =>
    compareCodeUnits(left.sourceId, right.sourceId),
  );
  return { normalized, duplicateCount };
};

const requireCanonicalLabels = (entry: PublicResearchEntry): void => {
  const canonicalLabels = [...new Set(entry.semanticLabels)].sort(
    compareCodeUnits,
  );
  if (canonicalJson(canonicalLabels) !== canonicalJson(entry.semanticLabels)) {
    fail(
      "NON_CANONICAL_LABELS",
      `semantic labels are not unique and sorted: ${entry.evidenceId}`,
    );
  }
};

const normalizeEntries = (
  manifest: PublicResearchProjectionManifest,
  sources: ReadonlyArray<PublicResearchProjectionManifest["sources"][number]>,
) => {
  const sourceById = new Map(sources.map((source) => [source.sourceId, source]));
  const byId = new Map<string, PublicResearchEntry>();
  let duplicateCount = 0;
  for (const entry of manifest.entries) {
    requireCanonicalLabels(entry);
    if (entry.contentDigest !== canonicalDigest(entryContent(entry))) {
      return fail(
        "ENTRY_DIGEST_MISMATCH",
        `entry digest did not match canonical content: ${entry.evidenceId}`,
      );
    }
    const source = sourceById.get(entry.sourceId);
    if (source === undefined) {
      return fail(
        "SOURCE_NOT_FOUND",
        `entry named an undeclared source: ${entry.evidenceId}`,
      );
    }
    if (source.revision !== entry.revision) {
      return fail(
        "REVISION_MISMATCH",
        `entry revision did not match its source: ${entry.evidenceId}`,
      );
    }
    if (
      Buffer.byteLength(entry.summary, "utf8") >
      manifest.limits.maxSummaryUtf8Bytes
    ) {
      return fail(
        "BYTE_LIMIT_EXCEEDED",
        `entry summary exceeded its UTF-8 byte bound: ${entry.evidenceId}`,
      );
    }
    const prior = byId.get(entry.evidenceId);
    if (prior === undefined) {
      byId.set(entry.evidenceId, entry);
      continue;
    }
    if (canonicalJson(prior) !== canonicalJson(entry)) {
      return fail(
        "DUPLICATE_EVIDENCE_CONFLICT",
        `evidence identity changed bytes: ${entry.evidenceId}`,
      );
    }
    duplicateCount += 1;
  }
  const normalized = [...byId.values()].sort((left, right) =>
    compareCodeUnits(left.evidenceId, right.evidenceId),
  );
  return { normalized, duplicateCount };
};

export const compilePublicResearchProjection = (
  rawManifest: unknown,
): Readonly<{
  projection: PublicResearchProjection;
  receipt: PublicResearchDryRunReceipt;
}> => {
  const manifest = decodeManifest(rawManifest);
  const sources = normalizeSources(manifest.sources);
  const entries = normalizeEntries(manifest, sources.normalized);
  const usedSourceIds = new Set(entries.normalized.map((entry) => entry.sourceId));
  const unusedSource = sources.normalized.find(
    (source) => !usedSourceIds.has(source.sourceId),
  );
  if (unusedSource !== undefined) {
    return fail(
      "UNUSED_SOURCE",
      `manifest contains an unused source: ${unusedSource.sourceId}`,
    );
  }
  const projectionPreimage = {
    kind: "PublicResearchProjection" as const,
    schemaVersion: "public-research-projection/1" as const,
    status: "PROPOSED" as const,
    projectionId: manifest.projectionId,
    scope: manifest.scope,
    policyVersion: manifest.policyVersion,
    sources: sources.normalized,
    entries: entries.normalized,
  };
  const projection = PublicResearchProjectionSchema.parse({
    ...projectionPreimage,
    projectionDigest: canonicalDigest(projectionPreimage),
  });
  const totalBytes = Buffer.byteLength(canonicalJson(projection), "utf8");
  if (totalBytes > manifest.limits.maxTotalUtf8Bytes) {
    return fail(
      "BYTE_LIMIT_EXCEEDED",
      "public research projection exceeded its aggregate UTF-8 byte bound",
    );
  }
  const receipt = PublicResearchDryRunReceiptSchema.parse({
    kind: "PublicResearchDryRunReceipt",
    schemaVersion: "public-research-dry-run-receipt/1",
    status: "PROPOSED",
    mode: "offline-dry-run",
    projectionId: manifest.projectionId,
    scope: manifest.scope,
    policyVersion: manifest.policyVersion,
    manifestDigest: canonicalDigest(manifest),
    projectionDigest: projection.projectionDigest,
    inputSourceCount: manifest.sources.length,
    admittedSourceCount: projection.sources.length,
    duplicateSourceCount: sources.duplicateCount,
    inputEntryCount: manifest.entries.length,
    admittedEntryCount: projection.entries.length,
    duplicateEntryCount: entries.duplicateCount,
    rejectedEntryCount: 0,
    liveNeo4jReadCount: 0,
    liveNeo4jWriteCount: 0,
    modelCallCount: 0,
    modelContextAdmission: false,
    completionClaim: false,
  });
  for (const source of projection.sources) Object.freeze(source);
  for (const entry of projection.entries) {
    Object.freeze(entry.semanticLabels);
    Object.freeze(entry);
  }
  Object.freeze(projection.sources);
  Object.freeze(projection.entries);
  Object.freeze(projection);
  Object.freeze(receipt);
  return Object.freeze({ projection, receipt });
};

export const compileRepositoryOwnedPublicResearchProjection = (
  rawManifest: unknown,
): ReturnType<typeof compilePublicResearchProjection> => {
  const compiled = compilePublicResearchProjection(rawManifest);
  if (
    compiled.projection.projectionId !==
    REPOSITORY_OWNED_PUBLIC_RESEARCH_MANIFEST_PIN.projectionId
  ) {
    return fail(
      "OWNED_PROJECTION_ID_MISMATCH",
      "public research projection did not name the repository-owned identity",
    );
  }
  if (
    compiled.receipt.manifestDigest !==
    REPOSITORY_OWNED_PUBLIC_RESEARCH_MANIFEST_PIN.manifestDigest
  ) {
    return fail(
      "OWNED_MANIFEST_DIGEST_MISMATCH",
      "public research manifest digest did not match the repository-owned manifest digest",
    );
  }
  return compiled;
};
