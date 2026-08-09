from __future__ import annotations

import copy
import importlib
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from m2_fixtures import load_cases, materialize_case, materialize_delta_input, materialize_rule_bundle, materialize_sequence_step
from m2il_oracle import canonical_bytes, pinned_public_m2_reference
from m2il_oracle import naive_semantics, naive_derived_delta
from m2il_fixtures import load_cases as load_m2il_cases, materialize_step as materialize_m2il_step


class M2ILIncrementalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.m2 = load_cases()
        cls.cases = json.loads((ROOT / "fixtures/m2il/cases.json").read_text(encoding="utf-8"))
        cls.m2il = load_m2il_cases()

    def sut(self):
        return importlib.import_module("flrh_logic_incremental")

    def test_public_boundary_is_exactly_one_symbol(self) -> None:
        module = self.sut()
        self.assertEqual(module.__all__, ["step_incremental_l"])
        self.assertTrue(callable(module.step_incremental_l))

    def test_noop_reuses_without_executing_cached_rule_bodies(self) -> None:
        module = self.sut()
        bundle, initial = materialize_m2il_step(self.m2il, "disjoint-chain-bootstrap-noop-unrelated-retract", 0, 1)
        first = module.step_incremental_l(None, bundle, initial, 1)
        self.assertEqual(first["kind"], "LPersistentLStep")
        calls = []
        with mock.patch("flrh_logic_incremental.incremental._evaluate_rule_body", side_effect=lambda *args, **kwargs: calls.append(args) or False), mock.patch("flrh_logic_incremental.incremental._construct_derived_support", side_effect=AssertionError("cached provenance executed")):
            second = module.step_incremental_l(first["next_checkpoint"], bundle, [], 2)
        self.assertEqual(calls, [])
        self.assertEqual(second["reuse_receipt"]["executed_candidate_body_evaluations"], 0)
        self.assertEqual(second["reuse_receipt"]["candidate_cache_hits"], 4)
        oracle = pinned_public_m2_reference(first["fixpoint_result"]["next_materialization"], bundle, [], 2)
        self.assertEqual(canonical_bytes(second["fixpoint_result"]), canonical_bytes(oracle))

    def test_candidate_source_never_calls_m2_full_derive(self) -> None:
        import ast
        tree = ast.parse((ROOT / "src/flrh_logic_incremental/incremental.py").read_text(encoding="utf-8"))
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"_derive", "_parse_prior"}]
        self.assertEqual(calls, [])

    def test_direct_candidate_hot_path_cannot_reach_m2_full_derive(self) -> None:
        import flrh_logic_incremental.incremental as implementation
        bundle, deltas = materialize_m2il_step(self.m2il, "disjoint-chain-bootstrap-noop-unrelated-retract", 0, 1)
        first = self.sut().step_incremental_l(None, bundle, deltas, 1)
        with mock.patch("flrh_logic.logic._derive", side_effect=AssertionError("candidate reached full derive")), mock.patch("flrh_logic.logic._parse_prior", side_effect=AssertionError("candidate reached prior full derive")), mock.patch("flrh_logic_incremental.incremental._evaluate_rule_body", side_effect=AssertionError("candidate cache hit evaluated body")), mock.patch("flrh_logic_incremental.incremental._construct_derived_support", side_effect=AssertionError("candidate cache hit built provenance")):
            candidate, cache, counts = implementation._candidate_fixpoint(first["fixpoint_result"]["next_materialization"], bundle, [], 2, first["next_checkpoint"]["evaluation_cache"])
        self.assertEqual(candidate["kind"], "LFixpointResult")
        self.assertEqual((counts["candidate_cache_hits"], counts["executed_candidate_body_evaluations"]), (4, 0))
        self.assertEqual(len(cache), 4)

    def test_every_accepted_prefix_is_exact_public_m2(self) -> None:
        module = self.sut()
        for sequence_id in ("two-support-retain-then-remove", "positive-cycle-delete"):
            sequence = next(item for item in self.m2["sequences"] if item["id"] == sequence_id)
            checkpoint = None
            prior = None
            for index in range(len(sequence["steps"])):
                bundle, deltas = materialize_sequence_step(self.m2, sequence, index, index + 1)
                result = module.step_incremental_l(checkpoint, bundle, deltas, index + 1)
                oracle = pinned_public_m2_reference(prior, bundle, deltas, index + 1)
                self.assertEqual(canonical_bytes(result.get("fixpoint_result", result)), canonical_bytes(oracle))
                if oracle["kind"] == "LRejection":
                    self.assertEqual(result, oracle)
                    break
                checkpoint = result["next_checkpoint"]
                prior = oracle["next_materialization"]

    def test_default_truth_states_duplicates_identity_and_permutations(self) -> None:
        module = self.sut()
        for case_id in ("default-negation-after-empty-lower-stratum", "default-negation-accepts-false-only", "lower-stratum-completes-before-default-negation", "default-negation-rejects-both", "exact-duplicate-batch-idempotent"):
            case = next(item for item in self.m2["success_cases"] if item["id"] == case_id)
            bundle, deltas = materialize_case(self.m2, case)
            result = module.step_incremental_l(None, bundle, deltas, 1)
            self.assertEqual(canonical_bytes(result["fixpoint_result"]), canonical_bytes(pinned_public_m2_reference(None, bundle, deltas, 1)))
        conflict = next(item for item in self.m2["rejection_cases"] if item["id"] == "identity-conflict-atomic")
        bundle, deltas = materialize_case(self.m2, conflict)
        self.assertEqual(module.step_incremental_l(None, bundle, deltas, 1), pinned_public_m2_reference(None, bundle, deltas, 1))

    def test_checkpoint_integrity_binding_bounds_and_immutability(self) -> None:
        module = self.sut()
        bundle = materialize_rule_bundle(self.m2, "empty")
        delta = materialize_delta_input(self.m2, "a_positive", 1)
        before = copy.deepcopy((bundle, delta))
        first = module.step_incremental_l(None, bundle, [delta], 1)
        self.assertEqual((bundle, delta), before)
        forged = copy.deepcopy(first["next_checkpoint"])
        forged["materialization_digest"] = "sha256:" + "0" * 64
        rejected = module.step_incremental_l(forged, bundle, [], 2)
        self.assertEqual(rejected["kind"], "LPersistentLRejection")
        self.assertEqual(rejected["code"], "CHECKPOINT_DIGEST_MISMATCH")
        malformed = copy.deepcopy(first["next_checkpoint"]); malformed.pop("evaluation_cache")
        self.assertEqual(module.step_incremental_l(malformed, bundle, [], 2)["code"], "MALFORMED_CHECKPOINT")
        unsupported = copy.deepcopy(first["next_checkpoint"]); unsupported["schema_version"] = "unsupported/1"
        self.assertEqual(module.step_incremental_l(unsupported, bundle, [], 2)["code"], "UNSUPPORTED_PERSISTENT_SCHEMA")
        binding = copy.deepcopy(first["next_checkpoint"]); binding["rule_bundle_digest"] = "sha256:" + "1" * 64
        without = {key: binding[key] for key in binding if key != "checkpoint_digest"}
        import flrh_logic_incremental.incremental as implementation
        binding["checkpoint_digest"] = implementation.canonical_digest({"kind": "M2ILCheckpointPreimage", "contract_version": implementation.CONTRACT_VERSION, "checkpoint_without_checkpoint_digest": without})
        self.assertEqual(module.step_incremental_l(binding, bundle, [], 2)["code"], "CHECKPOINT_BINDING_MISMATCH")
        too_many = [copy.deepcopy(delta) for _ in range(10001)]
        inherited = module.step_incremental_l(None, bundle, too_many, 1)
        self.assertEqual(inherited, pinned_public_m2_reference(None, bundle, too_many, 1))

    def test_recomputed_forged_cache_is_rejected_by_binding_or_equivalence(self) -> None:
        import flrh_logic_incremental.incremental as implementation
        bundle, deltas = materialize_m2il_step(self.m2il, "disjoint-chain-bootstrap-noop-unrelated-retract", 0, 1)
        first = self.sut().step_incremental_l(None, bundle, deltas, 1)
        forged = copy.deepcopy(first["next_checkpoint"])
        entry = forged["evaluation_cache"][0]
        entry["outcome"] = {"status": "unsatisfied", "depth": None, "support": None}
        without_entry = {key: entry[key] for key in entry if key != "entry_digest"}
        entry["entry_digest"] = implementation.canonical_digest({"kind": "M2ILCacheEntryPreimage", "contract_version": implementation.CONTRACT_VERSION, "entry_without_entry_digest": without_entry})
        forged["evaluation_cache"].sort(key=implementation.canonical_bytes)
        without_checkpoint = {key: forged[key] for key in forged if key != "checkpoint_digest"}
        forged["checkpoint_digest"] = implementation.canonical_digest({"kind": "M2ILCheckpointPreimage", "contract_version": implementation.CONTRACT_VERSION, "checkpoint_without_checkpoint_digest": without_checkpoint})
        result = self.sut().step_incremental_l(forged, bundle, [], 2)
        self.assertEqual((result["kind"], result["code"]), ("LPersistentLRejection", "EQUIVALENCE_VIOLATION"))

    def test_self_consistently_redigested_malformed_cache_outcomes_are_typed(self) -> None:
        import flrh_logic_incremental.incremental as implementation
        bundle, deltas = materialize_m2il_step(self.m2il, "disjoint-chain-bootstrap-noop-unrelated-retract", 0, 1)
        first = self.sut().step_incremental_l(None, bundle, deltas, 1)

        def redigest(checkpoint, index):
            entry = checkpoint["evaluation_cache"][index]
            without_entry = {key: entry[key] for key in entry if key != "entry_digest"}
            entry["entry_digest"] = implementation.canonical_digest({"kind": "M2ILCacheEntryPreimage", "contract_version": implementation.CONTRACT_VERSION, "entry_without_entry_digest": without_entry})
            checkpoint["evaluation_cache"].sort(key=implementation.canonical_bytes)
            without_checkpoint = {key: checkpoint[key] for key in checkpoint if key != "checkpoint_digest"}
            checkpoint["checkpoint_digest"] = implementation.canonical_digest({"kind": "M2ILCheckpointPreimage", "contract_version": implementation.CONTRACT_VERSION, "checkpoint_without_checkpoint_digest": without_checkpoint})

        mutations = [
            ("missing-status", lambda outcome: outcome.pop("status"), "/outcome/status"),
            ("empty-support", lambda outcome: outcome.update({"status": "satisfied", "depth": 1, "support": {}}), "/outcome/support"),
            ("string-depth", lambda outcome: outcome.update({"status": "satisfied", "depth": "x"}), "/outcome/depth"),
        ]
        for label, mutate, suffix in mutations:
            with self.subTest(mutant=label):
                forged = copy.deepcopy(first["next_checkpoint"])
                index = 0
                mutate(forged["evaluation_cache"][index]["outcome"])
                redigest(forged, index)
                result = self.sut().step_incremental_l(forged, bundle, [], 2)
                self.assertEqual(result["kind"], "LPersistentLRejection")
                self.assertEqual(result["code"], "MALFORMED_CHECKPOINT")
                self.assertTrue(result["path"].endswith(suffix), result)

    def test_checkpoint_versions_and_cache_identity_are_bound(self) -> None:
        import flrh_logic_incremental.incremental as implementation
        from jsonschema import Draft202012Validator
        schema = json.loads((ROOT / "spec/schema/m2il-incremental.v1.schema.json").read_text(encoding="utf-8"))
        checkpoint_validator = Draft202012Validator(schema).evolve(schema=schema["$defs"]["Checkpoint"])
        bundle, deltas = materialize_m2il_step(self.m2il, "disjoint-chain-bootstrap-noop-unrelated-retract", 0, 1)
        first = self.sut().step_incremental_l(None, bundle, deltas, 1)

        def redigest(checkpoint):
            without = {key: checkpoint[key] for key in checkpoint if key != "checkpoint_digest"}
            checkpoint["checkpoint_digest"] = implementation.canonical_digest({"kind": "M2ILCheckpointPreimage", "contract_version": implementation.CONTRACT_VERSION, "checkpoint_without_checkpoint_digest": without})

        for field in ("m2_contract_version", "m2_profile_id", "canonicalization_version"):
            with self.subTest(field=field):
                forged = copy.deepcopy(first["next_checkpoint"])
                forged[field] = "wrong/1"; redigest(forged)
                self.assertFalse(checkpoint_validator.is_valid(forged))
                result = self.sut().step_incremental_l(forged, bundle, [], 2)
                self.assertEqual((result["kind"], result["code"], result["path"]), ("LPersistentLRejection", "UNSUPPORTED_PERSISTENT_SCHEMA", "/prior_checkpoint/" + field))
        duplicate = copy.deepcopy(first["next_checkpoint"])
        duplicate["evaluation_cache"].append(copy.deepcopy(duplicate["evaluation_cache"][0]))
        duplicate["evaluation_cache"].sort(key=implementation.canonical_bytes); redigest(duplicate)
        self.assertFalse(checkpoint_validator.is_valid(duplicate))
        result = self.sut().step_incremental_l(duplicate, bundle, [], 2)
        self.assertEqual((result["kind"], result["code"]), ("LPersistentLRejection", "MALFORMED_CHECKPOINT"))
        self.assertTrue(result["path"].endswith("/context_digest"), result)

    def test_local_and_independent_canonicalizers_reject_noncanonical_object_keys(self) -> None:
        import flrh_logic_incremental.canonical as candidate_canonical
        import m2il_oracle
        for value in ({"e\u0301": 1}, {"\ud800": 1}):
            for encoder in (candidate_canonical.canonical_bytes, m2il_oracle.canonical_bytes):
                with self.subTest(value=repr(value), encoder=encoder.__module__):
                    with self.assertRaises(ValueError): encoder(value)

    def test_exact_inherited_rejection_is_valid_m2il_wire(self) -> None:
        from jsonschema import Draft202012Validator
        case = next(item for item in self.m2["rejection_cases"] if item["id"] == "identity-conflict-atomic")
        bundle, deltas = materialize_case(self.m2, case)
        rejection = self.sut().step_incremental_l(None, bundle, deltas, 1)
        self.assertEqual(rejection["kind"], "LRejection")
        self.assertNotIn("rejection_digest", rejection)
        schema = json.loads((ROOT / "spec/schema/m2il-incremental.v1.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(rejection)

    def test_disjoint_chain_unrelated_insert_and_root_retraction_against_naive_oracle(self) -> None:
        module = self.sut(); checkpoint = None; prior = None; active = []
        expected_ledgers = [["a+", "x+"], ["a+", "x+"], ["a+", "x+", "u+"], ["x+", "u+"]]
        for index, active in enumerate(expected_ledgers):
            bundle, deltas = materialize_m2il_step(self.m2il, "disjoint-chain-bootstrap-noop-unrelated-retract", index, index + 1)
            result = module.step_incremental_l(checkpoint, bundle, deltas, index + 1)
            semantic = naive_semantics(self.m2il, "disjoint_chain", active)
            actual = {next(name for name, atom in self.m2il["atoms"].items() if atom == state["atom"]): state["state"] for state in result["fixpoint_result"]["next_materialization"]["fact_states"]}
            self.assertEqual({name: actual[name] for name in semantic["states"]}, {name: value["state"] for name, value in semantic["states"].items()})
            if index in (1, 2): self.assertEqual(result["reuse_receipt"]["candidate_cache_hits"], 4)
            if index == 3: self.assertEqual(result["reuse_receipt"]["candidate_cache_hits"], 2)
            if index in (2, 3):
                golden_name = "insertion-reuse.fixpoint.json" if index == 2 else "retraction-reuse.fixpoint.json"
                golden = json.loads((ROOT / "fixtures/m2il/golden" / golden_name).read_text(encoding="utf-8"))
                self.assertEqual(canonical_bytes(result["fixpoint_result"]), canonical_bytes(golden))
            checkpoint = result["next_checkpoint"]; prior = result["fixpoint_result"]["next_materialization"]

    def test_default_sequential_truth_flip(self) -> None:
        module = self.sut(); checkpoint = None
        expected = [("NEITHER", "TRUE_ONLY"), ("TRUE_ONLY", "NEITHER"), ("BOTH", "NEITHER"), ("FALSE_ONLY", "TRUE_ONLY")]
        for index, pair in enumerate(expected):
            bundle, deltas = materialize_m2il_step(self.m2il, "default-state-flip", index, index + 1)
            result = module.step_incremental_l(checkpoint, bundle, deltas, index + 1)
            states = {state["atom"]["entity"].split(":")[-1]: state["state"] for state in result["fixpoint_result"]["next_materialization"]["fact_states"]}
            self.assertEqual((states["blocked"], states["eligible"]), pair)
            checkpoint = result["next_checkpoint"]

    def test_stdlib_naive_oracle_is_import_denied_and_covers_inherited_semantics(self) -> None:
        import builtins
        real_import = builtins.__import__
        def deny(name, *args, **kwargs):
            if name.startswith("flrh_logic"): raise AssertionError("independent oracle imported production")
            return real_import(name, *args, **kwargs)
        with mock.patch("builtins.__import__", side_effect=deny):
            disjoint = naive_semantics(self.m2il, "disjoint_chain", ["a+", "x+"])
            two = naive_semantics(self.m2, "two_supports", ["a_positive", "b_positive"])
            cycle_live = naive_semantics(self.m2, "positive_cycle", ["a_positive"])
            cycle_dead = naive_semantics(self.m2, "positive_cycle", [])
            both = naive_semantics(self.m2, "lower_stratum_default", ["candidate_positive", "blocked_positive", "blocked_negative"])
            defaults = [
                naive_semantics(self.m2, "lower_stratum_default", ["candidate_positive"]),
                naive_semantics(self.m2, "lower_stratum_default", ["candidate_positive", "blocked_negative"]),
                naive_semantics(self.m2, "lower_stratum_default", ["candidate_positive", "blocked_positive"]),
                both,
            ]
        self.assertEqual(len(disjoint["satisfied_rules"]), 4)
        self.assertEqual(two["states"]["c"]["positive_support_count"], 2)
        self.assertEqual(cycle_live["states"]["c"]["state"], "TRUE_ONLY")
        self.assertEqual(cycle_dead["states"]["c"]["state"], "NEITHER")
        self.assertEqual(both["states"]["blocked"]["state"], "BOTH")
        self.assertEqual(both["conflicts"], ["blocked"])
        self.assertEqual([item["states"]["eligible"]["state"] for item in defaults], ["TRUE_ONLY", "TRUE_ONLY", "NEITHER", "NEITHER"])

    def test_signed_head_body_conflict_supports_and_derived_delta_oracle(self) -> None:
        first = naive_semantics(self.m2il, "signed", ["p_false+"])
        both = naive_semantics(self.m2il, "signed", ["p_false+", "p_true+"])
        final = naive_semantics(self.m2il, "signed", ["p_true+"])
        self.assertEqual(first["states"]["q"]["state"], "FALSE_ONLY")
        self.assertEqual(first["states"]["q"]["negative_support_ids"], ["derived:rule:m2il:q-false-from-p-false"])
        self.assertEqual(both["states"]["p"]["state"], "BOTH")
        self.assertEqual(both["conflicts"], ["p"])
        self.assertEqual(naive_derived_delta(None, first, self.m2il, "signed"), [{"rule_id": "rule:m2il:q-false-from-p-false", "atom_ref": "q", "polarity": "negative", "diff": 1}])
        self.assertEqual(naive_derived_delta(both, final, self.m2il, "signed"), [{"rule_id": "rule:m2il:q-false-from-p-false", "atom_ref": "q", "polarity": "negative", "diff": -1}])

    def test_persistent_cap_n_and_n_plus_one_boundaries(self) -> None:
        import flrh_logic_incremental.incremental as implementation
        bundle, deltas = materialize_m2il_step(self.m2il, "disjoint-chain-bootstrap-noop-unrelated-retract", 0, 1)
        with mock.patch.object(implementation, "MAX_ACTIVE_BASE_SUPPORTS", 2), mock.patch.object(implementation, "MAX_CACHE_ENTRIES", 4), mock.patch.object(implementation, "MAX_BODY_EVALUATIONS", 4):
            accepted = self.sut().step_incremental_l(None, bundle, deltas, 1)
        self.assertEqual(accepted["kind"], "LPersistentLStep")
        for name, limit in (("MAX_ACTIVE_BASE_SUPPORTS", 1), ("MAX_CACHE_ENTRIES", 3), ("MAX_BODY_EVALUATIONS", 3)):
            with self.subTest(cap=name), mock.patch.object(implementation, name, limit):
                rejected = self.sut().step_incremental_l(None, bundle, deltas, 1)
                self.assertEqual((rejected["kind"], rejected["code"]), ("LPersistentLRejection", "PERSISTENT_BOUNDS_EXCEEDED"))
        exact_bytes = len(canonical_bytes(accepted["next_checkpoint"]))
        with mock.patch.object(implementation, "MAX_CHECKPOINT_BYTES", exact_bytes):
            self.assertEqual(self.sut().step_incremental_l(None, bundle, deltas, 1)["kind"], "LPersistentLStep")
        with mock.patch.object(implementation, "MAX_CHECKPOINT_BYTES", exact_bytes - 1):
            self.assertEqual(self.sut().step_incremental_l(None, bundle, deltas, 1)["code"], "PERSISTENT_BOUNDS_EXCEEDED")


if __name__ == "__main__":
    unittest.main()
