import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { describe, it } from "node:test";

import { Cause, Effect, Exit, Option } from "effect";

import {
  NEO4J_ONTOLOGY_FULLTEXT_QUERY,
  McpNeo4jKnowledgeGraphPort,
  KnowledgeFailure,
  PublicResearchAdmissionFailure,
  PublicResearchProjectionManifestSchema,
  REPOSITORY_OWNED_PUBLIC_RESEARCH_MANIFEST_PIN,
  compileRepositoryOwnedPublicResearchProjection,
  digestPublicResearchEntry,
  type KnowledgeQuery,
} from "../src/index.js";
import { unsafeCreateControlledMcpToolCallerForTest } from "../src/mcp-effect-port.js";

const query: KnowledgeQuery = {
  schemaVersion: "agent-coding-knowledge-query/1",
  runId: "run:kg-1",
  scope: "public-research",
  text: "LangGraph') MATCH (n) DETACH DELETE n //",
  limit: 3,
};

const projectionManifestRaw: unknown = JSON.parse(
  await readFile(
    new URL(
      "../fixtures/public-research/synthetic-foundations.manifest.v1.json",
      import.meta.url,
    ),
    "utf8",
  ),
);
const projectionManifest = PublicResearchProjectionManifestSchema.parse(
  projectionManifestRaw,
);
const admittedProjection =
  compileRepositoryOwnedPublicResearchProjection(projectionManifest);
const langGraphEntry = admittedProjection.projection.entries.find(
  (entry) => entry.evidenceId === "evidence:synthetic:langgraph-role-v1",
);
const langGraphSource = admittedProjection.projection.sources.find(
  (source) => source.sourceId === langGraphEntry?.sourceId,
);
if (langGraphEntry === undefined || langGraphSource === undefined) {
  throw new TypeError("synthetic public-research fixture is incomplete");
}

describe("Neo4j MCP knowledge adapter", () => {
  it("rejects a coherent rewrite of the repository-owned manifest identity", () => {
    const rewritten = structuredClone(projectionManifest);
    const source = rewritten.sources.at(0);
    const entry = rewritten.entries.at(0);
    assert.ok(source !== undefined);
    assert.ok(entry !== undefined);
    source.uri = "https://example.invalid/synthetic/non-public-source";
    entry.title = "Synthetic non-public reference";
    entry.summary = "Synthetic material outside the admitted public projection";
    entry.contentDigest = digestPublicResearchEntry(entry);
    assert.equal(
      rewritten.projectionId,
      REPOSITORY_OWNED_PUBLIC_RESEARCH_MANIFEST_PIN.projectionId,
    );
    const caller = unsafeCreateControlledMcpToolCallerForTest(async () => ({
      content: [{ type: "text" as const, text: "[]" }],
    }));

    assert.throws(
      () =>
        new McpNeo4jKnowledgeGraphPort({
          caller,
          componentId: "knowledge:coherent-private-rewrite",
          database: "neo4j",
          requestTimeoutMs: 1_500,
          projectionManifest: rewritten,
        }),
      (error: unknown) => {
        assert.ok(error instanceof PublicResearchAdmissionFailure);
        assert.equal(error.code, "OWNED_MANIFEST_DIGEST_MISMATCH");
        return true;
      },
    );
  });

  it("uses one explicit scope property without heterogeneous fallback coercion", () => {
    assert.doesNotMatch(
      NEO4J_ONTOLOGY_FULLTEXT_QUERY,
      /toString\(node\.(?:visibilityScope|visibility|scope)\)/u,
    );
    assert.match(
      NEO4J_ONTOLOGY_FULLTEXT_QUERY,
      /node\.visibilityScope = \$scope/u,
    );
    assert.doesNotMatch(
      NEO4J_ONTOLOGY_FULLTEXT_QUERY,
      /node\.(?:visibility|scope) = \$scope/u,
    );
    assert.doesNotMatch(
      NEO4J_ONTOLOGY_FULLTEXT_QUERY,
      /elementId\(node\)|'unknown'|'unnamed knowledge'/u,
    );
  });

  it("requires an explicit named public-research scope marker", () => {
    assert.doesNotMatch(
      NEO4J_ONTOLOGY_FULLTEXT_QUERY,
      /node\.public\s*=\s*true/u,
    );
  });

  it("keeps user text in parameters and executes one fixed read-only Cypher query", async () => {
    let observedParams: unknown;
    let observedOptions: unknown;
    const caller = unsafeCreateControlledMcpToolCallerForTest(
      async (params, options) => {
        observedParams = params;
        observedOptions = options;
        return {
          content: [
            {
              type: "text" as const,
              text: JSON.stringify([
                {
                  database: "neo4j",
                  scope: "public-research",
                  evidenceId: langGraphEntry.evidenceId,
                  title: langGraphEntry.title,
                  text: langGraphEntry.summary,
                  score: 7.5,
                  labels: langGraphEntry.semanticLabels,
                  sourceRef: langGraphSource.uri,
                  revision: langGraphEntry.revision,
                },
              ]),
            },
          ],
        };
      },
    );
    const port = new McpNeo4jKnowledgeGraphPort({
      caller,
      componentId: "knowledge:neo4j-public-research",
      database: "neo4j",
      requestTimeoutMs: 1_500,
      projectionManifest,
    });

    const result = await Effect.runPromise(port.search(query));

    assert.equal(result.evidence.length, 1);
    assert.equal(result.readOnly, true);
    assert.equal(
      result.projection.manifestDigest,
      admittedProjection.receipt.manifestDigest,
    );
    assert.equal(
      result.projection.projectionDigest,
      admittedProjection.projection.projectionDigest,
    );
    const admittedEvidence = result.evidence.at(0);
    assert.ok(admittedEvidence !== undefined);
    assert.equal("nodeRef" in admittedEvidence.source, false);
    assert.equal(
      admittedEvidence.source.contentDigest,
      langGraphEntry.contentDigest,
    );
    assert.deepEqual(observedParams, {
      name: "read_neo4j_cypher",
      arguments: {
        query: NEO4J_ONTOLOGY_FULLTEXT_QUERY,
        params: {
          query: query.text,
          limit: query.limit,
          scanLimit: 30,
          allowedLabels: [
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
          ],
          scope: "public-research",
          evidenceIds: [
            "evidence:synthetic:effect-role-v1",
            "evidence:synthetic:langgraph-role-v1",
          ],
        },
      },
    });
    assert.equal(NEO4J_ONTOLOGY_FULLTEXT_QUERY.includes(query.text), false);
    const callOptions = observedOptions as {
      readonly signal?: unknown;
      readonly timeout?: unknown;
      readonly maxTotalTimeout?: unknown;
      readonly resetTimeoutOnProgress?: unknown;
      readonly allowInputRequired?: unknown;
    };
    assert.ok(callOptions.signal instanceof AbortSignal);
    assert.equal(callOptions.timeout, 1_500);
    assert.equal(callOptions.maxTotalTimeout, 1_500);
    assert.equal(callOptions.resetTimeoutOnProgress, false);
    assert.equal(callOptions.allowInputRequired, false);
  });

  it("fails closed on an MCP error instead of treating text as knowledge", async () => {
    const caller = unsafeCreateControlledMcpToolCallerForTest(async () => ({
      isError: true,
      content: [{ type: "text" as const, text: "looks useful" }],
    }));
    const port = new McpNeo4jKnowledgeGraphPort({
      caller,
      componentId: "knowledge:error",
      database: "neo4j",
      requestTimeoutMs: 1_500,
      projectionManifest,
    });

    const exit = await Effect.runPromiseExit(port.search(query));
    assert.equal(Exit.isFailure(exit), true);
    if (Exit.isSuccess(exit)) return;
    const failure = Option.getOrThrow(Cause.failureOption(exit.cause));
    assert.ok(failure instanceof KnowledgeFailure);
    assert.match(failure.reason, /reported an error/u);
  });

  it("rejects rows carrying a label outside the public ontology allowlist", async () => {
    const caller = unsafeCreateControlledMcpToolCallerForTest(async () => ({
      content: [
        {
          type: "text" as const,
          text: JSON.stringify([
            {
              database: "neo4j",
              scope: "public-research",
              evidenceId: "kg:credential:1",
              title: "Secret-looking node",
              text: "must not enter model context",
              score: 9,
              labels: ["Technology", "Credential"],
              sourceRef: "neo4j:Credential/1",
              revision: "1",
            },
          ]),
        },
      ],
    }));
    const port = new McpNeo4jKnowledgeGraphPort({
      caller,
      componentId: "knowledge:label-boundary",
      database: "neo4j",
      requestTimeoutMs: 1_500,
      projectionManifest,
    });

    const exit = await Effect.runPromiseExit(port.search(query));
    assert.equal(Exit.isFailure(exit), true);
    if (Exit.isSuccess(exit)) return;
    const failure = Option.getOrThrow(Cause.failureOption(exit.cause));
    assert.ok(failure instanceof KnowledgeFailure);
    assert.match(failure.reason, /allowlist/u);
  });

  it("rejects an allowed-label row outside explicit public-research scope", async () => {
    const caller = unsafeCreateControlledMcpToolCallerForTest(async () => ({
      content: [
        {
          type: "text" as const,
          text: JSON.stringify([
            {
              database: "neo4j",
              scope: "private",
              evidenceId: "kg:private:1",
              title: "Unclassified internal node",
              text: "must not enter model context",
              score: 9,
              labels: ["Technology"],
              sourceRef: "neo4j:Technology/private",
              revision: "1",
            },
          ]),
        },
      ],
    }));
    const port = new McpNeo4jKnowledgeGraphPort({
      caller,
      componentId: "knowledge:scope-boundary",
      database: "neo4j",
      requestTimeoutMs: 1_500,
      projectionManifest,
    });

    const exit = await Effect.runPromiseExit(port.search(query));
    assert.equal(Exit.isFailure(exit), true);
    if (Exit.isSuccess(exit)) return;
    const failure = Option.getOrThrow(Cause.failureOption(exit.cause));
    assert.ok(failure instanceof KnowledgeFailure);
    assert.match(failure.reason, /scope/u);
  });

  it("binds provenance to the database reported by the query", async () => {
    const caller = unsafeCreateControlledMcpToolCallerForTest(async () => ({
      content: [
        {
          type: "text" as const,
          text: JSON.stringify([
            {
              database: "other-database",
              scope: "public-research",
              evidenceId: "kg:node:other",
              title: "Wrong database",
              text: "must fail closed",
              score: 2,
              labels: ["Method"],
              sourceRef: "neo4j:Method/other",
              revision: "1",
            },
          ]),
        },
      ],
    }));
    const port = new McpNeo4jKnowledgeGraphPort({
      caller,
      componentId: "knowledge:database-binding",
      database: "neo4j",
      requestTimeoutMs: 1_500,
      projectionManifest,
    });

    const exit = await Effect.runPromiseExit(port.search(query));
    assert.equal(Exit.isFailure(exit), true);
    if (Exit.isSuccess(exit)) return;
    const failure = Option.getOrThrow(Cause.failureOption(exit.cause));
    assert.ok(failure instanceof KnowledgeFailure);
    assert.match(failure.reason, /unexpected database/u);
  });

  it("rejects an unlisted evidence identity even when its row shape is valid", async () => {
    const caller = unsafeCreateControlledMcpToolCallerForTest(async () => ({
      content: [
        {
          type: "text" as const,
          text: JSON.stringify([
            {
              database: "neo4j",
              scope: "public-research",
              evidenceId: "evidence:unlisted",
              title: "Unlisted",
              text: "Shape-valid data is not admission.",
              score: 1,
              labels: ["Concept"],
              sourceRef: "https://example.invalid/research/unlisted",
              revision: "2026-08-12",
            },
          ]),
        },
      ],
    }));
    const port = new McpNeo4jKnowledgeGraphPort({
      caller,
      componentId: "knowledge:unlisted",
      database: "neo4j",
      requestTimeoutMs: 1_500,
      projectionManifest,
    });

    const exit = await Effect.runPromiseExit(port.search(query));
    assert.equal(Exit.isFailure(exit), true);
    if (Exit.isSuccess(exit)) return;
    const failure = Option.getOrThrow(Cause.failureOption(exit.cause));
    assert.ok(failure instanceof KnowledgeFailure);
    assert.match(failure.reason, /not admitted/u);
  });

  it("rejects changed bytes for an admitted evidence identity", async () => {
    const caller = unsafeCreateControlledMcpToolCallerForTest(async () => ({
      content: [
        {
          type: "text" as const,
          text: JSON.stringify([
            {
              database: "neo4j",
              scope: "public-research",
              evidenceId: langGraphEntry.evidenceId,
              title: langGraphEntry.title,
              text: `${langGraphEntry.summary} changed`,
              score: 1,
              labels: langGraphEntry.semanticLabels,
              sourceRef: langGraphSource.uri,
              revision: langGraphEntry.revision,
            },
          ]),
        },
      ],
    }));
    const port = new McpNeo4jKnowledgeGraphPort({
      caller,
      componentId: "knowledge:changed-projection",
      database: "neo4j",
      requestTimeoutMs: 1_500,
      projectionManifest,
    });

    const exit = await Effect.runPromiseExit(port.search(query));
    assert.equal(Exit.isFailure(exit), true);
    if (Exit.isSuccess(exit)) return;
    const failure = Option.getOrThrow(Cause.failureOption(exit.cause));
    assert.ok(failure instanceof KnowledgeFailure);
    assert.match(failure.reason, /changed admitted projection bytes/u);
  });
});
