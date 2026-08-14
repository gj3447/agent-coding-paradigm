import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { describe, it } from "node:test";

import {
  PublicResearchAdmissionFailure,
  PublicResearchDryRunReceiptSchema,
  PublicResearchProjectionManifestSchema,
  REPOSITORY_OWNED_PUBLIC_RESEARCH_MANIFEST_PIN,
  compilePublicResearchProjection,
  compileRepositoryOwnedPublicResearchProjection,
  digestPublicResearchEntry,
  type PublicResearchAdmissionFailureCode,
  type PublicResearchProjectionManifest,
} from "../src/index.js";

const fixtureUrl = new URL(
  "../fixtures/public-research/synthetic-foundations.manifest.v1.json",
  import.meta.url,
);
const goldenReceiptUrl = new URL(
  "../fixtures/public-research/synthetic-foundations.dry-run.receipt.v1.json",
  import.meta.url,
);

const readManifest = async (): Promise<PublicResearchProjectionManifest> => {
  const raw: unknown = JSON.parse(await readFile(fixtureUrl, "utf8"));
  return PublicResearchProjectionManifestSchema.parse(raw);
};

const expectFailureCode = (
  operation: () => unknown,
  code: PublicResearchAdmissionFailureCode,
): void => {
  assert.throws(operation, (error: unknown) => {
    assert.ok(error instanceof PublicResearchAdmissionFailure);
    assert.equal(error.code, code);
    return true;
  });
};

describe("public-research projection admission", () => {
  it("compiles a deterministic offline receipt without external work", async () => {
    const manifest = await readManifest();
    const first = compileRepositoryOwnedPublicResearchProjection(manifest);
    const second = compileRepositoryOwnedPublicResearchProjection(
      structuredClone(manifest),
    );
    const goldenRaw: unknown = JSON.parse(
      await readFile(goldenReceiptUrl, "utf8"),
    );
    const golden = PublicResearchDryRunReceiptSchema.parse(goldenRaw);

    assert.deepEqual(second, first);
    assert.deepEqual(first.receipt, golden);
    assert.equal(
      first.projection.projectionId,
      REPOSITORY_OWNED_PUBLIC_RESEARCH_MANIFEST_PIN.projectionId,
    );
    assert.equal(
      first.receipt.manifestDigest,
      REPOSITORY_OWNED_PUBLIC_RESEARCH_MANIFEST_PIN.manifestDigest,
    );
    assert.deepEqual(
      first.projection.entries.map((entry) => entry.evidenceId),
      [
        "evidence:synthetic:effect-role-v1",
        "evidence:synthetic:langgraph-role-v1",
      ],
    );
    assert.deepEqual(PublicResearchDryRunReceiptSchema.parse(first.receipt), {
      ...first.receipt,
      status: "PROPOSED",
      mode: "offline-dry-run",
      liveNeo4jReadCount: 0,
      liveNeo4jWriteCount: 0,
      modelCallCount: 0,
      modelContextAdmission: false,
      completionClaim: false,
    });
    assert.equal(Object.isFrozen(first.projection), true);
    assert.equal(Object.isFrozen(first.projection.sources), true);
    assert.equal(Object.isFrozen(first.projection.entries), true);
    assert.equal(Object.isFrozen(first.projection.entries.at(0)), true);
    assert.equal(Object.isFrozen(first.receipt), true);
  });

  it("deduplicates exact identities and records their counts", async () => {
    const manifest = await readManifest();
    const duplicated = structuredClone(manifest);
    const source = duplicated.sources.at(0);
    const entry = duplicated.entries.at(0);
    assert.ok(source !== undefined);
    assert.ok(entry !== undefined);
    duplicated.sources.push(structuredClone(source));
    duplicated.entries.push(structuredClone(entry));

    const { receipt } = compilePublicResearchProjection(duplicated);
    assert.equal(receipt.inputSourceCount, 3);
    assert.equal(receipt.admittedSourceCount, 2);
    assert.equal(receipt.duplicateSourceCount, 1);
    assert.equal(receipt.inputEntryCount, 3);
    assert.equal(receipt.admittedEntryCount, 2);
    assert.equal(receipt.duplicateEntryCount, 1);
  });

  it("rejects duplicate evidence identity with different bytes", async () => {
    const manifest = await readManifest();
    const entry = manifest.entries.at(0);
    assert.ok(entry !== undefined);
    const changedContent = {
      evidenceId: entry.evidenceId,
      sourceId: entry.sourceId,
      title: entry.title,
      summary: `${entry.summary} changed`,
      semanticLabels: entry.semanticLabels,
      revision: entry.revision,
    };
    const conflicting = {
      ...changedContent,
      contentDigest: digestPublicResearchEntry(changedContent),
    };

    expectFailureCode(
      () =>
        compilePublicResearchProjection({
          ...manifest,
          entries: [...manifest.entries, conflicting],
        }),
      "DUPLICATE_EVIDENCE_CONFLICT",
    );
  });

  it("rejects stale digests and undeclared or mismatched sources", async () => {
    const manifest = await readManifest();
    const entry = manifest.entries.at(0);
    assert.ok(entry !== undefined);
    expectFailureCode(
      () =>
        compilePublicResearchProjection({
          ...manifest,
          entries: [{ ...entry, contentDigest: `sha256:${"0".repeat(64)}` }],
          sources: [manifest.sources[0]],
        }),
      "ENTRY_DIGEST_MISMATCH",
    );
    const undeclared = {
      ...entry,
      sourceId: "source:missing",
    };
    expectFailureCode(
      () =>
        compilePublicResearchProjection({
          ...manifest,
          sources: [],
          entries: [
            {
              ...undeclared,
              contentDigest: digestPublicResearchEntry(undeclared),
            },
          ],
        }),
      "SOURCE_NOT_FOUND",
    );
    const wrongRevision = { ...entry, revision: "2026-08-13" };
    expectFailureCode(
      () =>
        compilePublicResearchProjection({
          ...manifest,
          sources: [manifest.sources[0]],
          entries: [
            {
              ...wrongRevision,
              contentDigest: digestPublicResearchEntry(wrongRevision),
            },
          ],
        }),
      "REVISION_MISMATCH",
    );
  });

  it("rejects noncanonical labels and text", async () => {
    const manifest = await readManifest();
    const entry = manifest.entries.at(0);
    assert.ok(entry !== undefined);
    const reversed = {
      ...entry,
      semanticLabels: [...entry.semanticLabels].reverse(),
    };
    expectFailureCode(
      () =>
        compilePublicResearchProjection({
          ...manifest,
          entries: [
            {
              ...reversed,
              contentDigest: digestPublicResearchEntry(reversed),
            },
          ],
          sources: [manifest.sources[0]],
        }),
      "NON_CANONICAL_LABELS",
    );
    const decomposed = {
      ...entry,
      title: "Cafe\u0301",
    };
    expectFailureCode(
      () =>
        compilePublicResearchProjection({
          ...manifest,
          entries: [
            {
              ...decomposed,
              contentDigest: `sha256:${"0".repeat(64)}`,
            },
          ],
          sources: [manifest.sources[0]],
        }),
      "NON_CANONICAL_TEXT",
    );
  });

  it("rejects non-HTTPS, unknown-revision, and out-of-scope manifests", async () => {
    const manifest = await readManifest();
    const source = manifest.sources.at(0);
    assert.ok(source !== undefined);
    expectFailureCode(
      () =>
        compilePublicResearchProjection({
          ...manifest,
          sources: [{ ...source, uri: "http://example.invalid/source" }],
          entries: [],
        }),
      "INVALID_MANIFEST",
    );
    expectFailureCode(
      () =>
        compilePublicResearchProjection({
          ...manifest,
          sources: [{ ...source, revision: "unknown" }],
          entries: [],
        }),
      "INVALID_MANIFEST",
    );
    expectFailureCode(
      () => compilePublicResearchProjection({ ...manifest, scope: "private" }),
      "INVALID_MANIFEST",
    );
  });

  it("rejects unused sources and UTF-8 byte overflow", async () => {
    const manifest = await readManifest();
    expectFailureCode(
      () =>
        compilePublicResearchProjection({
          ...manifest,
          entries: [manifest.entries[0]],
        }),
      "UNUSED_SOURCE",
    );
    const entry = manifest.entries.at(0);
    assert.ok(entry !== undefined);
    const oversized = { ...entry, summary: "한".repeat(4_096) };
    expectFailureCode(
      () =>
        compilePublicResearchProjection({
          ...manifest,
          sources: [manifest.sources[0]],
          entries: [
            {
              ...oversized,
              contentDigest: digestPublicResearchEntry(oversized),
            },
          ],
        }),
      "BYTE_LIMIT_EXCEEDED",
    );
  });

  it("counts source bytes in the aggregate projection bound", async () => {
    const manifest = await readManifest();
    const oversized = structuredClone(manifest);
    const source = oversized.sources.at(0);
    assert.ok(source !== undefined);
    source.uri = `https://example.com/${"a".repeat(70_000)}`;

    expectFailureCode(
      () => compilePublicResearchProjection(oversized),
      "BYTE_LIMIT_EXCEEDED",
    );
  });
});
