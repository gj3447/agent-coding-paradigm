import { Effect } from "effect";
import * as z from "zod";

import {
  KnowledgeEvidenceSchema,
  KnowledgeFailure,
  KnowledgeQuerySchema,
  KnowledgeResultSchema,
  type KnowledgeGraphPort,
  type KnowledgeQuery,
  type KnowledgeResult,
} from "./agent-coding-contracts.js";
import {
  requireControlledMcpToolCaller,
  type ControlledMcpToolCaller,
} from "./mcp-effect-port.js";
import { canonicalDigest, canonicalJson } from "./pure.js";
import {
  PUBLIC_RESEARCH_SEMANTIC_LABELS,
  compileRepositoryOwnedPublicResearchProjection,
  type PublicResearchProjection,
} from "./public-research.js";

const allowedLabelSet = new Set<string>(PUBLIC_RESEARCH_SEMANTIC_LABELS);

export const NEO4J_ONTOLOGY_FULLTEXT_QUERY = `
CALL db.info() YIELD name
WITH name AS database
CALL db.index.fulltext.queryNodes('ontology_fulltext', $query, {limit: $scanLimit})
YIELD node, score
WITH database, node, score,
  [label IN labels(node) WHERE label IN $allowedLabels] AS semanticLabels
WHERE size(semanticLabels) > 0
  AND node.visibilityScope = $scope
  AND node.evidenceId IN $evidenceIds
WITH database, node, score, semanticLabels
ORDER BY score DESC, node.evidenceId ASC
LIMIT $limit
RETURN
  database AS database,
  $scope AS scope,
  node.evidenceId AS evidenceId,
  node.publicResearchTitle AS title,
  node.publicResearchSummary AS text,
  score AS score,
  semanticLabels AS labels,
  node.sourceRef AS sourceRef,
  node.revision AS revision
`.trim();

const Neo4jRowSchema = z
  .object({
    database: z.string().min(1),
    scope: z.string().min(1),
    evidenceId: z.string().min(1),
    title: z.string().min(1),
    text: z.string(),
    score: z.number().finite().nonnegative(),
    labels: z.array(z.string().min(1)).min(1),
    sourceRef: z.string().min(1),
    revision: z.string().min(1),
  })
  .strict();

const McpTextResultSchema = z
  .object({
    isError: z.boolean().optional(),
    content: z
      .array(
        z
          .object({
            type: z.literal("text"),
            text: z.string(),
          })
          .passthrough(),
      )
      .length(1),
  })
  .passthrough();

export type McpNeo4jKnowledgeGraphPortOptions = {
  readonly caller: ControlledMcpToolCaller;
  readonly componentId: string;
  readonly database: string;
  readonly requestTimeoutMs: number;
  readonly projectionManifest: unknown;
};

const compareCodeUnits = (left: string, right: string): number => {
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
};

const decodeRows = (raw: unknown) => {
  const result = McpTextResultSchema.parse(raw);
  if (result.isError === true) {
    throw new KnowledgeFailure({
      reason: "Neo4j MCP read tool reported an error",
    });
  }
  const text = result.content[0]?.text;
  if (text === undefined) {
    throw new KnowledgeFailure({
      reason: "Neo4j MCP read tool returned no text result",
    });
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new KnowledgeFailure({
      reason: "Neo4j MCP read tool returned non-JSON text",
    });
  }
  return z.array(Neo4jRowSchema).max(25).parse(parsed);
};

export class McpNeo4jKnowledgeGraphPort implements KnowledgeGraphPort {
  readonly componentId: string;
  readonly #caller: ControlledMcpToolCaller;
  readonly #database: string;
  readonly #requestTimeoutMs: number;
  readonly #projection: PublicResearchProjection;
  readonly #manifestDigest: string;

  constructor(rawOptions: McpNeo4jKnowledgeGraphPortOptions) {
    const options = z
      .object({
        componentId: z.string().min(1),
        database: z.string().min(1),
        requestTimeoutMs: z.number().int().positive().max(300_000),
      })
      .strict()
      .parse({
        componentId: rawOptions.componentId,
        database: rawOptions.database,
        requestTimeoutMs: rawOptions.requestTimeoutMs,
      });
    this.componentId = options.componentId;
    this.#caller = requireControlledMcpToolCaller(rawOptions.caller);
    this.#database = options.database;
    this.#requestTimeoutMs = options.requestTimeoutMs;
    const admitted = compileRepositoryOwnedPublicResearchProjection(
      rawOptions.projectionManifest,
    );
    this.#projection = admitted.projection;
    this.#manifestDigest = admitted.receipt.manifestDigest;
  }

  search(
    rawQuery: KnowledgeQuery,
  ): Effect.Effect<KnowledgeResult, KnowledgeFailure> {
    return Effect.try({
      try: () => KnowledgeQuerySchema.parse(rawQuery),
      catch: () =>
        new KnowledgeFailure({
          reason: "knowledge query failed schema validation",
        }),
    }).pipe(
      Effect.flatMap((query) =>
        Effect.tryPromise({
          try: (signal) =>
            this.#caller.callTool(
              {
                name: "read_neo4j_cypher",
                arguments: {
                  query: NEO4J_ONTOLOGY_FULLTEXT_QUERY,
                  params: {
                    query: query.text,
                    limit: query.limit,
                    scanLimit: Math.min(query.limit * 10, 250),
                    allowedLabels: [...PUBLIC_RESEARCH_SEMANTIC_LABELS],
                    scope: query.scope,
                    evidenceIds: this.#projection.entries.map(
                      (entry) => entry.evidenceId,
                    ),
                  },
                },
              },
              {
                signal,
                timeout: this.#requestTimeoutMs,
                maxTotalTimeout: this.#requestTimeoutMs,
                resetTimeoutOnProgress: false,
                allowInputRequired: false,
              },
            ),
          catch: () =>
            new KnowledgeFailure({
              reason: "Neo4j MCP read failed",
            }),
        }).pipe(
          Effect.flatMap((raw) =>
            Effect.try({
              try: () => decodeRows(raw),
              catch: (error) =>
                error instanceof KnowledgeFailure
                  ? error
                  : new KnowledgeFailure({
                      reason: "Neo4j MCP rows failed strict validation",
                    }),
            }),
          ),
          Effect.flatMap((rows) =>
            Effect.try({
              try: () => {
                if (rows.length > query.limit) {
                  throw new KnowledgeFailure({
                    reason: "Neo4j MCP result exceeded the requested limit",
                  });
                }
                const evidence = rows.map((row) => {
                  if (row.database !== this.#database) {
                    throw new KnowledgeFailure({
                      reason: "Neo4j MCP result named an unexpected database",
                    });
                  }
                  if (row.scope !== query.scope) {
                    throw new KnowledgeFailure({
                      reason: "Neo4j MCP result escaped the requested knowledge scope",
                    });
                  }
                  if (!row.labels.every((label) => allowedLabelSet.has(label))) {
                    throw new KnowledgeFailure({
                      reason: "Neo4j MCP result escaped the public label allowlist",
                    });
                  }
                  const entry = this.#projection.entries.find(
                    (candidate) => candidate.evidenceId === row.evidenceId,
                  );
                  if (entry === undefined) {
                    throw new KnowledgeFailure({
                      reason: "Neo4j MCP evidence was not admitted by the projection",
                    });
                  }
                  const source = this.#projection.sources.find(
                    (candidate) => candidate.sourceId === entry.sourceId,
                  );
                  if (source === undefined) {
                    throw new KnowledgeFailure({
                      reason: "Neo4j MCP evidence lost its admitted source",
                    });
                  }
                  const normalizedLabels = [...new Set(row.labels)].sort(
                    compareCodeUnits,
                  );
                  if (
                    row.title !== entry.title ||
                    row.text !== entry.summary ||
                    row.sourceRef !== source.uri ||
                    row.revision !== entry.revision ||
                    canonicalJson(normalizedLabels) !==
                      canonicalJson(entry.semanticLabels)
                  ) {
                    throw new KnowledgeFailure({
                      reason: "Neo4j MCP evidence changed admitted projection bytes",
                    });
                  }
                  return KnowledgeEvidenceSchema.parse({
                    evidenceId: row.evidenceId,
                    title: row.title,
                    text: row.text,
                    score: row.score,
                    source: {
                      kind: "neo4j",
                      database: row.database,
                      scope: query.scope,
                      projectionId: this.#projection.projectionId,
                      labels: entry.semanticLabels,
                      sourceRef: row.sourceRef,
                      revision: row.revision,
                      contentDigest: entry.contentDigest,
                    },
                  });
                });
                return KnowledgeResultSchema.parse({
                  kind: "knowledge_result",
                  schemaVersion: "agent-coding-knowledge-result/1",
                  componentId: this.componentId,
                  queryDigest: canonicalDigest(query),
                  projection: {
                    projectionId: this.#projection.projectionId,
                    policyVersion: this.#projection.policyVersion,
                    manifestDigest: this.#manifestDigest,
                    projectionDigest: this.#projection.projectionDigest,
                    queryTemplateDigest: canonicalDigest(
                      NEO4J_ONTOLOGY_FULLTEXT_QUERY,
                    ),
                  },
                  evidence,
                  evidenceDigest: canonicalDigest(evidence),
                  readOnly: true,
                });
              },
              catch: (error) =>
                error instanceof KnowledgeFailure
                  ? error
                  : new KnowledgeFailure({
                      reason: "Neo4j MCP evidence failed normalization",
                    }),
            }),
          ),
        ),
      ),
    );
  }
}
