from __future__ import annotations

import copy
import importlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

SPEC = importlib.util.spec_from_file_location("validate_m1", ROOT / "scripts/validate_m1.py")
assert SPEC and SPEC.loader
M1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M1)
PACKAGE = importlib.import_module("flrh_kernel")
KERNEL = importlib.import_module("flrh_kernel.kernel")


class M1KernelTests(unittest.TestCase):
    def _base_document(self, name: str = "observe-no-effect") -> dict:
        return copy.deepcopy(M1.load_json("fixtures/m1/cases.json")["base_inputs"][name])

    def test_normative_schemas_manifest_and_canonical_oracle(self) -> None:
        counts = M1.validate_schemas_and_manifest()
        self.assertEqual(counts["m1_schemas"], 4)
        self.assertEqual(counts["m1_bindings"], 3)
        canonical = M1.validate_canonical_oracle()
        self.assertEqual(canonical["m1_canonical_reject"], 4)
        self.assertEqual(M1.validate_result_goldens()["m1_exact_result_goldens"], 2)

    def test_package_root_exposes_only_the_transition_waist(self) -> None:
        self.assertEqual(PACKAGE.__all__, ["step_f"])
        self.assertIs(PACKAGE.step_f, KERNEL.step_f)
        for helper in ("CanonicalizationError", "canonical_bytes", "canonical_digest"):
            self.assertFalse(hasattr(PACKAGE, helper), helper)

    def test_manifest_closure_rejects_missing_dependencies_and_status_drift(self) -> None:
        manifest = M1.load_json("spec/m1-manifest.v1.json")
        contract = M1.load_json("spec/m1-kernel-contract.v1.json")

        missing_dependency = copy.deepcopy(manifest)
        missing_dependency["inherited_normative_dependencies"].pop()
        with self.assertRaisesRegex(AssertionError, "dependency set/order drift"):
            M1._validate_manifest_closure(missing_dependency, contract)

        proposed_manifest = copy.deepcopy(manifest)
        proposed_contract = copy.deepcopy(contract)
        proposed_manifest["status"] = "PROPOSED_PENDING_MEASUREMENT"
        proposed_contract["status"] = "PROPOSED_PENDING_MEASUREMENT"
        with self.assertRaisesRegex(AssertionError, "cannot report measured conformance"):
            M1._validate_manifest_closure(proposed_manifest, proposed_contract)

    def test_success_rejection_equivalence_and_sensitivity_corpus(self) -> None:
        counts = M1.validate_cases()
        self.assertEqual(counts["m1_success_cases"], 7)
        self.assertEqual(counts["m1_success_input_schema_checks"], 7)
        self.assertEqual(counts["m1_rejection_cases"], 19)
        self.assertEqual(counts["m1_equivalence_pairs"], 1)
        self.assertEqual(counts["m1_sensitivity_mutations"], 7)

    def test_two_step_replay_and_two_clean_processes(self) -> None:
        replay = M1.validate_replay_sequences()
        self.assertEqual(replay["m1_replay_steps"], 2)
        processes = M1.validate_clean_process_replay()
        self.assertEqual(processes["m1_clean_process_comparisons"], 27)
        self.assertEqual(processes["m1_byte_mismatches"], 0)

    def test_nested_aliases_do_not_survive_the_boundary(self) -> None:
        document = self._base_document()
        shared = ["capture", "verify"]
        observation = document["accepted_event"]["payload"]["observation"]
        observation["alias_a"] = shared
        observation["alias_b"] = shared
        before = copy.deepcopy(document)
        result = KERNEL.step_f(document["snapshot"], document["accepted_event"])
        self.assertEqual(document, before)
        frozen_result = M1.kernel_canonical_bytes(result)
        shared.append("mutated-after-call")
        self.assertEqual(M1.kernel_canonical_bytes(result), frozen_result)

    def test_effect_proposals_are_inert_and_authority_free(self) -> None:
        document = self._base_document("observe-with-effect")
        result = KERNEL.step_f(document["snapshot"], document["accepted_event"])
        self.assertEqual(result["kind"], "FTransition")
        self.assertEqual(len(result["effect_proposals"]), 1)
        M1._check_no_h_authority(result)
        serialized = M1.kernel_canonical_bytes(result["effect_proposals"][0])
        round_tripped = json.loads(serialized)
        self.assertEqual(round_tripped["kind"], "EffectProposal")
        self.assertFalse(any(callable(value) for value in round_tripped.values()))

    def test_guard_before_import_and_real_control_mutants(self) -> None:
        counts = M1.validate_ambient_authority()
        self.assertEqual(counts["m1_ambient_guard_processes"], 2)
        self.assertEqual(counts["m1_ambient_guard_categories"], 8)
        self.assertEqual(counts["m1_audit_guard_self_tests"], 3)
        self.assertEqual(counts["m1_guard_self_tests"], 11)
        self.assertEqual(counts["m1_import_metadata_checks"], 10)
        self.assertEqual(counts["m1_control_mutants_detected"], 8)
        self.assertEqual(counts["m1_kernel_ambient_attempts"], 0)

    def test_kernel_import_surface_excludes_ambient_and_framework_modules(self) -> None:
        counts = M1.validate_static_authority_surface()
        self.assertEqual(counts["m1_manifested_implementation_files"], 3)
        self.assertEqual(counts["m1_forbidden_static_surfaces"], 0)

    def test_typed_rejection_regressions(self) -> None:
        tuple_document = self._base_document()
        tuple_document["accepted_event"]["payload"]["observation"]["ordered_steps"] = ("a", "b")
        tuple_result = KERNEL.step_f(tuple_document["snapshot"], tuple_document["accepted_event"])
        self.assertEqual(tuple_result["code"], "CANONICALIZATION_VIOLATION")

        surrogate_document = self._base_document()
        surrogate_document["accepted_event"]["payload"]["observation"]["status"] = "\ud800"
        surrogate_result = KERNEL.step_f(
            surrogate_document["snapshot"], surrogate_document["accepted_event"]
        )
        self.assertEqual(surrogate_result["code"], "CANONICALIZATION_VIOLATION")

        date_document = self._base_document()
        date_document["accepted_event"]["occurred_at"] = "2026-99-99T99:99:99Z"
        date_result = KERNEL.step_f(date_document["snapshot"], date_document["accepted_event"])
        self.assertEqual(date_result["code"], "MALFORMED_ACCEPTED_EVENT")

    def test_value_complete_identities_and_reserved_kind_payload_order(self) -> None:
        corpus = M1.load_json("fixtures/m1/cases.json")
        for mutation_id in (
            "sensitivity-logical-time",
            "sensitivity-effect-risk",
            "sensitivity-effect-preconditions",
            "sensitivity-effect-correlation",
        ):
            mutation = next(item for item in corpus["sensitivity_mutations"] if item["id"] == mutation_id)
            base_document = M1.materialize_case(
                corpus, {"input_ref": mutation["input_ref"], "mutations": []}
            )
            changed_document = M1.materialize_case(corpus, mutation)
            base = KERNEL.step_f(base_document["snapshot"], base_document["accepted_event"])
            changed = KERNEL.step_f(changed_document["snapshot"], changed_document["accepted_event"])
            for pointer in mutation["identity_paths"]:
                self.assertNotEqual(M1._at_pointer(base, pointer), M1._at_pointer(changed, pointer))

        first = M1.materialize_case(corpus, M1.find_case(corpus, "reserved-kind-action-order-a"))
        second = M1.materialize_case(corpus, M1.find_case(corpus, "reserved-kind-action-order-b"))
        first_result = KERNEL.step_f(first["snapshot"], first["accepted_event"])
        second_result = KERNEL.step_f(second["snapshot"], second["accepted_event"])
        self.assertNotEqual(first_result["transition_digest"], second_result["transition_digest"])


if __name__ == "__main__":
    unittest.main()
