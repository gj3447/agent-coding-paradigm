#!/usr/bin/env python3
"""Deterministic builders for the additive M4C-IL integration profile."""

from __future__ import annotations

import copy
from typing import Any, Dict

from flrh_kernel.canonical import canonical_digest
from m4c_fixtures import (
    build_l_inputs,
    build_low_risk_h_command,
    build_lr_inputs,
    load_m1_expected_transition,
    load_m1_input,
)


M4CIL_CONTRACT = "flrh-m4cil-integration/1"
M4CIL_PROFILE = "flrh-m4cil-single-effect-incremental-reference/1"


def fresh(value: Any) -> Any:
    return copy.deepcopy(value)


def load_chain_inputs() -> Dict[str, Any]:
    """Return a fresh, fully explicit input envelope for the bounded chain."""

    snapshot, accepted_event = load_m1_input()
    expected_transition = load_m1_expected_transition()
    rule_bundle, deltas, _proposal, _requirements, _frontiers = build_l_inputs(
        expected_transition
    )
    return {
        "snapshot": snapshot,
        "accepted_event": accepted_event,
        "expected_f_transition": expected_transition,
        "rule_bundle": rule_bundle,
        "bootstrap_input_deltas": deltas,
    }


def build_incremental_input_root_digest(
    accepted_event: Dict[str, Any],
    bootstrap_step: Dict[str, Any],
    reuse_step: Dict[str, Any],
) -> str:
    return canonical_digest({
        "kind": "M4CILInputRootPreimage",
        "contract_version": M4CIL_CONTRACT,
        "accepted_event": fresh(accepted_event),
        "bootstrap_step_digest": bootstrap_step["step_digest"],
        "bootstrap_checkpoint_digest": bootstrap_step["next_checkpoint"][
            "checkpoint_digest"
        ],
        "reuse_step_digest": reuse_step["step_digest"],
        "reuse_checkpoint_digest": reuse_step["next_checkpoint"][
            "checkpoint_digest"
        ],
        "logic_fixpoint_digest": reuse_step["fixpoint_result"]["fixpoint_digest"],
    })


def build_receipt_binding(
    accepted_event: Dict[str, Any],
    h_command: Dict[str, Any],
    bootstrap_step: Dict[str, Any],
    reuse_step: Dict[str, Any],
) -> Dict[str, str]:
    return {
        "command_digest": h_command["command_digest"],
        "input_root_digest": build_incremental_input_root_digest(
            accepted_event, bootstrap_step, reuse_step
        ),
        "platform_digest": canonical_digest({
            "kind": "M4CILPlatformPreimage",
            "contract_version": M4CIL_CONTRACT,
            "adapter_profile": "FakeAdapter",
            "durable_profile": "sqlite-wal-full/1",
            "logic_profile": "flrh-l-persistent-incremental/1",
            "canonicalization_version": "flrh-cjson/1",
        }),
    }


def build_receipt_evidence(h_projection: Dict[str, Any]):
    output_digest = canonical_digest({
        "kind": "M4CILAdapterOutputPreimage",
        "contract_version": M4CIL_CONTRACT,
        "projection_digest": h_projection["projection_digest"],
    })

    def receipt_evidence(_intent: Dict[str, Any], _attempt_id: str, outcome: str):
        return {
            "output_digests": [output_digest],
            "trace_ref": "trace:m4cil:single-effect",
            "outcome": outcome,
        }

    return receipt_evidence


def build_durable_checkpoint(
    h_projection: Dict[str, Any],
    bootstrap_step: Dict[str, Any],
    reuse_step: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "kind": "M4CILCheckpoint",
        "stage": "authority_projected",
        "projection_digest": h_projection["projection_digest"],
        "bootstrap_step_digest": bootstrap_step["step_digest"],
        "bootstrap_checkpoint_digest": bootstrap_step["next_checkpoint"][
            "checkpoint_digest"
        ],
        "reuse_step_digest": reuse_step["step_digest"],
        "logic_fixpoint_digest": reuse_step["fixpoint_result"]["fixpoint_digest"],
        "logic_checkpoint": fresh(reuse_step["next_checkpoint"]),
    }


__all__ = [
    "M4CIL_CONTRACT",
    "M4CIL_PROFILE",
    "build_durable_checkpoint",
    "build_incremental_input_root_digest",
    "build_l_inputs",
    "build_low_risk_h_command",
    "build_lr_inputs",
    "build_receipt_binding",
    "build_receipt_evidence",
    "fresh",
    "load_chain_inputs",
]
