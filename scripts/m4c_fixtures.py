#!/usr/bin/env python3
"""Deterministic builders for the bounded M4C public integration profile."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from flrh_kernel.canonical import canonical_digest
from lr_seam_fixtures import (
    literal,
    materialize_binding_profile,
    materialize_query,
    materialize_query_batch,
    materialize_r_profile,
    materialize_requirement,
    materialize_rule_bundle,
)


ROOT = Path(__file__).resolve().parents[1]
M4A_CONTRACT = "flrh-h-authority/1"
M4C_CONTRACT = "flrh-m4c-integration/1"


def fresh(value: Any) -> Any:
    return copy.deepcopy(value)


def load_m1_input() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    corpus = json.loads((ROOT / "fixtures/m1/cases.json").read_text(encoding="utf-8"))
    value = corpus["base_inputs"]["observe-with-effect"]
    return fresh(value["snapshot"]), fresh(value["accepted_event"])


def load_m1_expected_transition() -> Dict[str, Any]:
    return json.loads(
        (ROOT / "fixtures/m1/golden/observe-with-effect.transition.json").read_text(
            encoding="utf-8"
        )
    )


def build_l_inputs(f_transition: Dict[str, Any]) -> Tuple[
    Dict[str, Any], List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]], List[str]
]:
    """Build the exact L/LR inputs from the live F output, never from a golden."""

    if f_transition.get("kind") != "FTransition":
        raise ValueError("M4C requires one live FTransition")
    if len(f_transition.get("fact_deltas", [])) != 1:
        raise ValueError("M4C singleton profile requires one fact delta")
    if len(f_transition.get("effect_proposals", [])) != 1:
        raise ValueError("M4C singleton profile requires one effect proposal")

    proposal = fresh(f_transition["effect_proposals"][0])
    observation = fresh(f_transition["fact_deltas"][0]["tuple"])
    fact_precondition_ids = ["constraint:artifact-ready"]
    frontier_precondition_ids = ["frontier:1"]
    if set(proposal["preconditions"]) != set(fact_precondition_ids + frontier_precondition_ids):
        raise ValueError("M4C proposal precondition ownership changed")

    atom = {
        "predicate": "proposal_precondition_satisfied",
        "proposal_id": proposal["proposal_id"],
        "precondition_id": fact_precondition_ids[0],
    }
    requirements = [materialize_requirement(fact_precondition_ids[0], atom)]
    rules = [{
        "rule_id": "rule:m4c:artifact-ready",
        "stratum": 0,
        "head": literal(atom),
        "required_body": [literal(observation)],
        "default_not_positive_body": [],
    }]
    bundle = materialize_rule_bundle(
        query_atoms=[atom],
        rules=rules,
        rule_set_version="rules/0",
        dataflow_version="dataflow/0",
    )
    deltas = [{
        "kind": "LFactDeltaInput",
        "schema_version": "flrh-l-input/1",
        "polarity": "positive",
        "delta": fresh(f_transition["fact_deltas"][0]),
    }]
    return bundle, deltas, proposal, requirements, frontier_precondition_ids


def build_lr_inputs(
    f_transition: Dict[str, Any], l_result: Dict[str, Any]
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    bundle, _deltas, proposal, requirements, frontiers = build_l_inputs(f_transition)
    r_profile = materialize_r_profile()
    binding = materialize_binding_profile(rule_set_version="rules/0")
    query = materialize_query(
        proposal, requirements, frontier_precondition_ids=frontiers
    )
    batch = materialize_query_batch(
        binding_profile=binding,
        l_result=l_result,
        rule_bundle=bundle,
        r_profile=r_profile,
        queries=[query],
    )
    return bundle, r_profile, binding, batch


def build_low_risk_h_command(
    published_batch: Dict[str, Any], r_profile_digest: str
) -> Dict[str, Any]:
    proposal = published_batch["effect_proposals"][0]
    snapshot = {
        "kind": "HAuthoritySnapshot",
        "authority_version": "authority/1",
        "proposal_id": proposal["proposal_id"],
        "effect_type": proposal["effect_type"],
        "capability": "capability:artifact.publish",
        "decision": "allow",
        "assessed_risk": "reversible",
        "adapter_version": proposal["versions"]["tool"],
        "destination_digest": proposal["destination_digest"],
        "valid_from": 0,
        "valid_until": 200,
        "revoked": False,
    }
    snapshot["authority_digest"] = canonical_digest({
        "kind": "M4AAuthorityPreimage",
        "contract_version": M4A_CONTRACT,
        **snapshot,
    })
    command = {
        "kind": "HProjectIntentCommand",
        "schema_version": "flrh-h-project-intent-command/1",
        "contract_version": M4A_CONTRACT,
        "control_state": "PLAN_EFFECTS",
        "r_profile_digest": r_profile_digest,
        "published_batch": fresh(published_batch),
        "authority_snapshot": snapshot,
        "approval_context": None,
        "approval_request": None,
        "approval": None,
        "observed_at": 100,
        "effect_sequence": 1,
    }
    command["command_digest"] = canonical_digest({
        "kind": "M4ACommandPreimage",
        "contract_version": M4A_CONTRACT,
        **command,
    })
    return command


def build_receipt_binding(
    accepted_event: Dict[str, Any], h_command: Dict[str, Any]
) -> Dict[str, str]:
    return {
        "command_digest": h_command["command_digest"],
        "input_root_digest": canonical_digest({
            "kind": "M4CInputRootPreimage",
            "contract_version": M4C_CONTRACT,
            "accepted_event": fresh(accepted_event),
        }),
        "platform_digest": canonical_digest({
            "kind": "M4CPlatformPreimage",
            "contract_version": M4C_CONTRACT,
            "adapter_profile": "FakeAdapter",
            "durable_profile": "sqlite-wal-full/1",
            "canonicalization_version": "flrh-cjson/1",
        }),
    }


def build_receipt_evidence(h_projection: Dict[str, Any]):
    output_digest = canonical_digest({
        "kind": "M4CAdapterOutputPreimage",
        "contract_version": M4C_CONTRACT,
        "projection_digest": h_projection["projection_digest"],
    })

    def receipt_evidence(_intent: Dict[str, Any], _attempt_id: str, outcome: str):
        return {
            "output_digests": [output_digest],
            "trace_ref": "trace:m4c:one-shot",
            "outcome": outcome,
        }

    return receipt_evidence


__all__ = [
    "M4C_CONTRACT",
    "build_l_inputs",
    "build_low_risk_h_command",
    "build_lr_inputs",
    "build_receipt_binding",
    "build_receipt_evidence",
    "fresh",
    "load_m1_expected_transition",
    "load_m1_input",
]
