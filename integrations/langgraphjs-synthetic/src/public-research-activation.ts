import * as z from "zod";

import { canonicalDigest, canonicalJson } from "./pure.js";
import {
  compileRepositoryOwnedPublicResearchProjection,
  type PublicResearchProjection,
} from "./public-research.js";

const DigestSchema = z.string().regex(/^sha256:[0-9a-f]{64}$/u);
const EvidenceIdSchema = z.string().min(1);
const MAX_ACTIVATION_ENTRIES = 2 as const;
const PHYSICAL_LABELS = ["Concept"] as const;
const UID_TRIGGER_PROFILE_ID = "neo4j-concept-uid-envelope/v1" as const;
export const REPOSITORY_OWNED_PUBLIC_RESEARCH_ACTIVATION_PLAN_PIN =
  Object.freeze({
    projectionId: "projection:synthetic-agent-coding-foundations-v1",
    manifestDigest:
      "sha256:290a5c10cfd0fd799923d7e6db05a7faf92d4f8ce5516d4bcae7d5408269f8b2",
    projectionDigest:
      "sha256:03fc00a7d233d726859da3474c8d7149d60f78c4492ab7acb579e34dd5951c90",
    planDigest:
      "sha256:272177a97351479096ce13e5ff7469b90b49f83ac3b26ce09fd992682dfa45dd",
  } as const);

export const NEO4J_PUBLIC_RESEARCH_CONSTRAINT_QUERY = `
SHOW CONSTRAINTS
YIELD name, type, entityType, labelsOrTypes, properties, ownedIndex
WHERE type = 'NODE_PROPERTY_UNIQUENESS'
  AND entityType = 'NODE'
  AND labelsOrTypes = ['Concept']
  AND properties = ['evidenceId']
RETURN name, type, entityType, labelsOrTypes, properties, ownedIndex
LIMIT 2
`.trim();

export const NEO4J_PUBLIC_RESEARCH_INDEX_QUERY = `
SHOW INDEXES
YIELD name, type, entityType, labelsOrTypes, properties, state, owningConstraint
WHERE type = 'RANGE'
  AND entityType = 'NODE'
  AND labelsOrTypes = ['Concept']
  AND properties = ['evidenceId']
  AND state = 'ONLINE'
  AND owningConstraint IS NOT NULL
RETURN name, type, entityType, labelsOrTypes, properties, state, owningConstraint
LIMIT 2
`.trim();

export const NEO4J_PUBLIC_RESEARCH_UID_TRIGGER_QUERY = `
CALL apoc.trigger.list()
YIELD name, query, selector, installed, paused
WHERE name = 't_uid_forward_gate_v3'
WITH collect({
  query: query,
  phase: selector.phase,
  installed: installed,
  paused: paused
})[..2] AS candidates
RETURN '${UID_TRIGGER_PROFILE_ID}' AS profileId,
  size([candidate IN candidates WHERE candidate.installed = true
    AND candidate.paused = false
    AND candidate.phase = 'afterAsync'
    AND candidate.query CONTAINS 'UNWIND $createdNodes AS n'
    AND candidate.query CONTAINS 'n.uid IS NULL'
    AND candidate.query CONTAINS 'apoc.coll.sort(labels(n))[0]'
    AND candidate.query CONTAINS "n.uid_scheme = 'v1'"
    AND candidate.query CONTAINS "n.uid_source = 'forward-gate-v3'"
  ]) AS matchingTriggerCount
`.trim();

export const NEO4J_PUBLIC_RESEARCH_APPLY_QUERY = `
UNWIND $rows AS row
CALL (row) {
  OPTIONAL MATCH (uidOwner {uid: row.uid})
  RETURN collect(uidOwner)[..2] AS uidMatches
}
OPTIONAL MATCH (existing {evidenceId: row.evidenceId})
WITH row, uidMatches, existing, COUNT { (existing)--() } AS relationshipCount
WITH row, uidMatches,
  [match IN collect({node: existing, relationshipCount: relationshipCount})
    WHERE match.node IS NOT NULL][..2] AS matches
WITH collect({
  row: row,
  matches: matches,
  uidConflict: size(uidMatches) > 1
    OR (size(uidMatches) = 1 AND
      (size(matches) = 0 OR uidMatches[0] <> matches[0].node)),
  exact: size(matches) = 1
    AND size(uidMatches) = 1
    AND uidMatches[0] = matches[0].node
    AND size(labels(matches[0].node)) = size($physicalLabels)
    AND all(label IN labels(matches[0].node) WHERE label IN $physicalLabels)
    AND properties(matches[0].node) = row
    AND matches[0].relationshipCount = 0
}) AS inspected
WITH inspected,
  size([item IN inspected WHERE item.uidConflict OR size(item.matches) > 1
    OR (size(item.matches) = 1 AND NOT item.exact)]) AS conflictCount
FOREACH (item IN CASE WHEN conflictCount = 0 THEN inspected ELSE [] END |
  FOREACH (_ IN CASE WHEN size(item.matches) = 0 THEN [1] ELSE [] END |
    MERGE (node:Concept {
      evidenceId: item.row.evidenceId
    })
    ON CREATE SET node = item.row,
      node.uid = null,
      node.uid_scheme = null,
      node.uid_source = null
  )
)
RETURN conflictCount,
  CASE WHEN conflictCount = 0
    THEN size([item IN inspected WHERE size(item.matches) = 0]) ELSE 0 END
    AS createdCount,
  CASE WHEN conflictCount = 0
    THEN size([item IN inspected WHERE size(item.matches) = 1]) ELSE 0 END
    AS unchangedCount,
  size(inspected) AS observedEntryCount,
  CASE WHEN conflictCount = 0
    THEN [item IN inspected WHERE size(item.matches) = 0 | item.row.evidenceId]
    ELSE [] END AS createdEvidenceIds
LIMIT 3
`.trim();

export const NEO4J_PUBLIC_RESEARCH_READBACK_QUERY = `
UNWIND $evidenceIds AS evidenceId
OPTIONAL MATCH (node {evidenceId: evidenceId})
WITH evidenceId, collect(node)[..3] AS matches
UNWIND matches AS node
RETURN
  node.evidenceId AS evidenceId,
  node.projectionId AS projectionId,
  node.visibilityScope AS visibilityScope,
  node.publicResearchTitle AS publicResearchTitle,
  node.publicResearchSummary AS publicResearchSummary,
  node.name AS name,
  node.description AS description,
  node.uid AS uid,
  node.uid_scheme AS uid_scheme,
  node.uid_source AS uid_source,
  node.sourceRef AS sourceRef,
  node.revision AS revision,
  node.semanticLabels AS semanticLabels,
  node.contentDigest AS contentDigest,
  node.policyVersion AS policyVersion,
  node.manifestDigest AS manifestDigest,
  node.projectionDigest AS projectionDigest,
  properties(node) AS observedProperties,
  [label IN $physicalLabels WHERE label IN labels(node)] AS physicalLabels,
  size(labels(node)) AS physicalLabelCount,
  COUNT { (node)--() } AS relationshipCount
ORDER BY evidenceId
LIMIT 3
`.trim();

export const NEO4J_PUBLIC_RESEARCH_ROLLBACK_QUERY = `
UNWIND $createdRows AS row
OPTIONAL MATCH (node {evidenceId: row.evidenceId})
WITH row, node, COUNT { (node)--() } AS relationshipCount
WITH row,
  [match IN collect({node: node, relationshipCount: relationshipCount})
    WHERE match.node IS NOT NULL][..2] AS matches
WITH collect({
  row: row,
  matches: matches,
  exact: size(matches) = 1
    AND size(labels(matches[0].node)) = size($physicalLabels)
    AND all(label IN labels(matches[0].node) WHERE label IN $physicalLabels)
    AND properties(matches[0].node) = row
    AND matches[0].relationshipCount = 0
}) AS inspected
WITH inspected,
  size([item IN inspected WHERE NOT item.exact]) AS blockedCount
FOREACH (ownedNode IN CASE WHEN blockedCount = 0
  THEN [item IN inspected | item.matches[0].node] ELSE [] END |
  DELETE ownedNode
)
RETURN blockedCount,
  CASE WHEN blockedCount = 0 THEN size(inspected) ELSE 0 END AS deletedCount
LIMIT 3
`.trim();

const ActivationRowSchema = z
  .object({
    evidenceId: EvidenceIdSchema,
    projectionId: z.string().min(1),
    visibilityScope: z.literal("public-research"),
    publicResearchTitle: z.string().min(1).max(200),
    publicResearchSummary: z.string().min(1).max(4_096),
    name: z.string().min(1).max(200),
    description: z.string().min(1).max(4_096),
    uid: z.string().min(1).max(200),
    uid_scheme: z.literal("v1"),
    uid_source: z.literal("forward-gate-v3"),
    sourceRef: z.string().url(),
    revision: z.string().min(1),
    semanticLabels: z.tuple([z.literal("Concept"), z.literal("Technology")]),
    contentDigest: DigestSchema,
    policyVersion: z.literal("public-research-admission/1"),
    manifestDigest: DigestSchema,
    projectionDigest: DigestSchema,
  })
  .strict();

const ReadbackRowSchema = ActivationRowSchema.extend({
  observedProperties: z.record(z.string(), z.json()),
  physicalLabels: z.tuple([z.literal("Concept")]),
  physicalLabelCount: z.literal(1),
  relationshipCount: z.literal(0),
});

export const PublicResearchActivationPlanSchema = z
  .object({
    kind: z.literal("PublicResearchActivationPlan"),
    schemaVersion: z.literal("public-research-activation-plan/1"),
    status: z.literal("PROPOSED"),
    database: z.literal("neo4j"),
    projectionId: z.string().min(1),
    policyVersion: z.literal("public-research-admission/1"),
    manifestDigest: DigestSchema,
    projectionDigest: DigestSchema,
    physicalLabels: z.tuple([z.literal("Concept")]),
    uidTriggerProfileId: z.literal(UID_TRIGGER_PROFILE_ID),
    constraintQueryDigest: DigestSchema,
    indexQueryDigest: DigestSchema,
    uidTriggerQueryDigest: DigestSchema,
    applyQueryDigest: DigestSchema,
    readbackQueryDigest: DigestSchema,
    rollbackQueryDigest: DigestSchema,
    rows: z.array(ActivationRowSchema).length(MAX_ACTIVATION_ENTRIES),
    params: z
      .object({
        rows: z.array(ActivationRowSchema).length(MAX_ACTIVATION_ENTRIES),
        physicalLabels: z.tuple([z.literal("Concept")]),
      })
      .strict(),
    readbackParams: z
      .object({
        evidenceIds: z.array(EvidenceIdSchema).length(MAX_ACTIVATION_ENTRIES),
      })
      .strict(),
    requestedEntryCount: z.literal(MAX_ACTIVATION_ENTRIES),
    externalExactlyOnceClaim: z.literal(false),
    completionClaim: z.literal(false),
    planDigest: DigestSchema,
  })
  .strict();

export type PublicResearchActivationPlan = z.infer<
  typeof PublicResearchActivationPlanSchema
>;

const ConstraintRowSchema = z
  .object({
    name: z.string().min(1),
    type: z.literal("NODE_PROPERTY_UNIQUENESS"),
    entityType: z.literal("NODE"),
    labelsOrTypes: z.tuple([z.literal("Concept")]),
    properties: z.tuple([z.literal("evidenceId")]),
    ownedIndex: z.string().min(1),
  })
  .strict();

const IndexRowSchema = z
  .object({
    name: z.string().min(1),
    type: z.literal("RANGE"),
    entityType: z.literal("NODE"),
    labelsOrTypes: z.tuple([z.literal("Concept")]),
    properties: z.tuple([z.literal("evidenceId")]),
    state: z.literal("ONLINE"),
    owningConstraint: z.string().min(1),
  })
  .strict();

const ObservedIndexRowSchema = z
  .object({
    name: z.string().min(1),
    type: z.string().min(1),
    entityType: z.string().min(1),
    labelsOrTypes: z.array(z.string().min(1)).max(2),
    properties: z.array(z.string().min(1)).max(2),
    state: z.string().min(1),
    owningConstraint: z.string().min(1).nullable(),
  })
  .strict();

const ApplyRowSchema = z
  .object({
    conflictCount: z.number().int().nonnegative().max(MAX_ACTIVATION_ENTRIES),
    createdCount: z.number().int().nonnegative().max(MAX_ACTIVATION_ENTRIES),
    unchangedCount: z.number().int().nonnegative().max(MAX_ACTIVATION_ENTRIES),
    observedEntryCount: z.literal(MAX_ACTIVATION_ENTRIES),
    createdEvidenceIds: z.array(EvidenceIdSchema).max(MAX_ACTIVATION_ENTRIES),
  })
  .strict();

const ActivationObservationSchema = z
  .object({
    constraintRows: z.array(ConstraintRowSchema).max(1),
    indexRows: z.array(ObservedIndexRowSchema).max(1),
    uidTriggerRows: z
      .array(
        z
          .object({
            profileId: z.string().min(1).max(100),
            matchingTriggerCount: z.number().int().nonnegative().max(2),
          })
          .strict(),
      )
      .max(1),
    applyRows: z.array(ApplyRowSchema).max(1),
    readbackRows: z.array(ReadbackRowSchema).max(MAX_ACTIVATION_ENTRIES),
  })
  .strict();

export const PublicResearchActivationReceiptSchema = z
  .object({
    kind: z.literal("PublicResearchActivationReceipt"),
    schemaVersion: z.literal("public-research-activation-receipt/1"),
    status: z.literal("PROPOSED"),
    mode: z.literal("live-neo4j-activation"),
    database: z.literal("neo4j"),
    projectionId: z.string().min(1),
    policyVersion: z.literal("public-research-admission/1"),
    manifestDigest: DigestSchema,
    projectionDigest: DigestSchema,
    planDigest: DigestSchema,
    constraintQueryDigest: DigestSchema,
    indexQueryDigest: DigestSchema,
    applyQueryDigest: DigestSchema,
    readbackQueryDigest: DigestSchema,
    rollbackQueryDigest: DigestSchema,
    uidTriggerProfileId: z.literal(UID_TRIGGER_PROFILE_ID),
    uidTriggerQueryDigest: DigestSchema,
    requestedEntryCount: z.literal(MAX_ACTIVATION_ENTRIES),
    createdCount: z.number().int().nonnegative().max(MAX_ACTIVATION_ENTRIES),
    unchangedCount: z.number().int().nonnegative().max(MAX_ACTIVATION_ENTRIES),
    conflictCount: z.literal(0),
    verifiedEntryCount: z.literal(MAX_ACTIVATION_ENTRIES),
    createdEvidenceIds: z.array(EvidenceIdSchema).max(MAX_ACTIVATION_ENTRIES),
    liveNeo4jWriteCallCount: z.literal(1),
    liveNeo4jReadCallCount: z.literal(4),
    rollbackProposalDigest: DigestSchema,
    rollbackProposalIsAuthorization: z.literal(false),
    externalExactlyOnceClaim: z.literal(false),
    completionClaim: z.literal(false),
  })
  .strict();

export type PublicResearchActivationReceipt = z.infer<
  typeof PublicResearchActivationReceiptSchema
>;

const RollbackObservationSchema = z
  .object({
    rollbackRows: z
      .array(
        z
          .object({
            blockedCount: z.number().int().nonnegative().max(MAX_ACTIVATION_ENTRIES),
            deletedCount: z.number().int().nonnegative().max(MAX_ACTIVATION_ENTRIES),
          })
          .strict(),
      )
      .max(1),
    remainingRows: z.array(ReadbackRowSchema).max(MAX_ACTIVATION_ENTRIES),
  })
  .strict();

export const PublicResearchRollbackReceiptSchema = z
  .object({
    kind: z.literal("PublicResearchRollbackReceipt"),
    schemaVersion: z.literal("public-research-rollback-receipt/1"),
    status: z.literal("PROPOSED"),
    mode: z.literal("live-neo4j-rollback"),
    database: z.literal("neo4j"),
    projectionId: z.string().min(1),
    activationReceiptDigest: DigestSchema,
    rollbackQueryDigest: DigestSchema,
    readbackQueryDigest: DigestSchema,
    requestedDeleteCount: z.number().int().nonnegative().max(MAX_ACTIVATION_ENTRIES),
    deletedCount: z.number().int().nonnegative().max(MAX_ACTIVATION_ENTRIES),
    blockedCount: z.literal(0),
    verifiedAbsentCount: z.number().int().nonnegative().max(MAX_ACTIVATION_ENTRIES),
    liveNeo4jWriteCallCount: z.union([z.literal(0), z.literal(1)]),
    liveNeo4jReadCallCount: z.union([z.literal(0), z.literal(1)]),
    externalExactlyOnceClaim: z.literal(false),
    completionClaim: z.literal(false),
  })
  .strict();

export type PublicResearchRollbackReceipt = z.infer<
  typeof PublicResearchRollbackReceiptSchema
>;

export type PublicResearchActivationFailureCode =
  | "INVALID_OBSERVATION"
  | "PLAN_BINDING_MISMATCH"
  | "SCHEMA_PRECONDITION_FAILED"
  | "IDENTITY_CONFLICT"
  | "APPLY_RECEIPT_MISMATCH"
  | "READBACK_MISMATCH"
  | "ROLLBACK_BINDING_MISMATCH"
  | "ROLLBACK_BLOCKED"
  | "ROLLBACK_READBACK_MISMATCH";

export class PublicResearchActivationFailure extends Error {
  readonly code: PublicResearchActivationFailureCode;

  constructor(code: PublicResearchActivationFailureCode, message: string) {
    super(message);
    this.name = "PublicResearchActivationFailure";
    this.code = code;
  }
}

const fail = (
  code: PublicResearchActivationFailureCode,
  message: string,
): never => {
  throw new PublicResearchActivationFailure(code, message);
};

const freezeRows = <
  T extends ReadonlyArray<{ readonly semanticLabels: ReadonlyArray<string> }>,
>(rows: T): T => {
  for (const row of rows) {
    Object.freeze(row.semanticLabels);
    Object.freeze(row);
  }
  return Object.freeze(rows);
};

const makeRows = (
  projection: PublicResearchProjection,
  manifestDigest: string,
): ReadonlyArray<z.infer<typeof ActivationRowSchema>> =>
  projection.entries.map((entry) => {
    const source = projection.sources.find(
      (candidate) => candidate.sourceId === entry.sourceId,
    );
    if (source === undefined) {
      throw new TypeError("compiled public-research projection lost its source");
    }
    let normalizedName = entry.title.toLowerCase().trim();
    for (const whitespace of ["\t", "\n", "\r", "\f"] as const) {
      normalizedName = normalizedName.replaceAll(whitespace, " ");
    }
    for (let pass = 0; pass < 3; pass += 1) {
      normalizedName = normalizedName.replaceAll("  ", " ");
    }
    const uid = `sym:Concept:${normalizedName.replaceAll(" ", "_")}`.slice(
      0,
      200,
    );
    return ActivationRowSchema.parse({
      evidenceId: entry.evidenceId,
      projectionId: projection.projectionId,
      visibilityScope: projection.scope,
      publicResearchTitle: entry.title,
      publicResearchSummary: entry.summary,
      name: entry.title,
      description: entry.summary,
      uid,
      uid_scheme: "v1",
      uid_source: "forward-gate-v3",
      sourceRef: source.uri,
      revision: entry.revision,
      semanticLabels: entry.semanticLabels,
      contentDigest: entry.contentDigest,
      policyVersion: projection.policyVersion,
      manifestDigest,
      projectionDigest: projection.projectionDigest,
    });
  });

export const compilePublicResearchActivationPlan = (
  rawManifest: unknown,
): PublicResearchActivationPlan => {
  const compiled = compileRepositoryOwnedPublicResearchProjection(rawManifest);
  if (compiled.projection.entries.length !== MAX_ACTIVATION_ENTRIES) {
    throw new TypeError("repository activation pin requires exactly two entries");
  }
  const rows = freezeRows(
    makeRows(compiled.projection, compiled.receipt.manifestDigest),
  );
  const physicalLabels = Object.freeze([...PHYSICAL_LABELS]);
  const params = Object.freeze({ rows, physicalLabels });
  const readbackParams = Object.freeze({
    evidenceIds: Object.freeze(rows.map((row) => row.evidenceId)),
  });
  const preimage = {
    kind: "PublicResearchActivationPlan" as const,
    schemaVersion: "public-research-activation-plan/1" as const,
    status: "PROPOSED" as const,
    database: "neo4j" as const,
    projectionId: compiled.projection.projectionId,
    policyVersion: compiled.projection.policyVersion,
    manifestDigest: compiled.receipt.manifestDigest,
    projectionDigest: compiled.projection.projectionDigest,
    physicalLabels,
    uidTriggerProfileId: UID_TRIGGER_PROFILE_ID,
    constraintQueryDigest: canonicalDigest(
      NEO4J_PUBLIC_RESEARCH_CONSTRAINT_QUERY,
    ),
    indexQueryDigest: canonicalDigest(NEO4J_PUBLIC_RESEARCH_INDEX_QUERY),
    uidTriggerQueryDigest: canonicalDigest(
      NEO4J_PUBLIC_RESEARCH_UID_TRIGGER_QUERY,
    ),
    applyQueryDigest: canonicalDigest(NEO4J_PUBLIC_RESEARCH_APPLY_QUERY),
    readbackQueryDigest: canonicalDigest(
      NEO4J_PUBLIC_RESEARCH_READBACK_QUERY,
    ),
    rollbackQueryDigest: canonicalDigest(
      NEO4J_PUBLIC_RESEARCH_ROLLBACK_QUERY,
    ),
    rows,
    params,
    readbackParams,
    requestedEntryCount: MAX_ACTIVATION_ENTRIES,
    externalExactlyOnceClaim: false as const,
    completionClaim: false as const,
  };
  const plan = PublicResearchActivationPlanSchema.parse({
    ...preimage,
    planDigest: canonicalDigest(preimage),
  });
  Object.freeze(plan.physicalLabels);
  freezeRows(plan.rows);
  freezeRows(plan.params.rows);
  Object.freeze(plan.params.physicalLabels);
  Object.freeze(plan.params);
  Object.freeze(plan.readbackParams.evidenceIds);
  Object.freeze(plan.readbackParams);
  return Object.freeze(plan);
};

const requireRepositoryBoundPlan = (rawPlan: unknown) => {
  const decoded = PublicResearchActivationPlanSchema.safeParse(rawPlan);
  if (!decoded.success) {
    return fail("PLAN_BINDING_MISMATCH", "activation plan failed strict decoding");
  }
  const plan = decoded.data;
  const { planDigest: _ignored, ...preimage } = plan;
  if (
    plan.planDigest !== canonicalDigest(preimage) ||
    plan.planDigest !== REPOSITORY_OWNED_PUBLIC_RESEARCH_ACTIVATION_PLAN_PIN.planDigest ||
    plan.manifestDigest !==
      REPOSITORY_OWNED_PUBLIC_RESEARCH_ACTIVATION_PLAN_PIN.manifestDigest ||
    plan.projectionId !==
      REPOSITORY_OWNED_PUBLIC_RESEARCH_ACTIVATION_PLAN_PIN.projectionId ||
    plan.projectionDigest !==
      REPOSITORY_OWNED_PUBLIC_RESEARCH_ACTIVATION_PLAN_PIN.projectionDigest ||
    plan.constraintQueryDigest !==
      canonicalDigest(NEO4J_PUBLIC_RESEARCH_CONSTRAINT_QUERY) ||
    plan.indexQueryDigest !== canonicalDigest(NEO4J_PUBLIC_RESEARCH_INDEX_QUERY) ||
    plan.uidTriggerProfileId !== UID_TRIGGER_PROFILE_ID ||
    plan.uidTriggerQueryDigest !==
      canonicalDigest(NEO4J_PUBLIC_RESEARCH_UID_TRIGGER_QUERY) ||
    plan.applyQueryDigest !== canonicalDigest(NEO4J_PUBLIC_RESEARCH_APPLY_QUERY) ||
    plan.readbackQueryDigest !==
      canonicalDigest(NEO4J_PUBLIC_RESEARCH_READBACK_QUERY) ||
    plan.rollbackQueryDigest !==
      canonicalDigest(NEO4J_PUBLIC_RESEARCH_ROLLBACK_QUERY) ||
    canonicalJson(plan.rows) !== canonicalJson(plan.params.rows) ||
    canonicalJson(plan.physicalLabels) !== canonicalJson(PHYSICAL_LABELS) ||
    canonicalJson(plan.params.physicalLabels) !== canonicalJson(PHYSICAL_LABELS) ||
    canonicalJson(plan.readbackParams.evidenceIds) !==
      canonicalJson(plan.rows.map((row) => row.evidenceId))
  ) {
    return fail(
      "PLAN_BINDING_MISMATCH",
      "activation plan did not match repository-owned query and identity pins",
    );
  }
  return plan;
};

const expectedReadbackRows = (plan: PublicResearchActivationPlan) =>
  plan.rows.map((row) => ({
    ...row,
    observedProperties: row,
    physicalLabels: [...PHYSICAL_LABELS],
    physicalLabelCount: 1 as const,
    relationshipCount: 0 as const,
  }));

export const verifyPublicResearchActivation = (
  rawPlan: unknown,
  rawObservation: unknown,
): PublicResearchActivationReceipt => {
  const plan = requireRepositoryBoundPlan(rawPlan);
  const decoded = ActivationObservationSchema.safeParse(rawObservation);
  if (!decoded.success) {
    return fail(
      "INVALID_OBSERVATION",
      "activation observations failed strict bounded decoding",
    );
  }
  const observation = decoded.data;
  const uidTrigger = observation.uidTriggerRows.at(0);
  if (
    uidTrigger?.profileId !== UID_TRIGGER_PROFILE_ID ||
    uidTrigger.matchingTriggerCount !== 1
  ) {
    return fail(
      "SCHEMA_PRECONDITION_FAILED",
      "activation requires the exact installed UID forward-gate profile",
    );
  }
  const constraint = observation.constraintRows.at(0);
  const index = IndexRowSchema.safeParse(observation.indexRows.at(0));
  if (
    constraint === undefined ||
    !index.success ||
    constraint.name !== index.data.owningConstraint ||
    constraint.ownedIndex !== index.data.name
  ) {
    return fail(
      "SCHEMA_PRECONDITION_FAILED",
      "activation requires the exact online evidence identity constraint index",
    );
  }
  const apply = observation.applyRows.at(0);
  if (apply === undefined) {
    return fail("APPLY_RECEIPT_MISMATCH", "activation returned no write summary");
  }
  if (apply.conflictCount !== 0) {
    return fail("IDENTITY_CONFLICT", "activation found an identity conflict");
  }
  if (
    apply.createdCount + apply.unchangedCount !== plan.requestedEntryCount ||
    apply.createdEvidenceIds.length !== apply.createdCount ||
    new Set(apply.createdEvidenceIds).size !== apply.createdEvidenceIds.length ||
    !apply.createdEvidenceIds.every((id) =>
      plan.rows.some((row) => row.evidenceId === id),
    )
  ) {
    return fail(
      "APPLY_RECEIPT_MISMATCH",
      "activation write counts did not bind to the complete plan",
    );
  }
  if (
    canonicalJson(observation.readbackRows) !==
    canonicalJson(expectedReadbackRows(plan))
  ) {
    return fail(
      "READBACK_MISMATCH",
      "independent readback did not exactly match physical projection bytes",
    );
  }
  const rollbackProposalDigest = canonicalDigest({
    schemaVersion: "public-research-rollback-token/1",
    planDigest: plan.planDigest,
    createdEvidenceIds: apply.createdEvidenceIds,
  });
  const receipt = PublicResearchActivationReceiptSchema.parse({
    kind: "PublicResearchActivationReceipt",
    schemaVersion: "public-research-activation-receipt/1",
    status: "PROPOSED",
    mode: "live-neo4j-activation",
    database: plan.database,
    projectionId: plan.projectionId,
    policyVersion: plan.policyVersion,
    manifestDigest: plan.manifestDigest,
    projectionDigest: plan.projectionDigest,
    planDigest: plan.planDigest,
    constraintQueryDigest: plan.constraintQueryDigest,
    indexQueryDigest: plan.indexQueryDigest,
    applyQueryDigest: plan.applyQueryDigest,
    readbackQueryDigest: plan.readbackQueryDigest,
    rollbackQueryDigest: plan.rollbackQueryDigest,
    uidTriggerProfileId: plan.uidTriggerProfileId,
    uidTriggerQueryDigest: plan.uidTriggerQueryDigest,
    requestedEntryCount: plan.requestedEntryCount,
    createdCount: apply.createdCount,
    unchangedCount: apply.unchangedCount,
    conflictCount: 0,
    verifiedEntryCount: observation.readbackRows.length,
    createdEvidenceIds: apply.createdEvidenceIds,
    liveNeo4jWriteCallCount: 1,
    liveNeo4jReadCallCount: 4,
    rollbackProposalDigest,
    rollbackProposalIsAuthorization: false,
    externalExactlyOnceClaim: false,
    completionClaim: false,
  });
  Object.freeze(receipt.createdEvidenceIds);
  return Object.freeze(receipt);
};

export const publicResearchRollbackParams = (
  rawPlan: unknown,
  rawReceipt: unknown,
) => {
  const plan = requireRepositoryBoundPlan(rawPlan);
  const receipt = PublicResearchActivationReceiptSchema.parse(rawReceipt);
  const expectedProposalDigest = canonicalDigest({
    schemaVersion: "public-research-rollback-token/1",
    planDigest: plan.planDigest,
    createdEvidenceIds: receipt.createdEvidenceIds,
  });
  if (
    receipt.database !== plan.database ||
    receipt.projectionId !== plan.projectionId ||
    receipt.manifestDigest !== plan.manifestDigest ||
    receipt.projectionDigest !== plan.projectionDigest ||
    receipt.planDigest !== plan.planDigest ||
    receipt.rollbackQueryDigest !== plan.rollbackQueryDigest ||
    receipt.readbackQueryDigest !== plan.readbackQueryDigest ||
    receipt.uidTriggerProfileId !== plan.uidTriggerProfileId ||
    receipt.uidTriggerQueryDigest !== plan.uidTriggerQueryDigest ||
    receipt.rollbackProposalDigest !== expectedProposalDigest ||
    receipt.rollbackProposalIsAuthorization !== false
  ) {
    return fail(
      "ROLLBACK_BINDING_MISMATCH",
      "rollback receipt did not bind to the activation plan",
    );
  }
  const createdIds = new Set(receipt.createdEvidenceIds);
  const createdRows = plan.rows.filter((row) => createdIds.has(row.evidenceId));
  if (createdRows.length !== receipt.createdEvidenceIds.length) {
    return fail(
      "ROLLBACK_BINDING_MISMATCH",
      "rollback named an identity outside the activation plan",
    );
  }
  return Object.freeze({
    createdRows: freezeRows([...createdRows]),
    physicalLabels: Object.freeze([...PHYSICAL_LABELS]),
  });
};

export const verifyPublicResearchRollback = (
  rawPlan: unknown,
  rawActivationReceipt: unknown,
  rawObservation: unknown,
): PublicResearchRollbackReceipt => {
  const plan = requireRepositoryBoundPlan(rawPlan);
  const activationReceipt = PublicResearchActivationReceiptSchema.parse(
    rawActivationReceipt,
  );
  const params = publicResearchRollbackParams(plan, activationReceipt);
  const decoded = RollbackObservationSchema.safeParse(rawObservation);
  if (!decoded.success) {
    return fail(
      "INVALID_OBSERVATION",
      "rollback observations failed strict bounded decoding",
    );
  }
  const requestedDeleteCount = params.createdRows.length;
  if (requestedDeleteCount === 0) {
    if (
      decoded.data.rollbackRows.length !== 0 ||
      decoded.data.remainingRows.length !== 0
    ) {
      return fail(
        "ROLLBACK_READBACK_MISMATCH",
        "zero-created activation must not issue rollback I/O",
      );
    }
    return Object.freeze(
      PublicResearchRollbackReceiptSchema.parse({
        kind: "PublicResearchRollbackReceipt",
        schemaVersion: "public-research-rollback-receipt/1",
        status: "PROPOSED",
        mode: "live-neo4j-rollback",
        database: plan.database,
        projectionId: plan.projectionId,
        activationReceiptDigest: canonicalDigest(activationReceipt),
        rollbackQueryDigest: plan.rollbackQueryDigest,
        readbackQueryDigest: plan.readbackQueryDigest,
        requestedDeleteCount: 0,
        deletedCount: 0,
        blockedCount: 0,
        verifiedAbsentCount: 0,
        liveNeo4jWriteCallCount: 0,
        liveNeo4jReadCallCount: 0,
        externalExactlyOnceClaim: false,
        completionClaim: false,
      }),
    );
  }
  const rollback = decoded.data.rollbackRows.at(0);
  if (rollback === undefined) {
    return fail("ROLLBACK_READBACK_MISMATCH", "rollback returned no summary");
  }
  if (rollback.blockedCount !== 0) {
    return fail(
      "ROLLBACK_BLOCKED",
      "rollback found changed, duplicated, or relationship-bound owned data",
    );
  }
  if (
    rollback.deletedCount !== requestedDeleteCount ||
    decoded.data.remainingRows.length !== 0
  ) {
    return fail(
      "ROLLBACK_READBACK_MISMATCH",
      "independent rollback readback did not prove created IDs absent",
    );
  }
  return Object.freeze(
    PublicResearchRollbackReceiptSchema.parse({
      kind: "PublicResearchRollbackReceipt",
      schemaVersion: "public-research-rollback-receipt/1",
      status: "PROPOSED",
      mode: "live-neo4j-rollback",
      database: plan.database,
      projectionId: plan.projectionId,
      activationReceiptDigest: canonicalDigest(activationReceipt),
      rollbackQueryDigest: plan.rollbackQueryDigest,
      readbackQueryDigest: plan.readbackQueryDigest,
      requestedDeleteCount,
      deletedCount: rollback.deletedCount,
      blockedCount: 0,
      verifiedAbsentCount: requestedDeleteCount,
      liveNeo4jWriteCallCount: 1,
      liveNeo4jReadCallCount: 1,
      externalExactlyOnceClaim: false,
      completionClaim: false,
    }),
  );
};
