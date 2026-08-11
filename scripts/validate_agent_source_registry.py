#!/usr/bin/env python3
"""Offline validator for the pinned GitHub agent-coding source snapshot."""

from __future__ import annotations

import copy
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "research/agent-coding-source-registry.v1.json"
SCHEMA_PATH = ROOT / "spec/schema/agent-source-registry.v1.schema.json"
EXPECTED_CATEGORY_COUNTS = {
    "coding_agent": 8,
    "runtime_comparator": 2,
    "protocol": 1,
    "evaluation": 6,
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def validate(registry: dict[str, Any] | None = None) -> dict[str, Any]:
    registry = copy.deepcopy(registry) if registry is not None else _load(REGISTRY_PATH)
    schema = _load(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(registry),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    _require(not errors, f"agent source registry schema rejection: {errors[0].message if errors else ''}")

    _require(registry["epistemic_status"] == "MEASURED", "metadata observation is not labelled MEASURED")
    _require("not quality" in registry["measurement_scope"], "measurement scope overstates popularity")
    _require(registry["selection"]["stars_are_quality_evidence"] is False, "stars became quality evidence")
    _require(registry["selection"]["vendoring"] is False, "external code was marked for vendoring")
    _require(registry["selection"]["exhaustive"] is False, "non-exhaustive sample became exhaustive")

    sources = registry["sources"]
    ids = [source["source_id"] for source in sources]
    repositories = [source["repository"] for source in sources]
    _require(len(ids) == len(set(ids)), "duplicate source identity")
    _require(len(repositories) == len(set(repositories)), "duplicate repository")
    _require(Counter(source["category"] for source in sources) == Counter(EXPECTED_CATEGORY_COUNTS), "category coverage drift")

    observed_at = datetime.fromisoformat(registry["observation"]["observed_at"].replace("Z", "+00:00"))
    for source in sources:
        _require(source["url"] == f"https://github.com/{source['repository']}", f"repository URL mismatch: {source['source_id']}")
        _require(source["integration_mode"] == "reference_only", f"source is not reference-only: {source['source_id']}")
        _require(source["archived"] is False, f"archived source admitted: {source['source_id']}")
        committed_at = datetime.fromisoformat(source["head_committed_at"].replace("Z", "+00:00"))
        _require(committed_at <= observed_at, f"future head commit: {source['source_id']}")
        _require(set(source["reusable_mechanisms"]).isdisjoint(source["boundary_notes"]), f"mechanism/boundary collapse: {source['source_id']}")

    licenses = Counter(source["license_spdx"] for source in sources)
    return {
        "kind": "AgentSourceRegistryValidationReport",
        "status": "MEASURED_METADATA_SNAPSHOT_VALIDATED",
        "measurement_scope": "metadata_only",
        "sources": len(sources),
        "category_counts": dict(sorted(EXPECTED_CATEGORY_COUNTS.items())),
        "license_counts": dict(sorted(licenses.items())),
        "vendored_sources": 0,
        "stars_are_quality_evidence": False,
    }


def main() -> int:
    print(json.dumps(validate(), ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
