"""M4A pure authority projection conformance tests."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from flrh_authority import project_h_intent
from m4a_fixtures import digest, find_case, load_cases
from m4a_oracle import project_expected


class M4AAuthorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = load_cases()

    def test_01_public_surface_is_exact(self):
        import flrh_authority
        self.assertEqual(["project_h_intent"], flrh_authority.__all__)

    def test_02_successes_equal_independent_oracle_and_golden(self):
        source = (ROOT / "scripts/m4a_oracle.py").read_text(encoding="utf-8")
        self.assertNotIn("import flrh_authority", source)
        for case in self.corpus["success_cases"]:
            command = copy.deepcopy(case["command"])
            before = json.dumps(command, ensure_ascii=False, sort_keys=True)
            expected = project_expected(command)
            actual = project_h_intent(command)
            self.assertEqual(expected, actual, case["id"])
            self.assertEqual(before, json.dumps(command, ensure_ascii=False, sort_keys=True))
            golden = json.loads((ROOT / case["golden"]).read_text(encoding="utf-8"))
            self.assertEqual(golden, actual)

    def test_03_rejections_are_closed_and_immutable(self):
        for case in self.corpus["rejection_cases"]:
            command = copy.deepcopy(case["command"])
            before = copy.deepcopy(command)
            actual = project_h_intent(command)
            self.assertEqual("HRejection", actual["kind"], case["id"])
            self.assertEqual(case["expected_code"], actual["code"], case["id"])
            self.assertEqual(project_expected(command), actual, case["id"])
            self.assertEqual(before, command)

    def test_04_singleton_and_approval_lifecycle_boundary(self):
        low = project_h_intent(copy.deepcopy(find_case(self.corpus, "success:low-risk")))
        high = project_h_intent(copy.deepcopy(find_case(self.corpus, "success:approval-request")))
        granted = project_h_intent(copy.deepcopy(find_case(self.corpus, "success:approval-granted")))
        self.assertEqual(("EFFECT_AUTHORIZED", "COMMIT_INTENT"), (low["event"], low["next_control_state"]))
        self.assertIsNone(low["approval_request"])
        self.assertFalse(low["intent"]["approval_required"])
        self.assertEqual(("APPROVAL_REQUIRED", "WAIT_APPROVAL"), (high["event"], high["next_control_state"]))
        self.assertIsNone(high["intent"])
        self.assertEqual(("APPROVAL_GRANTED", "COMMIT_INTENT"), (granted["event"], granted["next_control_state"]))
        self.assertTrue(granted["intent"]["approval_required"])
        forbidden = {"INTENT_COMMITTED", "ATTEMPT_RECORDED", "EFFECT_RESULT_CONFIRMED"}
        self.assertFalse({low["event"], high["event"], granted["event"]} & forbidden)

    def test_05_replay_is_canonical_and_deterministic(self):
        command = find_case(self.corpus, "success:approval-granted")
        payload = json.dumps(command, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode() + b"\n"
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts/run_m4a_replay.py")],
            input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT,
        )
        self.assertEqual(0, completed.returncode, completed.stderr.decode())
        self.assertEqual(b"", completed.stderr)
        self.assertEqual(project_h_intent(copy.deepcopy(command)), json.loads(completed.stdout))

    def test_06_published_cardinality_identity_and_outer_digest_fail_closed(self):
        command = find_case(self.corpus, "success:low-risk")
        command["published_batch"]["published_batch_digest"] = "sha256:" + "0" * 64
        core = {key: copy.deepcopy(value) for key, value in command.items() if key != "command_digest"}
        command["command_digest"] = digest({"kind":"M4ACommandPreimage", "contract_version":"flrh-h-authority/1", **core})
        self.assertEqual("PUBLISHED_BATCH_DIGEST_MISMATCH", project_h_intent(command)["code"])

        command = find_case(self.corpus, "success:low-risk")
        command["published_batch"]["batch"]["cause_id"] = "reaction:" + "0" * 64
        published = command["published_batch"]
        published["published_batch_digest"] = digest({"kind":"M3PublishedBatchPreimage", "contract_version":"flrh-r-kernel/1", "batch":published["batch"], "ordered_effect_proposals":published["effect_proposals"], "ordered_eligibility_verdicts":published["eligibility_verdicts"]})
        core = {key: copy.deepcopy(value) for key, value in command.items() if key != "command_digest"}
        command["command_digest"] = digest({"kind":"M4ACommandPreimage", "contract_version":"flrh-h-authority/1", **core})
        self.assertEqual("BATCH_DIGEST_MISMATCH", project_h_intent(command)["code"])

    def test_07_approval_all_field_binding_matrix(self):
        base = find_case(self.corpus, "success:approval-granted")
        mutations = {
            "request_digest": "sha256:" + "1" * 64,
            "action_digest": "sha256:" + "2" * 64,
            "destination_digest": "sha256:" + "3" * 64,
            "capability": "capability:other",
            "authority_digest": "sha256:" + "4" * 64,
            "adapter_version": "publisher/other",
            "nonce": "nonce:other",
        }
        for field, replacement in mutations.items():
            command = copy.deepcopy(base)
            command["approval"][field] = replacement
            approval_core = {key: copy.deepcopy(value) for key, value in command["approval"].items() if key != "approval_digest"}
            command["approval"]["approval_digest"] = digest({"kind":"M4AApprovalPreimage", "contract_version":"flrh-h-authority/1", **approval_core})
            command_core = {key: copy.deepcopy(value) for key, value in command.items() if key != "command_digest"}
            command["command_digest"] = digest({"kind":"M4ACommandPreimage", "contract_version":"flrh-h-authority/1", **command_core})
            result = project_h_intent(command)
            self.assertEqual("APPROVAL_BINDING_MISMATCH", result["code"], field)

    def test_08_m3_batch_profile_and_semantics_fail_closed(self):
        base = find_case(self.corpus, "success:low-risk")
        for path, replacement, code in (
            (("published_batch", "batch", "logical_time"), -1, "MALFORMED_PUBLISHED_BATCH"),
            (("published_batch", "batch", "low_watermark"), 0, "MALFORMED_PUBLISHED_BATCH"),
            (("published_batch", "effect_proposals", 0, "proposal_id"), "bad id", "MALFORMED_PROPOSAL"),
            (("published_batch", "effect_proposals", 0, "preconditions"), ["p:1", "p:1"], "MALFORMED_PROPOSAL"),
        ):
            command = copy.deepcopy(base)
            target = command
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = replacement
            self._redigest_command(command)
            self.assertEqual(code, project_h_intent(command)["code"], path)
        command = copy.deepcopy(base)
        command["r_profile_digest"] = "sha256:" + "f" * 64
        self._redigest_command(command)
        self.assertEqual("BATCH_DIGEST_MISMATCH", project_h_intent(command)["code"])

    def test_09_idempotency_is_exact_loop_contract_tuple(self):
        command = find_case(self.corpus, "success:low-risk")
        result = project_h_intent(command)
        intent = result["intent"]
        expected = digest({
            "kind": "M4AIdempotencyPreimage",
            "contract_version": "flrh-h-authority/1",
            "run_id": command["approval_context"]["run_id"] if command["approval_context"] else command["published_batch"]["effect_proposals"][0]["correlation_id"],
            "transition_id": "authorize-low-risk",
            "effect_sequence": command["effect_sequence"],
            "action_digest": intent["action_digest"],
            "adapter_version": intent["adapter_version"],
        })
        self.assertEqual("effect:" + expected.split(":", 1)[1], intent["idempotency_key"])

    def test_10_approval_request_binds_context_and_loop_fields(self):
        command = find_case(self.corpus, "success:approval-request")
        request = project_h_intent(command)["approval_request"]
        context = command["approval_context"]
        for field in ("context_digest", "policy_version", "approver_scope", "run_id", "workflow_version", "artifact_digest", "visibility", "actor", "rationale"):
            self.assertEqual(context[field], request[field], field)

    def test_11_projection_has_exact_fsm_event_evidence(self):
        manifest = json.loads((ROOT / "spec/m4a-manifest.v1.json").read_text(encoding="utf-8"))
        dependency = next(item for item in manifest["inherited_dependencies"] if item["artifact"] == "spec/run-fsm.v1.json")
        fsm_path = ROOT / dependency["artifact"]
        self.assertEqual(dependency["sha256"], "sha256:" + hashlib.sha256(fsm_path.read_bytes()).hexdigest())
        fsm = json.loads(fsm_path.read_text(encoding="utf-8"))
        transitions = {item["event"]: item for item in fsm["machines"][0]["transitions"]}
        expected = {
            "success:low-risk": ("EFFECT_AUTHORIZED", "policy_evaluator", "effect.authorize_low_risk"),
            "success:approval-request": ("APPROVAL_REQUIRED", "policy_evaluator", "approval.request"),
            "success:approval-granted": ("APPROVAL_GRANTED", "human_approver", "approval.grant_exact_hash"),
        }
        for case_id, triple in expected.items():
            command = find_case(self.corpus, case_id)
            projection = project_h_intent(command)
            event = projection["control_event"]
            self.assertEqual(triple, (event["type"], event["actor_role"], event["capability"]))
            self.assertEqual(projection["command_digest"], event["payload"]["command_digest"])
            proposal = command["published_batch"]["effect_proposals"][0]
            snapshot = command["authority_snapshot"]
            semantic_evidence = {
                "action_digest": proposal["action_digest"],
                "risk_classification": snapshot["assessed_risk"],
                "policy_verdict": digest({
                    "kind": "M4APolicyVerdictEvidencePreimage",
                    "contract_version": "flrh-h-authority/1",
                    "r_profile_digest": command["r_profile_digest"],
                    "eligibility_verdict": command["published_batch"]["eligibility_verdicts"][0],
                    "authority_decision": snapshot["decision"],
                    "authority_digest": snapshot["authority_digest"],
                    "assessed_risk": snapshot["assessed_risk"],
                }),
                "capability_digest": digest({
                    "kind": "M4ACapabilityEvidencePreimage",
                    "contract_version": "flrh-h-authority/1",
                    "capability": snapshot["capability"],
                    "authority_digest": snapshot["authority_digest"],
                    "proposal_id": proposal["proposal_id"],
                    "effect_type": proposal["effect_type"],
                    "action_digest": proposal["action_digest"],
                    "destination_digest": proposal["destination_digest"],
                    "adapter_version": snapshot["adapter_version"],
                }),
                "exact_hash_approval_digest": command["approval"]["approval_digest"] if command["approval"] else None,
            }
            required = transitions[event["type"]]["evidence_required"]
            self.assertEqual(set(required), set(event["payload"]) & set(required), case_id)
            for field in required:
                self.assertEqual(semantic_evidence[field], event["payload"][field], f"{case_id}:{field}")

    def test_12_auditor_runtime_repros_fail_closed(self):
        approval_kind = find_case(self.corpus, "success:approval-granted")
        approval_kind["approval"]["kind"] = "NotHApproval"
        self._redigest_approval(approval_kind["approval"])
        self._redigest_command(approval_kind)

        authority_version = find_case(self.corpus, "success:low-risk")
        authority_version["authority_snapshot"]["authority_version"] = "a" * 129
        self._redigest_snapshot(authority_version["authority_snapshot"])
        self._redigest_command(authority_version)

        long_precondition = find_case(self.corpus, "success:low-risk")
        long_precondition["published_batch"]["effect_proposals"][0]["preconditions"] = ["p" * 129]
        self._redigest_published(long_precondition["published_batch"])
        self._redigest_command(long_precondition)

        long_support = find_case(self.corpus, "success:low-risk")
        long_support["published_batch"]["eligibility_verdicts"][0]["support_derivation_ids"] = ["s" * 129]
        self._redigest_published(long_support["published_batch"])
        self._redigest_command(long_support)

        repros = (
            ("approval.kind", approval_kind, "MALFORMED_APPROVAL", "/approval/kind"),
            ("authority_version", authority_version, "MALFORMED_AUTHORITY_SNAPSHOT", "/authority_snapshot/authority_version"),
            ("precondition length", long_precondition, "MALFORMED_PROPOSAL", "/published_batch/effect_proposals/0/preconditions"),
            ("support id length", long_support, "MALFORMED_VERDICT", "/published_batch/eligibility_verdicts/0/support_derivation_ids"),
        )
        for name, command, code, path in repros:
            with self.subTest(name=name):
                result = project_h_intent(command)
                self.assertEqual(("HRejection", code, path), (result.get("kind"), result.get("code"), result.get("path")))

    @staticmethod
    def _redigest_published(published):
        published["published_batch_digest"] = digest({
            "kind": "M3PublishedBatchPreimage",
            "contract_version": "flrh-r-kernel/1",
            "batch": published["batch"],
            "ordered_effect_proposals": published["effect_proposals"],
            "ordered_eligibility_verdicts": published["eligibility_verdicts"],
        })

    @staticmethod
    def _redigest_snapshot(snapshot):
        core = {key: copy.deepcopy(value) for key, value in snapshot.items() if key != "authority_digest"}
        snapshot["authority_digest"] = digest({"kind": "M4AAuthorityPreimage", "contract_version": "flrh-h-authority/1", **core})

    @staticmethod
    def _redigest_approval(approval):
        core = {key: copy.deepcopy(value) for key, value in approval.items() if key != "approval_digest"}
        approval["approval_digest"] = digest({"kind": "M4AApprovalPreimage", "contract_version": "flrh-h-authority/1", **core})

    @staticmethod
    def _redigest_command(command):
        core = {key: copy.deepcopy(value) for key, value in command.items() if key != "command_digest"}
        command["command_digest"] = digest({"kind":"M4ACommandPreimage", "contract_version":"flrh-h-authority/1", **core})


if __name__ == "__main__":
    unittest.main()
