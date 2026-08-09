#!/usr/bin/env python3
"""Independent source-reexecution verifier for bounded M4C-IL evidence."""

from __future__ import annotations

import copy
from typing import Any, Dict, Iterable, Optional, Tuple

from flrh_kernel.canonical import CanonicalizationError, canonical_digest
from m4cil_fixtures import M4CIL_CONTRACT
from run_m4cil_replay import run_incremental_reference_chain


def _child(path: str, token: Any) -> str:
    escaped = str(token).replace("~", "~0").replace("/", "~1")
    return (path or "") + "/" + escaped


def _first_difference(
    expected: Any, actual: Any, path: str = ""
) -> Optional[Tuple[str, Any, Any]]:
    if type(expected) is not type(actual):
        return path or "/", expected, actual
    if isinstance(expected, dict):
        expected_keys = set(expected)
        actual_keys = set(actual)
        missing = sorted(expected_keys - actual_keys)
        if missing:
            key = missing[0]
            return _child(path, key), expected[key], None
        extra = sorted(actual_keys - expected_keys)
        if extra:
            key = extra[0]
            return _child(path, key), None, actual[key]
        for key in sorted(expected):
            mismatch = _first_difference(expected[key], actual[key], _child(path, key))
            if mismatch is not None:
                return mismatch
        return None
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return path or "/", expected, actual
        for index, (left, right) in enumerate(zip(expected, actual)):
            mismatch = _first_difference(left, right, _child(path, index))
            if mismatch is not None:
                return mismatch
        return None
    if expected != actual:
        return path or "/", expected, actual
    return None


def _failure(path: str, expected: Any = None, actual: Any = None) -> Dict[str, Any]:
    value = {
        "kind": "M4CILVerificationFailure",
        "schema_version": "flrh-m4cil-verification/1",
        "contract_version": M4CIL_CONTRACT,
        "code": "EVIDENCE_MISMATCH",
        "path": path,
        "expected": copy.deepcopy(expected),
        "actual": copy.deepcopy(actual),
        "context": {},
    }
    value["failure_digest"] = canonical_digest({
        "kind": "M4CILVerificationFailurePreimage",
        "contract_version": M4CIL_CONTRACT,
        **copy.deepcopy(value),
    })
    return value


def _verify(evidence: Any) -> Dict[str, Any]:
    if not isinstance(evidence, dict):
        return _failure("/", "object", evidence)
    mode = evidence.get("replay_mode")
    if mode not in ("happy", "crash_after_external_success"):
        return _failure("/replay_mode", "happy|crash_after_external_success", mode)

    if "evidence_digest" not in evidence:
        return _failure("/evidence_digest")
    body = copy.deepcopy(evidence)
    supplied_digest = body.pop("evidence_digest")
    expected_digest = canonical_digest({
        "kind": "M4CILEvidencePreimage",
        "contract_version": M4CIL_CONTRACT,
        **body,
    })
    if supplied_digest != expected_digest:
        return _failure("/evidence_digest", expected_digest, supplied_digest)

    expected = run_incremental_reference_chain(
        mode == "crash_after_external_success"
    )
    if expected.get("kind") != "M4CILReplayEvidence":
        return _failure("/", "fresh source-bound replay evidence", expected)
    # The supplied outer digest was already recomputed and checked above.  Keep
    # it out of the source-bound structural comparison so a coherently
    # re-digested inner forgery is diagnosed at the first forged field instead
    # of being masked by the (necessarily different) outer digest.
    expected_body = copy.deepcopy(expected)
    actual_body = copy.deepcopy(evidence)
    expected_body.pop("evidence_digest")
    actual_body.pop("evidence_digest")
    mismatch = _first_difference(expected_body, actual_body)
    if mismatch is not None:
        return _failure(*mismatch)

    bootstrap = expected["bootstrap_logic_step"]
    reuse = expected["reuse_logic_step"]
    receipt = expected["action_receipt"]
    result = {
        "kind": "M4CILVerificationReceipt",
        "schema_version": "flrh-m4cil-verification/1",
        "contract_version": M4CIL_CONTRACT,
        "status": "SLICE_CONFORMED",
        "outer_fsm_stop_state": "HONOR_PENDING_INTERRUPT",
        "stage_digests": {
            "f_transition": expected["f_transition"]["transition_digest"],
            "bootstrap_step": bootstrap["step_digest"],
            "bootstrap_checkpoint": bootstrap["next_checkpoint"]["checkpoint_digest"],
            "reuse_step": reuse["step_digest"],
            "reuse_checkpoint": reuse["next_checkpoint"]["checkpoint_digest"],
            "l_fixpoint": reuse["fixpoint_result"]["fixpoint_digest"],
            "lr_projection": expected["lr_projection"]["projection_digest"],
            "r_published_batch": expected["r_published_batch"]["published_batch_digest"],
            "h_projection": expected["h_projection"]["projection_digest"],
            "action_receipt": canonical_digest(receipt),
            "replay_evidence": expected["evidence_digest"],
        },
        "checks": [
            "public_f_reexecution",
            "public_incremental_l_bootstrap_reexecution",
            "public_incremental_l_checkpoint_reuse_reexecution",
            "incremental_checkpoint_lineage",
            "exact_m2_compatible_fixpoint_to_lr_binding",
            "public_lr_r_h_reexecution",
            "durable_checkpoint_incremental_lineage",
            "exact_action_receipt_binding",
            "source_derived_fsm_evidence_projection",
            "real_subprocess_crash_recovery_when_selected",
        ],
    }
    result["verification_digest"] = canonical_digest({
        "kind": "M4CILVerificationPreimage",
        "contract_version": M4CIL_CONTRACT,
        "receipt": copy.deepcopy(result),
    })
    return result


def verify_m4cil_evidence(evidence: Any) -> Dict[str, Any]:
    try:
        return _verify(evidence)
    except CanonicalizationError:
        return _failure("/")
    except (KeyError, IndexError, TypeError, ValueError, RuntimeError):
        return _failure("/")


__all__ = ["verify_m4cil_evidence"]
