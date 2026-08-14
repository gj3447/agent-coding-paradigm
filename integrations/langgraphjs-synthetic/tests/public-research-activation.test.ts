import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { describe, it } from "node:test";

import {
  PublicResearchActivationFailure,
  PublicResearchProjectionManifestSchema,
  NEO4J_PUBLIC_RESEARCH_APPLY_QUERY,
  NEO4J_PUBLIC_RESEARCH_CONSTRAINT_QUERY,
  NEO4J_PUBLIC_RESEARCH_INDEX_QUERY,
  NEO4J_PUBLIC_RESEARCH_READBACK_QUERY,
  NEO4J_PUBLIC_RESEARCH_ROLLBACK_QUERY,
  NEO4J_PUBLIC_RESEARCH_UID_TRIGGER_QUERY,
  compilePublicResearchActivationPlan,
  verifyPublicResearchActivation,
  verifyPublicResearchRollback,
  type PublicResearchActivationFailureCode,
} from "../src/index.js";
import { canonicalDigest } from "../src/pure.js";

const fixtureUrl = new URL(
  "../fixtures/public-research/synthetic-foundations.manifest.v1.json",
  import.meta.url,
);

const readManifest = async () => {
  const raw: unknown = JSON.parse(await readFile(fixtureUrl, "utf8"));
  return PublicResearchProjectionManifestSchema.parse(raw);
};

const exactUidTriggerRows = () => [
  {
    profileId: "neo4j-concept-uid-envelope/v1",
    matchingTriggerCount: 1,
  },
];

const expectFailureCode = (
  operation: () => unknown,
  code: PublicResearchActivationFailureCode,
): void => {
  assert.throws(operation, (error: unknown) => {
    assert.ok(error instanceof PublicResearchActivationFailure);
    assert.equal(error.code, code);
    return true;
  });
};

describe("public-research live activation contract", () => {
  it("compiles a deterministic, deeply frozen, repository-pinned plan", async () => {
    const plan = compilePublicResearchActivationPlan(await readManifest());

    assert.equal(plan.status, "PROPOSED");
    assert.equal(plan.database, "neo4j");
    assert.equal(plan.requestedEntryCount, 2);
    assert.equal(plan.externalExactlyOnceClaim, false);
    assert.equal(plan.completionClaim, false);
    assert.equal(Object.isFrozen(plan), true);
    assert.equal(Object.isFrozen(plan.rows), true);
    assert.equal(Object.isFrozen(plan.rows.at(0)), true);
    assert.equal(Object.isFrozen(plan.rows.at(0)?.semanticLabels), true);
    assert.deepEqual(plan.params, {
      rows: plan.rows,
      physicalLabels: ["Concept"],
    });
    assert.equal(Object.isFrozen(plan.params), true);
    assert.doesNotMatch(JSON.stringify(plan), /PublicResearchEvidence/u);
    assert.deepEqual(plan.rows.map((row) => row.evidenceId), [
      "evidence:synthetic:effect-role-v1",
      "evidence:synthetic:langgraph-role-v1",
    ]);
    assert.deepEqual(plan.rows.map((row) => row.uid), [
      "sym:Concept:effect_boundary_role",
      "sym:Concept:langgraph.js_orchestration_role",
    ]);
    const first = plan.rows.at(0);
    assert.ok(first !== undefined);
    assert.deepEqual(first, {
      evidenceId: "evidence:synthetic:effect-role-v1",
      projectionId: plan.projectionId,
      visibilityScope: "public-research",
      publicResearchTitle: "Effect boundary role",
      publicResearchSummary:
        "Synthetic fixture: lazy typed effects bound timeout and cancellation without becoming a second agent loop.",
      name: "Effect boundary role",
      description:
        "Synthetic fixture: lazy typed effects bound timeout and cancellation without becoming a second agent loop.",
      uid: "sym:Concept:effect_boundary_role",
      uid_scheme: "v1",
      uid_source: "forward-gate-v3",
      sourceRef: "https://github.com/Effect-TS/effect",
      revision: "2026-08-12",
      semanticLabels: ["Concept", "Technology"],
      contentDigest:
        "sha256:4f5e3e9a86ca2ef019bc8c4637c467e8c615fc667e15437411462ae22604571d",
      policyVersion: "public-research-admission/1",
      manifestDigest: plan.manifestDigest,
      projectionDigest: plan.projectionDigest,
    });
  });

  it("rejects a changed repository-owned manifest before planning a write", async () => {
    const manifest = structuredClone(await readManifest());
    const entry = manifest.entries.at(0);
    assert.ok(entry !== undefined);
    entry.title = "Changed after pin";

    assert.throws(() => compilePublicResearchActivationPlan(manifest));
  });

  it("rejects a valid-shaped plan whose repository binding was changed", async () => {
    const plan = compilePublicResearchActivationPlan(await readManifest());
    const forged = structuredClone(plan);
    const first = forged.rows.at(0);
    assert.ok(first !== undefined);
    forged.rows[0] = {
      ...first,
      description: "caller-forged plan bytes",
    };
    const changed = forged.rows.at(0);
    assert.ok(changed !== undefined);
    forged.params.rows[0] = changed;

    expectFailureCode(
      () =>
        verifyPublicResearchActivation(forged, {
          uidTriggerRows: exactUidTriggerRows(),
          constraintRows: [],
          indexRows: [],
          applyRows: [],
          readbackRows: [],
        }),
      "PLAN_BINDING_MISMATCH",
    );

    const redigested = structuredClone(forged);
    const { planDigest: _ignored, ...preimage } = redigested;
    redigested.planDigest = canonicalDigest(preimage);
    expectFailureCode(
      () =>
        verifyPublicResearchActivation(redigested, {
          uidTriggerRows: exactUidTriggerRows(),
          constraintRows: [],
          indexRows: [],
          applyRows: [],
          readbackRows: [],
        }),
      "PLAN_BINDING_MISMATCH",
    );
  });

  it("keeps data DML fixed and APOC-free while binding the read-only trigger profile", () => {
    const queries = [
      NEO4J_PUBLIC_RESEARCH_CONSTRAINT_QUERY,
      NEO4J_PUBLIC_RESEARCH_INDEX_QUERY,
      NEO4J_PUBLIC_RESEARCH_APPLY_QUERY,
      NEO4J_PUBLIC_RESEARCH_READBACK_QUERY,
      NEO4J_PUBLIC_RESEARCH_ROLLBACK_QUERY,
    ];
    for (const query of queries) {
      assert.doesNotMatch(query, /apoc\./iu);
      assert.doesNotMatch(query, /DETACH\s+DELETE/iu);
      assert.doesNotMatch(query, /\$\([^)]*label|nodeRef|elementId\(/iu);
      assert.doesNotMatch(
        query,
        /\((?:matches|candidates)\[[^\]]+\]\)--\(\)/u,
      );
    }
    assert.match(NEO4J_PUBLIC_RESEARCH_UID_TRIGGER_QUERY, /apoc\.trigger\.list\(\)/u);
    assert.match(NEO4J_PUBLIC_RESEARCH_UID_TRIGGER_QUERY, /installed = true/u);
    assert.match(NEO4J_PUBLIC_RESEARCH_UID_TRIGGER_QUERY, /paused = false/u);
    assert.match(NEO4J_PUBLIC_RESEARCH_UID_TRIGGER_QUERY, /phase = 'afterAsync'/u);
    assert.match(NEO4J_PUBLIC_RESEARCH_UID_TRIGGER_QUERY, /n\.uid IS NULL/u);
    assert.match(NEO4J_PUBLIC_RESEARCH_UID_TRIGGER_QUERY, /uid_scheme = 'v1'/u);
    assert.match(
      NEO4J_PUBLIC_RESEARCH_UID_TRIGGER_QUERY,
      /uid_source = 'forward-gate-v3'/u,
    );
    assert.doesNotMatch(
      `${NEO4J_PUBLIC_RESEARCH_APPLY_QUERY}\n${NEO4J_PUBLIC_RESEARCH_READBACK_QUERY}\n${NEO4J_PUBLIC_RESEARCH_ROLLBACK_QUERY}`,
      /apoc\./iu,
    );
    assert.match(
      NEO4J_PUBLIC_RESEARCH_CONSTRAINT_QUERY,
      /NODE_PROPERTY_UNIQUENESS/u,
    );
    assert.match(NEO4J_PUBLIC_RESEARCH_INDEX_QUERY, /state = 'ONLINE'/u);
    assert.match(
      NEO4J_PUBLIC_RESEARCH_APPLY_QUERY,
      /MERGE \(node:Concept \{/u,
    );
    assert.match(NEO4J_PUBLIC_RESEARCH_APPLY_QUERY, /uidMatches/u);
    assert.match(
      NEO4J_PUBLIC_RESEARCH_APPLY_QUERY,
      /OPTIONAL MATCH \(uidOwner \{uid: row\.uid\}\)/u,
    );
    assert.match(NEO4J_PUBLIC_RESEARCH_APPLY_QUERY, /node\.uid = null/u);
    assert.match(NEO4J_PUBLIC_RESEARCH_APPLY_QUERY, /node\.uid_scheme = null/u);
    assert.match(NEO4J_PUBLIC_RESEARCH_APPLY_QUERY, /node\.uid_source = null/u);
    assert.doesNotMatch(
      `${NEO4J_PUBLIC_RESEARCH_APPLY_QUERY}\n${NEO4J_PUBLIC_RESEARCH_READBACK_QUERY}\n${NEO4J_PUBLIC_RESEARCH_ROLLBACK_QUERY}`,
      /PublicResearchEvidence/u,
    );
    assert.match(NEO4J_PUBLIC_RESEARCH_APPLY_QUERY, /conflictCount = 0/u);
    assert.match(NEO4J_PUBLIC_RESEARCH_APPLY_QUERY, /LIMIT 3/u);
    assert.match(NEO4J_PUBLIC_RESEARCH_READBACK_QUERY, /LIMIT 3/u);
    assert.match(
      NEO4J_PUBLIC_RESEARCH_ROLLBACK_QUERY,
      /matches\[0\]\.relationshipCount = 0/u,
    );
    assert.match(NEO4J_PUBLIC_RESEARCH_ROLLBACK_QUERY, /DELETE ownedNode/u);
  });

  it("fails closed without the exact online uniqueness constraint", async () => {
    const plan = compilePublicResearchActivationPlan(await readManifest());
    expectFailureCode(
      () =>
        verifyPublicResearchActivation(plan, {
          uidTriggerRows: exactUidTriggerRows(),
          constraintRows: [],
          indexRows: [],
          applyRows: [],
          readbackRows: [],
        }),
      "SCHEMA_PRECONDITION_FAILED",
    );
  });

  it("fails closed without the exact enabled afterAsync UID trigger profile", async () => {
    const plan = compilePublicResearchActivationPlan(await readManifest());
    for (const uidTriggerRows of [
      [],
      [
        {
          profileId: "neo4j-concept-uid-envelope/v1",
          matchingTriggerCount: 0,
        },
      ],
      [
        {
          profileId: "neo4j-concept-uid-envelope/v0",
          matchingTriggerCount: 1,
        },
      ],
      [
        {
          profileId: "neo4j-concept-uid-envelope/v1",
          matchingTriggerCount: 2,
        },
      ],
    ]) {
      expectFailureCode(
        () =>
          verifyPublicResearchActivation(plan, {
            uidTriggerRows,
            constraintRows: [],
            indexRows: [],
            applyRows: [],
            readbackRows: [],
          }),
        "SCHEMA_PRECONDITION_FAILED",
      );
    }
  });

  it("fails closed when a similarly shaped backing index is not online", async () => {
    const plan = compilePublicResearchActivationPlan(await readManifest());
    expectFailureCode(
      () =>
        verifyPublicResearchActivation(plan, {
          uidTriggerRows: exactUidTriggerRows(),
          constraintRows: [
            {
              name: "public_research_concept_evidence_id_unique",
              type: "NODE_PROPERTY_UNIQUENESS",
              entityType: "NODE",
              labelsOrTypes: ["Concept"],
              properties: ["evidenceId"],
              ownedIndex: "public_research_concept_evidence_id_unique",
            },
          ],
          indexRows: [
            {
              name: "public_research_concept_evidence_id_unique",
              type: "RANGE",
              entityType: "NODE",
              labelsOrTypes: ["Concept"],
              properties: ["evidenceId"],
              state: "POPULATING",
              owningConstraint: "public_research_concept_evidence_id_unique",
            },
          ],
          applyRows: [],
          readbackRows: [],
        }),
      "SCHEMA_PRECONDITION_FAILED",
    );
  });

  it("rejects conflicts even if a writer reports successful rows", async () => {
    const plan = compilePublicResearchActivationPlan(await readManifest());
    expectFailureCode(
      () =>
        verifyPublicResearchActivation(plan, {
          uidTriggerRows: exactUidTriggerRows(),
          constraintRows: [
            {
              name: "public_research_concept_evidence_id_unique",
              type: "NODE_PROPERTY_UNIQUENESS",
              entityType: "NODE",
              labelsOrTypes: ["Concept"],
              properties: ["evidenceId"],
              ownedIndex: "public_research_concept_evidence_id_unique",
            },
          ],
          indexRows: [
            {
              name: "public_research_concept_evidence_id_unique",
              type: "RANGE",
              entityType: "NODE",
              labelsOrTypes: ["Concept"],
              properties: ["evidenceId"],
              state: "ONLINE",
              owningConstraint: "public_research_concept_evidence_id_unique",
            },
          ],
          applyRows: [
            {
              conflictCount: 1,
              createdCount: 2,
              unchangedCount: 0,
              observedEntryCount: 2,
              createdEvidenceIds: plan.rows.map((row) => row.evidenceId),
            },
          ],
          readbackRows: plan.rows.map((row) => ({
            ...row,
            observedProperties: row,
            physicalLabels: ["Concept" as const],
            physicalLabelCount: 1 as const,
            relationshipCount: 0 as const,
          })),
        }),
      "IDENTITY_CONFLICT",
    );
  });

  it("rejects a false writer receipt and independent readback mismatch", async () => {
    const plan = compilePublicResearchActivationPlan(await readManifest());
    const constraintRows = [
      {
        name: "public_research_concept_evidence_id_unique",
        type: "NODE_PROPERTY_UNIQUENESS" as const,
        entityType: "NODE" as const,
        labelsOrTypes: ["Concept"],
        properties: ["evidenceId"],
        ownedIndex: "public_research_concept_evidence_id_unique",
      },
    ];
    const indexRows = [
      {
        name: "public_research_concept_evidence_id_unique",
        type: "RANGE" as const,
        entityType: "NODE" as const,
        labelsOrTypes: ["Concept"] as ["Concept"],
        properties: ["evidenceId"] as ["evidenceId"],
        state: "ONLINE" as const,
        owningConstraint: "public_research_concept_evidence_id_unique",
      },
    ];
    expectFailureCode(
      () =>
        verifyPublicResearchActivation(plan, {
          uidTriggerRows: exactUidTriggerRows(),
          constraintRows,
          indexRows,
          applyRows: [
            {
              conflictCount: 0,
              createdCount: 2,
              unchangedCount: 0,
              observedEntryCount: 2,
              createdEvidenceIds: plan.rows.map((row) => row.evidenceId),
            },
          ],
          readbackRows: [],
        }),
      "READBACK_MISMATCH",
    );
    expectFailureCode(
      () =>
        verifyPublicResearchActivation(plan, {
          uidTriggerRows: exactUidTriggerRows(),
          constraintRows,
          indexRows,
          applyRows: [
            {
              conflictCount: 0,
              createdCount: 2,
              unchangedCount: 0,
              observedEntryCount: 2,
              createdEvidenceIds: plan.rows.map((row) => row.evidenceId),
            },
          ],
          readbackRows: plan.rows.map((row, index) => ({
            ...row,
            description: index === 0 ? "changed after write" : row.description,
            observedProperties: row,
            physicalLabels: ["Concept" as const],
            physicalLabelCount: 1 as const,
            relationshipCount: 0 as const,
          })),
        }),
      "READBACK_MISMATCH",
    );
    expectFailureCode(
      () =>
        verifyPublicResearchActivation(plan, {
          uidTriggerRows: exactUidTriggerRows(),
          constraintRows,
          indexRows,
          applyRows: [
            {
              conflictCount: 0,
              createdCount: 2,
              unchangedCount: 0,
              observedEntryCount: 2,
              createdEvidenceIds: plan.rows.map((row) => row.evidenceId),
            },
          ],
          readbackRows: plan.rows.map((row, index) => ({
            ...row,
            observedProperties:
              index === 0
                ? { ...row, privateNote: "must not enter public projection" }
                : row,
            physicalLabels: ["Concept" as const],
            physicalLabelCount: 1 as const,
            relationshipCount: 0 as const,
          })),
        }),
      "READBACK_MISMATCH",
    );
    expectFailureCode(
      () =>
        verifyPublicResearchActivation(plan, {
          uidTriggerRows: exactUidTriggerRows(),
          constraintRows,
          indexRows,
          applyRows: [
            {
              conflictCount: 0,
              createdCount: 2,
              unchangedCount: 0,
              observedEntryCount: 2,
              createdEvidenceIds: plan.rows.map((row) => row.evidenceId),
            },
          ],
          readbackRows: plan.rows.map((row, index) => {
            if (index !== 0) {
              return {
                ...row,
                observedProperties: row,
                physicalLabels: ["Concept" as const],
                physicalLabelCount: 1 as const,
                relationshipCount: 0 as const,
              };
            }
            const collisionRow = {
              ...row,
              uid: `${row.uid}#collision`,
            };
            return {
              ...collisionRow,
              observedProperties: {
                ...collisionRow,
                uid_collision: true,
                uid_group: row.uid,
              },
              physicalLabels: ["Concept" as const],
              physicalLabelCount: 1 as const,
              relationshipCount: 0 as const,
            };
          }),
        }),
      "READBACK_MISMATCH",
    );
  });

  it("emits a bounded receipt only after exact independent readback", async () => {
    const plan = compilePublicResearchActivationPlan(await readManifest());
    const receipt = verifyPublicResearchActivation(plan, {
      uidTriggerRows: exactUidTriggerRows(),
      constraintRows: [
        {
          name: "public_research_concept_evidence_id_unique",
          type: "NODE_PROPERTY_UNIQUENESS",
          entityType: "NODE",
          labelsOrTypes: ["Concept"],
          properties: ["evidenceId"],
          ownedIndex: "public_research_concept_evidence_id_unique",
        },
      ],
      indexRows: [
        {
          name: "public_research_concept_evidence_id_unique",
          type: "RANGE",
          entityType: "NODE",
          labelsOrTypes: ["Concept"],
          properties: ["evidenceId"],
          state: "ONLINE",
          owningConstraint: "public_research_concept_evidence_id_unique",
        },
      ],
      applyRows: [
        {
          conflictCount: 0,
          createdCount: 2,
          unchangedCount: 0,
          observedEntryCount: 2,
          createdEvidenceIds: plan.rows.map((row) => row.evidenceId),
        },
      ],
      readbackRows: plan.rows.map((row) => ({
        ...row,
        observedProperties: row,
            physicalLabels: ["Concept" as const],
        physicalLabelCount: 1 as const,
        relationshipCount: 0 as const,
      })),
    });

    assert.equal(receipt.status, "PROPOSED");
    assert.equal(receipt.verifiedEntryCount, 2);
    assert.equal(receipt.liveNeo4jWriteCallCount, 1);
    assert.equal(receipt.liveNeo4jReadCallCount, 4);
    assert.equal(receipt.uidTriggerProfileId, "neo4j-concept-uid-envelope/v1");
    assert.equal(receipt.externalExactlyOnceClaim, false);
    assert.equal(receipt.completionClaim, false);
    assert.equal(Object.isFrozen(receipt), true);
    assert.equal(Object.isFrozen(receipt.createdEvidenceIds), true);
    assert.ok(receipt.rollbackProposalDigest.startsWith("sha256:"));
    assert.equal(receipt.rollbackProposalIsAuthorization, false);
  });

  it("does not manufacture a live rollback call when activation created nothing", async () => {
    const plan = compilePublicResearchActivationPlan(await readManifest());
    const receipt = verifyPublicResearchActivation(plan, {
      uidTriggerRows: exactUidTriggerRows(),
      constraintRows: [
        {
          name: "public_research_concept_evidence_id_unique",
          type: "NODE_PROPERTY_UNIQUENESS",
          entityType: "NODE",
          labelsOrTypes: ["Concept"],
          properties: ["evidenceId"],
          ownedIndex: "public_research_concept_evidence_id_unique",
        },
      ],
      indexRows: [
        {
          name: "public_research_concept_evidence_id_unique",
          type: "RANGE",
          entityType: "NODE",
          labelsOrTypes: ["Concept"],
          properties: ["evidenceId"],
          state: "ONLINE",
          owningConstraint: "public_research_concept_evidence_id_unique",
        },
      ],
      applyRows: [
        {
          conflictCount: 0,
          createdCount: 0,
          unchangedCount: 2,
          observedEntryCount: 2,
          createdEvidenceIds: [],
        },
      ],
      readbackRows: plan.rows.map((row) => ({
        ...row,
        observedProperties: row,
            physicalLabels: ["Concept" as const],
        physicalLabelCount: 1 as const,
        relationshipCount: 0 as const,
      })),
    });

    const rollback = verifyPublicResearchRollback(plan, receipt, {
      rollbackRows: [],
      remainingRows: [],
    });
    assert.equal(rollback.deletedCount, 0);
    assert.equal(rollback.liveNeo4jWriteCallCount, 0);
    assert.equal(rollback.liveNeo4jReadCallCount, 0);
  });

  it("binds rollback to created IDs and verifies absence independently", async () => {
    const plan = compilePublicResearchActivationPlan(await readManifest());
    const receipt = verifyPublicResearchActivation(plan, {
      uidTriggerRows: exactUidTriggerRows(),
      constraintRows: [
        {
          name: "public_research_concept_evidence_id_unique",
          type: "NODE_PROPERTY_UNIQUENESS",
          entityType: "NODE",
          labelsOrTypes: ["Concept"],
          properties: ["evidenceId"],
          ownedIndex: "public_research_concept_evidence_id_unique",
        },
      ],
      indexRows: [
        {
          name: "public_research_concept_evidence_id_unique",
          type: "RANGE",
          entityType: "NODE",
          labelsOrTypes: ["Concept"],
          properties: ["evidenceId"],
          state: "ONLINE",
          owningConstraint: "public_research_concept_evidence_id_unique",
        },
      ],
      applyRows: [
        {
          conflictCount: 0,
          createdCount: 1,
          unchangedCount: 1,
          observedEntryCount: 2,
          createdEvidenceIds: [plan.rows[0]?.evidenceId],
        },
      ],
      readbackRows: plan.rows.map((row) => ({
        ...row,
        observedProperties: row,
            physicalLabels: ["Concept" as const],
        physicalLabelCount: 1 as const,
        relationshipCount: 0 as const,
      })),
    });
    const rollback = verifyPublicResearchRollback(plan, receipt, {
      rollbackRows: [{ blockedCount: 0, deletedCount: 1 }],
      remainingRows: [],
    });
    assert.equal(rollback.deletedCount, 1);
    assert.equal(rollback.verifiedAbsentCount, 1);
    assert.equal(rollback.externalExactlyOnceClaim, false);

    expectFailureCode(
      () =>
        verifyPublicResearchRollback(plan, receipt, {
          rollbackRows: [{ blockedCount: 1, deletedCount: 0 }],
          remainingRows: [],
        }),
      "ROLLBACK_BLOCKED",
    );
    expectFailureCode(
      () =>
        verifyPublicResearchRollback(plan, receipt, {
          rollbackRows: [{ blockedCount: 0, deletedCount: 1 }],
          remainingRows: [
            {
              ...plan.rows[0],
              description: "changed before rollback",
              observedProperties: { ...plan.rows[0], privateNote: "must not be hidden" },
              physicalLabels: ["Concept"],
              physicalLabelCount: 1,
              relationshipCount: 0,
            },
          ],
        }),
      "ROLLBACK_READBACK_MISMATCH",
    );
  });
});
