#!/usr/bin/env python3
"""Offline verifier for the bounded public-research live observation."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = Path("research/PUBLIC_RESEARCH_LIVE_ACTIVATION_2026-08-12.json")
SCHEMA_PATH = Path(
    "spec/schema/public-research-live-activation-evidence.v1.schema.json"
)

_EXPECTED_DOCUMENT_FIELDS = {
    "schemaVersion": "public-research-live-activation-evidence/v1",
    "kind": "PublicResearchLiveActivationEvidence",
    "epistemicStatus": "MEASURED",
    "measurementScope": (
        "One bounded live Neo4j activation and final readback of the two "
        "repository-pinned synthetic public-research Concept nodes; not "
        "repository-wide efficacy, completion, production, publication, "
        "engine, or external exactly-once evidence"
    ),
    "repositoryClaimStatus": "PROPOSED",
    "receiptPath": str(EVIDENCE_PATH),
}
_EXPECTED_WINDOW_FIELDS = {
    "startedAtPrecision": "minute",
    "successfulCreateObservedAtPrecision": "second-approximate",
    "finalVerificationTimestampSource": (
        "UTC clock captured immediately before and after independent live reads"
    ),
    "clock": "UTC",
}
_EXPECTED_REPOSITORY_FIELDS = {
    "baseHead": "067f6203f709f50655ae392c9187376119b50fc6",
    "preActivationWorktreeDirty": True,
    "preActivationWorktreeEntryCount": 29,
    "activationSourcePath": (
        "integrations/langgraphjs-synthetic/src/public-research-activation.ts"
    ),
    "initialCreateSourceClosureFrozen": False,
    "initialCreateSourceSha256": None,
}
_EXPECTED_SUBJECT_FIELDS = {
    "database": "neo4j",
    "fixturePath": (
        "integrations/langgraphjs-synthetic/fixtures/public-research/"
        "synthetic-foundations.manifest.v1.json"
    ),
    "projectionId": "projection:synthetic-agent-coding-foundations-v1",
    "policyVersion": "public-research-admission/1",
    "planStatus": "PROPOSED",
    "uidTriggerProfileId": "neo4j-concept-uid-envelope/v1",
}
_EXPECTED_ENVIRONMENT = {
    "profile": "neo4j-community-2026.02.3-concept-uid-envelope-v1",
    "databaseProduct": "Neo4j Kernel",
    "databaseVersion": "2026.02.3",
    "databaseEdition": "community",
    "queryLanguage": "Cypher 5",
    "availableCypherComponentVersions": ["5", "25"],
    "connector": "Neo4j MCP",
    "hostIdentifierRecorded": False,
    "credentialsRecorded": False,
    "privateEndpointRecorded": False,
}
_EXPECTED_OPERATIONS = {
    "readCommand": "Neo4j MCP read_neo4j_cypher",
    "writeCommand": "Neo4j MCP write_neo4j_cypher",
    "schemaCommand": "CALL apoc.cypher.runSchema(statement,{})",
    "commandSemantics": (
        "Connector operations and repository query identifiers are recorded; "
        "no shell argv, host, endpoint, or credential value is retained"
    ),
}
_EXPECTED_SCHEMA_EVENTS = [
    {
        "eventId": "schema-direct-ddl-classifier-rejection",
        "command": "Neo4j MCP write_neo4j_cypher with direct CREATE CONSTRAINT",
        "target": "PublicResearchEvidence(evidenceId)",
        "outcome": "REJECTED_NO_MUTATION",
        "dataNodeMutationCount": 0,
    },
    {
        "eventId": "schema-temporary-evidence-label-constraint-created",
        "command": "CALL apoc.cypher.runSchema(statement,{})",
        "target": "public_research_evidence_id_unique on PublicResearchEvidence(evidenceId)",
        "outcome": "SUCCEEDED",
        "dataNodeMutationCount": 0,
    },
    {
        "eventId": "schema-concept-constraint-created",
        "command": "CALL apoc.cypher.runSchema(statement,{})",
        "target": "public_research_concept_evidence_id_unique on Concept(evidenceId)",
        "outcome": "SUCCEEDED",
        "dataNodeMutationCount": 0,
    },
    {
        "eventId": "schema-temporary-evidence-label-constraint-dropped",
        "command": "CALL apoc.cypher.runSchema(statement,{})",
        "target": "public_research_evidence_id_unique",
        "outcome": "SUCCEEDED",
        "dataNodeMutationCount": 0,
    },
]
_EXPECTED_ACTIVATION_ATTEMPTS = [
    {
        "attemptId": "candidate-parser-rejection",
        "queryProfile": "pre-repair candidate using an indexed path expression",
        "outcome": "REJECTED_NO_MUTATION",
        "reasonCode": "CYPHER_PARSER_REJECTED_INDEXED_PATH_EXPRESSION",
        "postAttemptEvidenceNodeCount": 0,
        "exactApplySummaryReturned": False,
        "atomicityClaim": False,
    },
    {
        "attemptId": "candidate-schema-freeze-rejection",
        "queryProfile": (
            "fixed DML candidate with unregistered PublicResearchEvidence physical label"
        ),
        "outcome": "REJECTED_NO_MUTATION",
        "reasonCode": "SCHEMA_FREEZE_UNREGISTERED_LABEL",
        "postAttemptEvidenceNodeCount": 0,
        "exactApplySummaryReturned": False,
        "atomicityClaim": False,
    },
    {
        "attemptId": "concept-only-fixed-dml",
        "queryProfile": (
            "unfrozen Concept-only fixed-DML predecessor; exact query bytes and "
            "source closure unavailable"
        ),
        "outcome": "CONNECTOR_MUTATION_METADATA_RETURNED",
        "reasonCode": "NONE",
        "postAttemptEvidenceNodeCount": 2,
        "exactApplySummaryReturned": False,
        "atomicityClaim": False,
    },
]
_EXPECTED_SUCCESSFUL_ACTIVATION = {
    "authorizationScope": (
        "Create only the two repository-pinned public-research Concept nodes; "
        "no rollback, publication, package, release, or production authority"
    ),
    "queryId": None,
    "queryDigest": None,
    "queryIdentityClosureFrozen": False,
    "physicalWriteLabel": "Concept",
    "connectorMetadata": {"nodesCreated": 2, "propertiesSet": 30},
    "initialCreateSourceClosureFrozen": False,
    "exactFirstApplySummaryReturned": False,
    "firstApplyAtomicityClaim": False,
}
_EXPECTED_UID_ENVELOPE_FIELDS = {
    "profileId": "neo4j-concept-uid-envelope/v1",
    "triggerName": "t_uid_forward_gate_v3",
    "queryId": "NEO4J_PUBLIC_RESEARCH_UID_TRIGGER_QUERY",
    "installed": True,
    "paused": False,
    "phase": "afterAsync",
    "matchingQueryProfileCount": 1,
    "observationBoundary": (
        "The preflight matches one installed, unpaused afterAsync trigger by "
        "bounded query-text predicates, and final reconciliation verifies the UID "
        "trio; this is not synchronous transaction, trigger semantic, durability, "
        "or global UID uniqueness proof"
    ),
}
_EXPECTED_CONSTRAINT = {
    "name": "public_research_concept_evidence_id_unique",
    "type": "NODE_PROPERTY_UNIQUENESS",
    "entityType": "NODE",
    "labelsOrTypes": ["Concept"],
    "properties": ["evidenceId"],
    "ownedIndex": "public_research_concept_evidence_id_unique",
}
_EXPECTED_INDEX = {
    "name": "public_research_concept_evidence_id_unique",
    "type": "RANGE",
    "entityType": "NODE",
    "labelsOrTypes": ["Concept"],
    "properties": ["evidenceId"],
    "state": "ONLINE",
    "populationPercent": 100,
    "owningConstraint": "public_research_concept_evidence_id_unique",
}
_EXPECTED_EXACT_STATE_INSPECTION = {
    "mode": "read-only final-plan exact-state inspection",
    "conflictCount": 0,
    "wouldCreateCount": 0,
    "unchangedCount": 2,
    "observedEntryCount": 2,
    "writeExecuted": False,
}
_EXPECTED_REAPPLY_FIELDS = {
    "queryId": "NEO4J_PUBLIC_RESEARCH_APPLY_QUERY",
    "writeCallCount": 1,
    "connectorResultKind": "empty-object",
    "exactApplySummaryReturned": False,
    "reportedMutationCount": None,
    "reportedConflictCount": None,
    "reportedCreatedCount": None,
    "reportedUnchangedCount": None,
    "mutationClaim": False,
}
_EXPECTED_COMPATIBILITY_FIELDS = {
    "executorRunObserved": False,
    "receiptIsLiveExecutorEvidence": False,
    "observationSource": (
        "read-only equivalent inspection plus separately supplied schema, "
        "trigger, and exact-state observations"
    ),
}
_EXPECTED_RECEIPT_FIELDS = {
    "kind": "PublicResearchActivationReceipt",
    "schemaVersion": "public-research-activation-receipt/1",
    "status": "PROPOSED",
    "uidTriggerProfileId": "neo4j-concept-uid-envelope/v1",
    "createdCount": 0,
    "unchangedCount": 2,
    "conflictCount": 0,
    "verifiedEntryCount": 2,
    "createdEvidenceIds": [],
    "liveNeo4jWriteCallCount": 1,
    "liveNeo4jReadCallCount": 4,
    "rollbackProposalIsAuthorization": False,
    "externalExactlyOnceClaim": False,
    "completionClaim": False,
}
_EXPECTED_FINAL_FIELDS = {
    "observationCompositionOrdered": False,
    "observationCompositionBoundary": (
        "The pure verifier compatibility receipt was constructed from a read-only "
        "equivalent inspection and separately supplied constraint, index, "
        "trigger-profile, and exact-state observations; it is not the connector "
        "reapply result or one proven ordered or atomic executor run"
    ),
    "producerSoleVerifier": False,
}
_EXPECTED_SIDE_EFFECTS = {
    "successfulSchemaMutationCount": 3,
    "createdDataNodeCount": 2,
    "initialCreateWriteCallCount": 1,
    "verifiedReapplyWriteCallCount": 1,
    "verifiedReapplyMutationCount": None,
    "finalRelationshipCount": 0,
    "rollbackExecuted": False,
    "rollbackWriteCallCount": 0,
    "modelCallCount": 0,
}
_EXPECTED_CLAIM_BOUNDARY = {
    "boundedObservationMeasured": True,
    "repositoryClaimPromoted": False,
    "externalExactlyOnce": False,
    "firstApplyAtomicity": False,
    "completion": False,
    "productionReadiness": False,
    "publication": False,
    "enginePromotion": False,
    "comparativeEfficacy": False,
    "globalUidUniqueness": False,
    "uidPreflightToctouClosed": False,
    "rollbackAuthorized": False,
    "rollbackAbaSafe": False,
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _activation_rows(
    manifest: dict[str, Any], projection_digest: str
) -> list[dict[str, Any]]:
    sources = {source["sourceId"]: source for source in manifest["sources"]}
    rows: list[dict[str, Any]] = []
    for entry in sorted(manifest["entries"], key=lambda item: item["evidenceId"]):
        content = {
            key: entry[key]
            for key in (
                "evidenceId",
                "sourceId",
                "title",
                "summary",
                "semanticLabels",
                "revision",
            )
        }
        _require(
            _canonical_digest(content) == entry["contentDigest"],
            f"fixture content digest drift: {entry['evidenceId']}",
        )
        normalized_name = entry["title"].lower().strip()
        for whitespace in ("\t", "\n", "\r", "\f"):
            normalized_name = normalized_name.replace(whitespace, " ")
        for _ in range(3):
            normalized_name = normalized_name.replace("  ", " ")
        source = sources[entry["sourceId"]]
        rows.append(
            {
                "evidenceId": entry["evidenceId"],
                "projectionId": manifest["projectionId"],
                "visibilityScope": manifest["scope"],
                "publicResearchTitle": entry["title"],
                "publicResearchSummary": entry["summary"],
                "name": entry["title"],
                "description": entry["summary"],
                "uid": ("sym:Concept:" + normalized_name.replace(" ", "_"))[:200],
                "uid_scheme": "v1",
                "uid_source": "forward-gate-v3",
                "sourceRef": source["uri"],
                "revision": entry["revision"],
                "semanticLabels": entry["semanticLabels"],
                "contentDigest": entry["contentDigest"],
                "policyVersion": manifest["policyVersion"],
                "manifestDigest": _canonical_digest(manifest),
                "projectionDigest": projection_digest,
            }
        )
    return rows


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _require_fields(
    actual: dict[str, Any], expected: dict[str, Any], message: str
) -> None:
    selected = {key: actual[key] for key in expected}
    _require(selected == expected, message)


def _query_constants(source: str) -> dict[str, str]:
    pattern = re.compile(
        r"export const (NEO4J_PUBLIC_RESEARCH_[A-Z_]+) = `\n(.*?)\n`\.trim\(\);",
        re.DOTALL,
    )
    constants = {name: body.strip() for name, body in pattern.findall(source)}
    # The checked-in trigger query has one compile-time interpolation. Resolve it
    # from the independently recorded, schema-constrained evidence value so the
    # Python verifier hashes the bytes exported by TypeScript, not its source
    # template spelling.
    return constants


def validate_evidence(
    root: Path = ROOT,
    *,
    evidence_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    schema = _load(root / SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    evidence = copy.deepcopy(
        evidence_override
        if evidence_override is not None
        else _load(root / EVIDENCE_PATH)
    )
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
            evidence
        ),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    _require(
        not errors,
        "evidence schema failure: " + "; ".join(error.message for error in errors),
    )

    _require_fields(evidence, _EXPECTED_DOCUMENT_FIELDS, "document semantics drift")
    window = evidence["observationWindow"]
    _require_fields(
        window, _EXPECTED_WINDOW_FIELDS, "observation window semantics drift"
    )
    timestamps = [
        datetime.fromisoformat(window[key].replace("Z", "+00:00"))
        for key in (
            "startedAt",
            "successfulCreateObservedAt",
            "finalVerificationStartedAt",
            "finalVerificationEndedAt",
        )
    ]
    _require(timestamps == sorted(timestamps), "observation chronology is inconsistent")

    repository = evidence["repositoryState"]
    _require_fields(
        repository, _EXPECTED_REPOSITORY_FIELDS, "repository semantics drift"
    )
    source_path = root / repository["activationSourcePath"]
    source_bytes = source_path.read_bytes()
    _require(
        _sha256_bytes(source_bytes) == repository["currentFinalActivationSourceSha256"],
        "activation source digest drift",
    )
    _require(
        repository["initialCreateSourceClosureFrozen"] is False
        and repository["initialCreateSourceSha256"] is None,
        "initial create source closure was overstated",
    )

    subject = evidence["subject"]
    _require_fields(subject, _EXPECTED_SUBJECT_FIELDS, "subject semantics drift")
    _require(
        evidence["environment"] == _EXPECTED_ENVIRONMENT, "environment semantics drift"
    )
    _require(
        evidence["operations"] == _EXPECTED_OPERATIONS, "operation semantics drift"
    )

    provisioning = evidence["schemaProvisioning"]
    _require(
        provisioning["initialRelevantConstraintCount"] == 0
        and provisioning["events"] == _EXPECTED_SCHEMA_EVENTS
        and provisioning["finalConstraint"] == _EXPECTED_CONSTRAINT
        and provisioning["finalBackingIndex"] == _EXPECTED_INDEX,
        "schema provisioning semantics drift",
    )
    _require(
        evidence["activationAttempts"] == _EXPECTED_ACTIVATION_ATTEMPTS,
        "activation attempt semantics drift",
    )
    successful = evidence["successfulActivation"]
    _require(
        successful == _EXPECTED_SUCCESSFUL_ACTIVATION,
        "successful activation semantics drift",
    )
    _require_fields(
        evidence["uidEnvelope"],
        _EXPECTED_UID_ENVELOPE_FIELDS,
        "UID envelope semantics drift",
    )
    _require(
        evidence["sideEffects"] == _EXPECTED_SIDE_EFFECTS,
        "side-effect semantics drift",
    )
    _require(
        evidence["claimBoundary"] == _EXPECTED_CLAIM_BOUNDARY,
        "claim boundary semantics drift",
    )

    fixture_path = root / subject["fixturePath"]
    manifest = _load(fixture_path)
    _require(
        _sha256_bytes(fixture_path.read_bytes()) == subject["fixtureFileSha256"],
        "public-research fixture file digest drift",
    )
    manifest_digest = _canonical_digest(manifest)
    _require(manifest_digest == subject["manifestDigest"], "manifest digest drift")
    normalized_sources = sorted(manifest["sources"], key=lambda item: item["sourceId"])
    normalized_entries = sorted(
        manifest["entries"], key=lambda item: item["evidenceId"]
    )
    projection_preimage = {
        "kind": "PublicResearchProjection",
        "schemaVersion": "public-research-projection/1",
        "status": "PROPOSED",
        "projectionId": manifest["projectionId"],
        "scope": manifest["scope"],
        "policyVersion": manifest["policyVersion"],
        "sources": normalized_sources,
        "entries": normalized_entries,
    }
    projection_digest = _canonical_digest(projection_preimage)
    _require(
        projection_digest == subject["projectionDigest"], "projection digest drift"
    )

    source = source_bytes.decode("utf-8")
    _require(
        subject["planDigest"] in source, "activation plan pin is not owned by source"
    )
    _require(
        subject["uidTriggerProfileId"] in source,
        "UID trigger profile is not owned by source",
    )

    queries = _query_constants(source)
    trigger_name = "NEO4J_PUBLIC_RESEARCH_UID_TRIGGER_QUERY"
    if trigger_name in queries:
        queries[trigger_name] = queries[trigger_name].replace(
            "${UID_TRIGGER_PROFILE_ID}", subject["uidTriggerProfileId"]
        )
    expected_names = {
        "constraint": "NEO4J_PUBLIC_RESEARCH_CONSTRAINT_QUERY",
        "index": "NEO4J_PUBLIC_RESEARCH_INDEX_QUERY",
        "uidTrigger": "NEO4J_PUBLIC_RESEARCH_UID_TRIGGER_QUERY",
        "apply": "NEO4J_PUBLIC_RESEARCH_APPLY_QUERY",
        "readback": "NEO4J_PUBLIC_RESEARCH_READBACK_QUERY",
        "rollback": "NEO4J_PUBLIC_RESEARCH_ROLLBACK_QUERY",
    }
    for receipt_key, constant_name in expected_names.items():
        _require(
            constant_name in queries, f"missing source query constant: {constant_name}"
        )
        _require(
            _canonical_digest(queries[constant_name])
            == subject["queryDigests"][receipt_key],
            f"query digest drift: {receipt_key}",
        )

    rows = _activation_rows(manifest, projection_digest)
    evidence_ids = [row["evidenceId"] for row in rows]
    _require(evidence_ids == subject["evidenceIds"], "evidence identity order drift")
    physical_labels = ["Concept"]
    plan_preimage = {
        "kind": "PublicResearchActivationPlan",
        "schemaVersion": "public-research-activation-plan/1",
        "status": "PROPOSED",
        "database": subject["database"],
        "projectionId": subject["projectionId"],
        "policyVersion": subject["policyVersion"],
        "manifestDigest": manifest_digest,
        "projectionDigest": projection_digest,
        "physicalLabels": physical_labels,
        "uidTriggerProfileId": subject["uidTriggerProfileId"],
        "constraintQueryDigest": subject["queryDigests"]["constraint"],
        "indexQueryDigest": subject["queryDigests"]["index"],
        "uidTriggerQueryDigest": subject["queryDigests"]["uidTrigger"],
        "applyQueryDigest": subject["queryDigests"]["apply"],
        "readbackQueryDigest": subject["queryDigests"]["readback"],
        "rollbackQueryDigest": subject["queryDigests"]["rollback"],
        "rows": rows,
        "params": {"rows": rows, "physicalLabels": physical_labels},
        "readbackParams": {"evidenceIds": evidence_ids},
        "requestedEntryCount": 2,
        "externalExactlyOnceClaim": False,
        "completionClaim": False,
    }
    _require(
        _canonical_digest(plan_preimage) == subject["planDigest"], "plan digest drift"
    )

    final = evidence["finalVerification"]
    _require_fields(final, _EXPECTED_FINAL_FIELDS, "final verification semantics drift")
    _require(
        final["schemaReadback"]
        == {"constraint": _EXPECTED_CONSTRAINT, "index": _EXPECTED_INDEX},
        "schema readback semantics drift",
    )
    _require(
        final["exactStateInspection"] == _EXPECTED_EXACT_STATE_INSPECTION,
        "exact-state inspection semantics drift",
    )
    observed_nodes = final["nodes"]
    _require(len(observed_nodes) == len(rows), "node readback count drift")
    for observed, expected in zip(observed_nodes, rows, strict=True):
        _require(observed["evidenceId"] == expected["evidenceId"], "node order drift")
        _require(
            observed["observedProperties"] == expected,
            f"exact node bytes drift: {expected['evidenceId']}",
        )
        _require(
            observed["globalIdentityMatchCount"] == 1
            and observed["conceptIdentityMatchCount"] == 1
            and observed["isolatedConceptMatchCount"] == 1
            and observed["observedPropertyCount"] == len(expected)
            and observed["physicalLabels"] == physical_labels
            and observed["physicalLabelCount"] == len(physical_labels)
            and observed["relationshipCount"] == 0,
            f"node envelope drift: {expected['evidenceId']}",
        )
    expected_fulltext = [(row["evidenceId"], f'name:"{row["name"]}"') for row in rows]
    _require(
        [(item["evidenceId"], item["query"]) for item in final["fulltext"]]
        == expected_fulltext,
        "full-text evidence binding drift",
    )
    _require(
        all(
            item["indexName"] == "ontology_fulltext"
            and item["score"] > 0
            and item["expectedEvidenceMatchCount"] == 1
            and item["wrongEvidenceAdmittedCount"] == 0
            for item in final["fulltext"]
        ),
        "full-text observation semantics drift",
    )

    reapply = final["reapplyObservation"]
    _require_fields(reapply, _EXPECTED_REAPPLY_FIELDS, "reapply semantics drift")
    _require(
        reapply["queryDigest"] == subject["queryDigests"]["apply"],
        "reapply query binding drift",
    )
    compatibility = final["derivedVerifierCompatibilityReceipt"]
    _require_fields(
        compatibility,
        _EXPECTED_COMPATIBILITY_FIELDS,
        "compatibility receipt semantics drift",
    )
    derived = compatibility["receipt"]
    _require_fields(derived, _EXPECTED_RECEIPT_FIELDS, "receipt semantics drift")
    _require(
        evidence["uidEnvelope"]["queryDigest"] == subject["queryDigests"]["uidTrigger"]
        and evidence["uidEnvelope"]["profileId"] == subject["uidTriggerProfileId"],
        "UID envelope binding drift",
    )
    expected_rollback_proposal_digest = _canonical_digest(
        {
            "schemaVersion": "public-research-rollback-token/1",
            "planDigest": subject["planDigest"],
            "createdEvidenceIds": [],
        }
    )
    _require(
        derived["planDigest"] == subject["planDigest"]
        and derived["uidTriggerProfileId"] == subject["uidTriggerProfileId"]
        and derived["uidTriggerQueryDigest"] == subject["queryDigests"]["uidTrigger"]
        and derived["rollbackProposalDigest"] == expected_rollback_proposal_digest
        and derived["createdCount"] == final["exactStateInspection"]["wouldCreateCount"]
        and derived["unchangedCount"] == final["exactStateInspection"]["unchangedCount"]
        and derived["conflictCount"] == final["exactStateInspection"]["conflictCount"],
        "compatibility receipt cross-field binding drift",
    )
    receipt = {
        "applyQueryDigest": subject["queryDigests"]["apply"],
        "completionClaim": False,
        "conflictCount": derived["conflictCount"],
        "constraintQueryDigest": subject["queryDigests"]["constraint"],
        "createdCount": derived["createdCount"],
        "createdEvidenceIds": derived["createdEvidenceIds"],
        "database": subject["database"],
        "externalExactlyOnceClaim": False,
        "indexQueryDigest": subject["queryDigests"]["index"],
        "kind": derived["kind"],
        "liveNeo4jReadCallCount": derived["liveNeo4jReadCallCount"],
        "liveNeo4jWriteCallCount": derived["liveNeo4jWriteCallCount"],
        "manifestDigest": subject["manifestDigest"],
        "mode": "live-neo4j-activation",
        "planDigest": derived["planDigest"],
        "policyVersion": subject["policyVersion"],
        "projectionDigest": subject["projectionDigest"],
        "projectionId": subject["projectionId"],
        "readbackQueryDigest": subject["queryDigests"]["readback"],
        "requestedEntryCount": len(subject["evidenceIds"]),
        "rollbackProposalDigest": derived["rollbackProposalDigest"],
        "rollbackProposalIsAuthorization": False,
        "rollbackQueryDigest": subject["queryDigests"]["rollback"],
        "schemaVersion": derived["schemaVersion"],
        "status": derived["status"],
        "uidTriggerProfileId": derived["uidTriggerProfileId"],
        "uidTriggerQueryDigest": derived["uidTriggerQueryDigest"],
        "unchangedCount": derived["unchangedCount"],
        "verifiedEntryCount": derived["verifiedEntryCount"],
    }
    _require(
        _canonical_digest(receipt) == derived["receiptDigest"],
        "derived exact-state receipt digest drift",
    )

    return {
        "kind": "PublicResearchLiveEvidenceValidationReport",
        "status": "PASS",
        "epistemicStatus": evidence["epistemicStatus"],
        "repositoryClaimStatus": evidence["repositoryClaimStatus"],
        "nodes": len(final["nodes"]),
        "queries": len(expected_names),
        "receiptDigest": derived["receiptDigest"],
        "externalExactlyOnceClaim": evidence["claimBoundary"]["externalExactlyOnce"],
        "enginePromotion": evidence["claimBoundary"]["enginePromotion"],
    }


def main() -> None:
    print(json.dumps(validate_evidence(), separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
