#!/usr/bin/env python3
"""Clean-process ambient-authority admission check for the M2 L kernel."""

from __future__ import annotations

# Legitimate interpreter dependencies are intentionally loaded before authority
# is locked.  Implementation code itself is compiled, but not executed, below.
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
from pathlib import Path
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from m2_guard import (  # noqa: E402
    AttemptedMutation,
    AuthorityGuard,
    GuardViolation,
    call_solve_l,
    write_tracking_copy,
)
from m2_fixtures import (  # noqa: E402
    load_cases,
    materialize_case,
    materialize_delta_input,
    materialize_sequence_step,
)


IMPLEMENTATION_MODULES = (
    ("flrh_logic.canonical", ROOT / "src/flrh_logic/canonical.py", False),
    ("flrh_logic.logic", ROOT / "src/flrh_logic/logic.py", False),
    ("flrh_logic", ROOT / "src/flrh_logic/__init__.py", True),
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


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _precompile_implementation() -> dict[str, tuple[types.CodeType, str, bool]]:
    """Read and compile sources before installing the no-authority boundary."""

    compiled: dict[str, tuple[types.CodeType, str, bool]] = {}
    for fullname, path, is_package in IMPLEMENTATION_MODULES:
        source = path.read_text(encoding="utf-8")
        compiled[fullname] = (compile(source, str(path), "exec"), str(path), is_package)
    return compiled


class _MemoryCodeLoader(importlib.abc.Loader):
    """Execute a precompiled module while preserving real import metadata."""

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
        ("environment", lambda: os.environ.get("M2_AMBIENT_CANARY")),
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


def _import_guarded_implementation(
    compiled: Mapping[str, tuple[types.CodeType, str, bool]],
) -> tuple[types.ModuleType, types.ModuleType, int]:
    for fullname, _, _ in reversed(IMPLEMENTATION_MODULES):
        sys.modules.pop(fullname, None)
    finder = _MemoryCodeFinder(compiled)
    sys.meta_path.insert(0, finder)
    try:
        package = __import__("flrh_logic", fromlist=["solve_l"])
        canonical = __import__("flrh_logic.canonical", fromlist=["canonical_bytes"])
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


def _representative_document() -> dict[str, Any]:
    """Small valid empty fixpoint used only for ambient admission."""

    bundle_preimage = {
        "kind": "M2RuleBundlePreimage",
        "contract_version": "flrh-l-kernel/1",
        "profile_id": "flrh-l-ground-stratified/1",
        "rule_set_version": "rules/0",
        "dataflow_version": "dataflow/0",
        "canonicalization_version": "flrh-cjson/1",
        "limits": {"max_rule_firings": 1000, "max_derivation_depth": 8},
        "ordered_query_atoms": [],
        "ordered_rules": [],
    }
    bundle_digest = "sha256:" + hashlib.sha256(canonical_bytes(bundle_preimage)).hexdigest()
    return {
        "prior_materialization": None,
        "rule_bundle": {
            "kind": "LRuleBundle",
            "schema_version": "flrh-l-rules/1",
            "contract_version": "flrh-l-kernel/1",
            "profile_id": "flrh-l-ground-stratified/1",
            "rule_set_version": "rules/0",
            "dataflow_version": "dataflow/0",
            "canonicalization_version": "flrh-cjson/1",
            "limits": {"max_rule_firings": 1000, "max_derivation_depth": 8},
            "query_atoms": [],
            "rules": [],
            "rule_bundle_digest": bundle_digest,
        },
        "fact_delta_inputs": [],
        "logical_time": 0,
    }


def _kernel_path_inputs() -> dict[str, dict[str, Any]]:
    """Build all filesystem-backed test inputs before authority is locked."""

    corpus = load_cases()
    successes = {case["id"]: case for case in corpus["success_cases"]}
    sequences = {sequence["id"]: sequence for sequence in corpus["sequences"]}

    firing_bundle, firing_deltas = materialize_case(
        corpus, successes["two-supports-and-downstream"], logical_time=1
    )
    default_bundle, default_deltas = materialize_case(
        corpus,
        successes["default-negation-after-empty-lower-stratum"],
        logical_time=1,
    )
    retract_bundle, retract_deltas = materialize_sequence_step(
        corpus, sequences["two-support-retain-then-remove"], 1, 2
    )
    late_valid = materialize_delta_input(
        corpus,
        "a_positive",
        3,
        rule_set_version=retract_bundle["rule_set_version"],
        dataflow_version=retract_bundle["dataflow_version"],
    )
    late_invalid = materialize_delta_input(
        corpus,
        "unknown_retract",
        3,
        rule_set_version=retract_bundle["rule_set_version"],
        dataflow_version=retract_bundle["dataflow_version"],
    )
    return {
        "nonempty_rule_firing": {
            "prior_materialization": None,
            "rule_bundle": firing_bundle,
            "fact_delta_inputs": firing_deltas,
            "logical_time": 1,
        },
        "default_witness": {
            "prior_materialization": None,
            "rule_bundle": default_bundle,
            "fact_delta_inputs": default_deltas,
            "logical_time": 1,
        },
        "prior_retraction": {
            "prior_materialization": None,
            "rule_bundle": retract_bundle,
            "fact_delta_inputs": retract_deltas,
            "logical_time": 2,
        },
        "prior_late_rejection": {
            "prior_materialization": None,
            "rule_bundle": retract_bundle,
            "fact_delta_inputs": [late_valid, late_invalid],
            "logical_time": 3,
        },
    }


def _run_guarded_kernel_paths(
    solve_l: Callable[..., dict[str, Any]],
    guard: AuthorityGuard,
    inputs: Mapping[str, dict[str, Any]],
) -> dict[str, int]:
    """Exercise stateful semantic branches under the locked authority guard."""

    ambient_attempts = 0
    mutation_attempts = 0

    def invoke(
        label: str,
        document: dict[str, Any],
        expected_kind: str,
    ) -> dict[str, Any]:
        nonlocal ambient_attempts, mutation_attempts
        before = canonical_bytes(document)
        writes: list[object] = []
        guarded = write_tracking_copy(copy.deepcopy(document), writes)
        before_attempts = len(guard.attempts)
        result = call_solve_l(solve_l, guarded)
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
        return result

    firing = invoke(
        "nonempty_rule_firing", inputs["nonempty_rule_firing"], "LFixpointResult"
    )
    if firing["stats"]["rule_firing_count"] < 1:
        raise AssertionError("non-empty guarded path did not fire a rule")

    default = invoke("default_witness", inputs["default_witness"], "LFixpointResult")
    if not any(
        support["default_absence_witnesses"]
        for support in default["next_materialization"]["derived_supports"]
    ):
        raise AssertionError("default-negation guarded path omitted its witness")

    retract_document = copy.deepcopy(inputs["prior_retraction"])
    retract_document["prior_materialization"] = firing["next_materialization"]
    retracted = invoke("prior_retraction", retract_document, "LFixpointResult")
    if retracted["stats"]["evaluation_mode"] != "full_recompute":
        raise AssertionError("prior retraction did not take the full-recompute path")

    rejection_document = copy.deepcopy(inputs["prior_late_rejection"])
    rejection_document["prior_materialization"] = retracted["next_materialization"]
    rejected = invoke("prior_late_rejection", rejection_document, "LRejection")
    if rejected.get("code") != "UNKNOWN_DERIVATION":
        raise AssertionError("prior-dependent guarded rejection was not closed")

    return {
        "kernel_path_ambient_attempts": ambient_attempts,
        "kernel_path_executions": 4,
        "kernel_path_input_mutation_attempts": mutation_attempts,
        "kernel_path_rejections": 1,
        "kernel_path_successes": 3,
    }


def _mutants() -> tuple[tuple[str, str, Callable[..., object]], ...]:
    def through(action: Callable[[], object]) -> Callable[..., object]:
        def mutant(prior: Any, rules: Any, deltas: Any, logical_time: Any) -> object:
            action()
            return {"prior": prior, "rules": rules, "deltas": deltas, "time": logical_time}

        return mutant

    def mutate_input(prior: Any, rules: Any, deltas: Any, logical_time: Any) -> object:
        rules["rules"] = []
        return {"prior": prior, "deltas": deltas, "time": logical_time}

    def read_import_metadata(prior: Any, rules: Any, deltas: Any, logical_time: Any) -> object:
        import flrh_logic.logic as implementation

        with builtins.open(implementation.__file__, "rb") as stream:
            stream.read(1)
        return {"prior": prior, "rules": rules, "deltas": deltas, "time": logical_time}

    def conditional_import_metadata_filesystem(
        prior: Any, rules: Any, deltas: Any, logical_time: Any
    ) -> object:
        if rules["rules"]:
            import flrh_logic.logic as implementation

            json.__loader__.get_data(implementation.__file__)
        return {"prior": prior, "rules": rules, "deltas": deltas, "time": logical_time}

    return (
        ("clock", "clock", through(time.time)),
        ("randomness", "randomness", through(lambda: random.SystemRandom().random())),
        ("environment", "environment", through(lambda: os.environ.get("M2_MUTANT"))),
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
    document: dict[str, Any],
    nonempty_document: dict[str, Any],
) -> int:
    detected = 0
    for label, expected_category, mutant in _mutants():
        mutation_attempts: list[object] = []
        source = (
            nonempty_document
            if label == "conditional_import_metadata_filesystem"
            else document
        )
        guarded_document = write_tracking_copy(copy.deepcopy(source), mutation_attempts)
        try:
            call_solve_l(mutant, guarded_document)
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
    document = _representative_document()
    kernel_path_inputs = _kernel_path_inputs()
    before_document = canonical_bytes(document)

    # Preserve original C call paths so the audit hook, not monkeypatches, proves
    # that direct backend access is denied.
    raw_os_open = os.open
    raw_socket = socket.socket
    raw_popen = subprocess.Popen

    guard = AuthorityGuard([ROOT / "src/flrh_logic"])
    guard.install()
    try:
        guard.lock_import_reads()
        explicit_tests = _run_explicit_guard_self_tests(guard)
        audit_tests = _run_audit_guard_self_tests(guard, raw_os_open, raw_socket, raw_popen)

        before_import_attempts = len(guard.attempts)
        package, canonical_module, metadata_checks = _import_guarded_implementation(compiled)
        import_attempts = len(guard.attempts) - before_import_attempts
        if import_attempts != 0:
            raise AssertionError("guarded implementation import attempted ambient authority")

        solve_l = getattr(package, "solve_l", None)
        if not callable(solve_l):
            raise AssertionError("flrh_logic.solve_l is not callable")
        if not callable(getattr(canonical_module, "canonical_bytes", None)):
            raise AssertionError("flrh_logic.canonical.canonical_bytes is not callable")

        mutation_attempts: list[object] = []
        guarded_document = write_tracking_copy(copy.deepcopy(document), mutation_attempts)
        before_kernel_attempts = len(guard.attempts)
        result = call_solve_l(solve_l, guarded_document)
        kernel_attempts = len(guard.attempts) - before_kernel_attempts
        if kernel_attempts != 0:
            raise AssertionError("M2 kernel attempted ambient authority")
        if mutation_attempts:
            raise AssertionError(f"M2 kernel attempted input mutation: {mutation_attempts!r}")
        if canonical_bytes(document) != before_document:
            raise AssertionError("M2 kernel changed unguarded input ownership")
        if result.get("kind") != "LFixpointResult":
            raise AssertionError(f"guarded M2 kernel rejected valid empty fixpoint: {result!r}")
        canonical_module.canonical_bytes(result)

        kernel_paths = _run_guarded_kernel_paths(solve_l, guard, kernel_path_inputs)
        kernel_attempts += kernel_paths["kernel_path_ambient_attempts"]
        kernel_input_mutation_attempts = (
            len(mutation_attempts)
            + kernel_paths["kernel_path_input_mutation_attempts"]
        )

        mutants_detected = _run_mutants(
            guard, document, kernel_path_inputs["nonempty_rule_firing"]
        )
    finally:
        # M1's process-local guard is deliberately irreversible.  This checker
        # exits immediately after emitting the report, so no cleanup is needed.
        pass

    report = {
        "ambient_categories": AMBIENT_CATEGORIES,
        "audit_guard_self_tests": audit_tests,
        "explicit_guard_self_tests": explicit_tests,
        "guard_self_tests": explicit_tests + audit_tests,
        "import_attempts": import_attempts,
        "import_metadata_checks": metadata_checks,
        "kernel_ambient_attempts": kernel_attempts,
        "kernel_input_mutation_attempts": kernel_input_mutation_attempts,
        "mutants_detected": mutants_detected,
    }
    report.update(kernel_paths)
    sys.stdout.buffer.write(canonical_bytes(report) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
