"""Direct L-to-R projection seam conformance and adversarial tests."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from flrh_logic import solve_l
from flrh_lr_seam import project_lr
from flrh_reactive import step_r
from lr_seam_fixtures import (
    actual_chain_inputs,
    canonical_bytes,
    digest,
    fact_delta_input,
    fresh,
    load_cases,
    materialize_binding_profile,
    materialize_proposal,
    materialize_query,
    materialize_query_batch,
    materialize_r_profile,
    materialize_requirement,
    truth_fixture_inputs,
)
from lr_seam_oracle import project_expected
import validate_lr_seam as lr_validator


LR_ADMISSION_EVIDENCE = [
    "spec/lr-seam-contract.v1.json",
    "spec/lr-seam-manifest.v1.json",
    "fixtures/lr-seam/cases.json",
    "fixtures/lr-seam/golden/eligible.projection.json",
    "fixtures/lr-seam/golden/mismatch.rejection.json",
    "scripts/lr_seam_oracle.py",
    "scripts/check_lr_seam_semantic_mutants.py",
    "scripts/validate_lr_seam.py",
    "tests/test_lr_seam.py",
    "docs/LR_SEAM.md",
]
LR_CI_ORDER = [
    "python scripts/validate_m0.py",
    "python scripts/validate_m1.py",
    "python scripts/validate_m2.py",
    "python scripts/validate_m3.py",
    "python scripts/validate_lr_seam.py",
]
CURRENT_GOVERNANCE_PATHS = (
    ".github/workflows/ci.yml",
    "spec/lr-seam-contract.v1.json",
    "spec/lr-seam-manifest.v1.json",
    "spec/claims.v1.json",
    "spec/engine-decision.v1.json",
)
PROMOTION_PATHS = (
    "README.md",
    "docs/ARCHITECTURE.md",
    "docs/CLAIMS_AND_STATUS.md",
    "docs/ROADMAP.md",
    "docs/SEMANTICS.md",
    "docs/LR_SEAM.md",
    "docs/adr/0001-defer-engine-verdict.md",
    "spec/engine-decision.v1.json",
    ".github/workflows/ci.yml",
    "spec/lr-seam-contract.v1.json",
    "spec/lr-seam-manifest.v1.json",
    "spec/claims.v1.json",
)
TEST_PROPOSED_PROMOTION_SHA256 = {
    "README.md": "sha256:801e2d95adb2e463a7d506c1fe18c5063c010adf4cbda2a603bcae18d6359f35",
    "docs/ARCHITECTURE.md": "sha256:6a5734abeec39b7607519e7a3ace91c89a6322bd47d97e3ae819c148d7200ed7",
    "docs/CLAIMS_AND_STATUS.md": "sha256:53ef53d0ec7f2d5ecdf1ae67ca4cdeb56a96c1a866dd99d72efd109facc8b946",
    "docs/ROADMAP.md": "sha256:9c757531a4309ce7d797a5f447f617254b8a2834c4614e199e3fc12281625ad1",
    "docs/SEMANTICS.md": "sha256:ec28119f4e4a60c46536106c10dc5915a35e38d69b649962b9e0174848da5fa9",
    "docs/LR_SEAM.md": "sha256:a697020b334a5025f794d2efdccfa3fc1bff9f68c6b2afef339e62ffc1df97e7",
    "docs/adr/0001-defer-engine-verdict.md": "sha256:19b0b1227323d8b7e6ddf008b53e9b21ffa0345255d4a79c293da01a2d3a5d7d",
    "spec/engine-decision.v1.json": "sha256:38d8149732d9f9258c89e1c141c926bbbc9f543835250b8a1eeafc4b7f792edb",
    ".github/workflows/ci.yml": "sha256:a7865d541bae7e1003efcc57b5df3442c6a321f3de12fc57feb17fa77c6f10d7",
    "spec/lr-seam-contract.v1.json": "sha256:9182eb695545decb92f2423c5ba7b1be2a426b508d90af41776c89d232a05c99",
    "spec/lr-seam-manifest.v1.json": "sha256:f2979c5907f24b2d1e9ac31489256c6107b0d44bfdb0f4994afec63d744ae9d5",
    "spec/claims.v1.json": "sha256:a956711d2c93ea4c27de95de472fd09f4140257398d9c877ece631288138040b",
}
TEST_MEASURED_PROMOTION_SHA256 = {
    "README.md": "sha256:2db649295835e9b107fc5e44d98f38c08c2cfcca13fcfff0c1969c620d2002ea",
    "docs/ARCHITECTURE.md": "sha256:94eded60e4198c2026ef1e7388b6b92560fc11d5d2716a1d7e5ef43c7e006c08",
    "docs/CLAIMS_AND_STATUS.md": "sha256:8278753c50d7941c800d9774dfe55079ebb324667cf439aa7f234dfe17664aa7",
    "docs/ROADMAP.md": "sha256:1c9b9e4b7cd65240d3a26cbd90f592cf24aef654ad8c4d15996eec1951f36504",
    "docs/SEMANTICS.md": "sha256:b54be50a202635fe392b4e8d8283996e44325c67f35563902211843abb8efe26",
    "docs/LR_SEAM.md": "sha256:8d5a67c8ddca1ac0d31ed72fa1aeb2afb9c2a4b54daf516946b22506bc32c413",
    "docs/adr/0001-defer-engine-verdict.md": "sha256:c2ea82105737c2b62af32128e802c73d92323999ca8bd02e4c11ff0bc667e284",
    "spec/engine-decision.v1.json": "sha256:14c50ee2fddb5f0788e80ae5a43aa184a454a19ccb8241f4cb76d1b33e4ef32d",
    ".github/workflows/ci.yml": "sha256:31456c64cbca63fa502ea94875f6596c556b83027504273520ff845d2783819e",
    "spec/lr-seam-contract.v1.json": "sha256:64e89e638231cdc3fb0616fc64765aa12f89f1cca7488327268ec84e75bc3bff",
    "spec/lr-seam-manifest.v1.json": "sha256:ad82acbdf5d7204cd6f7bc481f6003de9bdfba6741fb0030b769c6db4c370dca",
    "spec/claims.v1.json": "sha256:9e3ed5e8f600c41f846752c598be3e208ee8d4ab99be60d6b0b0d4f1b3397633",
}
TEST_MEASURED_GATE_REPORT = {
    "ambient_paths": 10,
    "clean_process_descriptors": [
        "replay:clean-a", "replay:clean-b",
        "ambient:clean-a", "ambient:clean-b",
        "semantic:clean-a", "semantic:clean-b",
    ],
    "clean_processes": 6,
    "inherited_nonregression_gates": 4,
    "lr_conformance_test_gate": 1,
    "manifest_artifacts": 34,
    "oracle_comparisons": 8,
    "public_step_r_publication_chains": 8,
    "rejection_paths": 24,
    "semantic_axes": 14,
    "status": "MEASURED_REFERENCE_CONFORMANCE",
    "success_paths": 8,
}
def by_id(items, identifier):
    return next(item for item in items if item["id"] == identifier)


class LRSeamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = load_cases()
        cls.bundle, cls.deltas, cls.atoms = truth_fixture_inputs()
        cls.l_result = solve_l(None, cls.bundle, cls.deltas, 7)
        if cls.l_result["kind"] != "LFixpointResult":
            raise AssertionError(cls.l_result)
        cls.r_profile = materialize_r_profile()
        cls.binding = materialize_binding_profile()

    def proposal(self, suffix, preconditions):
        return materialize_proposal(suffix, preconditions)

    def query(self, suffix, requirements, frontier=()):
        preconditions = [item["precondition_id"] for item in requirements] + list(frontier)
        return materialize_query(
            self.proposal(suffix, preconditions), requirements,
            frontier_precondition_ids=frontier,
        )

    def batch(self, queries, *, l_result=None, bundle=None, r_profile=None, binding=None):
        return materialize_query_batch(
            binding_profile=binding or self.binding,
            l_result=l_result or self.l_result,
            rule_bundle=bundle or self.bundle,
            r_profile=r_profile or self.r_profile,
            queries=queries,
        )

    def project(self, batch, *, l_result=None, bundle=None, r_profile=None, binding=None):
        return project_lr(
            l_result or self.l_result, bundle or self.bundle, r_profile or self.r_profile,
            binding or self.binding, batch,
        )

    def truth_query(self, suffix, atom_name, polarity="positive"):
        precondition = f"precondition:lr:{suffix}"
        return self.query(
            suffix,
            [materialize_requirement(precondition, self.atoms[atom_name], polarity)],
        )

    def rejection_expected(self, identifier):
        return fresh(by_id(self.corpus["rejection_cases"], identifier)["expected"])

    def write_promotion_surfaces(self, root, status):
        self.assertIn(status, {lr_validator.PROPOSED_STATUS, lr_validator.MEASURED_STATUS})
        receipt = lr_validator._parse_lr_receipt(
            (ROOT / lr_validator.LR_RECEIPT_RELATIVE).read_bytes()
        )
        revision = receipt[
            "measured_commit" if status == lr_validator.MEASURED_STATUS
            else "candidate_commit"
        ]
        for relative in PROMOTION_PATHS:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            completed = subprocess.run(
                ["git", "show", f"{revision}:{relative}"],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            target.write_bytes(completed.stdout)
        validator_target = root / "scripts/validate_lr_seam.py"
        validator_target.parent.mkdir(parents=True, exist_ok=True)
        validator_target.write_bytes((ROOT / "scripts/validate_lr_seam.py").read_bytes())
        return self.governance_inputs(root)

    def write_measured_promotion_surfaces(self, root):
        return self.write_promotion_surfaces(root, lr_validator.MEASURED_STATUS)

    def write_proposed_promotion_surfaces(self, root):
        return self.write_promotion_surfaces(root, lr_validator.PROPOSED_STATUS)

    def governance_inputs(self, root):
        manifest = json.loads(
            (root / "spec/lr-seam-manifest.v1.json").read_text(encoding="utf-8")
        )
        contract = json.loads(
            (root / "spec/lr-seam-contract.v1.json").read_text(encoding="utf-8")
        )
        ledger = json.loads(
            (root / "spec/claims.v1.json").read_text(encoding="utf-8")
        )
        claims = [
            item for item in ledger["claims"]
            if item["id"] == "lr-direct-l-to-r-projection"
        ]
        self.assertEqual(len(claims), 1)
        return manifest, contract, claims[0]

    def promotion_digest_map(self, root):
        return {
            relative: "sha256:" + hashlib.sha256((root / relative).read_bytes()).hexdigest()
            for relative in PROMOTION_PATHS
        }

    def copy_current_governance_surfaces(self, root):
        for relative in CURRENT_GOVERNANCE_PATHS:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / relative).read_bytes())
        receipt = root / lr_validator.LR_RECEIPT_RELATIVE
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_bytes((ROOT / lr_validator.LR_RECEIPT_RELATIVE).read_bytes())
        return self.governance_inputs(root)

    def receipt_payload(self, root, *, candidate_commit="1" * 40,
                        candidate_tree="2" * 40, measured_commit="3" * 40,
                        measured_tree="4" * 40):
        validator_sha = hashlib.sha256(
            (root / "scripts/validate_lr_seam.py").read_bytes()
        ).hexdigest()
        return {
            "schema_version": "lr-seam-validation-receipt/v1",
            "candidate_commit": candidate_commit,
            "candidate_tree": candidate_tree,
            "measured_commit": measured_commit,
            "measured_tree": measured_tree,
            "candidate_validator_sha256": validator_sha,
            "measured_validator_sha256": validator_sha,
            "candidate_ci_run_id": "1001",
            "candidate_ci_head_sha": candidate_commit,
            "candidate_ci_conclusion": "success",
            "measured_ci_run_id": "1002",
            "measured_ci_head_sha": measured_commit,
            "measured_ci_conclusion": "success",
            "promotion_paths": list(PROMOTION_PATHS),
            "admission_evidence": fresh(LR_ADMISSION_EVIDENCE),
            "gate_report": fresh(TEST_MEASURED_GATE_REPORT),
        }

    def receipt_bytes(self, payload):
        return (
            "# Direct L-to-R Seam Validation Receipt\n\n"
            "This follow-up receipt freezes the measured subject and exact CI readback.\n\n"
            "## Machine-readable receipt\n\n"
            "```json\n"
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            + "\n```\n"
        ).encode("utf-8")

    def add_receipt(self, root, payload):
        readme = root / "README.md"
        readme.write_bytes(readme.read_bytes() + b"LR receipt recorded.\n")
        receipt = root / lr_validator.LR_RECEIPT_RELATIVE
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_bytes(self.receipt_bytes(payload))
        return receipt

    def git(self, root, *arguments):
        completed = subprocess.run(
            ["git", *arguments], cwd=root, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr.decode("utf-8", "replace"))
        return completed.stdout.decode("utf-8").strip()

    def redigest_l_result(self, candidate):
        without_digest = fresh(candidate)
        without_digest.pop("fixpoint_digest", None)
        candidate["fixpoint_digest"] = digest({
            "kind": "M2FixpointPreimage", "contract_version": "flrh-l-kernel/1",
            "fixpoint_result_without_fixpoint_digest": without_digest,
        })
        return candidate

    def redigest_materialization(self, candidate):
        materialization = candidate["next_materialization"]
        without_digest = fresh(materialization)
        without_digest.pop("materialization_digest", None)
        materialization["materialization_digest"] = digest({
            "kind": "M2MaterializationPreimage",
            "contract_version": "flrh-l-kernel/1",
            "materialization_without_materialization_digest": without_digest,
        })
        return self.redigest_l_result(candidate)

    def test_00_fixture_root_and_independent_oracle_are_closed(self):
        self.assertEqual(
            {"schema_version", "binding_profile", "rule_bundle", "r_profile", "l_results",
             "query_batches", "success_cases", "rejection_cases", "equivalence_pairs", "goldens"},
            set(self.corpus),
        )
        source = (ROOT / "scripts/lr_seam_oracle.py").read_text(encoding="utf-8")
        for forbidden in ("flrh_lr_seam", "flrh_logic", "flrh_reactive", "canonical import"):
            self.assertNotIn(forbidden, source)

    def test_01_all_four_truth_states_and_polarity_inversion(self):
        queries = [
            self.truth_query("positive-true", "true_only"),
            self.truth_query("positive-false", "false_only"),
            self.truth_query("positive-both", "both"),
            self.truth_query("positive-neither", "neither"),
            self.truth_query("negative-true", "true_only", "negative"),
            self.truth_query("negative-false", "false_only", "negative"),
        ]
        batch = self.batch(queries)
        actual = self.project(batch)
        self.assertEqual(project_expected(self.l_result, self.bundle, self.r_profile, self.binding, batch), actual)
        statuses = {verdict["proposal_id"].split(":")[-1]: verdict["status"]
                    for verdict in actual["verdicts"]}
        self.assertEqual(
            {"positive-true": "eligible", "positive-false": "ineligible",
             "positive-both": "conflicted", "positive-neither": "ineligible",
             "negative-true": "ineligible", "negative-false": "eligible"}, statuses,
        )

    def test_02_multiple_requirement_aggregation_and_exact_evidence(self):
        requirements = [
            materialize_requirement("precondition:multi:true", self.atoms["true_only"]),
            materialize_requirement("precondition:multi:false-negative", self.atoms["false_only"], "negative"),
        ]
        eligible = self.query("multi-eligible", requirements)
        conflicted = self.query(
            "multi-conflict",
            [requirements[0], materialize_requirement("precondition:multi:both", self.atoms["both"])],
        )
        actual = self.project(self.batch([eligible, conflicted]))
        statuses = {item["proposal_id"]: item for item in actual["verdicts"]}
        self.assertEqual("eligible", statuses["proposal:lr:multi-eligible"]["status"])
        self.assertEqual("conflicted", statuses["proposal:lr:multi-conflict"]["status"])
        facts = {item["state"]: item for item in self.l_result["next_materialization"]["fact_states"]}
        self.assertEqual(
            sorted(facts["TRUE_ONLY"]["positive_support_ids"] + facts["FALSE_ONLY"]["negative_support_ids"]),
            statuses["proposal:lr:multi-eligible"]["support_derivation_ids"],
        )
        self.assertEqual(
            sorted(facts["TRUE_ONLY"]["positive_support_ids"] + facts["BOTH"]["positive_support_ids"]
                   + facts["BOTH"]["negative_support_ids"]),
            statuses["proposal:lr:multi-conflict"]["support_derivation_ids"],
        )

        retracted_l = solve_l(
            self.l_result["next_materialization"], self.bundle,
            [fact_delta_input(self.atoms["true_only"], logical_time=8, polarity="positive",
                              derivation_id="derivation:lr:true", diff=-1)], 8,
        )
        conflict_l = solve_l(
            self.l_result["next_materialization"], self.bundle,
            [fact_delta_input(self.atoms["true_only"], logical_time=8, polarity="negative",
                              derivation_id="derivation:lr:true-negative")], 8,
        )
        transition_query = self.truth_query("support-transition", "true_only")
        retracted_batch = self.batch([transition_query], l_result=retracted_l)
        conflict_batch = self.batch([transition_query], l_result=conflict_l)
        retracted = self.project(retracted_batch, l_result=retracted_l)["verdicts"][0]
        conflict = self.project(conflict_batch, l_result=conflict_l)["verdicts"][0]
        self.assertEqual(("ineligible", []), (retracted["status"], retracted["support_derivation_ids"]))
        self.assertEqual("conflicted", conflict["status"])
        self.assertEqual(
            ["derivation:lr:true", "derivation:lr:true-negative"],
            conflict["support_derivation_ids"],
        )

    def test_03_exact_eligible_golden_and_oracle(self):
        query = self.truth_query("eligible-golden", "true_only")
        batch = self.batch([query])
        expected = json.loads((ROOT / "fixtures/lr-seam/golden/eligible.projection.json").read_text())
        self.assertEqual(expected, project_expected(self.l_result, self.bundle, self.r_profile, self.binding, batch))
        self.assertEqual(canonical_bytes(expected), canonical_bytes(self.project(batch)))

    def test_04_precondition_partition_orphan_duplicate_and_overlap_reject(self):
        requirement = materialize_requirement("precondition:partition:fact", self.atoms["true_only"])
        orphan = materialize_query(self.proposal("orphan", ["precondition:partition:fact", "precondition:orphan"]), [requirement])
        overlap = materialize_query(
            self.proposal("overlap", ["precondition:partition:fact"]), [requirement],
            frontier_precondition_ids=["precondition:partition:fact"],
        )
        duplicate = materialize_query(
            self.proposal("duplicate-binding", ["precondition:partition:fact"]),
            [requirement, requirement],
        )
        for identifier, query in (("reject:orphan-precondition", orphan),
                                  ("reject:overlap-precondition", overlap),
                                  ("reject:duplicate-precondition", duplicate)):
            self.assertEqual(self.rejection_expected(identifier), self.project(self.batch([query])))

    def test_05_undeclared_atom_and_missing_fact_state_reject_exactly(self):
        undeclared_atom = {"predicate": "not_declared", "subject": "lr"}
        requirement = materialize_requirement("precondition:undeclared", undeclared_atom)
        undeclared = self.query("undeclared", [requirement])
        self.assertEqual(self.rejection_expected("reject:undeclared-query-atom"), self.project(self.batch([undeclared])))

        missing_l = fresh(self.l_result)
        missing_l["next_materialization"]["fact_states"] = [
            item for item in missing_l["next_materialization"]["fact_states"]
            if item["atom"] != self.atoms["neither"]
        ]
        materialization = missing_l["next_materialization"]
        materialization_without_digest = fresh(materialization)
        materialization_without_digest.pop("materialization_digest")
        materialization["materialization_digest"] = digest({
            "kind": "M2MaterializationPreimage", "contract_version": "flrh-l-kernel/1",
            "materialization_without_materialization_digest": materialization_without_digest,
        })
        l_without_digest = fresh(missing_l)
        l_without_digest.pop("fixpoint_digest")
        missing_l["fixpoint_digest"] = digest({
            "kind": "M2FixpointPreimage", "contract_version": "flrh-l-kernel/1",
            "fixpoint_result_without_fixpoint_digest": l_without_digest,
        })
        query = materialize_query(
            self.proposal("missing", ["precondition:missing"]),
            [materialize_requirement("precondition:missing", self.atoms["neither"])],
        )
        missing_batch = self.batch([query], l_result=missing_l)
        result = self.project(missing_batch, l_result=missing_l)
        self.assertEqual(self.rejection_expected("reject:missing-fact-state"), result)

    def test_06_digest_version_profile_and_rule_dataflow_mismatches(self):
        query = self.truth_query("mismatch", "true_only")
        bad_digest = self.batch([query])
        bad_digest["query_batch_digest"] = "sha256:" + "0" * 64
        self.assertEqual(self.rejection_expected("reject:query-batch-digest"), self.project(bad_digest))

        proposal = self.proposal("version", ["precondition:version"])
        proposal["versions"]["rule_set"] = "rules/wrong/1"
        version_query = materialize_query(
            proposal, [materialize_requirement("precondition:version", self.atoms["true_only"])]
        )
        self.assertEqual(self.rejection_expected("reject:proposal-rule-version"), self.project(self.batch([version_query])))

        good_batch = self.batch([query])
        bad_binding = fresh(self.binding)
        bad_binding["profile_digest"] = "sha256:" + "5" * 64
        self.assertEqual(
            self.rejection_expected("reject:binding-profile-digest"),
            self.project(good_batch, binding=bad_binding),
        )
        bad_binding_version = fresh(self.binding)
        bad_binding_version["dataflow_version"] = "dataflow/wrong/1"
        self.assertEqual(
            self.rejection_expected("reject:binding-dataflow-version"),
            self.project(good_batch, binding=bad_binding_version),
        )
        bad_bundle = fresh(self.bundle)
        bad_bundle["rule_bundle_digest"] = "sha256:" + "2" * 64
        self.assertEqual(
            self.rejection_expected("reject:rule-bundle-digest"),
            self.project(good_batch, bundle=bad_bundle),
        )
        bad_l = fresh(self.l_result)
        bad_l["fixpoint_digest"] = "sha256:" + "3" * 64
        bad_l_batch = fresh(good_batch)
        bad_l_batch["l_fixpoint_digest"] = bad_l["fixpoint_digest"]
        self.assertEqual(
            self.rejection_expected("reject:l-fixpoint-digest"),
            self.project(bad_l_batch, l_result=bad_l),
        )
        bad_r = fresh(self.r_profile)
        bad_r["profile_digest"] = "sha256:" + "4" * 64
        self.assertEqual(
            self.rejection_expected("reject:r-profile-digest"),
            self.project(good_batch, r_profile=bad_r),
        )
        bad_query_binding = fresh(good_batch)
        bad_query_binding["binding_profile_digest"] = "sha256:" + "6" * 64
        self.assertEqual(
            self.rejection_expected("reject:query-binding-digest"),
            self.project(bad_query_binding),
        )
        noncanonical = fresh(good_batch)
        noncanonical["queries"][0]["proposal"]["destination_digest"] = 1.5
        self.assertEqual(
            self.rejection_expected("reject:canonical-float"), self.project(noncanonical)
        )

    def test_07_duplicate_proposal_rejects_atomically(self):
        query = self.truth_query("duplicate-proposal", "true_only")
        duplicate = fresh(query)
        duplicate["proposal"]["cause_id"] = "cause:lr:duplicate-second"
        duplicate = materialize_query(duplicate["proposal"], duplicate["fact_requirements"])
        result = self.project(self.batch([query, duplicate]))
        self.assertEqual(self.rejection_expected("reject:duplicate-proposal"), result)
        self.assertEqual("LRProjectionRejection", result["kind"])
        self.assertNotIn("command", result)
        self.assertNotIn("verdicts", result)

    def test_07a_set_like_invalid_query_order_has_one_diagnostic_result(self):
        undeclared = materialize_query(
            self.proposal("diag-undeclared", ["precondition:diag:undeclared"]),
            [materialize_requirement(
                "precondition:diag:undeclared", {"predicate": "undeclared_diag", "slot": "a"}
            )],
        )
        wrong_version_proposal = self.proposal("diag-version", ["precondition:diag:version"])
        wrong_version_proposal["versions"]["rule_set"] = "rules/wrong/diagnostic"
        wrong_version = materialize_query(
            wrong_version_proposal,
            [materialize_requirement("precondition:diag:version", self.atoms["true_only"])],
        )
        left = self.batch([undeclared, wrong_version])
        right = fresh(left)
        right["queries"].reverse()
        left_result, right_result = self.project(left), self.project(right)
        self.assertEqual(self.rejection_expected("reject:diagnostic-query-order-left"), left_result)
        self.assertEqual(self.rejection_expected("reject:diagnostic-query-order-right"), right_result)
        self.assertEqual(canonical_bytes(left_result), canonical_bytes(right_result))

        nested_requirements = [
            materialize_requirement("precondition:diag:nested-a", {"predicate": "undeclared_diag", "slot": "a"}),
            materialize_requirement("precondition:diag:nested-b", {"predicate": "undeclared_diag", "slot": "b"}),
        ]
        nested_left = self.batch([materialize_query(
            self.proposal("diag-nested", [item["precondition_id"] for item in nested_requirements]),
            nested_requirements,
        )])
        nested_right = fresh(nested_left)
        nested_right["queries"][0]["fact_requirements"].reverse()
        nested_left_result, nested_right_result = self.project(nested_left), self.project(nested_right)
        self.assertEqual(self.rejection_expected("reject:diagnostic-nested-order-left"), nested_left_result)
        self.assertEqual(self.rejection_expected("reject:diagnostic-nested-order-right"), nested_right_result)
        self.assertEqual(canonical_bytes(nested_left_result), canonical_bytes(nested_right_result))

    def test_07b_self_consistent_schema_invalid_l_result_rejects(self):
        query = self.truth_query("schema-invalid-l", "true_only")
        junk_delta = self.redigest_l_result(fresh(self.l_result))
        junk_delta["derived_fact_deltas"] = ["junk"]
        self.redigest_l_result(junk_delta)
        junk_batch = self.batch([query], l_result=junk_delta)
        junk_result = self.project(junk_batch, l_result=junk_delta)
        self.assertEqual(
            self.rejection_expected("reject:schema-invalid-derived-delta"), junk_result
        )

        excessive_stats = fresh(self.l_result)
        excessive_stats["stats"]["rule_firing_count"] = 1001
        self.redigest_l_result(excessive_stats)
        stats_batch = self.batch([query], l_result=excessive_stats)
        stats_result = self.project(stats_batch, l_result=excessive_stats)
        self.assertEqual(
            self.rejection_expected("reject:schema-invalid-rule-firing-count"), stats_result
        )

    def test_07c_self_consistent_duplicate_stratum_digest_rejects(self):
        bundle, deltas, proposal, requirements, frontiers = actual_chain_inputs()
        l_result = solve_l(None, bundle, deltas, 1)
        duplicate = fresh(l_result)
        duplicate["next_materialization"]["stratum_digests"].append(
            fresh(duplicate["next_materialization"]["stratum_digests"][0])
        )
        self.redigest_materialization(duplicate)
        r_profile = materialize_r_profile()
        binding = materialize_binding_profile(rule_set_version="rules/0")
        query = materialize_query(
            proposal, requirements, frontier_precondition_ids=frontiers
        )
        batch = materialize_query_batch(
            binding_profile=binding,
            l_result=duplicate,
            rule_bundle=bundle,
            r_profile=r_profile,
            queries=[query],
        )
        self.assertEqual(
            {
                "kind": "LRProjectionRejection",
                "schema_version": "flrh-lr-result/1",
                "contract_version": "flrh-lr-seam/1",
                "code": "MALFORMED_L_RESULT",
                "path": "/l_result/next_materialization/stratum_digests/1",
                "logical_time": None,
                "binding_profile_digest": None,
                "l_fixpoint_digest": None,
                "query_batch_digest": None,
                "r_profile_digest": None,
                "context": {},
            },
            project_lr(duplicate, bundle, r_profile, binding, batch),
        )

    def test_07d_self_consistent_duplicate_absence_witness_rejects(self):
        bundle, deltas, _, _, _ = actual_chain_inputs()
        duplicate = fresh(solve_l(None, bundle, deltas, 1))
        materialization = duplicate["next_materialization"]
        support = materialization["derived_supports"][0]
        atom = materialization["base_supports"][0]["literal"]["atom"]
        fact_key = digest({
            "kind": "M2FactKeyPreimage",
            "contract_version": "flrh-l-kernel/1",
            "atom": atom,
        })
        completed_stratum_digest = materialization["stratum_digests"][0]["digest"]
        witness = {
            "kind": "LAbsenceWitness",
            "fact_key": fact_key,
            "atom": fresh(atom),
            "referenced_stratum": 0,
            "completed_stratum_digest": completed_stratum_digest,
        }
        witness["witness_digest"] = digest({
            "kind": "M2AbsenceWitnessPreimage",
            "contract_version": "flrh-l-kernel/1",
            "fact_key": fact_key,
            "atom": atom,
            "referenced_stratum": 0,
            "completed_stratum_digest": completed_stratum_digest,
        })
        support["default_absence_witnesses"] = [fresh(witness), fresh(witness)]
        support["support_content_digest"] = digest({
            "kind": "M2DerivedSupportContentPreimage",
            "contract_version": "flrh-l-kernel/1",
            "profile_id": "flrh-l-ground-stratified/1",
            "literal": support["literal"],
            "rule_id": support["rule_id"],
            "rule_digest": support["rule_digest"],
            "ordered_premise_literal_keys": support["premise_literal_keys"],
            "ordered_default_absence_witness_digests": [
                witness["witness_digest"], witness["witness_digest"]
            ],
            "rule_set_version": support["rule_set_version"],
            "dataflow_version": support["dataflow_version"],
        })
        old_derivation_id = support["derivation_id"]
        support["derivation_id"] = (
            "derivation:" + support["support_content_digest"].split(":", 1)[1]
        )
        for fact in materialization["fact_states"]:
            for field in ("positive_support_ids", "negative_support_ids"):
                fact[field] = [
                    support["derivation_id"] if item == old_derivation_id else item
                    for item in fact[field]
                ]
        self.redigest_materialization(duplicate)
        r_profile = materialize_r_profile()
        binding = materialize_binding_profile(rule_set_version="rules/0")
        batch = materialize_query_batch(
            binding_profile=binding,
            l_result=duplicate,
            rule_bundle=bundle,
            r_profile=r_profile,
            queries=[],
        )
        self.assertEqual(
            {
                "kind": "LRProjectionRejection",
                "schema_version": "flrh-lr-result/1",
                "contract_version": "flrh-lr-seam/1",
                "code": "MALFORMED_L_RESULT",
                "path": (
                    "/l_result/next_materialization/derived_supports/0/"
                    "default_absence_witnesses/1"
                ),
                "logical_time": None,
                "binding_profile_digest": None,
                "l_fixpoint_digest": None,
                "query_batch_digest": None,
                "r_profile_digest": None,
                "context": {},
            },
            project_lr(duplicate, bundle, r_profile, binding, batch),
        )

    def test_07e_self_consistent_duplicate_conflict_rejects(self):
        deltas = fresh(self.deltas)
        deltas.append(fact_delta_input(
            self.atoms["true_only"], logical_time=7, polarity="negative",
            derivation_id="derivation:lr:true-extra-negative",
        ))
        duplicate = fresh(solve_l(None, self.bundle, deltas, 7))
        conflicts = duplicate["next_materialization"]["conflicts"]
        self.assertEqual(2, len(conflicts))
        duplicate["next_materialization"]["conflicts"] = [
            fresh(conflicts[0]), fresh(conflicts[0])
        ]
        self.redigest_materialization(duplicate)
        batch = self.batch([], l_result=duplicate)
        self.assertEqual(
            {
                "kind": "LRProjectionRejection",
                "schema_version": "flrh-lr-result/1",
                "contract_version": "flrh-lr-seam/1",
                "code": "MALFORMED_L_RESULT",
                "path": "/l_result/next_materialization/conflicts/1",
                "logical_time": None,
                "binding_profile_digest": None,
                "l_fixpoint_digest": None,
                "query_batch_digest": None,
                "r_profile_digest": None,
                "context": {},
            },
            self.project(batch, l_result=duplicate),
        )

    def test_07f_self_consistent_empty_base_provenance_rejects(self):
        malformed = fresh(self.l_result)
        support = malformed["next_materialization"]["base_supports"][0]
        support["provenance_delta"] = {}
        support["support_content_digest"] = digest({
            "kind": "M2BaseSupportContentPreimage",
            "contract_version": "flrh-l-kernel/1",
            "profile_id": "flrh-l-ground-stratified/1",
            "literal": support["literal"],
            "provenance_delta": {},
            "rule_set_version": support["rule_set_version"],
            "dataflow_version": support["dataflow_version"],
        })
        self.redigest_materialization(malformed)
        batch = self.batch([], l_result=malformed)
        self.assertEqual(
            {
                "kind": "LRProjectionRejection",
                "schema_version": "flrh-lr-result/1",
                "contract_version": "flrh-lr-seam/1",
                "code": "MALFORMED_L_RESULT",
                "path": (
                    "/l_result/next_materialization/base_supports/0/provenance_delta"
                ),
                "logical_time": None,
                "binding_profile_digest": None,
                "l_fixpoint_digest": None,
                "query_batch_digest": None,
                "r_profile_digest": None,
                "context": {},
            },
            self.project(batch, l_result=malformed),
        )

    def test_07g_schema_invalid_conflict_support_string_rejects(self):
        normalized = fresh(self.l_result)
        materialization = normalized["next_materialization"]
        conflict = materialization["conflicts"][0]
        positive_old = conflict["positive_support_ids"][0]
        negative_old = conflict["negative_support_ids"][0]
        for support in materialization["base_supports"]:
            if support["derivation_id"] == positive_old:
                support["derivation_id"] = "a"
            elif support["derivation_id"] == negative_old:
                support["derivation_id"] = "b"
        for fact in materialization["fact_states"]:
            fact["positive_support_ids"] = [
                "a" if item == positive_old else item
                for item in fact["positive_support_ids"]
            ]
            fact["negative_support_ids"] = [
                "b" if item == negative_old else item
                for item in fact["negative_support_ids"]
            ]
        conflict["positive_support_ids"] = ["a"]
        conflict["negative_support_ids"] = ["b"]
        conflict_preimage = {
            "kind": "M2ConflictPreimage",
            "contract_version": "flrh-l-kernel/1",
            "fact_key": conflict["fact_key"],
            "atom": conflict["atom"],
            "ordered_positive_support_ids": ["a"],
            "ordered_negative_support_ids": ["b"],
        }
        conflict["conflict_id"] = "conflict:" + digest(conflict_preimage).split(":", 1)[1]
        for field in (
            "base_supports", "derived_supports", "fact_states", "conflicts",
            "stratum_digests",
        ):
            materialization[field] = sorted(
                materialization[field], key=canonical_bytes
            )
        self.redigest_materialization(normalized)
        malformed = fresh(normalized)
        malformed["next_materialization"]["conflicts"][0]["positive_support_ids"] = "a"
        malformed["next_materialization"]["conflicts"][0]["negative_support_ids"] = "b"
        batch = self.batch([], l_result=malformed)
        self.assertEqual(
            {
                "kind": "LRProjectionRejection",
                "schema_version": "flrh-lr-result/1",
                "contract_version": "flrh-lr-seam/1",
                "code": "MALFORMED_L_RESULT",
                "path": (
                    "/l_result/next_materialization/conflicts/0/positive_support_ids"
                ),
                "logical_time": None,
                "binding_profile_digest": None,
                "l_fixpoint_digest": None,
                "query_batch_digest": None,
                "r_profile_digest": None,
                "context": {},
            },
            self.project(batch, l_result=malformed),
        )

    def test_07h_stratum_digest_coverage_and_identity_are_exact(self):
        bundle, deltas, _, _, _ = actual_chain_inputs()
        l_result = fresh(solve_l(None, bundle, deltas, 1))
        self.assertEqual("LFixpointResult", l_result["kind"])
        r_profile = materialize_r_profile()
        binding = materialize_binding_profile(rule_set_version="rules/0")

        def empty_batch(candidate):
            return materialize_query_batch(
                binding_profile=binding,
                l_result=candidate,
                rule_bundle=bundle,
                r_profile=r_profile,
                queries=[],
            )

        self.assertEqual(
            1,
            len(l_result["next_materialization"]["stratum_digests"]),
        )
        expected_digest = l_result["next_materialization"][
            "stratum_digests"
        ][0]["digest"]
        wrong_digest = "sha256:" + "0" * 64

        corrupted = fresh(l_result)
        corrupted["next_materialization"]["stratum_digests"][0][
            "digest"
        ] = wrong_digest
        self.redigest_materialization(corrupted)
        self.assertEqual(
            {
                "kind": "LRProjectionRejection",
                "schema_version": "flrh-lr-result/1",
                "contract_version": "flrh-lr-seam/1",
                "code": "DIGEST_MISMATCH",
                "path": (
                    "/l_result/next_materialization/stratum_digests/0/digest"
                ),
                "logical_time": None,
                "binding_profile_digest": None,
                "l_fixpoint_digest": None,
                "query_batch_digest": None,
                "r_profile_digest": None,
                "context": {
                    "expected": expected_digest,
                    "actual": wrong_digest,
                },
            },
            project_lr(corrupted, bundle, r_profile, binding, empty_batch(corrupted)),
        )

        missing = fresh(l_result)
        missing["next_materialization"]["stratum_digests"] = []
        self.redigest_materialization(missing)
        self.assertEqual(
            {
                "kind": "LRProjectionRejection",
                "schema_version": "flrh-lr-result/1",
                "contract_version": "flrh-lr-seam/1",
                "code": "MALFORMED_L_RESULT",
                "path": "/l_result/next_materialization/stratum_digests",
                "logical_time": None,
                "binding_profile_digest": None,
                "l_fixpoint_digest": None,
                "query_batch_digest": None,
                "r_profile_digest": None,
                "context": {},
            },
            project_lr(missing, bundle, r_profile, binding, empty_batch(missing)),
        )

    def test_07i_complete_query_fact_projection_is_required(self):
        incomplete = fresh(self.l_result)
        incomplete["next_materialization"]["fact_states"] = [
            fact
            for fact in incomplete["next_materialization"]["fact_states"]
            if fact["atom"] != self.atoms["neither"]
        ]
        self.redigest_materialization(incomplete)
        batch = materialize_query_batch(
            binding_profile=self.binding,
            l_result=incomplete,
            rule_bundle=self.bundle,
            r_profile=self.r_profile,
            queries=[],
        )
        self.assertEqual(
            {
                "kind": "LRProjectionRejection",
                "schema_version": "flrh-lr-result/1",
                "contract_version": "flrh-lr-seam/1",
                "code": "INVARIANT_VIOLATION",
                "path": "/l_result/next_materialization/fact_states",
                "logical_time": None,
                "binding_profile_digest": None,
                "l_fixpoint_digest": None,
                "query_batch_digest": None,
                "r_profile_digest": None,
                "context": {"invariant": "complete_fact_state_projection"},
            },
            project_lr(
                incomplete,
                self.bundle,
                self.r_profile,
                self.binding,
                batch,
            ),
        )

    def test_08_empty_batch_is_exact_null_command(self):
        batch = self.batch([])
        result = self.project(batch)
        self.assertEqual(project_expected(self.l_result, self.bundle, self.r_profile, self.binding, batch), result)
        self.assertEqual([], result["verdicts"])
        self.assertIsNone(result["command"])

    def test_09_query_limit_n_and_n_plus_one(self):
        queries = [self.truth_query(f"limit-{index}", "true_only") for index in range(9)]
        accepted = self.project(self.batch(queries[:8]))
        self.assertEqual("LRProjectionResult", accepted["kind"])
        rejected = self.project(self.batch(queries))
        self.assertEqual(self.rejection_expected("reject:max-queries-n-plus-one"), rejected)
        requirements = [
            materialize_requirement(f"precondition:req-limit:{index}", self.atoms["true_only"])
            for index in range(5)
        ]
        requirement_overflow = materialize_query(
            self.proposal("req-limit", [item["precondition_id"] for item in requirements]),
            requirements,
        )
        self.assertEqual(
            self.rejection_expected("reject:max-requirements-n-plus-one"),
            self.project(self.batch([requirement_overflow])),
        )

    def test_10_order_and_nested_set_permutations_are_byte_equal(self):
        left_query = self.query(
            "permutation",
            [materialize_requirement("precondition:perm:a", self.atoms["true_only"]),
             materialize_requirement("precondition:perm:b", self.atoms["false_only"], "negative")],
        )
        left_batch = self.batch([left_query, self.truth_query("permutation-two", "true_only")])
        right_batch = fresh(left_batch)
        right_batch["queries"].reverse()
        for query in right_batch["queries"]:
            query["fact_requirements"].reverse()
            query["proposal"]["preconditions"].reverse()
        self.assertNotEqual(canonical_bytes(left_batch), canonical_bytes(right_batch))
        left_oracle = project_expected(
            self.l_result, self.bundle, self.r_profile, self.binding, left_batch
        )
        right_oracle = project_expected(
            self.l_result, self.bundle, self.r_profile, self.binding, right_batch
        )
        self.assertEqual(canonical_bytes(left_oracle), canonical_bytes(right_oracle))
        self.assertEqual(canonical_bytes(self.project(left_batch)), canonical_bytes(left_oracle))
        self.assertEqual(canonical_bytes(self.project(right_batch)), canonical_bytes(right_oracle))

    def test_11_inputs_are_unchanged_outputs_unaliased_and_authority_absent(self):
        batch = self.batch([self.truth_query("immutability", "true_only")])
        inputs = [fresh(value) for value in (self.l_result, self.bundle, self.r_profile, self.binding, batch)]
        before = fresh(inputs)
        result = project_lr(*inputs)
        self.assertEqual(before, inputs)
        result["verdicts"][0]["status"] = "ineligible"
        self.assertEqual(before, inputs)
        encoded = canonical_bytes(result)
        for forbidden in (b'"frontier"', b'"demand"', b'"effect_intent"', b'"authorization"', b'"h_state"'):
            self.assertNotIn(forbidden, encoded.lower())

    def test_12_real_public_solve_project_step_strict_frontier_then_demand(self):
        bundle, deltas, proposal, requirements, frontiers = actual_chain_inputs()
        l_result = solve_l(None, bundle, deltas, 1)
        r_profile = materialize_r_profile()
        binding = materialize_binding_profile(rule_set_version="rules/0")
        query = materialize_query(proposal, requirements, frontier_precondition_ids=frontiers)
        batch = materialize_query_batch(binding_profile=binding, l_result=l_result,
                                        rule_bundle=bundle, r_profile=r_profile, queries=[query])
        projection = project_lr(l_result, bundle, r_profile, binding, batch)
        self.assertEqual("LRProjectionResult", projection["kind"])
        state = step_r(None, r_profile, projection["command"])["next_state"]
        for source in r_profile["source_ids"]:
            command = {"kind": "RAdvanceFrontier", "schema_version": "flrh-r-command/1",
                       "profile_digest": r_profile["profile_digest"],
                       "dataflow_version": r_profile["dataflow_version"],
                       "source_id": source, "low_watermark": 1}
            transition = step_r(state, r_profile, command)
            state = transition["next_state"]
        self.assertEqual([], state["ready_batches"])
        for source in r_profile["source_ids"]:
            command = {"kind": "RAdvanceFrontier", "schema_version": "flrh-r-command/1",
                       "profile_digest": r_profile["profile_digest"],
                       "dataflow_version": r_profile["dataflow_version"],
                       "source_id": source, "low_watermark": 2}
            state = step_r(state, r_profile, command)["next_state"]
        self.assertEqual(1, len(state["ready_batches"]))
        demand = {"kind": "RGrantDemand", "schema_version": "flrh-r-command/1",
                  "profile_digest": r_profile["profile_digest"],
                  "dataflow_version": r_profile["dataflow_version"], "batches": 1}
        published = step_r(state, r_profile, demand)
        self.assertEqual(1, len(published["published_batches"]))
        self.assertEqual([proposal], published["published_batches"][0]["effect_proposals"])
        self.assertEqual(projection["verdicts"], published["published_batches"][0]["eligibility_verdicts"])

    def test_13_runner_single_sequence_and_clean_process_replay(self):
        batch = self.batch([self.truth_query("eligible-golden", "true_only")])
        case = {"l_result": self.l_result, "rule_bundle": self.bundle,
                "r_profile": self.r_profile, "binding_profile": self.binding,
                "query_batch": batch}
        expected_single = canonical_bytes({"mode": "single", "result": self.project(batch)}) + b"\n"
        envelopes = [
            ({"mode": "single", **case}, expected_single),
            ({"mode": "sequence", "cases": [case, case]},
             canonical_bytes({"mode": "sequence", "results": [self.project(batch), self.project(batch)]}) + b"\n"),
        ]
        for seed, timezone, cwd in (("1", "UTC", ROOT), ("777", "Asia/Tokyo", Path(tempfile.gettempdir()))):
            for envelope, expected in envelopes:
                env = {"PATH": os.environ.get("PATH", ""), "PYTHONHASHSEED": seed,
                       "TZ": timezone, "LR_SEAM_AMBIENT_NOISE": f"noise-{seed}"}
                completed = subprocess.run(
                    [sys.executable, str(ROOT / "scripts/run_lr_seam_replay.py")],
                    input=canonical_bytes(envelope), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    cwd=cwd, env=env, check=False,
                )
                self.assertEqual(0, completed.returncode, completed.stderr)
                self.assertEqual(b"", completed.stderr)
                self.assertEqual(expected, completed.stdout)

    def test_14_full_rejection_golden(self):
        requirement = materialize_requirement("precondition:golden:fact", self.atoms["true_only"])
        query = materialize_query(
            self.proposal("golden-mismatch", ["precondition:golden:fact", "precondition:golden:orphan"]),
            [requirement],
        )
        result = self.project(self.batch([query]))
        golden = json.loads((ROOT / "fixtures/lr-seam/golden/mismatch.rejection.json").read_text())
        self.assertEqual(golden, result)
        self.assertEqual(self.rejection_expected("reject:golden-mismatch"), result)

    def test_15_proposed_and_measured_promotion_states_are_exactly_frozen(self):
        self.assertEqual(PROMOTION_PATHS, tuple(lr_validator.LR_PROMOTION_PATHS))
        self.assertEqual(TEST_PROPOSED_PROMOTION_SHA256,
                         lr_validator.PROPOSED_PROMOTION_SHA256)
        self.assertEqual(TEST_MEASURED_PROMOTION_SHA256,
                         lr_validator.MEASURED_PROMOTION_SHA256)
        ci = (ROOT / ".github/workflows/ci.yml").read_bytes()
        self.assertIn(b"fetch-depth: 0\n", ci)
        self.assertNotIn(b"fetch-depth: 3\n", ci)
        for status, expected in (
            (lr_validator.PROPOSED_STATUS, TEST_PROPOSED_PROMOTION_SHA256),
            (lr_validator.MEASURED_STATUS, TEST_MEASURED_PROMOTION_SHA256),
        ):
            with self.subTest(status=status), tempfile.TemporaryDirectory(
                prefix="flrh-lr-governance-state-"
            ) as raw:
                root = Path(raw)
                inputs = self.write_promotion_surfaces(root, status)
                self.assertEqual(expected, self.promotion_digest_map(root))
                lr_validator._validate_promotion_governance(
                    root, *inputs, verify_receipt_git=False
                )

    def test_15a_arbitrary_unrelated_governance_evolution_is_admitted(self):
        with tempfile.TemporaryDirectory(prefix="flrh-lr-current-governance-") as raw:
            root = Path(raw)
            self.copy_current_governance_surfaces(root)

            ledger_path = root / "spec/claims.v1.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            lr_claim = fresh(next(
                item for item in ledger["claims"]
                if item["id"] == "lr-direct-l-to-r-projection"
            ))
            ledger["updated_at"] = "2099-01-01T00:00:00Z"
            ledger["claims"] = [
                {
                    "id": "unrelated-governance",
                    "statement": "An unrelated assertion may evolve independently.",
                    "epistemic_status": "ACCEPTED",
                    "disposition": "retired",
                    "scope": "outside the LR admission boundary",
                    "evidence": [],
                    "falsifiers": ["This entry becomes relevant to LR admission."],
                },
                lr_claim,
            ]
            ledger_path.write_text(
                json.dumps(ledger, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )

            decision_path = root / "spec/engine-decision.v1.json"
            decision_path.write_text(
                json.dumps({
                    "verdict": "defer",
                    "unrelated_policy": {"revision": 99, "notes": ["free to evolve"]},
                }),
                encoding="utf-8",
            )
            ci_path = root / ".github/workflows/ci.yml"
            ci_path.write_text(
                """name: unrelated governance evolution
jobs:
  admission:
    steps:
      - run: echo unrelated-before
      - run: python scripts/validate_m0.py
      - run: echo unrelated-between-zero-and-one
      - run: python scripts/validate_m1.py
      - run: python scripts/validate_m2.py
      - run: echo unrelated-between-two-and-three
      - run: python scripts/validate_m3.py
      - run: python scripts/validate_lr_seam.py
      - run: echo unrelated-after
  independent:
    steps:
      - run: echo independently-evolving-command
""",
                encoding="utf-8",
            )

            self.assertFalse((root / "README.md").exists())
            self.assertFalse((root / "docs/ROADMAP.md").exists())
            self.assertFalse((root / "docs/adr/0001-defer-engine-verdict.md").exists())
            lr_validator._validate_promotion_governance(
                root, *self.governance_inputs(root), verify_receipt_git=False
            )

    def test_15b_current_governance_rejects_lr_status_and_evidence_drift(self):
        for attack in ("claim-downgrade", "evidence-drift", "coherent-downgrade"):
            with self.subTest(attack=attack), tempfile.TemporaryDirectory(
                prefix=f"flrh-lr-state-{attack}-"
            ) as raw:
                root = Path(raw)
                self.copy_current_governance_surfaces(root)
                ledger_path = root / "spec/claims.v1.json"
                ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
                claim = next(
                    item for item in ledger["claims"]
                    if item["id"] == "lr-direct-l-to-r-projection"
                )
                if attack == "claim-downgrade":
                    claim["epistemic_status"] = "PROPOSED"
                    expected = "LR claim-ledger status drift"
                elif attack == "evidence-drift":
                    claim["evidence"] = list(reversed(claim["evidence"]))
                    expected = (
                        "measured LR claim evidence differs from frozen admission evidence"
                    )
                else:
                    claim["epistemic_status"] = "PROPOSED"
                    for relative in (
                        "spec/lr-seam-manifest.v1.json",
                        "spec/lr-seam-contract.v1.json",
                    ):
                        path = root / relative
                        document = json.loads(path.read_text(encoding="utf-8"))
                        document["status"] = lr_validator.PROPOSED_STATUS
                        path.write_text(json.dumps(document), encoding="utf-8")
                    expected = "measured LR promotion receipt drift"
                ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
                with self.assertRaisesRegex(AssertionError, f"^{expected}$"):
                    lr_validator._validate_promotion_governance(
                        root, *self.governance_inputs(root), verify_receipt_git=False
                    )

    def test_15c_current_governance_rejects_engine_promotion_and_lr_ci_drift(self):
        for attack in ("engine", "ci-removal", "ci-order", "ci-duplicate"):
            with self.subTest(attack=attack), tempfile.TemporaryDirectory(
                prefix=f"flrh-lr-boundary-{attack}-"
            ) as raw:
                root = Path(raw)
                self.copy_current_governance_surfaces(root)
                if attack == "engine":
                    path = root / "spec/engine-decision.v1.json"
                    decision = json.loads(path.read_text(encoding="utf-8"))
                    decision["verdict"] = "engine"
                    path.write_text(json.dumps(decision), encoding="utf-8")
                    expected = "LR admission must preserve the deferred engine verdict"
                else:
                    path = root / ".github/workflows/ci.yml"
                    ci = path.read_text(encoding="utf-8")
                    lr_line = "      - run: python scripts/validate_lr_seam.py\n"
                    self.assertEqual(1, ci.count(lr_line))
                    if attack == "ci-removal":
                        ci = ci.replace(lr_line, "", 1)
                    elif attack == "ci-order":
                        predecessor = "      - run: python scripts/validate_m3.py\n"
                        self.assertEqual(1, ci.count(predecessor))
                        ci = ci.replace(predecessor + lr_line, lr_line + predecessor, 1)
                    else:
                        ci = ci.replace(lr_line, lr_line + lr_line, 1)
                    path.write_text(ci, encoding="utf-8")
                    expected = "measured LR CI command/order drift"
                with self.assertRaisesRegex(AssertionError, f"^{expected}$"):
                    lr_validator._validate_promotion_governance(
                        root, *self.governance_inputs(root), verify_receipt_git=False
                    )

    def test_16_promotion_arguments_are_bound_to_on_disk_state(self):
        with tempfile.TemporaryDirectory(prefix="flrh-lr-argument-binding-") as raw:
            root = Path(raw)
            manifest, contract, claim = self.write_measured_promotion_surfaces(root)
            for label, index in (("manifest", 0), ("contract", 1), ("claim", 2)):
                with self.subTest(label=label):
                    mutated = [fresh(manifest), fresh(contract), fresh(claim)]
                    mutated[index]["x_argument_drift"] = True
                    with self.assertRaisesRegex(
                        AssertionError,
                        rf"^{label} argument differs from on-disk LR promotion file$",
                    ):
                        lr_validator._validate_promotion_governance(
                            root, *mutated, verify_receipt_git=False
                        )

            type_drift = fresh(contract)
            type_drift["limits"]["max_queries_ceiling"] = 1024.0
            with self.assertRaisesRegex(
                AssertionError,
                "^contract argument differs from on-disk LR promotion file$",
            ):
                lr_validator._validate_promotion_governance(
                    root, manifest, type_drift, claim, verify_receipt_git=False
                )

            ledger_path = root / "spec/claims.v1.json"
            ledger = json.loads(ledger_path.read_bytes())
            disk_claim = next(
                item for item in ledger["claims"]
                if item["id"] == "lr-direct-l-to-r-projection"
            )
            disk_claim["evidence"].append(lr_validator.LR_RECEIPT_RELATIVE)
            ledger_path.write_bytes(
                (json.dumps(ledger, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            )
            with self.assertRaisesRegex(
                AssertionError,
                "^claim argument differs from on-disk LR promotion file$",
            ):
                lr_validator._validate_promotion_governance(
                    root, manifest, contract, claim, verify_receipt_git=False
                )

    def test_17_live_governance_is_not_byte_or_prose_bound(self):
        with tempfile.TemporaryDirectory(prefix="flrh-lr-semantic-governance-") as raw:
            root = Path(raw)
            self.write_measured_promotion_surfaces(root)
            for relative in set(PROMOTION_PATHS) - set(CURRENT_GOVERNANCE_PATHS):
                (root / relative).unlink()
            for relative in (
                "spec/lr-seam-manifest.v1.json",
                "spec/lr-seam-contract.v1.json",
                "spec/claims.v1.json",
                "spec/engine-decision.v1.json",
            ):
                path = root / relative
                document = json.loads(path.read_text(encoding="utf-8"))
                path.write_text(
                    json.dumps(document, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8",
                )
            lr_validator._validate_promotion_governance(
                root, *self.governance_inputs(root), verify_receipt_git=False
            )

    def test_18_followup_receipt_is_structurally_exact_without_live_doc_markers(self):
        with tempfile.TemporaryDirectory(prefix="flrh-lr-receipt-") as raw:
            root = Path(raw)
            inputs = self.write_measured_promotion_surfaces(root)
            readme = root / "README.md"
            payload = self.receipt_payload(root)
            receipt = self.add_receipt(root, payload)
            receipt_bytes = receipt.read_bytes()
            readme.write_text("arbitrary unrelated live prose\n", encoding="utf-8")
            lr_validator._validate_promotion_governance(
                root, *inputs, verify_receipt_git=False
            )
            readme.unlink()
            lr_validator._validate_promotion_governance(
                root, *inputs, verify_receipt_git=False
            )

            attacks = []
            attacks.append(("empty-receipt", b""))
            attacks.append((
                "wrong-h1",
                receipt_bytes.replace(
                    b"# Direct L-to-R Seam Validation Receipt",
                    b"# Wrong Receipt",
                    1,
                ),
            ))
            extra_payload = fresh(payload)
            extra_payload["extra"] = True
            attacks.append(("extra-key", self.receipt_bytes(extra_payload)))
            boolean_payload = fresh(payload)
            boolean_payload["gate_report"]["lr_conformance_test_gate"] = True
            attacks.append(("boolean-count", self.receipt_bytes(boolean_payload)))
            reused_run_payload = fresh(payload)
            reused_run_payload["measured_ci_run_id"] = (
                reused_run_payload["candidate_ci_run_id"]
            )
            attacks.append(("reused-ci-run", self.receipt_bytes(reused_run_payload)))
            for label, candidate_receipt in attacks:
                with self.subTest(label=label):
                    if receipt.exists() or receipt.is_symlink():
                        receipt.unlink()
                    receipt.write_bytes(candidate_receipt)
                    with self.assertRaisesRegex(
                        AssertionError, "^measured LR promotion receipt drift$"
                    ):
                        lr_validator._validate_promotion_governance(
                            root, *inputs, verify_receipt_git=False
                        )

            if receipt.exists() or receipt.is_symlink():
                receipt.unlink()
            unrelated = root / "unrelated.txt"
            unrelated.write_text("unrelated\n", encoding="utf-8")
            receipt.symlink_to(unrelated)
            with self.assertRaisesRegex(
                AssertionError, "^measured LR promotion receipt drift$"
            ):
                lr_validator._validate_promotion_governance(
                    root, *inputs, verify_receipt_git=False
                )
            receipt.unlink()

    def test_19_committed_receipt_proves_exact_candidate_measured_receipt_ancestry(self):
        with tempfile.TemporaryDirectory(prefix="flrh-lr-receipt-git-") as raw:
            root = Path(raw)
            root.mkdir(exist_ok=True)
            self.git(root, "init", "-b", "main")
            self.write_proposed_promotion_surfaces(root)
            self.git(root, "add", "--", *PROMOTION_PATHS,
                     "scripts/validate_lr_seam.py")
            self.git(root, "-c", "user.name=LR Test", "-c",
                     "user.email=lr@example.invalid", "commit", "-m", "candidate")
            candidate = self.git(root, "rev-parse", "HEAD")
            candidate_tree = self.git(root, "rev-parse", "HEAD^{tree}")

            self.write_measured_promotion_surfaces(root)
            self.git(root, "add", "--", *PROMOTION_PATHS)
            self.git(root, "-c", "user.name=LR Test", "-c",
                     "user.email=lr@example.invalid", "commit", "-m", "measured")
            measured = self.git(root, "rev-parse", "HEAD")
            measured_tree = self.git(root, "rev-parse", "HEAD^{tree}")

            inputs = self.governance_inputs(root)
            payload = self.receipt_payload(
                root, candidate_commit=candidate, candidate_tree=candidate_tree,
                measured_commit=measured, measured_tree=measured_tree,
            )
            self.add_receipt(root, payload)
            self.git(root, "add", "--", "README.md", lr_validator.LR_RECEIPT_RELATIVE)
            self.git(root, "-c", "user.name=LR Test", "-c",
                     "user.email=lr@example.invalid", "commit", "-m", "receipt")
            lr_validator._validate_promotion_governance(
                root, *inputs, verify_receipt_git=True
            )

            (root / "unexpected.txt").write_text("drift\n", encoding="utf-8")
            self.git(root, "add", "--", "unexpected.txt")
            self.git(root, "-c", "user.name=LR Test", "-c",
                     "user.email=lr@example.invalid", "commit", "-m", "extra")
            lr_validator._validate_promotion_governance(
                root, *inputs, verify_receipt_git=True
            )

    def test_20_receipt_binds_historical_candidate_and_measured_bytes(self):
        for drift_stage in ("candidate", "measured"):
            with self.subTest(drift_stage=drift_stage), tempfile.TemporaryDirectory(
                prefix=f"flrh-lr-history-{drift_stage}-"
            ) as raw:
                root = Path(raw)
                root.mkdir(exist_ok=True)
                self.git(root, "init", "-b", "main")
                self.write_proposed_promotion_surfaces(root)
                if drift_stage == "candidate":
                    with (root / "README.md").open("ab") as handle:
                        handle.write(b"CANDIDATE-NOT-FROZEN\n")
                self.git(root, "add", "--", *PROMOTION_PATHS,
                         "scripts/validate_lr_seam.py")
                self.git(root, "-c", "user.name=LR Test", "-c",
                         "user.email=lr@example.invalid", "commit", "-m", "candidate")
                candidate = self.git(root, "rev-parse", "HEAD")
                candidate_tree = self.git(root, "rev-parse", "HEAD^{tree}")

                self.write_measured_promotion_surfaces(root)
                if drift_stage == "measured":
                    with (root / "README.md").open("ab") as handle:
                        handle.write(b"MEASURED-NOT-FROZEN\n")
                self.git(root, "add", "--", *PROMOTION_PATHS)
                self.git(root, "-c", "user.name=LR Test", "-c",
                         "user.email=lr@example.invalid", "commit", "-m", "measured")
                measured = self.git(root, "rev-parse", "HEAD")
                measured_tree = self.git(root, "rev-parse", "HEAD^{tree}")

                self.write_measured_promotion_surfaces(root)
                inputs = self.governance_inputs(root)
                payload = self.receipt_payload(
                    root, candidate_commit=candidate, candidate_tree=candidate_tree,
                    measured_commit=measured, measured_tree=measured_tree,
                )
                self.add_receipt(root, payload)
                self.git(root, "add", "--", "README.md",
                         lr_validator.LR_RECEIPT_RELATIVE)
                self.git(root, "-c", "user.name=LR Test", "-c",
                         "user.email=lr@example.invalid", "commit", "-m", "receipt")
                with self.assertRaisesRegex(
                    AssertionError, "^measured LR promotion receipt git drift$"
                ):
                    lr_validator._validate_promotion_governance(
                        root, *inputs, verify_receipt_git=True
                    )

    def test_21_published_receipt_cannot_be_removed_from_later_history(self):
        with tempfile.TemporaryDirectory(prefix="flrh-lr-receipt-ratchet-") as raw:
            root = Path(raw)
            root.mkdir(exist_ok=True)
            self.git(root, "init", "-b", "main")
            self.write_proposed_promotion_surfaces(root)
            self.git(root, "add", "--", *PROMOTION_PATHS,
                     "scripts/validate_lr_seam.py")
            self.git(root, "-c", "user.name=LR Test", "-c",
                     "user.email=lr@example.invalid", "commit", "-m", "candidate")
            candidate = self.git(root, "rev-parse", "HEAD")
            candidate_tree = self.git(root, "rev-parse", "HEAD^{tree}")
            self.write_measured_promotion_surfaces(root)
            self.git(root, "add", "--", *PROMOTION_PATHS)
            self.git(root, "-c", "user.name=LR Test", "-c",
                     "user.email=lr@example.invalid", "commit", "-m", "measured")
            measured = self.git(root, "rev-parse", "HEAD")
            measured_tree = self.git(root, "rev-parse", "HEAD^{tree}")
            inputs = self.governance_inputs(root)
            self.add_receipt(
                root,
                self.receipt_payload(
                    root, candidate_commit=candidate, candidate_tree=candidate_tree,
                    measured_commit=measured, measured_tree=measured_tree,
                ),
            )
            self.git(root, "add", "--", "README.md",
                     lr_validator.LR_RECEIPT_RELATIVE)
            self.git(root, "-c", "user.name=LR Test", "-c",
                     "user.email=lr@example.invalid", "commit", "-m", "receipt")

            self.write_measured_promotion_surfaces(root)
            (root / lr_validator.LR_RECEIPT_RELATIVE).unlink()
            self.git(root, "add", "-u", "--", "README.md",
                     lr_validator.LR_RECEIPT_RELATIVE)
            self.git(root, "-c", "user.name=LR Test", "-c",
                     "user.email=lr@example.invalid", "commit", "-m", "remove receipt")
            with self.assertRaisesRegex(
                AssertionError, "^measured LR promotion receipt git drift$"
            ):
                lr_validator._validate_promotion_governance(
                    root, *inputs, verify_receipt_git=True
                )

            proposed_inputs = self.write_proposed_promotion_surfaces(root)
            self.git(root, "add", "--", *PROMOTION_PATHS)
            self.git(root, "-c", "user.name=LR Test", "-c",
                     "user.email=lr@example.invalid", "commit", "-m",
                     "downgrade to proposed")
            with self.assertRaisesRegex(
                AssertionError, "^measured LR promotion receipt git drift$"
            ):
                lr_validator._validate_promotion_governance(
                    root, *proposed_inputs, verify_receipt_git=True
                )

            for index in range(3):
                later = root / f"later-{index}.txt"
                later.write_text(f"later {index}\n", encoding="utf-8")
                self.git(root, "add", "--", later.name)
                self.git(root, "-c", "user.name=LR Test", "-c",
                         "user.email=lr@example.invalid", "commit", "-m",
                         f"later {index}")
            with tempfile.TemporaryDirectory(
                prefix="flrh-lr-shallow-ratchet-"
            ) as shallow_raw:
                shallow = Path(shallow_raw) / "checkout"
                completed = subprocess.run(
                    ["git", "clone", "--depth", "3", f"file://{root}", str(shallow)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                )
                self.assertEqual(0, completed.returncode, completed.stderr)
                self.assertEqual(
                    "true", self.git(shallow, "rev-parse", "--is-shallow-repository")
                )
                shallow_inputs = self.governance_inputs(shallow)
                with self.assertRaisesRegex(
                    AssertionError, "^measured LR promotion receipt git drift$"
                ):
                    lr_validator._validate_promotion_governance(
                        shallow, *shallow_inputs, verify_receipt_git=True
                    )

    def test_22_immutable_receipt_allows_clean_descendants_only(self):
        with tempfile.TemporaryDirectory(prefix="flrh-lr-receipt-descendant-") as raw:
            root = Path(raw)
            root.mkdir(exist_ok=True)
            self.git(root, "init", "-b", "main")
            self.write_proposed_promotion_surfaces(root)
            frozen = root / "src/flrh_lr_seam/seam.py"
            frozen.parent.mkdir(parents=True, exist_ok=True)
            frozen.write_bytes((ROOT / "src/flrh_lr_seam/seam.py").read_bytes())
            self.git(root, "add", "--", *PROMOTION_PATHS,
                     "scripts/validate_lr_seam.py", "src/flrh_lr_seam/seam.py")
            self.git(root, "-c", "user.name=LR Test", "-c",
                     "user.email=lr@example.invalid", "commit", "-m", "candidate")
            candidate = self.git(root, "rev-parse", "HEAD")
            candidate_tree = self.git(root, "rev-parse", "HEAD^{tree}")

            self.write_measured_promotion_surfaces(root)
            self.git(root, "add", "--", *PROMOTION_PATHS)
            self.git(root, "-c", "user.name=LR Test", "-c",
                     "user.email=lr@example.invalid", "commit", "-m", "measured")
            measured = self.git(root, "rev-parse", "HEAD")
            measured_tree = self.git(root, "rev-parse", "HEAD^{tree}")
            receipt = self.add_receipt(
                root,
                self.receipt_payload(
                    root, candidate_commit=candidate, candidate_tree=candidate_tree,
                    measured_commit=measured, measured_tree=measured_tree,
                ),
            )
            receipt_bytes = receipt.read_bytes()
            self.git(root, "add", "--", "README.md",
                     lr_validator.LR_RECEIPT_RELATIVE)
            self.git(root, "-c", "user.name=LR Test", "-c",
                     "user.email=lr@example.invalid", "commit", "-m", "receipt")

            for relative in PROMOTION_PATHS:
                (root / relative).write_bytes((ROOT / relative).read_bytes())
            inputs = self.governance_inputs(root)
            validator = root / "scripts/validate_lr_seam.py"
            validator.write_bytes(validator.read_bytes() + b"# descendant evolution\n")
            (root / "later.txt").write_text("later\n", encoding="utf-8")
            self.git(
                root, "add", "--", *PROMOTION_PATHS,
                "scripts/validate_lr_seam.py", "later.txt",
            )
            self.git(root, "-c", "user.name=LR Test", "-c",
                     "user.email=lr@example.invalid", "commit", "-m", "descendant")
            descendant = self.git(root, "rev-parse", "HEAD")

            lr_validator._validate_promotion_governance(
                root, *inputs, verify_receipt_git=True
            )

            self.git(root, "switch", "-c", "frozen-drift")
            frozen.write_bytes(frozen.read_bytes() + b"# drift\n")
            self.git(root, "add", "--", "src/flrh_lr_seam/seam.py")
            self.git(root, "-c", "user.name=LR Test", "-c",
                     "user.email=lr@example.invalid", "commit", "-m", "frozen drift")
            with self.assertRaisesRegex(
                AssertionError, "^measured LR promotion receipt git drift$"
            ):
                lr_validator._validate_promotion_governance(
                    root, *inputs, verify_receipt_git=True
                )

            self.git(root, "switch", "--detach", descendant)
            self.git(root, "switch", "-c", "receipt-edit-revert")
            receipt.write_bytes(receipt_bytes.replace(b"follow-up", b"changed", 1))
            self.git(root, "add", "--", lr_validator.LR_RECEIPT_RELATIVE)
            self.git(root, "-c", "user.name=LR Test", "-c",
                     "user.email=lr@example.invalid", "commit", "-m", "edit receipt")
            receipt.write_bytes(receipt_bytes)
            self.git(root, "add", "--", lr_validator.LR_RECEIPT_RELATIVE)
            self.git(root, "-c", "user.name=LR Test", "-c",
                     "user.email=lr@example.invalid", "commit", "-m", "restore receipt")
            with self.assertRaisesRegex(
                AssertionError, "^measured LR promotion receipt git drift$"
            ):
                lr_validator._validate_promotion_governance(
                    root, *inputs, verify_receipt_git=True
                )

            self.git(root, "switch", "--detach", descendant)
            self.git(root, "switch", "-c", "receipt-delete-readd")
            receipt.unlink()
            self.git(root, "add", "-u", "--", lr_validator.LR_RECEIPT_RELATIVE)
            self.git(root, "-c", "user.name=LR Test", "-c",
                     "user.email=lr@example.invalid", "commit", "-m", "delete receipt")
            receipt.write_bytes(receipt_bytes)
            self.git(root, "add", "--", lr_validator.LR_RECEIPT_RELATIVE)
            self.git(root, "-c", "user.name=LR Test", "-c",
                     "user.email=lr@example.invalid", "commit", "-m", "readd receipt")
            with self.assertRaisesRegex(
                AssertionError, "^measured LR promotion receipt git drift$"
            ):
                lr_validator._validate_promotion_governance(
                    root, *inputs, verify_receipt_git=True
                )

            with tempfile.TemporaryDirectory(prefix="flrh-lr-descendant-shallow-") as clone_raw:
                shallow = Path(clone_raw) / "checkout"
                completed = subprocess.run(
                    ["git", "clone", "--depth", "2", f"file://{root}", str(shallow)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                )
                self.assertEqual(0, completed.returncode, completed.stderr)
                shallow_inputs = self.governance_inputs(shallow)
                with self.assertRaisesRegex(
                    AssertionError, "^measured LR promotion receipt git drift$"
                ):
                    lr_validator._validate_promotion_governance(
                        shallow, *shallow_inputs, verify_receipt_git=True
                    )


if __name__ == "__main__":
    unittest.main()
