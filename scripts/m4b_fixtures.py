"""M4B fixture loading helpers."""

from __future__ import annotations

import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def load_cases():
    return json.loads((ROOT/"fixtures/m4b/cases.json").read_text(encoding="utf-8"))
