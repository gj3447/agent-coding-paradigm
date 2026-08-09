from __future__ import annotations

import copy
import importlib
import json
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from m1_guard import write_tracking_copy  # noqa: E402
from m2_fixtures import (  # noqa: E402
    canonical_bytes,
    load_cases,
    materialize_case,
    materialize_delta_input,
    materialize_rule_bundle,
    materialize_sequence_step,
)


def _logic() -> Any:
    return importlib.import_module("flrh_logic")


def _solve(
    prior: dict[str, Any] | None,
    bundle: dict[str, Any],
    deltas: list[dict[str, Any]],
    logical_time: int,
) -> dict[str, Any]:
    return _logic().solve_l(prior, bundle, deltas, logical_time)


def _state_for(materialization: dict[str, Any], atom: dict[str, Any]) -> dict[str, Any]:
    matches = [state for state in materialization["fact_states"] if state["atom"] == atom]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one state for {atom!r}, got {matches!r}")
    return matches[0]


def _assert_closed_rejection(test: unittest.TestCase, result: dict[str, Any], code: str) -> None:
    test.assertEqual(result["kind"], "LRejection")
    test.assertEqual(result["code"], code)
    test.assertNotIn("next_materialization", result)
    test.assertNotIn("derived_fact_deltas", result)
    encoded = json.dumps(result, sort_keys=True).lower()
    test.assertNotIn("traceback", encoded)
    test.assertNotIn("exception", encoded)


def _expected_rejection(
    descriptor: dict[str, Any], bundle: dict[str, Any], logical_time: int
) -> dict[str, Any]:
    return {
        "kind": "LRejection",
        "schema_version": "flrh-l-result/1",
        "contract_version": "flrh-l-kernel/1",
        "code": descriptor["expected_code"],
        "path": descriptor["expected_path"],
        "logical_time": logical_time,
        "rule_bundle_digest": (
            bundle["rule_bundle_digest"]
            if descriptor["expected_rule_bundle_digest"] == "supplied"
            else None
        ),
        "context": copy.deepcopy(descriptor["expected_context"]),
    }


def _naive_ground_oracle(
    corpus: dict[str, Any], bundle_ref: str, active_delta_refs: list[str]
) -> dict[bytes, dict[str, Any]]:
    """Independent full recomputation by repeated ground-rule scans.

    This deliberately does not import the M2 implementation, compute its IDs,
    or use its semi-naive worklist.  It is a small semantic oracle only for the
    finite fixture profile.
    """

    bundle = corpus["base_rule_bundles"][bundle_ref]
    supports: dict[bytes, dict[str, set[str]]] = {}

    def slot(atom: dict[str, Any]) -> dict[str, set[str]]:
        return supports.setdefault(canonical_bytes(atom), {"positive": set(), "negative": set()})

    def lookup(atom: dict[str, Any]) -> dict[str, set[str]]:
        """Read an absent literal without expanding the projected fact universe."""

        return supports.get(canonical_bytes(atom), {"positive": set(), "negative": set()})

    for ref in active_delta_refs:
        template = corpus["base_fact_delta_inputs"][ref]
        if template["diff"] != 1:
            raise AssertionError(f"oracle active ledger received retraction: {ref}")
        slot(corpus["atoms"][template["atom_ref"]])[template["polarity"]].add(
            template["derivation_id"]
        )

    strata = sorted({rule["stratum"] for rule in bundle["rules"]})
    for stratum in strata:
        rules = [rule for rule in bundle["rules"] if rule["stratum"] == stratum]
        changed = True
        while changed:
            changed = False
            for rule in rules:
                required = all(
                    bool(lookup(corpus["atoms"][item["atom_ref"]])[item["polarity"]])
                    for item in rule["required"]
                )
                default_absent = all(
                    not lookup(corpus["atoms"][item["atom_ref"]])["positive"]
                    for item in rule["default_not_positive"]
                )
                if not (required and default_absent):
                    continue
                head = slot(corpus["atoms"][rule["head"]["atom_ref"]])
                marker = "derived-by:" + rule["rule_id"]
                if marker not in head[rule["head"]["polarity"]]:
                    head[rule["head"]["polarity"]].add(marker)
                    changed = True

    for atom_ref in bundle["query_atom_refs"]:
        slot(corpus["atoms"][atom_ref])
    projected = {}
    for atom_bytes, polarities in supports.items():
        positive = polarities["positive"]
        negative = polarities["negative"]
        state = (
            "BOTH" if positive and negative else
            "TRUE_ONLY" if positive else
            "FALSE_ONLY" if negative else
            "NEITHER"
        )
        projected[atom_bytes] = {
            "state": state,
            "positive_support_count": len(positive),
            "negative_support_count": len(negative),
        }
    return projected


def _literal_key(atom: dict[str, Any], polarity: str) -> str:
    """Independent exact key oracle from the frozen contract preimage."""

    import hashlib

    preimage = {
        "kind": "M2LiteralKeyPreimage",
        "contract_version": "flrh-l-kernel/1",
        "literal": {"kind": "LLiteral", "polarity": polarity, "atom": atom},
    }
    return "sha256:" + hashlib.sha256(canonical_bytes(preimage)).hexdigest()


class M2LogicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = load_cases()

    def test_public_logic_kernel_exists(self) -> None:
        module = _logic()
        self.assertEqual(module.__all__, ["solve_l"])
        self.assertTrue(callable(module.solve_l))

    def test_m1_exact_golden_fact_delta_is_the_positive_m2_seam(self) -> None:
        transition = json.loads(
            (ROOT / "fixtures/m1/golden/observe-with-effect.transition.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(self.corpus["m1_positive_seam"], transition["fact_deltas"][0])
        case = next(case for case in self.corpus["success_cases"] if case["id"] == "m1-positive-seam")
        bundle, deltas = materialize_case(self.corpus, case)
        self.assertEqual(deltas[0]["delta"], transition["fact_deltas"][0])
        result = _solve(None, bundle, deltas, 1)
        self.assertEqual(result["kind"], "LFixpointResult")
        state = _state_for(result["next_materialization"], transition["fact_deltas"][0]["tuple"])
        self.assertEqual(state["state"], "TRUE_ONLY")
        self.assertEqual(state["positive_support_ids"], [transition["fact_deltas"][0]["derivation_id"]])

    def test_success_corpus_has_full_semantic_state_and_support_assertions(self) -> None:
        for case in self.corpus["success_cases"]:
            with self.subTest(case=case["id"]):
                bundle, deltas = materialize_case(self.corpus, case)
                before = copy.deepcopy((bundle, deltas))
                result = _solve(None, bundle, deltas, 1)
                self.assertEqual((bundle, deltas), before)
                self.assertEqual(result["kind"], "LFixpointResult")
                self.assertEqual(result["stats"]["evaluation_mode"], "full_recompute")
                materialization = result["next_materialization"]
                for atom_ref, expected in case["expected_states"].items():
                    if atom_ref == "observation_recorded":
                        atom = self.corpus["m1_positive_seam"]["tuple"]
                    else:
                        atom = self.corpus["atoms"][atom_ref]
                    self.assertEqual(_state_for(materialization, atom)["state"], expected)
                for atom_ref, expected_count in case.get("expected_positive_support_counts", {}).items():
                    state = _state_for(materialization, self.corpus["atoms"][atom_ref])
                    self.assertEqual(len(state["positive_support_ids"]), expected_count)
                for atom_ref, expected_count in case.get("expected_negative_support_counts", {}).items():
                    state = _state_for(materialization, self.corpus["atoms"][atom_ref])
                    self.assertEqual(len(state["negative_support_ids"]), expected_count)
                if "$m1_positive_seam" not in case["delta_refs"]:
                    oracle = _naive_ground_oracle(self.corpus, case["bundle_ref"], case["delta_refs"])
                    for atom_bytes, expected in oracle.items():
                        actual = next(
                            state
                            for state in materialization["fact_states"]
                            if canonical_bytes(state["atom"]) == atom_bytes
                        )
                        self.assertEqual(actual["state"], expected["state"])
                        self.assertEqual(
                            len(actual["positive_support_ids"]), expected["positive_support_count"]
                        )
                        self.assertEqual(
                            len(actual["negative_support_ids"]), expected["negative_support_count"]
                        )

    def test_neither_and_both_are_distinct_and_both_has_exact_conflict_projection(self) -> None:
        case = next(case for case in self.corpus["success_cases"] if case["id"] == "four-truth-states")
        bundle, deltas = materialize_case(self.corpus, case)
        materialization = _solve(None, bundle, deltas, 1)["next_materialization"]
        neither = _state_for(materialization, self.corpus["atoms"]["neither"])
        both = _state_for(materialization, self.corpus["atoms"]["both"])
        self.assertEqual((neither["positive_support_ids"], neither["negative_support_ids"]), ([], []))
        self.assertEqual(len(both["positive_support_ids"]), 1)
        self.assertEqual(len(both["negative_support_ids"]), 1)
        self.assertEqual(len(materialization["conflicts"]), 1)
        conflict = materialization["conflicts"][0]
        self.assertEqual(conflict["atom"], both["atom"])
        self.assertEqual(conflict["fact_key"], both["fact_key"])
        self.assertEqual(conflict["positive_support_ids"], both["positive_support_ids"])
        self.assertEqual(conflict["negative_support_ids"], both["negative_support_ids"])

    def test_derived_supports_bind_exact_rules_premises_and_absence_witnesses(self) -> None:
        two_supports = next(
            case for case in self.corpus["success_cases"]
            if case["id"] == "two-supports-and-downstream"
        )
        bundle, deltas = materialize_case(self.corpus, two_supports)
        materialization = _solve(None, bundle, deltas, 1)["next_materialization"]
        by_rule = {support["rule_id"]: support for support in materialization["derived_supports"]}
        self.assertEqual(
            set(by_rule), {"rule:c-from-a", "rule:c-from-b", "rule:d-from-c"}
        )
        for rule_id, premise_ref in {
            "rule:c-from-a": "a",
            "rule:c-from-b": "b",
            "rule:d-from-c": "c",
        }.items():
            support = by_rule[rule_id]
            rule = next(item for item in bundle["rules"] if item["rule_id"] == rule_id)
            self.assertEqual(support["rule_digest"], rule["rule_digest"])
            self.assertEqual(
                support["premise_literal_keys"],
                [_literal_key(self.corpus["atoms"][premise_ref], "positive")],
            )
            self.assertEqual(support["default_absence_witnesses"], [])

        four_states = {
            "default-negation-after-empty-lower-stratum": ("NEITHER", True),
            "default-negation-accepts-false-only": ("FALSE_ONLY", True),
            "lower-stratum-completes-before-default-negation": ("TRUE_ONLY", False),
            "default-negation-rejects-both": ("BOTH", False),
        }
        for case_id, (blocked_state, should_fire) in four_states.items():
            with self.subTest(default_truth_state=blocked_state):
                default_case = next(
                    case for case in self.corpus["success_cases"] if case["id"] == case_id
                )
                bundle, deltas = materialize_case(self.corpus, default_case)
                materialization = _solve(None, bundle, deltas, 1)["next_materialization"]
                self.assertEqual(
                    _state_for(materialization, self.corpus["atoms"]["blocked"])["state"],
                    blocked_state,
                )
                eligible = _state_for(materialization, self.corpus["atoms"]["eligible"])
                self.assertEqual(eligible["state"], "TRUE_ONLY" if should_fire else "NEITHER")
                supports = [
                    item for item in materialization["derived_supports"]
                    if item["rule_id"] == "rule:eligible-if-not-blocked"
                ]
                if not should_fire:
                    self.assertEqual(supports, [])
                    continue
                self.assertEqual(len(supports), 1)
                support = supports[0]
                self.assertEqual(
                    support["premise_literal_keys"],
                    [_literal_key(self.corpus["atoms"]["candidate"], "positive")],
                )
                self.assertEqual(len(support["default_absence_witnesses"]), 1)
                witness = support["default_absence_witnesses"][0]
                self.assertEqual(witness["atom"], self.corpus["atoms"]["blocked"])
                self.assertEqual(witness["referenced_stratum"], 0)
                self.assertEqual(
                    witness["completed_stratum_digest"],
                    next(
                        item["digest"] for item in materialization["stratum_digests"]
                        if item["stratum"] == 0
                    ),
                )

    def test_negative_cycle_duplicate_conflict_unknown_and_budget_rejections_are_closed(self) -> None:
        for case in self.corpus["rejection_cases"]:
            with self.subTest(case=case["id"]):
                bundle, deltas = materialize_case(self.corpus, case)
                before = copy.deepcopy((bundle, deltas))
                result = _solve(None, bundle, deltas, 1)
                self.assertEqual((bundle, deltas), before)
                expected = _expected_rejection(case, bundle, 1)
                self.assertEqual(canonical_bytes(result), canonical_bytes(expected))
                if case["id"] == "negative-cycle":
                    golden = (ROOT / "fixtures/m2/golden/negative-cycle.rejection.json").read_bytes()
                    self.assertEqual(canonical_bytes(result) + b"\n", golden)

    def test_two_support_retraction_retains_then_removes_reverse_closure_and_provenance(self) -> None:
        sequence = next(item for item in self.corpus["sequences"] if item["id"] == "two-support-retain-then-remove")
        prior = None
        results = []
        for index in range(3):
            bundle, deltas = materialize_sequence_step(self.corpus, sequence, index, index + 1)
            result = _solve(prior, bundle, deltas, index + 1)
            self.assertEqual(result["kind"], "LFixpointResult")
            self.assertEqual(result["stats"]["evaluation_mode"], "full_recompute")
            results.append(result)
            prior = result["next_materialization"]

        c_atom = self.corpus["atoms"]["c"]
        d_atom = self.corpus["atoms"]["d"]
        first_c = _state_for(results[0]["next_materialization"], c_atom)
        self.assertEqual(len(first_c["positive_support_ids"]), 2)
        retained_c = _state_for(results[1]["next_materialization"], c_atom)
        retained_d = _state_for(results[1]["next_materialization"], d_atom)
        self.assertEqual((len(retained_c["positive_support_ids"]), retained_c["state"]), (1, "TRUE_ONLY"))
        self.assertEqual((len(retained_d["positive_support_ids"]), retained_d["state"]), (1, "TRUE_ONLY"))
        retained_golden = (
            ROOT / "fixtures/m2/golden/two-support-retraction.fixpoint.json"
        ).read_bytes()
        self.assertEqual(canonical_bytes(results[1]) + b"\n", retained_golden)
        final = results[2]["next_materialization"]
        self.assertEqual(_state_for(final, c_atom)["state"], "NEITHER")
        self.assertEqual(_state_for(final, d_atom)["state"], "NEITHER")
        self.assertFalse(final["derived_supports"])
        self.assertFalse(final["base_supports"])
        removed_atoms = [item["delta"]["tuple"] for item in results[2]["derived_fact_deltas"] if item["delta"]["diff"] == -1]
        self.assertCountEqual(removed_atoms, [c_atom, d_atom])

    def test_positive_recursive_deletion_equals_independent_clean_recomputation(self) -> None:
        sequence = next(item for item in self.corpus["sequences"] if item["id"] == "positive-cycle-delete")
        bundle, insert = materialize_sequence_step(self.corpus, sequence, 0, 1)
        first = _solve(None, bundle, insert, 1)
        self.assertEqual(first["kind"], "LFixpointResult")
        bundle, retract = materialize_sequence_step(self.corpus, sequence, 1, 2)
        recomputed = _solve(first["next_materialization"], bundle, retract, 2)
        oracle = _naive_ground_oracle(self.corpus, "positive_cycle", [])
        self.assertEqual(recomputed["kind"], "LFixpointResult")
        for atom_ref in ("a", "b", "c"):
            state = _state_for(recomputed["next_materialization"], self.corpus["atoms"][atom_ref])
            expected = oracle[canonical_bytes(self.corpus["atoms"][atom_ref])]
            self.assertEqual(state["state"], expected["state"])
            self.assertEqual(len(state["positive_support_ids"]), expected["positive_support_count"])
            self.assertEqual(len(state["negative_support_ids"]), expected["negative_support_count"])
        self.assertFalse(recomputed["next_materialization"]["derived_supports"])

    def test_rule_and_input_permutations_are_full_byte_equal(self) -> None:
        for pair in self.corpus["equivalence_pairs"]:
            with self.subTest(pair=pair["id"]):
                base_bundle, base_deltas = materialize_case(self.corpus, pair)
                changed_bundle, changed_deltas = materialize_case(
                    self.corpus,
                    pair,
                    reverse_rules=pair["reverse_rules"],
                    reverse_deltas=pair["reverse_deltas"],
                )
                base = _solve(None, base_bundle, base_deltas, 1)
                changed = _solve(None, changed_bundle, changed_deltas, 1)
                self.assertEqual(canonical_bytes(base), canonical_bytes(changed))

    def test_every_successful_sequence_step_declares_full_recompute_mode(self) -> None:
        for sequence in self.corpus["sequences"]:
            prior = None
            for index in range(len(sequence["steps"])):
                bundle, deltas = materialize_sequence_step(
                    self.corpus, sequence, index, index + 1
                )
                result = _solve(prior, bundle, deltas, index + 1)
                if result["kind"] == "LRejection":
                    self.assertEqual(index, len(sequence["steps"]) - 1)
                    self.assertIn("expected_terminal_rejection", sequence)
                    break
                self.assertEqual(
                    result["stats"]["evaluation_mode"], "full_recompute"
                )
                prior = result["next_materialization"]

    def test_duplicate_then_retraction_and_double_retraction_are_exact(self) -> None:
        sequence = next(item for item in self.corpus["sequences"] if item["id"] == "duplicate-then-double-retract")
        prior = None
        for index in range(3):
            bundle, deltas = materialize_sequence_step(self.corpus, sequence, index, index + 1)
            result = _solve(prior, bundle, deltas, index + 1)
            self.assertEqual(result["kind"], "LFixpointResult")
            prior = result["next_materialization"]
            if index == 1:
                self.assertEqual(len(prior["base_supports"]), 1)
            if index == 2:
                self.assertFalse(prior["base_supports"])
        bundle, deltas = materialize_sequence_step(self.corpus, sequence, 3, 4)
        before_prior = copy.deepcopy(prior)
        attempts: list[str] = []
        rejection = _solve(
            write_tracking_copy(prior, attempts),
            write_tracking_copy(bundle, attempts),
            write_tracking_copy(deltas, attempts),
            4,
        )
        expected = _expected_rejection(sequence["expected_terminal_rejection"], bundle, 4)
        self.assertEqual(canonical_bytes(rejection), canonical_bytes(expected))
        self.assertEqual(attempts, [])
        self.assertEqual(prior, before_prior)

    def test_authority_shaped_atom_and_caller_provenance_are_opaque_and_inert(self) -> None:
        case = next(
            item for item in self.corpus["success_cases"]
            if item["id"] == "opaque-authority-shaped-data-is-inert"
        )
        bundle, deltas = materialize_case(self.corpus, case)
        atom = self.corpus["atoms"]["authority_shaped"]
        provenance = self.corpus["base_fact_delta_inputs"]["authority_shaped_positive"][
            "provenance_delta"
        ]
        before = copy.deepcopy((bundle, deltas))
        result = _solve(None, bundle, deltas, 1)
        self.assertEqual((bundle, deltas), before)
        self.assertEqual(result["kind"], "LFixpointResult")
        self.assertEqual(result["stats"]["evaluation_mode"], "full_recompute")
        state = _state_for(result["next_materialization"], atom)
        self.assertEqual(state["state"], "TRUE_ONLY")
        support = next(
            item for item in result["next_materialization"]["base_supports"]
            if item["derivation_id"] == "derivation:base:authority-shaped"
        )
        self.assertEqual(support["literal"]["atom"], atom)
        self.assertEqual(support["provenance_delta"], provenance)

    def test_mixed_valid_invalid_batch_is_atomic_against_existing_prior(self) -> None:
        bundle = materialize_rule_bundle(self.corpus, "empty")
        initial = materialize_delta_input(self.corpus, "a_positive", 1)
        prior = _solve(None, bundle, [initial], 1)["next_materialization"]
        valid = materialize_delta_input(self.corpus, "b_positive", 2)
        invalid = materialize_delta_input(self.corpus, "unknown_retract", 2)
        before = copy.deepcopy(prior)
        result = _solve(prior, bundle, [valid, invalid], 2)
        _assert_closed_rejection(self, result, "UNKNOWN_DERIVATION")
        self.assertEqual(prior, before)

    def test_inputs_are_recursively_write_detected_on_success_and_late_rejection(self) -> None:
        success = next(case for case in self.corpus["success_cases"] if case["id"] == "two-supports-and-downstream")
        bundle, deltas = materialize_case(self.corpus, success)
        attempts: list[str] = []
        guarded_bundle = write_tracking_copy(bundle, attempts)
        guarded_deltas = write_tracking_copy(deltas, attempts)
        result = _solve(None, guarded_bundle, guarded_deltas, 1)
        self.assertEqual(result["kind"], "LFixpointResult")
        self.assertEqual(attempts, [])

        conflict = next(case for case in self.corpus["rejection_cases"] if case["id"] == "identity-conflict-atomic")
        bundle, deltas = materialize_case(self.corpus, conflict)
        attempts = []
        result = _solve(None, write_tracking_copy(bundle, attempts), write_tracking_copy(deltas, attempts), 1)
        _assert_closed_rejection(self, result, "DERIVATION_IDENTITY_CONFLICT")
        self.assertEqual(attempts, [])

    def test_shared_nested_aliases_are_accepted_without_mutation(self) -> None:
        case = next(case for case in self.corpus["success_cases"] if case["id"] == "four-truth-states")
        bundle, deltas = materialize_case(self.corpus, case)
        shared_atom = deltas[2]["delta"]["tuple"]
        deltas[3]["delta"]["tuple"] = shared_atom
        before = copy.deepcopy(deltas)
        result = _solve(None, bundle, deltas, 1)
        self.assertEqual(result["kind"], "LFixpointResult")
        self.assertEqual(deltas, before)
        self.assertEqual(_state_for(result["next_materialization"], shared_atom)["state"], "BOTH")

    def test_non_nfc_nested_input_is_typed_canonical_rejection(self) -> None:
        bundle = materialize_rule_bundle(self.corpus, "empty")
        delta = materialize_delta_input(self.corpus, "a_positive", 1)
        delta["delta"]["tuple"]["subject"] = "e\u0301"
        result = _solve(None, bundle, [delta], 1)
        _assert_closed_rejection(self, result, "CANONICALIZATION_VIOLATION")

    def test_non_nfc_object_key_returns_a_canonical_typed_rejection(self) -> None:
        bundle = materialize_rule_bundle(self.corpus, "empty")
        bundle["query_atoms"] = [{"e\u0301": "opaque"}]
        result = _solve(None, bundle, [], 1)
        _assert_closed_rejection(self, result, "CANONICALIZATION_VIOLATION")
        self.assertEqual(result["path"], "/rule_bundle/query_atoms/0")
        self.assertEqual(result["context"], {"invariant": "NON_NFC_OBJECT_KEY"})
        canonical_bytes(result)

    def test_fact_delta_input_ceiling_is_declared_and_duplicate_boundary_is_exact(self) -> None:
        contract = json.loads(
            (ROOT / "spec/m2-logic-contract.v1.json").read_text(encoding="utf-8")
        )
        self.assertEqual(contract["limits"]["max_fact_delta_inputs"], 10_000)
        bundle = materialize_rule_bundle(self.corpus, "empty")
        delta = materialize_delta_input(self.corpus, "a_positive", 1)
        accepted = _solve(None, bundle, [copy.deepcopy(delta) for _ in range(10_000)], 1)
        self.assertEqual(accepted["kind"], "LFixpointResult")
        self.assertEqual(len(accepted["input_delta_digests"]), 1)
        self.assertEqual(len(accepted["next_materialization"]["base_supports"]), 1)
        rejected = _solve(None, bundle, [copy.deepcopy(delta) for _ in range(10_001)], 1)
        self.assertEqual(
            rejected,
            {
                "kind": "LRejection",
                "schema_version": "flrh-l-result/1",
                "contract_version": "flrh-l-kernel/1",
                "code": "MALFORMED_FACT_DELTA_INPUT",
                "path": "/fact_delta_inputs",
                "logical_time": 1,
                "rule_bundle_digest": bundle["rule_bundle_digest"],
                "context": {"limit": 10_000, "observed": 10_001},
            },
        )
        with mock.patch(
            "flrh_logic.logic._derive",
            side_effect=AssertionError("input ceiling must precede evaluation"),
        ):
            preempted = _solve(
                accepted["next_materialization"],
                bundle,
                [delta] * 10_001,
                2,
            )
        self.assertEqual(preempted["code"], "MALFORMED_FACT_DELTA_INPUT")
        self.assertEqual(preempted["context"], {"limit": 10_000, "observed": 10_001})

    def test_rejection_precedence_is_independent_of_set_and_mapping_order(self) -> None:
        bundle = materialize_rule_bundle(self.corpus, "one_firing_exact")

        bad_kind = copy.deepcopy(bundle["rules"][0])
        bad_kind["kind"] = "NotLRule"
        bad_stratum = copy.deepcopy(bundle["rules"][0])
        bad_stratum["stratum"] = "not-an-integer"
        rule_results = []
        for rules in ([bad_kind, bad_stratum], [bad_stratum, bad_kind]):
            changed = copy.deepcopy(bundle)
            changed["rules"] = copy.deepcopy(rules)
            rule_results.append(_solve(None, changed, [], 1))
        self.assertEqual(canonical_bytes(rule_results[0]), canonical_bytes(rule_results[1]))

        bad_rule_float = copy.deepcopy(bundle["rules"][0])
        bad_rule_float["head"]["atom"]["invalid"] = 1.0
        bad_rule_nfc = copy.deepcopy(bundle["rules"][0])
        bad_rule_nfc["head"]["atom"]["invalid"] = "e\u0301"
        canonical_rule_results = []
        for rules in ([bad_rule_float, bad_rule_nfc], [bad_rule_nfc, bad_rule_float]):
            changed = copy.deepcopy(bundle)
            changed["rules"] = copy.deepcopy(rules)
            canonical_rule_results.append(_solve(None, changed, [], 1))
        self.assertEqual(
            canonical_bytes(canonical_rule_results[0]),
            canonical_bytes(canonical_rule_results[1]),
        )

        def invalid_literal(value: Any) -> dict[str, Any]:
            literal = copy.deepcopy(bundle["rules"][0]["required_body"][0])
            literal["atom"] = {"x": value}
            return literal

        invalid_float = invalid_literal(1.0)
        invalid_surrogate = invalid_literal("\ud800")
        invalid_nfc = invalid_literal("e\u0301")
        cross_level_results = []
        for first_body in (
            [invalid_float, invalid_surrogate],
            [invalid_surrogate, invalid_float],
        ):
            rule_a = copy.deepcopy(bundle["rules"][0])
            rule_a["required_body"] = copy.deepcopy(first_body)
            rule_b = copy.deepcopy(bundle["rules"][0])
            rule_b["required_body"] = [copy.deepcopy(invalid_nfc)]
            changed = copy.deepcopy(bundle)
            changed["rules"] = [rule_a, rule_b]
            cross_level_results.append(_solve(None, changed, [], 1))
        self.assertEqual(
            canonical_bytes(cross_level_results[0]),
            canonical_bytes(cross_level_results[1]),
        )

        bad_literal_kind = copy.deepcopy(bundle["rules"][0]["required_body"][0])
        bad_literal_kind["kind"] = "NotLLiteral"
        bad_literal_polarity = copy.deepcopy(bundle["rules"][0]["required_body"][0])
        bad_literal_polarity["polarity"] = "not-a-polarity"
        body_results = []
        for body in (
            [bad_literal_kind, bad_literal_polarity],
            [bad_literal_polarity, bad_literal_kind],
        ):
            changed = copy.deepcopy(bundle)
            changed["rules"][0]["required_body"] = copy.deepcopy(body)
            body_results.append(_solve(None, changed, [], 1))
        self.assertEqual(canonical_bytes(body_results[0]), canonical_bytes(body_results[1]))

        mapping_results = []
        for atom in (
            {"a": 1.0, "b": 2.0},
            {"b": 2.0, "a": 1.0},
        ):
            changed = materialize_rule_bundle(self.corpus, "empty")
            changed["query_atoms"] = [atom]
            mapping_results.append(_solve(None, changed, [], 1))
        self.assertEqual(canonical_bytes(mapping_results[0]), canonical_bytes(mapping_results[1]))

        bad_input_float = materialize_delta_input(self.corpus, "a_positive", 1)
        bad_input_float["delta"]["tuple"]["invalid"] = 1.0
        bad_input_nfc = materialize_delta_input(self.corpus, "a_positive", 1)
        bad_input_nfc["delta"]["tuple"]["invalid"] = "e\u0301"
        input_bundle = materialize_rule_bundle(self.corpus, "empty")
        input_results = [
            _solve(None, input_bundle, inputs, 1)
            for inputs in (
                [bad_input_float, bad_input_nfc],
                [bad_input_nfc, bad_input_float],
            )
        ]
        self.assertEqual(canonical_bytes(input_results[0]), canonical_bytes(input_results[1]))

        base_bundle = materialize_rule_bundle(self.corpus, "empty")
        base_delta = materialize_delta_input(self.corpus, "a_positive", 1)
        prior = _solve(None, base_bundle, [base_delta], 1)["next_materialization"]
        bad_support_kind = copy.deepcopy(prior["base_supports"][0])
        bad_support_kind["kind"] = "NotLBaseSupport"
        bad_support_id = copy.deepcopy(prior["base_supports"][0])
        bad_support_id["derivation_id"] = "not a valid id"
        prior_results = []
        for supports in (
            [bad_support_kind, bad_support_id],
            [bad_support_id, bad_support_kind],
        ):
            changed = copy.deepcopy(prior)
            changed["base_supports"] = copy.deepcopy(supports)
            prior_results.append(_solve(changed, base_bundle, [], 2))
        self.assertEqual(canonical_bytes(prior_results[0]), canonical_bytes(prior_results[1]))

        derived_case = next(
            item
            for item in self.corpus["success_cases"]
            if item["id"] == "two-supports-and-downstream"
        )
        derived_bundle, derived_deltas = materialize_case(self.corpus, derived_case)
        derived_prior = _solve(None, derived_bundle, derived_deltas, 1)[
            "next_materialization"
        ]
        nested_results = []
        for premise_keys in ([1.0, "e\u0301"], ["e\u0301", 1.0]):
            changed = copy.deepcopy(derived_prior)
            changed["derived_supports"][0]["premise_literal_keys"] = premise_keys
            nested_results.append(_solve(changed, derived_bundle, [], 2))
        self.assertEqual(canonical_bytes(nested_results[0]), canonical_bytes(nested_results[1]))

    def test_validate_m2_aggregate_when_available(self) -> None:
        try:
            validator = importlib.import_module("validate_m2")
        except ModuleNotFoundError:
            self.skipTest("validate_m2 has not landed yet")
        counts = validator.validate_m2()
        self.assertEqual(counts["m2_success_cases"], len(self.corpus["success_cases"]))
        self.assertEqual(counts["m2_rejection_cases"], len(self.corpus["rejection_cases"]))
        self.assertEqual(counts["m2_equivalence_pairs"], len(self.corpus["equivalence_pairs"]))
        self.assertEqual(counts["m2_sequences"], len(self.corpus["sequences"]))


if __name__ == "__main__":
    unittest.main()
