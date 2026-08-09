"""M3 scalar-frontier reactive conformance and adversarial tests."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from flrh_reactive import step_r
from m3_fixtures import find_by_id, load_cases
from m3_oracle import (
    canonical_bytes,
    command_digest,
    delivery_id,
    digest,
    profile_digest,
    run_sequence,
    step_expected,
    value_digest,
)


class M3ReactiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = load_cases()

    def setUp(self) -> None:
        self.profile = copy.deepcopy(self.corpus["profile"])
        self.proposal = copy.deepcopy(self.corpus["proposals"]["m1_effect_proposal"])
        self.verdict = copy.deepcopy(self.corpus["verdicts"]["m3_verdict"])

    def command(self, kind: str, **fields):
        return {
            "kind": kind,
            "schema_version": "flrh-r-command/1",
            "profile_digest": self.profile["profile_digest"],
            "dataflow_version": self.profile["dataflow_version"],
            **fields,
        }

    def delta(self, source_id, logical_time, value_kind, value, diff=1):
        bound = value_digest(value_kind, value)
        return {
            "kind": "RValueDelta",
            "schema_version": "flrh-r-value-delta/1",
            "delivery_id": delivery_id(
                source_id,
                logical_time,
                self.profile["dataflow_version"],
                value_kind,
                bound,
            ),
            "source_id": source_id,
            "logical_time": logical_time,
            "diff": diff,
            "dataflow_version": self.profile["dataflow_version"],
            "value_kind": value_kind,
            "value_digest": bound,
            "value": copy.deepcopy(value),
        }

    def pair(self, logical_time=7, suffix="one", status="eligible"):
        proposal = copy.deepcopy(self.proposal)
        if suffix != "one":
            proposal["proposal_id"] = f"proposal:m3:{suffix}"
            proposal["proposal_dedup_key"] = f"proposal-dedup:m3:{suffix}"
            proposal["cause_id"] = f"cause:m3:proposal:{suffix}"
        verdict = copy.deepcopy(self.verdict)
        verdict["proposal_id"] = proposal["proposal_id"]
        verdict["verdict_id"] = f"verdict:m3:{suffix}"
        verdict["cause_id"] = f"cause:m3:verdict:{suffix}"
        verdict["status"] = status
        return (
            self.delta("source:m3:a", logical_time, "effect_proposal", proposal),
            self.delta("source:m3:b", logical_time, "eligibility_verdict", verdict),
        )

    def run_commands(self, commands):
        state = None
        results = []
        for command in commands:
            result = step_r(state, self.profile, command)
            results.append(result)
            if result["kind"] == "RRejection":
                break
            state = result["next_state"]
        return results

    def assert_oracle(self, commands):
        actual = self.run_commands(commands)
        expected = run_sequence(None, self.profile, commands)
        self.assertEqual(expected, actual)
        return actual

    def close(self, watermark=8):
        return [
            self.command("RAdvanceFrontier", source_id="source:m3:a", low_watermark=watermark),
            self.command("RAdvanceFrontier", source_id="source:m3:b", low_watermark=watermark),
        ]

    def redigest_state(self, candidate):
        without = copy.deepcopy(candidate)
        without.pop("state_digest", None)
        candidate["state_digest"] = digest({
            "kind": "M3StatePreimage", "contract_version": "flrh-r-kernel/1",
            "state_without_state_digest": without,
        })
        return candidate

    def redigest_ready_state(self, candidate):
        for published in candidate["ready_batches"]:
            batch = published["batch"]
            stable_digest = digest({
                "kind": "M3StableBatchPreimage", "contract_version": "flrh-r-kernel/1",
                "profile_digest": candidate["profile_digest"], "logical_time": batch["logical_time"],
                "low_watermark": batch["low_watermark"], "ordered_proposal_ids": batch["proposal_ids"],
                "ordered_eligibility_verdict_ids": batch["eligibility_verdict_ids"],
                "dataflow_version": candidate["dataflow_version"],
            })
            suffix = stable_digest.split(":", 1)[1]
            batch.update({"batch_digest": stable_digest, "batch_id": "batch:" + suffix, "cause_id": "reaction:" + suffix})
            published["published_batch_digest"] = digest({
                "kind": "M3PublishedBatchPreimage", "contract_version": "flrh-r-kernel/1",
                "batch": batch, "ordered_effect_proposals": published["effect_proposals"],
                "ordered_eligibility_verdicts": published["eligibility_verdicts"],
            })
        candidate["ready_batches"] = sorted(
            candidate["ready_batches"],
            key=lambda item: (item["batch"]["logical_time"], canonical_bytes(item)),
        )
        return self.redigest_state(candidate)

    def test_01_fixture_pins_m1_and_opaque_m2_support_only(self):
        golden = json.loads((ROOT / "fixtures/m1/golden/observe-with-effect.transition.json").read_text())
        self.assertEqual(golden["effect_proposals"][0], self.proposal)
        self.assertEqual(2, len(self.verdict["support_derivation_ids"]))
        self.assertTrue(all(item.startswith("derivation:") for item in self.verdict["support_derivation_ids"]))

    def test_02_oracle_is_independent_and_demand_golden_is_exact(self):
        source = (ROOT / "scripts/m3_oracle.py").read_text()
        self.assertNotIn("import flrh_reactive", source)
        sequence = find_by_id(self.corpus["success_sequences"], "sequence:frontier-stable")
        commands = [step["command"] for step in sequence["steps"]]
        expected = json.loads((ROOT / "fixtures/m3/golden/frontier-stable.transition.json").read_text())
        self.assertEqual(expected, run_sequence(None, self.profile, commands)[-1])
        self.assertEqual(expected, self.run_commands(commands)[-1])

    def test_03_apply_permutation_has_same_command_and_transition_bytes(self):
        proposal, verdict = self.pair()
        left = self.command("RApplyDeltaBatch", deltas=[proposal, verdict])
        right = self.command("RApplyDeltaBatch", deltas=[verdict, proposal])
        self.assertEqual(command_digest(left), command_digest(right))
        self.assertEqual(canonical_bytes(step_r(None, self.profile, left)), canonical_bytes(step_r(None, self.profile, right)))
        reversed_proposal = copy.deepcopy(proposal["value"])
        reversed_proposal["preconditions"].reverse()
        reversed_verdict = copy.deepcopy(verdict["value"])
        reversed_verdict["support_derivation_ids"].reverse()
        nested_reversed = self.command(
            "RApplyDeltaBatch",
            deltas=[
                self.delta("source:m3:a", 7, "effect_proposal", reversed_proposal),
                self.delta("source:m3:b", 7, "eligibility_verdict", reversed_verdict),
            ],
        )
        self.assertEqual(canonical_bytes(step_r(None, self.profile, left)), canonical_bytes(step_r(None, self.profile, nested_reversed)))

    def test_04_strict_min_frontier_equality_then_greater_atomic_batch(self):
        proposal, verdict = self.pair(7)
        commands = [self.command("RApplyDeltaBatch", deltas=[proposal, verdict])]
        commands += self.close(7)
        commands += [self.command("RAdvanceFrontier", source_id="source:m3:a", low_watermark=8)]
        at_equal = self.assert_oracle(commands)
        self.assertEqual([], at_equal[-1]["published_batches"])
        result = step_r(at_equal[-1]["next_state"], self.profile, self.command("RAdvanceFrontier", source_id="source:m3:b", low_watermark=8))
        self.assertEqual(1, len(result["next_state"]["ready_batches"]))
        queued = result["next_state"]["ready_batches"][0]
        self.assertEqual(1, len(queued["effect_proposals"]))
        self.assertEqual(1, len(queued["eligibility_verdicts"]))

    def test_05_late_batch_rejects_atomically_even_with_on_time_member(self):
        proposal, verdict = self.pair(7)
        closed = self.run_commands([self.command("RApplyDeltaBatch", deltas=[proposal, verdict]), *self.close(8)])[-1]["next_state"]
        late, _ = self.pair(6, "late")
        on_time, _ = self.pair(8, "ontime")
        before = canonical_bytes(closed)
        result = step_r(closed, self.profile, self.command("RApplyDeltaBatch", deltas=[on_time, late]))
        self.assertEqual("LATE_DELTA", result["code"])
        self.assertEqual(before, canonical_bytes(closed))
        skewed = self.run_commands([
            self.command("RAdvanceFrontier", source_id="source:m3:a", low_watermark=10),
            self.command("RAdvanceFrontier", source_id="source:m3:b", low_watermark=5),
        ])[-1]["next_state"]
        self.assertEqual(
            sorted(skewed["source_frontiers"], key=canonical_bytes),
            skewed["source_frontiers"],
        )
        from_a, _ = self.pair(7, "source-a-late")
        rejected = step_r(skewed, self.profile, self.command("RApplyDeltaBatch", deltas=[from_a]))
        self.assertEqual("LATE_DELTA", rejected["code"])
        from_b_value = copy.deepcopy(from_a["value"])
        from_b = self.delta("source:m3:b", 7, "effect_proposal", from_b_value)
        accepted = step_r(skewed, self.profile, self.command("RApplyDeltaBatch", deltas=[from_b]))
        self.assertEqual("RTransition", accepted["kind"])

    def test_05a_source_lateness_takes_precedence_over_exact_replay(self):
        proposal, verdict = self.pair(7, "late-replay")
        open_state = step_r(
            None,
            self.profile,
            self.command("RApplyDeltaBatch", deltas=[proposal, verdict]),
        )["next_state"]
        at_equal = step_r(
            open_state,
            self.profile,
            self.command(
                "RAdvanceFrontier", source_id="source:m3:a", low_watermark=7
            ),
        )["next_state"]
        replay = self.command("RApplyDeltaBatch", deltas=[proposal])
        equal_result = step_r(at_equal, self.profile, replay)
        self.assertEqual("RTransition", equal_result["kind"])
        self.assertEqual(0, equal_result["stats"]["accepted_delta_count"])

        a_ahead = step_r(
            equal_result["next_state"],
            self.profile,
            self.command(
                "RAdvanceFrontier", source_id="source:m3:a", low_watermark=8
            ),
        )["next_state"]
        before = canonical_bytes(a_ahead)
        expected_late = step_expected(a_ahead, self.profile, replay)
        self.assertEqual("LATE_DELTA", expected_late["code"])
        self.assertEqual(expected_late, step_r(a_ahead, self.profile, replay))
        self.assertEqual(before, canonical_bytes(a_ahead))

        closed = step_r(
            a_ahead,
            self.profile,
            self.command(
                "RAdvanceFrontier", source_id="source:m3:b", low_watermark=8
            ),
        )["next_state"]
        closed_before = canonical_bytes(closed)
        self.assertEqual("LATE_DELTA", step_r(closed, self.profile, replay)["code"])
        self.assertEqual(closed_before, canonical_bytes(closed))

    def test_05b_late_rejection_pointer_names_the_caller_element(self):
        closed = self.run_commands(self.close(8))[-1]["next_state"]
        proposal, verdict = self.pair(6, "two-late")
        for deltas in ([proposal, verdict], [verdict, proposal]):
            command = self.command("RApplyDeltaBatch", deltas=list(deltas))
            expected = step_expected(closed, self.profile, command)
            self.assertEqual("/command/deltas/0/logical_time", expected["path"])
            self.assertEqual(expected, step_r(closed, self.profile, command))

    def test_06_zero_demand_queues_then_one_demand_publishes_whole_epoch(self):
        proposal, verdict = self.pair()
        results = self.assert_oracle([self.command("RApplyDeltaBatch", deltas=[proposal, verdict]), *self.close(8)])
        state = results[-1]["next_state"]
        self.assertEqual((1, 0), (len(state["ready_batches"]), state["outstanding_demand"]))
        result = step_r(state, self.profile, self.command("RGrantDemand", batches=1))
        self.assertEqual(1, len(result["published_batches"]))
        self.assertEqual([], result["next_state"]["ready_batches"])

    def test_07_exact_active_and_demand_bounds_accept_n_reject_n_plus_one(self):
        self.profile["limits"]["max_active_values"] = 2
        self.profile["profile_digest"] = profile_digest(self.profile)
        proposal, verdict = self.pair()
        accepted = step_r(None, self.profile, self.command("RApplyDeltaBatch", deltas=[proposal, verdict]))
        self.assertEqual("RTransition", accepted["kind"])
        extra, _ = self.pair(8, "extra")
        rejected = step_r(accepted["next_state"], self.profile, self.command("RApplyDeltaBatch", deltas=[extra]))
        self.assertEqual("QUEUE_CAPACITY_EXCEEDED", rejected["code"])
        demand = step_r(None, self.profile, self.command("RGrantDemand", batches=2))
        self.assertEqual(2, demand["next_state"]["outstanding_demand"])
        overflow = step_r(demand["next_state"], self.profile, self.command("RGrantDemand", batches=2))
        self.assertEqual("DEMAND_LIMIT_EXCEEDED", overflow["code"])

    def test_07a_demand_addition_is_checked_before_ready_drain(self):
        self.profile["limits"]["max_demand_per_command"] = 4
        self.profile["limits"]["max_outstanding_demand"] = 3
        self.profile["profile_digest"] = profile_digest(self.profile)
        proposal, verdict = self.pair()
        ready = self.run_commands(
            [self.command("RApplyDeltaBatch", deltas=[proposal, verdict]), *self.close(8)]
        )[-1]["next_state"]
        self.assertEqual(1, len(ready["ready_batches"]))
        prior_bytes = canonical_bytes(ready)
        command = self.command("RGrantDemand", batches=4)
        expected = step_expected(ready, self.profile, command)
        self.assertEqual("DEMAND_LIMIT_EXCEEDED", expected["code"])
        self.assertEqual("/command/batches", expected["path"])
        self.assertEqual({"limit": 3, "observed": 4}, expected["context"])
        self.assertEqual(expected, step_r(ready, self.profile, command))
        self.assertEqual(prior_bytes, canonical_bytes(ready))

    def test_07b_ready_capacity_bounds_the_retained_queue_after_drain(self):
        self.profile["limits"]["max_ready_batches"] = 1
        self.profile["profile_digest"] = profile_digest(self.profile)
        p5, v5 = self.pair(5, "five-ready-limit")
        p7, v7 = self.pair(7, "seven-ready-limit")
        state = self.run_commands(
            [
                self.command("RGrantDemand", batches=1),
                self.command("RApplyDeltaBatch", deltas=[p5, v5, p7, v7]),
                self.command("RAdvanceFrontier", source_id="source:m3:a", low_watermark=8),
            ]
        )[-1]["next_state"]
        self.assertEqual(1, state["outstanding_demand"])
        command = self.command(
            "RAdvanceFrontier", source_id="source:m3:b", low_watermark=8
        )
        expected = step_expected(state, self.profile, command)
        self.assertEqual("RTransition", expected["kind"])
        self.assertEqual((1, 1), (len(expected["published_batches"]), len(expected["next_state"]["ready_batches"])))
        prior_bytes = canonical_bytes(state)
        self.assertEqual(expected, step_r(state, self.profile, command))
        self.assertEqual(prior_bytes, canonical_bytes(state))

        p3, v3 = self.pair(3, "three-ready-limit")
        three_epochs = [p3, v3, p5, v5, p7, v7]
        one_credit_state = self.run_commands(
            [
                self.command("RGrantDemand", batches=1),
                self.command("RApplyDeltaBatch", deltas=three_epochs),
                self.command("RAdvanceFrontier", source_id="source:m3:a", low_watermark=8),
            ]
        )[-1]["next_state"]
        close_b = self.command(
            "RAdvanceFrontier", source_id="source:m3:b", low_watermark=8
        )
        rejected = step_expected(one_credit_state, self.profile, close_b)
        self.assertEqual("QUEUE_CAPACITY_EXCEEDED", rejected["code"])
        self.assertEqual({"limit": 1, "observed": 2}, rejected["context"])
        self.assertEqual(rejected, step_r(one_credit_state, self.profile, close_b))

        two_credit_state = self.run_commands(
            [
                self.command("RGrantDemand", batches=2),
                self.command("RApplyDeltaBatch", deltas=three_epochs),
                self.command("RAdvanceFrontier", source_id="source:m3:a", low_watermark=8),
            ]
        )[-1]["next_state"]
        accepted = step_expected(two_credit_state, self.profile, close_b)
        self.assertEqual("RTransition", accepted["kind"])
        self.assertEqual((2, 1), (len(accepted["published_batches"]), len(accepted["next_state"]["ready_batches"])))
        self.assertEqual(accepted, step_r(two_credit_state, self.profile, close_b))

    def test_07c_open_epoch_capacity_rejects_new_without_silent_drop(self):
        self.profile["limits"]["max_open_epochs"] = 1
        self.profile["limits"]["max_active_values"] = 8
        self.profile["profile_digest"] = profile_digest(self.profile)
        p5, v5 = self.pair(5, "five-open-limit")
        p7, v7 = self.pair(7, "seven-open-limit")
        command = self.command(
            "RApplyDeltaBatch", deltas=[p5, v5, p7, v7]
        )
        expected = step_expected(None, self.profile, command)
        self.assertEqual("QUEUE_CAPACITY_EXCEEDED", expected["code"])
        self.assertEqual("/command/deltas", expected["path"])
        self.assertEqual({"limit": 1, "observed": 2}, expected["context"])
        self.assertEqual(expected, step_r(None, self.profile, command))
        self.assertNotIn("next_state", expected)

    def test_08_ready_batches_publish_in_time_order_with_canonical_ties(self):
        p7, v7 = self.pair(7, "seven")
        p5, v5 = self.pair(5, "five")
        commands = [self.command("RGrantDemand", batches=2), self.command("RApplyDeltaBatch", deltas=[v7, p5, p7, v5]), *self.close(8)]
        result = self.assert_oracle(commands)[-1]
        self.assertEqual([5, 7], [item["batch"]["logical_time"] for item in result["published_batches"]])

    def test_09_duplicate_retraction_unknown_and_identity_conflict(self):
        proposal, _ = self.pair()
        duplicate = self.command("RApplyDeltaBatch", deltas=[proposal, copy.deepcopy(proposal)])
        first = step_r(None, self.profile, duplicate)
        self.assertEqual(1, first["stats"]["accepted_delta_count"])
        retract = copy.deepcopy(proposal)
        retract["diff"] = -1
        removed = step_r(first["next_state"], self.profile, self.command("RApplyDeltaBatch", deltas=[retract]))
        self.assertEqual(1, removed["stats"]["retracted_delta_count"])
        self.assertEqual("UNKNOWN_DELIVERY", step_r(removed["next_state"], self.profile, self.command("RApplyDeltaBatch", deltas=[retract]))["code"])
        conflict = copy.deepcopy(proposal)
        conflict["value"]["cause_id"] = "cause:m3:conflict"
        self.assertEqual("VALUE_IDENTITY_CONFLICT", step_r(None, self.profile, self.command("RApplyDeltaBatch", deltas=[conflict]))["code"])

    def test_10_dependency_bijection_and_rule_set_binding_reject(self):
        proposal, verdict = self.pair()
        for deltas, code in [([proposal], "UNRESOLVED_DEPENDENCY"), ([verdict], "UNRESOLVED_DEPENDENCY")]:
            state = step_r(None, self.profile, self.command("RApplyDeltaBatch", deltas=deltas))["next_state"]
            result = self.run_from(state, self.close(8))
            self.assertEqual(code, result["code"])
        bad_verdict = copy.deepcopy(verdict)
        bad_verdict["value"]["rule_set_version"] = "rules/other"
        bad_verdict = self.delta("source:m3:b", 7, "eligibility_verdict", bad_verdict["value"])
        state = step_r(None, self.profile, self.command("RApplyDeltaBatch", deltas=[proposal, bad_verdict]))["next_state"]
        self.assertEqual("RULE_SET_VERSION_MISMATCH", self.run_from(state, self.close(8))["code"])
        bad_delta = copy.deepcopy(proposal)
        bad_delta["dataflow_version"] = "dataflow/other"
        self.assertEqual("DATAFLOW_VERSION_MISMATCH", step_r(None, self.profile, self.command("RApplyDeltaBatch", deltas=[bad_delta]))["code"])
        bad_value = copy.deepcopy(proposal["value"])
        bad_value["versions"]["dataflow"] = "dataflow/other"
        nested_bad = self.delta("source:m3:a", 7, "effect_proposal", bad_value)
        self.assertEqual("DATAFLOW_VERSION_MISMATCH", step_r(None, self.profile, self.command("RApplyDeltaBatch", deltas=[nested_bad]))["code"])

    def run_from(self, state, commands):
        result = None
        for command in commands:
            result = step_r(state, self.profile, command)
            if result["kind"] == "RRejection":
                return result
            state = result["next_state"]
        return result

    def test_11_duplicate_protocol_identity_with_distinct_delivery_rejects(self):
        proposal, verdict = self.pair()
        second_value = copy.deepcopy(proposal["value"])
        second_value["cause_id"] = "cause:m3:same-proposal-other-value"
        second = self.delta("source:m3:b", 7, "effect_proposal", second_value)
        state = step_r(None, self.profile, self.command("RApplyDeltaBatch", deltas=[proposal, second, verdict]))["next_state"]
        self.assertEqual("UNRESOLVED_DEPENDENCY", self.run_from(state, self.close(8))["code"])
        other_proposal, other_verdict = self.pair(7, "other")
        duplicate_verdict_id = copy.deepcopy(other_verdict["value"])
        duplicate_verdict_id["verdict_id"] = verdict["value"]["verdict_id"]
        other_verdict = self.delta("source:m3:b", 7, "eligibility_verdict", duplicate_verdict_id)
        state = step_r(None, self.profile, self.command("RApplyDeltaBatch", deltas=[proposal, verdict, other_proposal, other_verdict]))["next_state"]
        self.assertEqual("UNRESOLVED_DEPENDENCY", self.run_from(state, self.close(8))["code"])

        ready = self.run_commands([
            self.command("RApplyDeltaBatch", deltas=[proposal, verdict]), *self.close(8)
        ])[-1]["next_state"]

        orphan = copy.deepcopy(ready)
        orphan["ready_batches"][0]["eligibility_verdicts"] = []
        orphan["ready_batches"][0]["batch"]["eligibility_verdict_ids"] = []
        self.assertEqual("UNRESOLVED_DEPENDENCY", step_r(self.redigest_ready_state(orphan), self.profile, self.command("RGrantDemand", batches=1))["code"])
        wrong_rule = copy.deepcopy(ready)
        wrong_rule["ready_batches"][0]["eligibility_verdicts"][0]["rule_set_version"] = "rules/other"
        self.assertEqual("RULE_SET_VERSION_MISMATCH", step_r(self.redigest_ready_state(wrong_rule), self.profile, self.command("RGrantDemand", batches=1))["code"])
        wrong_dataflow = copy.deepcopy(ready)
        wrong_dataflow["ready_batches"][0]["effect_proposals"][0]["versions"]["dataflow"] = "dataflow/other"
        self.assertEqual("DATAFLOW_VERSION_MISMATCH", step_r(self.redigest_ready_state(wrong_dataflow), self.profile, self.command("RGrantDemand", batches=1))["code"])

    def test_11a_protocol_identity_uniqueness_is_epoch_local(self):
        proposal, verdict = self.pair(7, "epoch-local")
        same_proposal_later = self.delta(
            "source:m3:a", 9, "effect_proposal", proposal["value"]
        )
        same_verdict_later = self.delta(
            "source:m3:b", 9, "eligibility_verdict", verdict["value"]
        )
        commands = [
            self.command("RGrantDemand", batches=2),
            self.command(
                "RApplyDeltaBatch",
                deltas=[proposal, verdict, same_proposal_later, same_verdict_later],
            ),
            *self.close(10),
        ]
        result = self.assert_oracle(commands)[-1]
        self.assertEqual(2, len(result["published_batches"]))
        self.assertEqual(
            [proposal["value"]["proposal_id"]] * 2,
            [item["batch"]["proposal_ids"][0] for item in result["published_batches"]],
        )

    def test_12_non_nfc_float_and_int64_are_closed_rejections(self):
        for command in [
            self.command("RAdvanceFrontier", source_id="source:m3:a", low_watermark=2**63),
            self.command("RGrantDemand", batches=1.5),
            {**self.command("RAdvanceFrontier", source_id="source:m3:a", low_watermark=1), "extra": "e\u0301"},
        ]:
            result = step_r(None, self.profile, command)
            self.assertEqual("RRejection", result["kind"])
            self.assertIn(result["code"], {"CANONICALIZATION_VIOLATION", "MALFORMED_COMMAND"})

        proposal, _ = self.pair()
        malformed_digest = copy.deepcopy(proposal)
        malformed_digest["value_digest"] = True
        rejection = step_r(
            None,
            self.profile,
            self.command("RApplyDeltaBatch", deltas=[malformed_digest]),
        )
        self.assertEqual("MALFORMED_VALUE_DELTA", rejection["code"])
        self.assertEqual("/command/deltas/0/value_digest", rejection["path"])
        self.assertEqual({}, rejection["context"])

    def test_13_inputs_are_not_mutated_or_aliased(self):
        proposal, verdict = self.pair()
        command = self.command("RApplyDeltaBatch", deltas=[proposal, verdict])
        profile_before, command_before = canonical_bytes(self.profile), canonical_bytes(command)
        result = step_r(None, self.profile, command)
        self.assertEqual(profile_before, canonical_bytes(self.profile))
        self.assertEqual(command_before, canonical_bytes(command))
        frozen = canonical_bytes(result)
        command["deltas"][0]["value"]["cause_id"] = "cause:mutated"
        self.profile["source_ids"].append("source:mutated")
        self.assertEqual(frozen, canonical_bytes(result))

        open_state = copy.deepcopy(result["next_state"])
        duplicate_epoch = copy.deepcopy(open_state)
        duplicate_epoch["open_epochs"].append(copy.deepcopy(duplicate_epoch["open_epochs"][0]))
        before = canonical_bytes(self.redigest_state(duplicate_epoch))
        rejection = step_r(duplicate_epoch, copy.deepcopy(self.corpus["profile"]), self.command("RGrantDemand", batches=1))
        self.assertEqual("MALFORMED_REACTIVE_STATE", rejection["code"])
        self.assertEqual(before, canonical_bytes(duplicate_epoch))

        noncanonical = copy.deepcopy(open_state)
        stored_proposal = next(
            item for item in noncanonical["open_epochs"][0]["values"]
            if item["value_kind"] == "effect_proposal"
        )
        stored_proposal["value"]["preconditions"].reverse()
        self.redigest_state(noncanonical)
        self.assertEqual("MALFORMED_REACTIVE_STATE", step_r(noncanonical, copy.deepcopy(self.corpus["profile"]), self.command("RGrantDemand", batches=1))["code"])

        base_profile = copy.deepcopy(self.corpus["profile"])
        self.profile = base_profile
        p, v = self.pair()
        ready = self.run_commands([self.command("RApplyDeltaBatch", deltas=[p, v]), *self.close(8)])[-1]["next_state"]
        duplicate_ready = copy.deepcopy(ready)
        duplicate_ready["ready_batches"].append(copy.deepcopy(duplicate_ready["ready_batches"][0]))
        self.assertEqual("MALFORMED_REACTIVE_STATE", step_r(self.redigest_state(duplicate_ready), base_profile, self.command("RGrantDemand", batches=1))["code"])
        future_watermark = copy.deepcopy(ready)
        future_watermark["ready_batches"][0]["batch"]["low_watermark"] = 9
        self.assertEqual("MALFORMED_REACTIVE_STATE", step_r(self.redigest_ready_state(future_watermark), base_profile, self.command("RGrantDemand", batches=1))["code"])

        empty_ready = copy.deepcopy(ready)
        empty_ready["ready_batches"][0]["effect_proposals"] = []
        empty_ready["ready_batches"][0]["eligibility_verdicts"] = []
        empty_ready["ready_batches"][0]["batch"]["proposal_ids"] = []
        empty_ready["ready_batches"][0]["batch"]["eligibility_verdict_ids"] = []
        empty_result = step_r(
            self.redigest_ready_state(empty_ready),
            base_profile,
            self.command("RGrantDemand", batches=1),
        )
        self.assertEqual("MALFORMED_REACTIVE_STATE", empty_result["code"])

    def test_14_fixture_rejections_are_complete_exact_objects(self):
        for case in self.corpus["rejection_cases"]:
            prior = None
            if case["prior_sequence_ref"] is not None:
                sequence = find_by_id(self.corpus["success_sequences"], case["prior_sequence_ref"])
                prior = self.run_commands(
                    [step["command"] for step in sequence["steps"][: case["prior_step"] + 1]]
                )[-1]["next_state"]
            self.assertEqual(case["expected"], step_r(prior, self.profile, case["command"]))
        golden = json.loads((ROOT / "fixtures/m3/golden/late-delta.rejection.json").read_text())
        self.assertEqual(self.corpus["rejection_cases"][0]["expected"], golden)

    def test_15_replay_is_clean_and_r_does_not_claim_h_authority(self):
        commands = None
        for status in ("eligible", "ineligible", "conflicted"):
            proposal, verdict = self.pair(status=status)
            status_commands = [
                self.command("RGrantDemand", batches=1),
                self.command("RApplyDeltaBatch", deltas=[proposal, verdict]),
                *self.close(8),
            ]
            direct = self.run_commands(status_commands)[-1]
            self.assertEqual(status, direct["published_batches"][0]["eligibility_verdicts"][0]["status"])
            self.assertEqual(proposal["value"], direct["published_batches"][0]["effect_proposals"][0])
            self.assertNotIn("effect_intents", direct)
            self.assertNotIn("receipts", direct)
            if status == "conflicted":
                commands = status_commands

        self.assertIsNotNone(commands)
        document = {"mode": "sequence", "prior_state": None, "profile": self.profile, "commands": commands}
        completed = subprocess.run([sys.executable, str(ROOT / "scripts/run_m3_replay.py")], input=json.dumps(document).encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        self.assertEqual(b"", completed.stderr)
        result = json.loads(completed.stdout)
        final = result["results"][-1]
        self.assertEqual("conflicted", final["published_batches"][0]["eligibility_verdicts"][0]["status"])
        self.assertNotIn("effect_intents", final)
        self.assertNotIn("receipts", final)


if __name__ == "__main__":
    unittest.main()
