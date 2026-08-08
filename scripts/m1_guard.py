"""Process-local test guard for the M1 ambient-authority admission check.

This module is non-normative.  It combines an audit hook, explicit Python
surface traps, an import blocker, and recursively write-detecting inputs.  It
is evidence for the named CPython surfaces only, not a universal sandbox.
"""

from __future__ import annotations

import builtins
import datetime
import io
import os
import pathlib
import random
import secrets
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import MutableMapping
from typing import Any, Callable, Iterable, Iterator, Optional


class GuardViolation(RuntimeError):
    def __init__(self, category: str, primitive: str) -> None:
        super().__init__(f"AMBIENT_EFFECT_FORBIDDEN:{category}:{primitive}")
        self.category = category
        self.primitive = primitive


class AttemptedMutation(RuntimeError):
    pass


class _BlockedImports:
    def __init__(self, guard: "AuthorityGuard", names: Iterable[str]) -> None:
        self.guard = guard
        self.names = frozenset(names)

    def find_spec(self, fullname: str, _path: Any = None, _target: Any = None) -> None:
        if fullname.split(".", 1)[0] in self.names:
            self.guard.block("model_or_tool", f"import:{fullname}")
        return None


class _GuardedEnvironment(MutableMapping):
    def __init__(self, guard: "AuthorityGuard") -> None:
        self.guard = guard

    def _deny(self, operation: str) -> None:
        self.guard.block("environment", f"os.environ.{operation}")

    def __getitem__(self, key: str) -> str:
        self._deny("getitem")
        raise KeyError(key)

    def __setitem__(self, key: str, value: str) -> None:
        self._deny("setitem")

    def __delitem__(self, key: str) -> None:
        self._deny("delitem")

    def __iter__(self) -> Iterator[str]:
        self._deny("iter")
        return iter(())

    def __len__(self) -> int:
        self._deny("len")
        return 0

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        self._deny("get")
        return default


class AuthorityGuard:
    def __init__(self, import_roots: Iterable[pathlib.Path]) -> None:
        self.import_roots = tuple(path.resolve() for path in import_roots)
        self.import_reads_allowed = True
        self.attempts: list[dict[str, str]] = []
        self._original_open = builtins.open
        self._original_io_open = io.open

    def block(self, category: str, primitive: str) -> None:
        self.attempts.append({"category": category, "primitive": primitive})
        raise GuardViolation(category, primitive)

    def clear(self) -> None:
        self.attempts.clear()

    def _allowed_import_read(self, target: Any, mode: Any) -> bool:
        if not self.import_reads_allowed or not isinstance(target, (str, bytes, os.PathLike)):
            return False
        if isinstance(mode, str) and any(character in mode for character in "wax+"):
            return False
        try:
            resolved = pathlib.Path(target).resolve()
        except (OSError, TypeError, ValueError):
            return False
        for root in self.import_roots:
            try:
                resolved.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    def _guarded_open(self, target: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if self._allowed_import_read(target, mode):
            return self._original_open(target, mode, *args, **kwargs)
        self.block("filesystem", "builtins.open")

    def _guarded_io_open(self, target: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if self._allowed_import_read(target, mode):
            return self._original_io_open(target, mode, *args, **kwargs)
        self.block("filesystem", "io.open")

    def _audit(self, event: str, args: tuple[Any, ...]) -> None:
        if event == "open":
            target = args[0] if args else None
            mode = args[1] if len(args) > 1 else None
            if not self._allowed_import_read(target, mode):
                self.block("filesystem", "audit:open")
        elif event.startswith("socket."):
            self.block("network", f"audit:{event}")
        elif event == "subprocess.Popen" or event == "os.system" or event.startswith("os.posix_spawn"):
            self.block("subprocess", f"audit:{event}")

    def _trap(self, category: str, primitive: str) -> Callable[..., Any]:
        def denied(*_args: Any, **_kwargs: Any) -> Any:
            self.block(category, primitive)

        return denied

    def install(self) -> None:
        sys.addaudithook(self._audit)

        for name in (
            "time",
            "time_ns",
            "monotonic",
            "monotonic_ns",
            "perf_counter",
            "perf_counter_ns",
            "process_time",
            "process_time_ns",
            "thread_time",
            "thread_time_ns",
            "clock_gettime",
            "clock_gettime_ns",
        ):
            if hasattr(time, name):
                setattr(time, name, self._trap("clock", f"time.{name}"))

        guard = self

        class GuardedDateTime(datetime.datetime):
            @classmethod
            def now(cls, *_args: Any, **_kwargs: Any) -> Any:
                guard.block("clock", "datetime.datetime.now")

            @classmethod
            def utcnow(cls, *_args: Any, **_kwargs: Any) -> Any:
                guard.block("clock", "datetime.datetime.utcnow")

            @classmethod
            def today(cls, *_args: Any, **_kwargs: Any) -> Any:
                guard.block("clock", "datetime.datetime.today")

        class GuardedDate(datetime.date):
            @classmethod
            def today(cls, *_args: Any, **_kwargs: Any) -> Any:
                guard.block("clock", "datetime.date.today")

        datetime.datetime = GuardedDateTime
        datetime.date = GuardedDate

        for name in (
            "random",
            "randrange",
            "randint",
            "choice",
            "choices",
            "shuffle",
            "getrandbits",
            "uniform",
            "Random",
            "SystemRandom",
        ):
            if hasattr(random, name):
                setattr(random, name, self._trap("randomness", f"random.{name}"))
        for name in ("choice", "randbelow", "randbits", "token_bytes", "token_hex", "token_urlsafe"):
            if hasattr(secrets, name):
                setattr(secrets, name, self._trap("randomness", f"secrets.{name}"))
        os.urandom = self._trap("randomness", "os.urandom")
        for name in ("uuid1", "uuid4"):
            setattr(uuid, name, self._trap("uuid", f"uuid.{name}"))

        os.getenv = self._trap("environment", "os.getenv")
        os.environ = _GuardedEnvironment(self)

        builtins.open = self._guarded_open
        io.open = self._guarded_io_open
        for name in (
            "open",
            "read_bytes",
            "read_text",
            "write_bytes",
            "write_text",
            "touch",
            "mkdir",
            "unlink",
            "rename",
            "replace",
        ):
            setattr(pathlib.Path, name, self._trap("filesystem", f"pathlib.Path.{name}"))

        backend = sys.modules.get(os.name)
        for module, label in ((os, "os"), (backend, os.name)):
            if module is None:
                continue
            for name in (
                "read",
                "readv",
                "pread",
                "preadv",
                "stat",
                "lstat",
                "fstat",
                "listdir",
                "scandir",
                "readlink",
            ):
                if hasattr(module, name):
                    setattr(module, name, self._trap("filesystem", f"{label}.{name}"))

        for name in ("socket", "create_connection", "getaddrinfo", "socketpair"):
            if hasattr(socket, name):
                setattr(socket, name, self._trap("network", f"socket.{name}"))

        for name in ("Popen", "run", "call", "check_call", "check_output", "getoutput", "getstatusoutput"):
            if hasattr(subprocess, name):
                setattr(subprocess, name, self._trap("subprocess", f"subprocess.{name}"))
        for name in ("system", "popen"):
            if hasattr(os, name):
                setattr(os, name, self._trap("subprocess", f"os.{name}"))

        sys.meta_path.insert(
            0,
            _BlockedImports(
                self,
                {"openai", "anthropic", "model_adapter", "tool_adapter", "langchain", "litellm"},
            ),
        )

    def lock_import_reads(self) -> None:
        self.import_reads_allowed = False


class WriteTrackingDict(dict):
    def __init__(self, attempts: list[str]) -> None:
        dict.__init__(self)
        self._attempts = attempts

    def _deny(self, operation: str) -> None:
        self._attempts.append(f"dict.{operation}")
        raise AttemptedMutation(f"INPUT_MUTATION_FORBIDDEN:dict.{operation}")

    def __setitem__(self, key: Any, value: Any) -> None:
        self._deny("setitem")

    def __delitem__(self, key: Any) -> None:
        self._deny("delitem")

    def clear(self) -> None:
        self._deny("clear")

    def pop(self, key: Any, default: Any = None) -> Any:
        self._deny("pop")

    def popitem(self) -> Any:
        self._deny("popitem")

    def setdefault(self, key: Any, default: Any = None) -> Any:
        self._deny("setdefault")

    def update(self, *args: Any, **kwargs: Any) -> None:
        self._deny("update")

    def __ior__(self, other: Any) -> "WriteTrackingDict":
        self._deny("ior")
        return self


class WriteTrackingList(list):
    def __init__(self, attempts: list[str]) -> None:
        list.__init__(self)
        self._attempts = attempts

    def _deny(self, operation: str) -> None:
        self._attempts.append(f"list.{operation}")
        raise AttemptedMutation(f"INPUT_MUTATION_FORBIDDEN:list.{operation}")

    def __setitem__(self, key: Any, value: Any) -> None:
        self._deny("setitem")

    def __delitem__(self, key: Any) -> None:
        self._deny("delitem")

    def append(self, value: Any) -> None:
        self._deny("append")

    def extend(self, values: Any) -> None:
        self._deny("extend")

    def insert(self, index: int, value: Any) -> None:
        self._deny("insert")

    def pop(self, index: int = -1) -> Any:
        self._deny("pop")

    def remove(self, value: Any) -> None:
        self._deny("remove")

    def clear(self) -> None:
        self._deny("clear")

    def sort(self, *args: Any, **kwargs: Any) -> None:
        self._deny("sort")

    def reverse(self) -> None:
        self._deny("reverse")

    def __iadd__(self, values: Any) -> "WriteTrackingList":
        self._deny("iadd")
        return self

    def __imul__(self, count: int) -> "WriteTrackingList":
        self._deny("imul")
        return self


def write_tracking_copy(value: Any, attempts: list[str], memo: Optional[dict[int, Any]] = None) -> Any:
    if memo is None:
        memo = {}
    identity = id(value)
    if identity in memo:
        return memo[identity]
    if isinstance(value, dict):
        result = WriteTrackingDict(attempts)
        memo[identity] = result
        for key, item in value.items():
            dict.__setitem__(result, key, write_tracking_copy(item, attempts, memo))
        return result
    if isinstance(value, list):
        result = WriteTrackingList(attempts)
        memo[identity] = result
        for item in value:
            list.append(result, write_tracking_copy(item, attempts, memo))
        return result
    return value
