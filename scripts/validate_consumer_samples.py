#!/usr/bin/env python3
"""Offline admission checker for public synthetic consumer samples.

Passing this checker establishes only the declared PROPOSED corpus shape. It
does not execute a private workflow or establish runtime efficacy.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "spec/consumer-sample-contract.v1.json"
SCHEMA_PATH = ROOT / "spec/schema/consumer-sample.v1.schema.json"
CORPUS_PATH = ROOT / "fixtures/consumer-samples/cases.json"

REQUIRED_VARIANTS = {
    "variant:happy-path",
    "variant:insufficient-headroom",
    "variant:unknown-after-dispatch",
    "variant:duplicate-intent-conflict",
    "variant:producer-self-report-only",
    "variant:cancel-while-unknown",
}
PRIVATE_VALUE_PATTERNS = {
    "email": re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])"),
    "ipv4": re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)"),
    "private_absolute_path": re.compile(r"(?:^|\s)/(?:Users|data|home|mnt|srv)/(?:[^\s]+)"),
    "ssh_command": re.compile(r"(?:^|\s)ssh\s+[^\s]+"),
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _walk(value: Any, path: tuple[str, ...] = ()) -> Iterable[tuple[tuple[str, ...], Any]]:
    yield path, value
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _walk(item, (*path, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk(item, (*path, str(index)))


def validate(
    corpus: dict[str, Any] | None = None,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = copy.deepcopy(contract) if contract is not None else _load(CONTRACT_PATH)
    corpus = copy.deepcopy(corpus) if corpus is not None else _load(CORPUS_PATH)
    schema = _load(SCHEMA_PATH)

    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(corpus),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    _require(not errors, f"consumer sample schema rejection: {errors[0].message if errors else ''}")
    _require(contract.get("schema_version") == "consumer-sample-contract/v1", "wrong contract version")
    _require(contract.get("epistemic_status") == "PROPOSED", "unearned contract status")
    _require(contract["source_boundary"]["raw_payload_inclusion"] is False, "contract admits private payloads")
    _require(corpus["epistemic_status"] == "PROPOSED", "unearned corpus status")

    required_lanes = set(contract["required_data_lanes"])
    prohibited_keys = set()
    for sample in corpus["samples"]:
        prohibited_keys.update(sample["privacy"]["forbidden_field_names"])

    for path, value in _walk(corpus):
        if path and path[-1] in prohibited_keys:
            raise AssertionError(f"forbidden private field at /{'/'.join(path)}")
        if not isinstance(value, str):
            continue
        if len(path) >= 2 and path[-2] in {"forbidden_field_names", "synthetic_markers"}:
            continue
        for label, pattern in PRIVATE_VALUE_PATTERNS.items():
            _require(not pattern.search(value), f"{label} leaked at /{'/'.join(path)}")

    variant_count = 0
    for sample in corpus["samples"]:
        _require(set(sample["task"]["data_lanes"]) == required_lanes, "required data lane drift")
        _require(sample["origin"]["source_payload_included"] is False, "origin payload included")
        _require(sample["privacy"]["source_payload_included"] is False, "privacy payload included")

        stages = sample["stages"]
        _require([stage["sequence"] for stage in stages] == list(range(1, len(stages) + 1)), "stage sequence is not contiguous")
        _require(len({stage["stage_id"] for stage in stages}) == len(stages), "duplicate stage identity")
        owners = {stage["kind"]: stage["owner"] for stage in stages}
        _require(
            owners == {
                "decide": "F",
                "derive_eligibility": "L",
                "stabilize": "R",
                "commit_intent": "H",
                "dispatch": "H",
                "reconcile": "H",
                "verify": "EXTERNAL_VERIFIER",
                "close_terminal": "H",
            },
            "FLR-H ownership drift",
        )
        _require(
            all(not stage["external_mutation"] for stage in stages if stage["owner"] in {"F", "L", "R"}),
            "pure plane owns an external mutation",
        )
        _require(
            [stage["kind"] for stage in stages if stage["external_mutation"]] == ["dispatch"],
            "external mutation boundary drift",
        )
        _require(
            [stage["kind"] for stage in stages if stage["completion_authority"]] == ["close_terminal"],
            "H is not the sole terminal authority",
        )
        _require(sample["verifier"]["producer_role"] != sample["verifier"]["verifier_role"], "producer is its own verifier")

        variants = {variant["variant_id"]: variant for variant in sample["variants"]}
        _require(set(variants) == REQUIRED_VARIANTS, "consumer variant set drift")
        variant_count += len(variants)
        for variant in variants.values():
            route = variant["expected_route"]
            if "retry" in route:
                _require("reconcile" in route and route.index("reconcile") < route.index("retry"), "retry precedes reconciliation")

        unknown_route = variants["variant:unknown-after-dispatch"]["expected_route"]
        _require("reconcile" in unknown_route, "unknown outcome bypasses reconciliation")
        duplicate_route = variants["variant:duplicate-intent-conflict"]["expected_route"]
        _require("conflict" in duplicate_route and "retry" not in duplicate_route, "identity conflict became retry")
        self_report = variants["variant:producer-self-report-only"]
        _require(self_report["expected_terminal"] == "ACTIVE" and "terminal" not in self_report["expected_route"], "producer self-report completed the run")
        cancel_route = variants["variant:cancel-while-unknown"]["expected_route"]
        _require(cancel_route.index("reconcile") < cancel_route.index("honor_cancel"), "cancellation stranded an unknown effect")
        happy_route = variants["variant:happy-path"]["expected_route"]
        _require(happy_route.index("verify") < happy_route.index("terminal"), "success precedes independent verification")

    return {
        "kind": "ConsumerSampleValidationReport",
        "status": "PROPOSED_CORPUS_ADMISSION",
        "samples": len(corpus["samples"]),
        "variants": variant_count,
        "data_lanes": len(required_lanes),
        "private_value_patterns": len(PRIVATE_VALUE_PATTERNS),
    }


def main() -> int:
    print(json.dumps(validate(), ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
