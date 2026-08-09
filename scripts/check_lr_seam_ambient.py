#!/usr/bin/env python3
"""Clean-process ambient and public-waist admission for the proposed L/R seam.

This is bounded CPython evidence, not a universal purity proof.  Inputs are
materialized before authority is locked; the LR implementation is precompiled,
imported with ordinary metadata through a memory loader, then exercised through
the root ``flrh_lr_seam.project_lr`` export on non-empty truth-state, actual
M1->M2->LR, empty, rejection, and bound paths.
"""

from __future__ import annotations

import builtins
import copy
import hashlib
import importlib.abc
import importlib.util
import io
import json
import os
import pathlib
import random
import socket
import subprocess
import sys
import time
import types
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from flrh_logic import solve_l  # materialization occurs before the guard
from lr_seam_fixtures import (
    actual_chain_inputs,
    canonical_bytes,
    load_cases,
    materialize_binding_profile,
    materialize_proposal,
    materialize_query,
    materialize_query_batch,
    materialize_r_profile,
    materialize_requirement,
    truth_fixture_inputs,
)
from lr_seam_guard import (
    AttemptedMutation,
    AuthorityGuard,
    GuardViolation,
    call_project_lr,
    write_tracking_copy,
)


IMPLEMENTATION_MODULES = (
    ("flrh_lr_seam.canonical", ROOT / "src/flrh_lr_seam/canonical.py", False),
    ("flrh_lr_seam.seam", ROOT / "src/flrh_lr_seam/seam.py", False),
    ("flrh_lr_seam", ROOT / "src/flrh_lr_seam/__init__.py", True),
)
AMBIENT_CATEGORIES = [
    "clock", "randomness", "uuid", "environment", "filesystem", "network",
    "subprocess", "model_or_tool",
]
FORBIDDEN_OUTPUT_KEYS = frozenset(
    {
        "effect_intent", "effect_intents", "authority", "authority_digest",
        "approval", "approval_digest", "capability", "checkpoint", "receipt",
        "frontier", "frontiers", "demand", "backpressure",
    }
)


def _precompile() -> dict[str, tuple[types.CodeType, str, bool]]:
    return {
        fullname: (compile(path.read_text(encoding="utf-8"), str(path), "exec"), str(path), package)
        for fullname, path, package in IMPLEMENTATION_MODULES
    }


class _MemoryLoader(importlib.abc.Loader):
    def __init__(self, code: types.CodeType, origin: str, package: bool) -> None:
        self.code, self.origin, self.package = code, origin, package

    def create_module(self, spec: object) -> None:
        return None

    def exec_module(self, module: types.ModuleType) -> None:
        module.__file__ = self.origin
        module.__cached__ = None
        if self.package:
            module.__path__ = [str(Path(self.origin).parent)]
        exec(self.code, module.__dict__)


class _MemoryFinder(importlib.abc.MetaPathFinder):
    def __init__(self, compiled: Mapping[str, tuple[types.CodeType, str, bool]]) -> None:
        self.compiled = dict(compiled)

    def find_spec(self, fullname: str, path: object = None, target: object = None):
        entry = self.compiled.get(fullname)
        if entry is None:
            return None
        code, origin, package = entry
        loader = _MemoryLoader(code, origin, package)
        spec = importlib.util.spec_from_loader(fullname, loader, origin=origin, is_package=package)
        if spec is None:
            raise RuntimeError(f"cannot construct import spec for {fullname}")
        if package:
            spec.submodule_search_locations = [str(Path(origin).parent)]
        return spec


def _guarded_import(compiled: Mapping[str, tuple[types.CodeType, str, bool]]):
    for fullname, _path, _package in reversed(IMPLEMENTATION_MODULES):
        sys.modules.pop(fullname, None)
    finder = _MemoryFinder(compiled)
    sys.meta_path.insert(0, finder)
    try:
        package = __import__("flrh_lr_seam", fromlist=["project_lr"])
        seam = __import__("flrh_lr_seam.seam", fromlist=["project_lr"])
    finally:
        sys.meta_path.remove(finder)
    checks = 0
    for fullname, expected_path, is_package in IMPLEMENTATION_MODULES:
        module = sys.modules.get(fullname)
        if module is None or module.__spec__ is None:
            raise AssertionError(f"guarded import omitted metadata for {fullname}")
        spec = module.__spec__
        if not isinstance(spec.loader, _MemoryLoader):
            raise AssertionError(f"guarded import used wrong loader for {fullname}")
        checks += 1
        if spec.name != fullname:
            raise AssertionError(f"guarded import name mismatch for {fullname}")
        checks += 1
        if spec.origin != str(expected_path) or module.__file__ != str(expected_path):
            raise AssertionError(f"guarded import origin mismatch for {fullname}")
        checks += 1
        if is_package:
            if list(spec.submodule_search_locations or ()) != [str(expected_path.parent)]:
                raise AssertionError("guarded package search path mismatch")
            checks += 1
    if package.__all__ != ["project_lr"]:
        raise AssertionError("root package exposes more than project_lr")
    checks += 1
    if package.project_lr is not seam.project_lr:
        raise AssertionError("root project_lr bypasses the implementation publication path")
    checks += 1
    return package, checks


def _document(l_result, bundle, r_profile, binding, query_batch) -> dict[str, Any]:
    return {
        "l_result": l_result, "rule_bundle": bundle, "r_profile": r_profile,
        "binding_profile": binding, "query_batch": query_batch,
    }


def _truth_context():
    cases = load_cases()
    expected_root = {
        "schema_version", "binding_profile", "rule_bundle", "r_profile",
        "l_results", "query_batches", "success_cases", "rejection_cases",
        "equivalence_pairs", "goldens",
    }
    if set(cases) != expected_root:
        raise AssertionError("LR descriptor corpus root drift")
    logical_time = cases["l_results"]["truth-four"]["logical_time"]
    bundle, deltas, atoms = truth_fixture_inputs(logical_time)
    l_result = solve_l(None, bundle, deltas, logical_time)
    if l_result.get("kind") != "LFixpointResult":
        raise AssertionError("truth fixture failed to materialize through public solve_l")
    r_profile = materialize_r_profile(**cases["r_profile"]["kwargs"])
    binding = materialize_binding_profile(**cases["binding_profile"]["kwargs"])
    return cases, bundle, atoms, l_result, r_profile, binding


def _truth_query(suffix, atoms, atom_name, polarity="positive"):
    precondition = f"precondition:lr:{suffix}"
    return materialize_query(
        materialize_proposal(suffix, [precondition]),
        [materialize_requirement(precondition, atoms[atom_name], polarity)],
    )


def _build_success_documents() -> list[tuple[str, dict[str, Any], str]]:
    """Materialize every success descriptor in the frozen corpus."""
    cases, bundle, atoms, l_result, r_profile, binding = _truth_context()
    query_batches: dict[str, dict[str, Any]] = {}
    truth_queries = [
        _truth_query("positive-true", atoms, "true_only"),
        _truth_query("positive-false", atoms, "false_only"),
        _truth_query("positive-both", atoms, "both"),
        _truth_query("positive-neither", atoms, "neither"),
        _truth_query("negative-true", atoms, "true_only", "negative"),
        _truth_query("negative-false", atoms, "false_only", "negative"),
    ]
    query_batches["truth-matrix"] = materialize_query_batch(
        binding_profile=binding, l_result=l_result, rule_bundle=bundle,
        r_profile=r_profile, queries=truth_queries,
    )
    query_batches["eligible-golden"] = materialize_query_batch(
        binding_profile=binding, l_result=l_result, rule_bundle=bundle,
        r_profile=r_profile,
        queries=[_truth_query("eligible-golden", atoms, "true_only")],
    )
    multi_requirements = [
        materialize_requirement("precondition:multi:true", atoms["true_only"]),
        materialize_requirement(
            "precondition:multi:false-negative", atoms["false_only"], "negative"
        ),
    ]
    multi_queries = [
        materialize_query(
            materialize_proposal(
                "multi-eligible", [item["precondition_id"] for item in multi_requirements]
            ),
            multi_requirements,
        ),
        materialize_query(
            materialize_proposal(
                "multi-conflict", ["precondition:multi:true", "precondition:multi:both"]
            ),
            [multi_requirements[0], materialize_requirement(
                "precondition:multi:both", atoms["both"]
            )],
        ),
    ]
    query_batches["multi-aggregation"] = materialize_query_batch(
        binding_profile=binding, l_result=l_result, rule_bundle=bundle,
        r_profile=r_profile, queries=multi_queries,
    )
    query_batches["empty"] = materialize_query_batch(
        binding_profile=binding, l_result=l_result, rule_bundle=bundle,
        r_profile=r_profile, queries=[],
    )
    limit = binding["limits"]["max_queries"]
    limit_queries = [
        _truth_query(f"limit-{index}", atoms, "true_only") for index in range(limit)
    ]
    query_batches["limit-n"] = materialize_query_batch(
        binding_profile=binding, l_result=l_result, rule_bundle=bundle,
        r_profile=r_profile, queries=limit_queries,
    )
    left_queries = [
        materialize_query(
            materialize_proposal("permutation", ["precondition:perm:a", "precondition:perm:b"]),
            [materialize_requirement("precondition:perm:a", atoms["true_only"]),
             materialize_requirement("precondition:perm:b", atoms["false_only"], "negative")],
        ),
        _truth_query("permutation-two", atoms, "true_only"),
    ]
    left = materialize_query_batch(
        binding_profile=binding, l_result=l_result, rule_bundle=bundle,
        r_profile=r_profile, queries=left_queries,
    )
    right = copy.deepcopy(left)
    right["queries"].reverse()
    for query in right["queries"]:
        query["fact_requirements"].reverse()
        query["proposal"]["preconditions"].reverse()
    query_batches["permutation-left"] = left
    query_batches["permutation-right"] = right

    chain_bundle, chain_deltas, proposal, requirements, frontier_ids = actual_chain_inputs()
    chain_time = cases["l_results"]["actual-m1-chain"]["logical_time"]
    chain_result = solve_l(None, chain_bundle, chain_deltas, chain_time)
    if chain_result.get("kind") != "LFixpointResult":
        raise AssertionError("actual M1->M2 chain failed through public solve_l")
    chain_r = materialize_r_profile(**cases["r_profile"]["kwargs"])
    chain_binding = materialize_binding_profile(
        **{**cases["binding_profile"]["kwargs"], "rule_set_version": "rules/0"}
    )
    chain_query = materialize_query(
        proposal, requirements, frontier_precondition_ids=frontier_ids
    )
    query_batches["actual-chain"] = materialize_query_batch(
        binding_profile=chain_binding, l_result=chain_result,
        rule_bundle=chain_bundle, r_profile=chain_r, queries=[chain_query],
    )

    descriptors = []
    for descriptor in cases["success_cases"]:
        query_ref = descriptor["query_batch_ref"]
        if descriptor["l_result_ref"] == "actual-m1-chain":
            document = _document(
                chain_result, chain_bundle, chain_r, chain_binding, query_batches[query_ref]
            )
        elif descriptor["l_result_ref"] == "truth-four":
            document = _document(
                l_result, bundle, r_profile, binding, query_batches[query_ref]
            )
        else:
            raise AssertionError(f"unknown L result descriptor: {descriptor['l_result_ref']}")
        descriptors.append((descriptor["id"], document, "success"))
    return descriptors


def _build_documents() -> list[tuple[str, dict[str, Any], str]]:
    """Focused ambient/mutant probes derived from the final descriptor corpus."""
    cases, bundle, atoms, l_result, r_profile, binding = _truth_context()
    documents: list[tuple[str, dict[str, Any], str]] = []
    truth_probes = (
        ("true-positive", "true_only", "positive"),
        ("false-positive", "false_only", "positive"),
        ("both-positive", "both", "positive"),
        ("neither-positive", "neither", "positive"),
        ("true-negative", "true_only", "negative"),
        ("false-negative", "false_only", "negative"),
    )
    for label, atom_name, polarity in truth_probes:
        query = _truth_query(label, atoms, atom_name, polarity)
        batch = materialize_query_batch(
            binding_profile=binding, l_result=l_result, rule_bundle=bundle,
            r_profile=r_profile, queries=[query],
        )
        documents.append((label, _document(l_result, bundle, r_profile, binding, batch), "success"))

    (
        chain_bundle,
        chain_deltas,
        proposal,
        requirements,
        frontier_precondition_ids,
    ) = actual_chain_inputs()
    chain_time = cases["l_results"]["actual-m1-chain"]["logical_time"]
    chain_result = solve_l(None, chain_bundle, chain_deltas, chain_time)
    if chain_result.get("kind") != "LFixpointResult":
        raise AssertionError("actual M1->M2 chain failed through public solve_l")
    chain_r = materialize_r_profile()
    chain_binding = materialize_binding_profile(rule_set_version="rules/0")
    chain_query = materialize_query(
        proposal, requirements, frontier_precondition_ids=frontier_precondition_ids
    )
    chain_batch = materialize_query_batch(
        binding_profile=chain_binding, l_result=chain_result,
        rule_bundle=chain_bundle, r_profile=chain_r, queries=[chain_query],
    )
    documents.append(("actual-chain", _document(chain_result, chain_bundle, chain_r, chain_binding, chain_batch), "success"))

    empty_batch = materialize_query_batch(
        binding_profile=binding, l_result=l_result, rule_bundle=bundle,
        r_profile=r_profile, queries=[],
    )
    documents.append(("empty", _document(l_result, bundle, r_profile, binding, empty_batch), "success"))

    mismatch = copy.deepcopy(documents[0][1])
    mismatch["query_batch"]["l_fixpoint_digest"] = "sha256:" + "0" * 64
    documents.append(("binding-rejection", mismatch, "rejection"))

    bounded = materialize_binding_profile(max_queries=1)
    two_queries = []
    for index, atom_name in enumerate(("true_only", "false_only")):
        pid = f"precondition:lr:bound:{index}"
        two_queries.append(materialize_query(
            materialize_proposal(f"bound-{index}", [pid]),
            [materialize_requirement(pid, atoms[atom_name])],
        ))
    bound_batch = materialize_query_batch(
        binding_profile=bounded, l_result=l_result, rule_bundle=bundle,
        r_profile=r_profile, queries=two_queries,
    )
    documents.append(("query-bound", _document(l_result, bundle, r_profile, bounded, bound_batch), "rejection"))
    return documents


def _walk_forbidden(value: Any, path: str = "") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in FORBIDDEN_OUTPUT_KEYS:
                raise AssertionError(f"forbidden H/frontier/demand output at {path}/{key}")
            _walk_forbidden(item, f"{path}/{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_forbidden(item, f"{path}/{index}")


def _assert_result(result: Any, expected: str) -> None:
    if not isinstance(result, dict):
        raise AssertionError("project_lr result is not one object")
    kind = result.get("kind")
    wanted = "LRProjectionResult" if expected == "success" else "LRProjectionRejection"
    if kind != wanted:
        raise AssertionError(f"unexpected LR result kind: {kind!r}, wanted {wanted}")
    _walk_forbidden(result)


def _expect_guard(category: str, action: Callable[[], object]) -> None:
    try:
        action()
    except GuardViolation as error:
        if error.category != category:
            raise AssertionError(f"guard category mismatch: {category} != {error.category}") from error
        return
    raise AssertionError(f"ambient authority escaped: {category}")


def _explicit_self_tests(guard: AuthorityGuard) -> int:
    probes = (
        ("clock", time.time),
        ("randomness", lambda: random.SystemRandom().random()),
        ("uuid", uuid.uuid4),
        ("environment", lambda: os.environ.get("LR_SEAM_CANARY")),
        ("filesystem", lambda: builtins.open(__file__, "rb")),
        ("network", socket.socket),
        ("subprocess", lambda: subprocess.run([sys.executable, "-V"])),
        ("model_or_tool", lambda: __import__("openai")),
    )
    before = len(guard.attempts)
    for category, action in probes:
        _expect_guard(category, action)
    if len(guard.attempts) - before != len(probes):
        raise AssertionError("explicit guard counter mismatch")
    return len(probes)


def _audit_self_tests(guard: AuthorityGuard, raw_open, raw_socket, raw_popen) -> int:
    probes = (
        ("filesystem", lambda: raw_open(__file__, os.O_RDONLY)),
        ("network", lambda: raw_socket(socket.AF_INET, socket.SOCK_STREAM)),
        ("subprocess", lambda: raw_popen([sys.executable, "-V"])),
    )
    before = len(guard.attempts)
    for category, action in probes:
        _expect_guard(category, action)
    if len(guard.attempts) - before != len(probes):
        raise AssertionError("audit guard counter mismatch")
    return len(probes)


def _control_mutants(document: Mapping[str, Any]) -> int:
    detected = 0
    args = tuple(document[key] for key in (
        "l_result", "rule_bundle", "r_profile", "binding_profile", "query_batch"
    ))

    def mutator(l_result, *_rest):
        l_result["kind"] = "mutated"
        return {}

    attempts: list[str] = []
    tracked = tuple(write_tracking_copy(value, attempts) for value in args)
    try:
        call_project_lr(mutator, *tracked)
    except AttemptedMutation:
        detected += 1
    else:
        raise AssertionError("input-mutation control mutant escaped")

    def alias(l_result, *_rest):
        return l_result

    try:
        call_project_lr(alias, *args)
    except ValueError:
        detected += 1
    else:
        raise AssertionError("alias control mutant escaped")

    for payload in (
        {"kind": "LRProjectionResult", "effect_intents": []},
        {"kind": "LRProjectionResult", "frontier": 1},
        {"kind": "LRProjectionResult", "demand": 1},
    ):
        try:
            _walk_forbidden(payload)
        except AssertionError:
            detected += 1
        else:
            raise AssertionError("authority/frontier/demand control mutant escaped")
    return detected


def main() -> int:
    documents = _build_documents()
    compiled = _precompile()
    raw_open, raw_socket, raw_popen = os.open, socket.socket, subprocess.Popen
    guard = AuthorityGuard([ROOT / "src", ROOT / "scripts"])
    guard.install()
    package, metadata_checks = _guarded_import(compiled)
    guard.lock_import_reads()
    explicit = _explicit_self_tests(guard)
    audit = _audit_self_tests(guard, raw_open, raw_socket, raw_popen)
    guard.clear()

    successes = rejections = mutation_attempts = 0
    for label, document, expected in documents:
        attempts: list[str] = []
        tracked = {
            key: write_tracking_copy(value, attempts) for key, value in document.items()
        }
        result = call_project_lr(
            package.project_lr,
            tracked["l_result"], tracked["rule_bundle"], tracked["r_profile"],
            tracked["binding_profile"], tracked["query_batch"],
        )
        _assert_result(result, expected)
        if attempts:
            raise AssertionError(f"caller input mutation on {label}: {attempts}")
        if expected == "success":
            successes += 1
        else:
            rejections += 1
        mutation_attempts += len(attempts)
    kernel_attempts = len(guard.attempts)
    if kernel_attempts:
        raise AssertionError(f"ambient authority used by LR seam: {guard.attempts}")
    mutants = _control_mutants(documents[0][1])

    report = {
        "ambient_categories": AMBIENT_CATEGORIES,
        "audit_guard_self_tests": audit,
        "explicit_guard_self_tests": explicit,
        "guard_self_tests": audit + explicit,
        "import_metadata_checks": metadata_checks,
        "kernel_ambient_attempts": kernel_attempts,
        "kernel_input_mutation_attempts": mutation_attempts,
        "kernel_path_executions": len(documents),
        "kernel_path_rejections": rejections,
        "kernel_path_successes": successes,
        "mutants_detected": mutants,
        "public_export": "flrh_lr_seam.project_lr",
    }
    sys.stdout.buffer.write(canonical_bytes(report) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
