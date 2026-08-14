"""Compatibility entry point for the TypeScript Effect comparison runner."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import NoReturn, Sequence


HERE = Path(__file__).resolve().parent


def _tsx_executable() -> Path:
    executable = HERE / "node_modules" / ".bin" / "tsx"
    if not executable.is_file():
        raise FileNotFoundError(f"TypeScript runner is unavailable: {executable}")
    return executable


def compatibility_command(argv: Sequence[str]) -> list[str]:
    executable = _tsx_executable()
    return [str(executable), str(HERE / "src" / "compare-cli.ts"), *argv]


def main(argv: Sequence[str] | None = None) -> NoReturn:
    command = compatibility_command(sys.argv[1:] if argv is None else argv)
    os.execv(command[0], command)
    raise AssertionError("os.execv returned unexpectedly")


if __name__ == "__main__":
    main()
