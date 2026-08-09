#!/usr/bin/env python3
"""Clean-process ambient-authority admission check for the M3 R kernel.

This checker is deliberately nonnormative.  It precompiles the trusted source,
locks named CPython authority surfaces, imports the package through an in-memory
loader with real metadata, and then exercises non-empty reactive paths with
recursively write-detecting inputs.  The result is bounded evidence for those
surfaces, not a universal sandbox or purity proof.
"""

from __future__ import annotations

# Load legitimate interpreter dependencies before authority is locked.  The
# implementation source is read and compiled, but no module body is executed,
# by _precompile_implementation below.
import builtins
import copy
import dataclasses
import hashlib
import importlib.abc
import importlib.util
import io
import json
import os
import pathlib
import random
import re
import socket
import subprocess
import sys
import time
import types
import typing
import unicodedata
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from m3_guard import (  # noqa: E402
    AttemptedMutation,
    AuthorityGuard,
    GuardViolation,
    call_step_r,
    write_tracking_copy,
)


IMPLEMENTATION_MODULES = (
    ("flrh_reactive.canonical", ROOT / "src/flrh_reactive/canonical.py", False),
    ("flrh_reactive.reactive", ROOT / "src/flrh_reactive/reactive.py", False),
    ("flrh_reactive", ROOT / "src/flrh_reactive/__init__.py", True),
)

AMBIENT_CATEGORIES = [
    "clock",
    "randomness",
    "uuid",
    "environment",
    "filesystem",
    "network",
    "subprocess",
    "model_or_tool",
]

CONTRACT_VERSION = "flrh-r-kernel/1"
PROFILE_ID = "flrh-r-scalar-frontier/1"
PROFILE_SCHEMA_VERSION = "flrh-r-profile/1"
COMMAND_SCHEMA_VERSION = "flrh-r-command/1"
VALUE_DELTA_SCHEMA_VERSION = "flrh-r-value-delta/1"
CANONICALIZATION_VERSION = "flrh-cjson/1"
DATAFLOW_VERSION = "dataflow/m3-guard/1"
RULE_SET_VERSION = "rules/m3-guard/1"
PROPOSAL_SOURCE = "source:m3:proposal"
VERDICT_SOURCE = "source:m3:verdict"


def canonical_bytes(value: Any) -> bytes:
    """Encode the checker report and its ASCII-only fixture preimages."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def _normalized_protocol_value(value: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize the two inherited protocol set fields without kernel imports."""

    normalized = copy.deepcopy(dict(value))
    set_fields = {
        "EffectProposal": ("preconditions",),
        "EligibilityVerdict": ("support_derivation_ids",),
    }.get(normalized.get("kind"), ())
    for field in set_fields:
        normalized[field] = sorted(normalized[field], key=canonical_bytes)
    return normalized


def _precompile_implementation() -> dict[str, tuple[types.CodeType, str, bool]]:
    """Read and compile all M3 sources before installing the guard."""

    compiled: dict[str, tuple[types.CodeType, str, bool]] = {}
    for fullname, path, is_package in IMPLEMENTATION_MODULES:
        source = path.read_text(encoding="utf-8")
        compiled[fullname] = (compile(source, str(path), "exec"), str(path), is_package)
    return compiled


class _MemoryCodeLoader(importlib.abc.Loader):
    """Execute precompiled code while retaining ordinary import metadata."""

    def __init__(self, code: types.CodeType, origin: str, is_package: bool) -> None:
        self.code = code
        self.origin = origin
        self.is_package = is_package

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> None:
        return None

    def exec_module(self, module: types.ModuleType) -> None:
        module.__file__ = self.origin
        module.__cached__ = None
        if self.is_package:
            module.__path__ = [str(Path(self.origin).parent)]
        exec(self.code, module.__dict__)


class _MemoryCodeFinder(importlib.abc.MetaPathFinder):
    def __init__(self, modules: Mapping[str, tuple[types.CodeType, str, bool]]) -> None:
        self.modules = dict(modules)

    def find_spec(
        self,
        fullname: str,
        path: object = None,
        target: object = None,
    ) -> importlib.machinery.ModuleSpec | None:
        entry = self.modules.get(fullname)
        if entry is None:
            return None
        code, origin, is_package = entry
        loader = _MemoryCodeLoader(code, origin, is_package)
        spec = importlib.util.spec_from_loader(
            fullname,
            loader,
            origin=origin,
            is_package=is_package,
        )
        if spec is None:
            raise RuntimeError(f"could not build in-memory spec for {fullname}")
        if is_package:
            spec.submodule_search_locations = [str(Path(origin).parent)]
        return spec


def _import_guarded_implementation(
    compiled: Mapping[str, tuple[types.CodeType, str, bool]],
) -> tuple[types.ModuleType, types.ModuleType, int]:
    for fullname, _path, _is_package in reversed(IMPLEMENTATION_MODULES):
        sys.modules.pop(fullname, None)
    finder = _MemoryCodeFinder(compiled)
    sys.meta_path.insert(0, finder)
    try:
        package = __import__("flrh_reactive", fromlist=["step_r"])
        canonical = __import__("flrh_reactive.canonical", fromlist=["canonical_bytes"])
    finally:
        sys.meta_path.remove(finder)

    checks = 0
    for fullname, expected_path, is_package in IMPLEMENTATION_MODULES:
        module = sys.modules.get(fullname)
        if module is None:
            raise AssertionError(f"guarded import omitted {fullname}")
        spec = module.__spec__
        if spec is None or not isinstance(spec.loader, _MemoryCodeLoader):
            raise AssertionError(f"guarded import metadata missing loader for {fullname}")
        checks += 1
        if spec.name != fullname:
            raise AssertionError(f"guarded import metadata name mismatch for {fullname}")
        checks += 1
        if spec.origin != str(expected_path) or module.__file__ != str(expected_path):
            raise AssertionError(f"guarded import metadata origin mismatch for {fullname}")
        checks += 1
        if is_package:
            locations = list(spec.submodule_search_locations or ())
            if locations != [str(expected_path.parent)]:
                raise AssertionError("guarded package search locations mismatch")
            checks += 1
    return package, canonical, checks


def _expect_guard(expected_category: str, action: Callable[[], object]) -> None:
    try:
        action()
    except GuardViolation as error:
        if error.category != expected_category:
            raise AssertionError(
                f"ambient guard category mismatch: {expected_category} != {error.category}"
            ) from error
        return
    raise AssertionError(f"ambient authority was not blocked: {expected_category}")


def _run_explicit_guard_self_tests(guard: AuthorityGuard) -> int:
    probes: tuple[tuple[str, Callable[[], object]], ...] = (
        ("clock", time.time),
        ("randomness", lambda: random.SystemRandom().random()),
        ("uuid", uuid.uuid4),
        ("environment", lambda: os.environ.get("M3_AMBIENT_CANARY")),
        ("filesystem", lambda: builtins.open(__file__, "rb")),
        ("network", lambda: socket.socket()),
        ("subprocess", lambda: subprocess.run([sys.executable, "-V"], check=False)),
        ("model_or_tool", lambda: __import__("openai")),
    )
    before = len(guard.attempts)
    for label, action in probes:
        _expect_guard(label, action)
    if len(guard.attempts) - before != len(probes):
        raise AssertionError("explicit guard self-test counter mismatch")
    return len(probes)


def _run_audit_guard_self_tests(
    guard: AuthorityGuard,
    raw_os_open: Callable[..., int],
    raw_socket: Callable[..., socket.socket],
    raw_popen: Callable[..., subprocess.Popen[bytes]],
) -> int:
    probes: tuple[tuple[str, Callable[[], object]], ...] = (
        ("filesystem", lambda: raw_os_open(__file__, os.O_RDONLY)),
        ("network", lambda: raw_socket(socket.AF_INET, socket.SOCK_STREAM)),
        ("subprocess", lambda: raw_popen([sys.executable, "-V"])),
    )
    before = len(guard.attempts)
    for label, action in probes:
        _expect_guard(label, action)
    if len(guard.attempts) - before != len(probes):
        raise AssertionError("audit-hook self-test counter mismatch")
    return len(probes)


def _digest_literal(character: str) -> str:
    return "sha256:" + character * 64


def _versions() -> dict[str, str]:
    return {
        "canonicalization": CANONICALIZATION_VERSION,
        "composition_profile": "composition/m3-guard/1",
        "dataflow": DATAFLOW_VERSION,
        "event_schema": "event/m3-guard/1",
        "gate": "gate/m3-guard/1",
        "graph_schema": "graph/m3-guard/1",
        "model": "none/0",
        "oracle": "oracle/m3-guard/1",
        "resolver": "resolver/m3-guard/1",
        "rule_set": RULE_SET_VERSION,
        "state_schema": "state/m3-guard/1",
        "tool": "tool/m3-guard/1",
        "workflow": "workflow/m3-guard/1",
    }


def _proposal(suffix: str) -> dict[str, Any]:
    return {
        "kind": "EffectProposal",
        "proposal_id": f"proposal:m3:{suffix}",
        "effect_type": "artifact.publish",
        "action_digest": _digest_literal("1" if suffix == "primary" else "2"),
        "cause_id": f"cause:m3:{suffix}",
        "correlation_id": "run:m3:guard",
        "proposal_dedup_key": f"proposal-dedup:m3:{suffix}",
        "destination_digest": _digest_literal("3" if suffix == "primary" else "4"),
        "goal_id": "goal:m3:guard",
        "obligation_id": f"obligation:m3:{suffix}",
        "declared_risk_hint": "read_only",
        "preconditions": ["precondition:m3:a", "precondition:m3:z"],
        "versions": _versions(),
    }


def _verdict(proposal: Mapping[str, Any], suffix: str) -> dict[str, Any]:
    return {
        "kind": "EligibilityVerdict",
        "verdict_id": f"verdict:m3:{suffix}",
        "proposal_id": proposal["proposal_id"],
        "status": "eligible",
        "support_derivation_ids": [
            f"derivation:m3:{suffix}:a",
            f"derivation:m3:{suffix}:z",
        ],
        "cause_id": proposal["cause_id"],
        "rule_set_version": RULE_SET_VERSION,
    }


def _profile(max_active_values: int) -> dict[str, Any]:
    limits = {
        "max_deltas_per_command": 8,
        "max_active_values": max_active_values,
        "max_open_epochs": 4,
        "max_ready_batches": 4,
        "max_demand_per_command": 4,
        "max_outstanding_demand": 4,
    }
    sources = sorted([PROPOSAL_SOURCE, VERDICT_SOURCE])
    preimage = {
        "kind": "M3ProfilePreimage",
        "contract_version": CONTRACT_VERSION,
        "profile_id": PROFILE_ID,
        "dataflow_version": DATAFLOW_VERSION,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "ordered_source_ids": sources,
        "late_event_policy": "reject",
        "overflow_policy": "reject_new",
        "limits": limits,
    }
    return {
        "kind": "RDataflowProfile",
        "schema_version": PROFILE_SCHEMA_VERSION,
        "contract_version": CONTRACT_VERSION,
        "profile_id": PROFILE_ID,
        "dataflow_version": DATAFLOW_VERSION,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "source_ids": sources,
        "late_event_policy": "reject",
        "overflow_policy": "reject_new",
        "limits": limits,
        "profile_digest": canonical_digest(preimage),
    }


def _delta(
    profile: Mapping[str, Any],
    *,
    source_id: str,
    logical_time: int,
    value_kind: str,
    value: Mapping[str, Any],
    diff: int = 1,
) -> dict[str, Any]:
    value_preimage = {
        "kind": "M3ValuePreimage",
        "contract_version": CONTRACT_VERSION,
        "value_kind": value_kind,
        "value": _normalized_protocol_value(value),
    }
    value_digest = canonical_digest(value_preimage)
    delivery_preimage = {
        "kind": "M3DeliveryPreimage",
        "contract_version": CONTRACT_VERSION,
        "source_id": source_id,
        "logical_time": logical_time,
        "dataflow_version": profile["dataflow_version"],
        "value_kind": value_kind,
        "value_digest": value_digest,
    }
    delivery_hex = canonical_digest(delivery_preimage).removeprefix("sha256:")
    return {
        "kind": "RValueDelta",
        "schema_version": VALUE_DELTA_SCHEMA_VERSION,
        "delivery_id": "delivery:" + delivery_hex,
        "source_id": source_id,
        "logical_time": logical_time,
        "diff": diff,
        "dataflow_version": profile["dataflow_version"],
        "value_kind": value_kind,
        "value_digest": value_digest,
        "value": copy.deepcopy(value),
    }


def _command_base(profile: Mapping[str, Any], kind: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "schema_version": COMMAND_SCHEMA_VERSION,
        "profile_digest": profile["profile_digest"],
        "dataflow_version": profile["dataflow_version"],
    }


def _apply(profile: Mapping[str, Any], deltas: list[dict[str, Any]]) -> dict[str, Any]:
    command = _command_base(profile, "RApplyDeltaBatch")
    command["deltas"] = copy.deepcopy(deltas)
    return command


def _advance(
    profile: Mapping[str, Any], source_id: str, low_watermark: int
) -> dict[str, Any]:
    command = _command_base(profile, "RAdvanceFrontier")
    command.update({"source_id": source_id, "low_watermark": low_watermark})
    return command


def _demand(profile: Mapping[str, Any], batches: int) -> dict[str, Any]:
    command = _command_base(profile, "RGrantDemand")
    command["batches"] = batches
    return command


def _kernel_path_inputs() -> dict[str, Any]:
    """Build two complete profiles without importing the implementation."""

    standard = _profile(max_active_values=8)
    capacity = _profile(max_active_values=2)
    proposal = _proposal("primary")
    verdict = _verdict(proposal, "primary")
    proposal_delta = _delta(
        standard,
        source_id=PROPOSAL_SOURCE,
        logical_time=1,
        value_kind="effect_proposal",
        value=proposal,
    )
    verdict_delta = _delta(
        standard,
        source_id=VERDICT_SOURCE,
        logical_time=1,
        value_kind="eligibility_verdict",
        value=verdict,
    )
    permuted_proposal = copy.deepcopy(proposal)
    permuted_proposal["preconditions"].reverse()
    permuted_verdict = copy.deepcopy(verdict)
    permuted_verdict["support_derivation_ids"].reverse()
    permuted_proposal_delta = _delta(
        standard,
        source_id=PROPOSAL_SOURCE,
        logical_time=1,
        value_kind="effect_proposal",
        value=permuted_proposal,
    )
    permuted_verdict_delta = _delta(
        standard,
        source_id=VERDICT_SOURCE,
        logical_time=1,
        value_kind="eligibility_verdict",
        value=permuted_verdict,
    )
    late_proposal = _proposal("late")
    late_delta = _delta(
        standard,
        source_id=PROPOSAL_SOURCE,
        logical_time=1,
        value_kind="effect_proposal",
        value=late_proposal,
    )
    capacity_proposal_delta = _delta(
        capacity,
        source_id=PROPOSAL_SOURCE,
        logical_time=1,
        value_kind="effect_proposal",
        value=proposal,
    )
    capacity_verdict_delta = _delta(
        capacity,
        source_id=VERDICT_SOURCE,
        logical_time=1,
        value_kind="eligibility_verdict",
        value=verdict,
    )
    capacity_extra = _proposal("capacity-extra")
    capacity_extra_delta = _delta(
        capacity,
        source_id=PROPOSAL_SOURCE,
        logical_time=2,
        value_kind="effect_proposal",
        value=capacity_extra,
    )
    return {
        "standard_profile": standard,
        "capacity_profile": capacity,
        "apply": _apply(standard, [proposal_delta, verdict_delta]),
        "apply_nested_permuted": _apply(
            standard, [permuted_verdict_delta, permuted_proposal_delta]
        ),
        "frontier_proposal_equal": _advance(standard, PROPOSAL_SOURCE, 1),
        "frontier_verdict_equal": _advance(standard, VERDICT_SOURCE, 1),
        "frontier_proposal_pass": _advance(standard, PROPOSAL_SOURCE, 2),
        "frontier_proposal_regression": _advance(standard, PROPOSAL_SOURCE, 1),
        "frontier_verdict_pass": _advance(standard, VERDICT_SOURCE, 2),
        "demand": _demand(standard, 1),
        "late": _apply(standard, [late_delta]),
        "capacity_apply": _apply(
            capacity, [capacity_proposal_delta, capacity_verdict_delta]
        ),
        "capacity_frontier_proposal": _advance(capacity, PROPOSAL_SOURCE, 2),
        "capacity_frontier_verdict": _advance(capacity, VERDICT_SOURCE, 2),
        "capacity_overflow": _apply(capacity, [capacity_extra_delta]),
    }


def _run_guarded_kernel_paths(
    step_r: Callable[..., dict[str, Any]],
    guard: AuthorityGuard,
    inputs: Mapping[str, Any],
) -> dict[str, int]:
    """Exercise actual apply/frontier/demand/rejection branches under lock."""

    ambient_attempts = 0
    mutation_attempts = 0

    def invoke(
        label: str,
        prior_state: Any,
        profile: Mapping[str, Any],
        command: Mapping[str, Any],
        expected_kind: str,
    ) -> dict[str, Any]:
        nonlocal ambient_attempts, mutation_attempts
        document = {
            "prior_state": prior_state,
            "profile": profile,
            "command": command,
        }
        before = canonical_bytes(document)
        writes: list[object] = []
        guarded = write_tracking_copy(copy.deepcopy(document), writes)
        before_attempts = len(guard.attempts)
        result = call_step_r(
            step_r,
            guarded["prior_state"],
            guarded["profile"],
            guarded["command"],
        )
        attempted = len(guard.attempts) - before_attempts
        ambient_attempts += attempted
        mutation_attempts += len(writes)
        if attempted:
            raise AssertionError(f"guarded kernel path used ambient authority: {label}")
        if writes:
            raise AssertionError(f"guarded kernel path mutated input: {label}: {writes!r}")
        if canonical_bytes(document) != before:
            raise AssertionError(f"guarded kernel path changed input ownership: {label}")
        if result.get("kind") != expected_kind:
            raise AssertionError(
                f"guarded kernel path result mismatch: {label}: {result!r}"
            )
        if expected_kind == "RTransition":
            frontiers = result.get("next_state", {}).get("source_frontiers")
            if not isinstance(frontiers, list) or frontiers != sorted(
                frontiers, key=canonical_bytes
            ):
                raise AssertionError(
                    f"source frontier records are not canonically ordered: {label}"
                )
        return result

    profile = inputs["standard_profile"]
    applied = invoke("apply_values", None, profile, inputs["apply"], "RTransition")
    permuted = invoke(
        "apply_nested_protocol_permutation",
        None,
        profile,
        inputs["apply_nested_permuted"],
        "RTransition",
    )
    if canonical_bytes(inputs["apply"]) == canonical_bytes(
        inputs["apply_nested_permuted"]
    ):
        raise AssertionError("nested permutation probe did not change raw input bytes")
    if canonical_bytes(applied) != canonical_bytes(permuted):
        raise AssertionError("nested protocol permutation changed transition bytes")
    state = applied["next_state"]
    if len(state["open_epochs"]) != 1 or applied["published_batches"]:
        raise AssertionError("non-empty apply did not retain exactly one open epoch")

    proposal_equal = invoke(
        "frontier_proposal_equal",
        state,
        profile,
        inputs["frontier_proposal_equal"],
        "RTransition",
    )
    state = proposal_equal["next_state"]
    if state["global_low_watermark"] is not None:
        raise AssertionError("partial source frontier produced a global watermark")

    verdict_equal = invoke(
        "frontier_verdict_equal",
        state,
        profile,
        inputs["frontier_verdict_equal"],
        "RTransition",
    )
    state = verdict_equal["next_state"]
    if state["global_low_watermark"] != 1:
        raise AssertionError("global frontier is not the declared-source minimum")
    if len(state["open_epochs"]) != 1 or state["ready_batches"]:
        raise AssertionError("frontier equality stabilized an epoch")

    proposal_pass = invoke(
        "frontier_proposal_pass",
        state,
        profile,
        inputs["frontier_proposal_pass"],
        "RTransition",
    )
    state = proposal_pass["next_state"]
    if state["global_low_watermark"] != 1 or not state["open_epochs"]:
        raise AssertionError("source maximum was used instead of global minimum")

    regression = invoke(
        "frontier_regression_rejection",
        state,
        profile,
        inputs["frontier_proposal_regression"],
        "RRejection",
    )
    if (
        regression.get("code") != "FRONTIER_REGRESSION"
        or regression.get("path") != "/command/low_watermark"
    ):
        raise AssertionError("frontier regression did not take the closed rejection path")

    verdict_pass = invoke(
        "frontier_verdict_pass",
        state,
        profile,
        inputs["frontier_verdict_pass"],
        "RTransition",
    )
    state = verdict_pass["next_state"]
    if state["global_low_watermark"] != 2:
        raise AssertionError("strict frontier passage did not advance globally")
    if state["open_epochs"] or len(state["ready_batches"]) != 1:
        raise AssertionError("strict frontier passage did not close one whole epoch")
    if verdict_pass["published_batches"]:
        raise AssertionError("frontier closure published without demand")

    demanded = invoke("grant_demand", state, profile, inputs["demand"], "RTransition")
    state = demanded["next_state"]
    if len(demanded["published_batches"]) != 1 or state["ready_batches"]:
        raise AssertionError("whole-batch demand did not publish exactly one batch")
    published = demanded["published_batches"][0]
    if (
        len(published["effect_proposals"]) != 1
        or len(published["eligibility_verdicts"]) != 1
    ):
        raise AssertionError("published epoch was partially exposed")

    late = invoke("late_rejection", state, profile, inputs["late"], "RRejection")
    if (
        late.get("code") != "LATE_DELTA"
        or late.get("path") != "/command/deltas/0/logical_time"
        or late.get("context") != {"source_id": PROPOSAL_SOURCE}
    ):
        raise AssertionError("late delta did not take the closed rejection path")

    capacity_profile = inputs["capacity_profile"]
    capacity_applied = invoke(
        "capacity_apply",
        None,
        capacity_profile,
        inputs["capacity_apply"],
        "RTransition",
    )
    capacity_state = capacity_applied["next_state"]
    capacity_proposal = invoke(
        "capacity_frontier_proposal",
        capacity_state,
        capacity_profile,
        inputs["capacity_frontier_proposal"],
        "RTransition",
    )
    capacity_state = capacity_proposal["next_state"]
    capacity_verdict = invoke(
        "capacity_frontier_verdict",
        capacity_state,
        capacity_profile,
        inputs["capacity_frontier_verdict"],
        "RTransition",
    )
    capacity_state = capacity_verdict["next_state"]
    if capacity_state["open_epochs"] or len(capacity_state["ready_batches"]) != 1:
        raise AssertionError("capacity profile did not retain one ready batch")
    capacity = invoke(
        "ready_inclusive_capacity_rejection",
        capacity_state,
        capacity_profile,
        inputs["capacity_overflow"],
        "RRejection",
    )
    if (
        capacity.get("code") != "QUEUE_CAPACITY_EXCEEDED"
        or capacity.get("context") != {"limit": 2, "observed": 3}
    ):
        raise AssertionError("ready-inclusive reject-new capacity path was not atomic")

    return {
        "kernel_path_ambient_attempts": ambient_attempts,
        "kernel_path_executions": 13,
        "kernel_path_input_mutation_attempts": mutation_attempts,
        "kernel_path_profiles": 2,
        "kernel_path_rejections": 3,
        "kernel_path_successes": 10,
    }


def _mutants() -> tuple[tuple[str, str, Callable[..., object]], ...]:
    def through(action: Callable[[], object]) -> Callable[..., object]:
        def mutant(prior: Any, profile: Any, command: Any) -> object:
            action()
            return {"prior": prior, "profile": profile, "command": command}

        return mutant

    def mutate_input(prior: Any, profile: Any, command: Any) -> object:
        command["deltas"][0]["value"]["preconditions"].append("mutant")
        return {"prior": prior, "profile": profile, "command": command}

    def read_import_metadata(prior: Any, profile: Any, command: Any) -> object:
        import flrh_reactive.reactive as implementation

        with builtins.open(implementation.__file__, "rb") as stream:
            stream.read(1)
        return {"prior": prior, "profile": profile, "command": command}

    def conditional_import_metadata_filesystem(
        prior: Any, profile: Any, command: Any
    ) -> object:
        if command.get("deltas"):
            import flrh_reactive.reactive as implementation

            json.__loader__.get_data(implementation.__file__)
        return {"prior": prior, "profile": profile, "command": command}

    return (
        ("clock", "clock", through(time.time)),
        ("randomness", "randomness", through(lambda: random.SystemRandom().random())),
        ("uuid", "uuid", through(uuid.uuid4)),
        ("environment", "environment", through(lambda: os.environ.get("M3_MUTANT"))),
        ("filesystem", "filesystem", through(lambda: pathlib.Path(__file__).read_bytes())),
        ("network", "network", through(socket.socket)),
        ("subprocess", "subprocess", through(lambda: subprocess.run([sys.executable, "-V"]))),
        ("model_or_tool", "model_or_tool", through(lambda: __import__("openai"))),
        ("tool_adapter", "model_or_tool", through(lambda: __import__("tool_adapter"))),
        ("input_mutation", "input_mutation", mutate_input),
        ("os_backend_read", "filesystem", through(lambda: sys.modules[os.name].read(0, 0))),
        ("os_backend_stat", "filesystem", through(lambda: os.stat(__file__))),
        ("import_metadata_filesystem", "filesystem", read_import_metadata),
        (
            "conditional_import_metadata_filesystem",
            "filesystem",
            conditional_import_metadata_filesystem,
        ),
    )


def _run_mutants(
    guard: AuthorityGuard,
    profile: dict[str, Any],
    command: dict[str, Any],
) -> int:
    detected = 0
    for label, expected_category, mutant in _mutants():
        mutation_attempts: list[object] = []
        guarded_profile = write_tracking_copy(copy.deepcopy(profile), mutation_attempts)
        guarded_command = write_tracking_copy(copy.deepcopy(command), mutation_attempts)
        try:
            call_step_r(mutant, None, guarded_profile, guarded_command)
        except GuardViolation as error:
            if label == "input_mutation":
                raise AssertionError("input mutation mutant raised ambient violation")
            if error.category != expected_category:
                raise AssertionError(
                    f"mutant category mismatch for {label}: "
                    f"{expected_category} != {error.category}"
                ) from error
            detected += 1
            continue
        except AttemptedMutation:
            if label != "input_mutation":
                raise
            detected += 1
            continue
        if label == "input_mutation" and mutation_attempts:
            detected += 1
            continue
        raise AssertionError(f"real mutant escaped admission guard: {label}")
    return detected


def main() -> int:
    compiled = _precompile_implementation()
    kernel_inputs = _kernel_path_inputs()

    # Preserve raw C-backed paths so audit-hook tests are independent of the
    # explicit Python monkeypatches installed below.
    raw_os_open = os.open
    raw_socket = socket.socket
    raw_popen = subprocess.Popen

    guard = AuthorityGuard([ROOT / "src/flrh_reactive"])
    guard.install()
    try:
        guard.lock_import_reads()
        explicit_tests = _run_explicit_guard_self_tests(guard)
        audit_tests = _run_audit_guard_self_tests(guard, raw_os_open, raw_socket, raw_popen)

        before_import_attempts = len(guard.attempts)
        package, canonical_module, metadata_checks = _import_guarded_implementation(compiled)
        import_attempts = len(guard.attempts) - before_import_attempts
        if import_attempts:
            raise AssertionError("guarded implementation import attempted ambient authority")

        step_r = getattr(package, "step_r", None)
        if not callable(step_r):
            raise AssertionError("flrh_reactive.step_r is not callable")
        if not callable(getattr(canonical_module, "canonical_bytes", None)):
            raise AssertionError("flrh_reactive.canonical.canonical_bytes is not callable")

        kernel_paths = _run_guarded_kernel_paths(step_r, guard, kernel_inputs)
        canonical_module.canonical_bytes(kernel_paths)
        mutants_detected = _run_mutants(
            guard,
            kernel_inputs["standard_profile"],
            kernel_inputs["apply"],
        )
    finally:
        # The inherited process-local guard is intentionally irreversible.  The
        # checker exits immediately after its one report, so cleanup is neither
        # possible nor required.
        pass

    report = {
        "ambient_categories": AMBIENT_CATEGORIES,
        "audit_guard_self_tests": audit_tests,
        "explicit_guard_self_tests": explicit_tests,
        "guard_self_tests": explicit_tests + audit_tests,
        "import_attempts": import_attempts,
        "import_metadata_checks": metadata_checks,
        "kernel_ambient_attempts": kernel_paths["kernel_path_ambient_attempts"],
        "kernel_input_mutation_attempts": kernel_paths[
            "kernel_path_input_mutation_attempts"
        ],
        "mutants_detected": mutants_detected,
    }
    report.update(kernel_paths)
    sys.stdout.buffer.write(canonical_bytes(report) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
