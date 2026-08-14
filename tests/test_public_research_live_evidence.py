from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.validate_public_research_live_evidence import (
    EVIDENCE_PATH,
    ROOT,
    SCHEMA_PATH,
    validate_evidence,
)


class PublicResearchLiveEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.evidence = json.loads((ROOT / EVIDENCE_PATH).read_text(encoding="utf-8"))

    def test_checked_in_evidence_passes_offline_validation(self) -> None:
        report = validate_evidence()
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["nodes"], 2)
        self.assertEqual(report["queries"], 6)
        self.assertFalse(report["externalExactlyOnceClaim"])
        self.assertFalse(report["enginePromotion"])

    def test_validation_does_not_require_the_current_claim_ledger(self) -> None:
        dependencies = [
            EVIDENCE_PATH,
            SCHEMA_PATH,
            Path(self.evidence["repositoryState"]["activationSourcePath"]),
            Path(self.evidence["subject"]["fixturePath"]),
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            isolated_root = Path(temporary_directory)
            for relative_path in dependencies:
                destination = isolated_root / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative_path, destination)

            report = validate_evidence(isolated_root)

        self.assertEqual(report["status"], "PASS")

    def test_reapply_result_is_separate_from_read_only_compatibility_receipt(
        self,
    ) -> None:
        final = self.evidence["finalVerification"]
        self.assertNotIn("derivedExactStateReceipt", final)
        reapply = final["reapplyObservation"]
        self.assertEqual(reapply["connectorResultKind"], "empty-object")
        self.assertFalse(reapply["exactApplySummaryReturned"])
        self.assertIsNone(reapply["reportedMutationCount"])
        compatibility = final["derivedVerifierCompatibilityReceipt"]
        self.assertFalse(compatibility["executorRunObserved"])
        self.assertEqual(
            compatibility["observationSource"],
            "read-only equivalent inspection plus separately supplied schema, trigger, and exact-state observations",
        )

    def test_schema_rejects_malformed_shape_before_semantic_validation(self) -> None:
        candidate = copy.deepcopy(self.evidence)
        del candidate["claimBoundary"]["enginePromotion"]

        with self.assertRaisesRegex(RuntimeError, r"^evidence schema failure:"):
            validate_evidence(evidence_override=candidate)

    def test_structurally_valid_semantic_drift_reaches_python_validator(self) -> None:
        candidate = copy.deepcopy(self.evidence)
        candidate["environment"]["databaseVersion"] = "2099.01"

        with self.assertRaisesRegex(RuntimeError, "environment semantics drift"):
            validate_evidence(evidence_override=candidate)

    def test_claim_and_binding_mutants_fail_closed(self) -> None:
        def mutate(path: tuple[str | int, ...], value: object) -> dict[str, object]:
            candidate = copy.deepcopy(self.evidence)
            target = candidate
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            return candidate

        mutants = {
            "repository-promotion": mutate(("repositoryClaimStatus",), "MEASURED"),
            "ordered-observation": mutate(
                ("finalVerification", "observationCompositionOrdered"), True
            ),
            "reversed-observation-window": mutate(
                ("observationWindow", "finalVerificationStartedAt"),
                "2026-08-12T07:30:00Z",
            ),
            "external-exactly-once": mutate(
                ("claimBoundary", "externalExactlyOnce"), True
            ),
            "engine-promotion": mutate(("claimBoundary", "enginePromotion"), True),
            "source-digest": mutate(
                ("repositoryState", "currentFinalActivationSourceSha256"),
                "sha256:" + "0" * 64,
            ),
            "plan-digest": mutate(("subject", "planDigest"), "sha256:" + "1" * 64),
            "query-digest": mutate(
                ("subject", "queryDigests", "apply"), "sha256:" + "2" * 64
            ),
            "uid-envelope-query-digest": mutate(
                ("uidEnvelope", "queryDigest"), "sha256:" + "4" * 64
            ),
            "receipt-digest": mutate(
                (
                    "finalVerification",
                    "derivedVerifierCompatibilityReceipt",
                    "receipt",
                    "receiptDigest",
                ),
                "sha256:" + "3" * 64,
            ),
            "invented-reapply-mutation-count": mutate(
                ("finalVerification", "reapplyObservation", "reportedMutationCount"),
                0,
            ),
            "compatibility-plan-digest": mutate(
                (
                    "finalVerification",
                    "derivedVerifierCompatibilityReceipt",
                    "receipt",
                    "planDigest",
                ),
                "sha256:" + "5" * 64,
            ),
            "rollback-proposal-digest": mutate(
                (
                    "finalVerification",
                    "derivedVerifierCompatibilityReceipt",
                    "receipt",
                    "rollbackProposalDigest",
                ),
                "sha256:" + "6" * 64,
            ),
            "promoted-compatibility-receipt": mutate(
                (
                    "finalVerification",
                    "derivedVerifierCompatibilityReceipt",
                    "executorRunObserved",
                ),
                True,
            ),
            "invented-initial-query-digest": mutate(
                ("successfulActivation", "queryDigest"),
                self.evidence["subject"]["queryDigests"]["apply"],
            ),
            "invented-initial-apply-summary": mutate(
                ("activationAttempts", 2, "exactApplySummaryReturned"), True
            ),
            "extra-physical-label": mutate(
                ("finalVerification", "nodes", 0, "physicalLabels"),
                ["Concept", "Technology"],
            ),
            "relationship": mutate(
                ("finalVerification", "nodes", 0, "relationshipCount"), 1
            ),
            "changed-public-summary": mutate(
                (
                    "finalVerification",
                    "nodes",
                    0,
                    "observedProperties",
                    "publicResearchSummary",
                ),
                "Synthetic but not the repository-pinned summary.",
            ),
            "rollback-authority": mutate(("claimBoundary", "rollbackAuthorized"), True),
        }
        for name, mutant in mutants.items():
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                validate_evidence(evidence_override=mutant)


if __name__ == "__main__":
    unittest.main()
