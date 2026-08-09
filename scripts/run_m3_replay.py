#!/usr/bin/env python3
"""Run one M3 command or one stop-on-rejection M3 sequence from stdin.

Approved nonnormative envelopes are:

* ``{"mode":"single","prior_state":...,"profile":...,"command":...}``
* ``{"mode":"sequence","prior_state":...,"profile":...,"commands":[...]}``

Valid input produces exactly one canonical JSON line on stdout and no stderr.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from flrh_reactive import step_r  # noqa: E402
from flrh_reactive.canonical import canonical_bytes  # noqa: E402
from m3_guard import run_document, validate_input_document  # noqa: E402


def main() -> int:
    document = json.loads(sys.stdin.buffer.read())
    validated = validate_input_document(document)
    result = run_document(step_r, validated)
    sys.stdout.buffer.write(canonical_bytes(result) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
