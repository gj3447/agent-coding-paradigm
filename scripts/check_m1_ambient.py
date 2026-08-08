#!/usr/bin/env python3
"""Run M1 import and transition behind process-local ambient guards."""

from __future__ import annotations

import copy
import builtins
import importlib
import importlib.abc
import importlib.machinery
import json
import os
import random
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable

# Preload every standard-library dependency used by the implementation before
# guard installation so import-time package reads are the only allowed I/O.
import dataclasses  # noqa: F401
import hashlib  # noqa: F401
import re  # noqa: F401
import typing  # noqa: F401
import unicodedata  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
# macOS' system Python redirects bytecode reads into ~/Library/Caches.  Point
# that lookup back underneath the pinned package root and disable writes so the
# import admission test neither depends on nor mutates an ambient cache.
sys.pycache_prefix = str(ROOT / "src/flrh_kernel/.m1-guard-cache")
sys.dont_write_bytecode = True

from m1_guard import (  # noqa: E402
    AttemptedMutation,
    AuthorityGuard,
    GuardViolation,
    write_tracking_copy,
)


IMPLEMENTATION_MODULES = (
    ("flrh_kernel.canonical", ROOT / "src/flrh_kernel/canonical.py"),
    ("flrh_kernel.kernel", ROOT / "src/flrh_kernel/kernel.py"),
    ("flrh_kernel", ROOT / "src/flrh_kernel/__init__.py"),
)


def _precompile_implementation() -> dict[str, Any]:
    """Perform trusted loader I/O before the guard, but no module-body execution."""

    return {
        name: compile(path.read_text(encoding="utf-8"), str(path), "exec")
        for name, path in IMPLEMENTATION_MODULES
    }


class _MemoryCodeLoader(importlib.abc.Loader):
    def __init__(self, name: str, path: Path, code: Any, *, is_package: bool) -> None:
        self.name = name
        self.path = path
        self.code = code
        self._is_package = is_package

    def create_module(self, _spec: importlib.machinery.ModuleSpec) -> None:
        return None

    def exec_module(self, module: Any) -> None:
        exec(self.code, module.__dict__)

    def is_package(self, fullname: str) -> bool:
        return fullname == self.name and self._is_package


class _MemoryCodeFinder(importlib.abc.MetaPathFinder):
    def __init__(self, code_objects: dict[str, Any]) -> None:
        paths = dict(IMPLEMENTATION_MODULES)
        self.loaders = {
            name: _MemoryCodeLoader(
                name,
                paths[name],
                code,
                is_package=name == "flrh_kernel",
            )
            for name, code in code_objects.items()
        }

    def find_spec(
        self, fullname: str, _path: Any = None, _target: Any = None
    ) -> importlib.machinery.ModuleSpec | None:
        loader = self.loaders.get(fullname)
        if loader is None:
            return None
        spec = importlib.machinery.ModuleSpec(
            fullname,
            loader,
            origin=str(loader.path),
            is_package=loader.is_package(fullname),
        )
        spec.has_location = True
        if loader.is_package(fullname):
            spec.submodule_search_locations = [str(loader.path.parent)]
        return spec


def _import_guarded_implementation(
    code_objects: dict[str, Any]
) -> tuple[Any, _MemoryCodeFinder]:
    """Use normal import semantics while executing precompiled code without loader I/O."""

    for name, _path in reversed(IMPLEMENTATION_MODULES):
        sys.modules.pop(name, None)
    finder = _MemoryCodeFinder(code_objects)
    sys.meta_path.insert(0, finder)
    package = importlib.import_module("flrh_kernel")
    return package, finder


def _expect_guard(guard: AuthorityGuard, category: str, call: Callable[[], Any]) -> None:
    guard.clear()
    try:
        call()
    except GuardViolation as error:
        if error.category != category:
            raise AssertionError(f"guard category mismatch: {category} != {error.category}") from error
    else:
        raise AssertionError(f"guard self-test did not fire: {category}")
    if len(guard.attempts) != 1:
        raise AssertionError(f"guard self-test count drift: {category}: {guard.attempts}")


def _run_mutant(
    guard: AuthorityGuard,
    document: dict[str, Any],
    mutant: Callable[[Any, Any], Any],
    expected: str,
) -> None:
    ambient_attempts: list[str] = []
    guarded = write_tracking_copy(copy.deepcopy(document), ambient_attempts)
    guard.clear()
    try:
        mutant(guarded["snapshot"], guarded["accepted_event"])
    except GuardViolation as error:
        if error.category != expected:
            raise AssertionError(f"mutant guard mismatch: {expected} != {error.category}") from error
    except AttemptedMutation:
        if expected != "input_mutation":
            raise
    else:
        raise AssertionError(f"mutant survived guard: {expected}")


def main() -> int:
    document = json.loads((ROOT / "fixtures/m1/cases.json").read_text(encoding="utf-8"))["base_inputs"][
        "observe-with-effect"
    ]
    code_objects = _precompile_implementation()
    audit_os_open = os.open
    audit_socket = socket.socket
    audit_popen = subprocess.Popen
    guard = AuthorityGuard([ROOT / "src/flrh_kernel"])
    guard.install()
    guard.lock_import_reads()

    self_tests = (
        ("clock", lambda: time.monotonic()),
        ("randomness", lambda: random.SystemRandom()),
        ("uuid", lambda: uuid.uuid4()),
        ("environment", lambda: os.environ["FLRH_AMBIENT_POISON"]),
        ("filesystem", lambda: builtins.open(ROOT / "src/flrh_kernel/kernel.py")),
        ("network", lambda: socket.socket()),
        ("subprocess", lambda: subprocess.Popen(["ambient-self-test"])),
        ("model_or_tool", lambda: importlib.import_module("openai")),
    )
    for category, call in self_tests:
        _expect_guard(guard, category, call)

    def audit_open_probe() -> None:
        descriptor = audit_os_open("ambient-audit-self-test", os.O_RDONLY)
        os.close(descriptor)

    def audit_socket_probe() -> None:
        connection = audit_socket()
        connection.close()

    def audit_subprocess_probe() -> None:
        child = audit_popen([sys.executable, "-c", "pass"], env={})
        child.wait()

    audit_self_tests = (
        ("filesystem", audit_open_probe),
        ("network", audit_socket_probe),
        ("subprocess", audit_subprocess_probe),
    )
    for category, call in audit_self_tests:
        _expect_guard(guard, category, call)

    guard.clear()
    implementation, memory_finder = _import_guarded_implementation(code_objects)
    canonical_bytes = sys.modules["flrh_kernel.canonical"].canonical_bytes
    step_f = implementation.step_f

    if guard.attempts:
        raise AssertionError(f"implementation import attempted ambient authority: {guard.attempts}")
    imported_modules = [sys.modules[name] for name, _path in IMPLEMENTATION_MODULES]
    metadata_checks = 0
    for module in imported_modules:
        if module.__spec__ is None or module.__loader__ is None:
            raise AssertionError(f"guarded import metadata missing: {module.__name__}")
        if module.__spec__.origin != module.__file__:
            raise AssertionError(f"guarded import origin mismatch: {module.__name__}")
        if module.__loader__ is not memory_finder.loaders[module.__name__]:
            raise AssertionError(f"guarded import loader mismatch: {module.__name__}")
        metadata_checks += 3
    if implementation.__spec__.submodule_search_locations != [str(ROOT / "src/flrh_kernel")]:
        raise AssertionError("guarded package search path mismatch")
    metadata_checks += 1

    mutation_attempts: list[str] = []
    guarded_document = write_tracking_copy(copy.deepcopy(document), mutation_attempts)
    before = json.dumps(guarded_document, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
    result = step_f(guarded_document["snapshot"], guarded_document["accepted_event"])
    after = json.dumps(guarded_document, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
    if result["kind"] != "FTransition":
        raise AssertionError(f"guarded kernel rejected valid input: {result}")
    if guard.attempts:
        raise AssertionError(f"kernel attempted ambient authority: {guard.attempts}")
    if mutation_attempts or before != after:
        raise AssertionError(f"kernel attempted input mutation: {mutation_attempts}")
    canonical_bytes(result)

    def clock_mutant(snapshot: Any, event: Any) -> Any:
        import time as mutant_time

        mutant_time.monotonic()
        return step_f(snapshot, event)

    def filesystem_mutant(snapshot: Any, event: Any) -> Any:
        import pathlib

        pathlib.Path("ambient-mutant").read_bytes()
        return step_f(snapshot, event)

    def model_mutant(snapshot: Any, event: Any) -> Any:
        importlib.import_module("openai")
        return step_f(snapshot, event)

    def dispatch_mutant(snapshot: Any, event: Any) -> Any:
        subprocess.Popen(["ambient-mutant"])
        return step_f(snapshot, event)

    def mutation_mutant(snapshot: Any, event: Any) -> Any:
        snapshot["revision"] = snapshot["revision"]
        return step_f(snapshot, event)

    def backend_read_mutant(snapshot: Any, event: Any) -> Any:
        sys.modules[os.name].read(0, 0)
        return step_f(snapshot, event)

    def backend_stat_mutant(snapshot: Any, event: Any) -> Any:
        sys.modules[os.name].stat(".")
        return step_f(snapshot, event)

    def import_metadata_branch_mutant(snapshot: Any, event: Any) -> Any:
        if implementation.__spec__ is not None:
            builtins.open(implementation.__file__, "rb").read(1)
        return step_f(snapshot, event)

    mutants = (
        (clock_mutant, "clock"),
        (filesystem_mutant, "filesystem"),
        (model_mutant, "model_or_tool"),
        (dispatch_mutant, "subprocess"),
        (mutation_mutant, "input_mutation"),
        (backend_read_mutant, "filesystem"),
        (backend_stat_mutant, "filesystem"),
        (import_metadata_branch_mutant, "filesystem"),
    )
    for mutant, expected in mutants:
        _run_mutant(guard, document, mutant, expected)

    report = {
        "ambient_categories": [category for category, _call in self_tests],
        "explicit_guard_self_tests": len(self_tests),
        "audit_guard_self_tests": len(audit_self_tests),
        "guard_self_tests": len(self_tests) + len(audit_self_tests),
        "import_attempts": 0,
        "import_metadata_checks": metadata_checks,
        "kernel_ambient_attempts": 0,
        "kernel_input_mutation_attempts": 0,
        "mutants_detected": len(mutants),
    }
    sys.stdout.write(json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
