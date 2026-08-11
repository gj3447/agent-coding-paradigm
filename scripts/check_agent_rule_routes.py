#!/usr/bin/env python3
"""Validate deterministic, quality-first routing of repository instructions.

The checker records context size but has no size threshold. It must never fail,
truncate, or omit a required rule because of prompt-token count.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
ROUTES_PATH = ROOT / "agent-rules/routes.v1.json"
ROUTES_SCHEMA_PATH = ROOT / "spec/schema/agent-rule-routes.v1.schema.json"
CASES_PATH = ROOT / "fixtures/agent-rules/routing-cases.v1.json"
RULE_ID_RE = re.compile(r"`((?:GOV[1-4])|(?:RT(?:10|[1-9])))`\s+[-—]")


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _metrics(text: str) -> dict[str, Any]:
    encoded = text.encode("utf-8")
    return {
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "bytes": len(encoded),
        "words": len(text.split()),
    }


def _source_text(path: str, overrides: Mapping[str, str]) -> str:
    if path in overrides:
        return overrides[path]
    candidate = (ROOT / path).resolve()
    _require(candidate.is_relative_to(ROOT.resolve()), f"rule source escapes repository: {path}")
    _require(candidate.is_file(), f"rule source missing: {path}")
    return candidate.read_text(encoding="utf-8")


def validate(
    routes_document: dict[str, Any] | None = None,
    cases_document: dict[str, Any] | None = None,
    source_text_overrides: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    routes_document = copy.deepcopy(routes_document) if routes_document is not None else _load(ROUTES_PATH)
    cases_document = copy.deepcopy(cases_document) if cases_document is not None else _load(CASES_PATH)
    overrides = dict(source_text_overrides or {})
    schema = _load(ROUTES_SCHEMA_PATH)

    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(routes_document),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    _require(not errors, f"agent rule route schema rejection: {errors[0].message if errors else ''}")
    _require(cases_document.get("schema_version") == "agent-rule-routing-cases/v1", "wrong routing fixture version")
    _require(cases_document.get("epistemic_status") == "PROPOSED", "unearned routing fixture status")

    policy = routes_document["context_policy"]
    _require(policy["quality_first"] is True, "context routing is not quality-first")
    _require(policy["hard_prompt_token_limit"] is False, "hard prompt-token limit introduced")
    _require(policy["truncation_allowed"] is False, "instruction truncation introduced")
    _require(policy["fail_on_prompt_token_count"] is False, "prompt-token count became a failure condition")
    _require(policy["runtime_safety_budgets_are_separate"] is True, "runtime safety budgets conflated with prompt context")
    _require(routes_document["resolution"]["manifest_closure_semantics"] == "integrity_evidence_not_preload", "manifest closure became preload")

    agent_text = _source_text("AGENTS.md", overrides)
    always_ids = RULE_ID_RE.findall(agent_text)
    _require(always_ids == routes_document["always_rule_ids"], "always-on rule ID drift")
    _require(len(always_ids) == len(set(always_ids)), "duplicate always-on rule ID")

    routes = {route["route_id"]: route for route in routes_document["routes"]}
    _require(len(routes) == len(routes_document["routes"]), "duplicate route ID")
    _require(list(routes) == sorted(routes), "routes are not in canonical route_id order")

    reports = []
    for case in cases_document["cases"]:
        _require(
            set(case) == {"case_id", "selected_routes", "expected_sources", "must_include_rule_ids", "must_exclude_rule_ids"},
            f"closed routing fixture shape violated: {case.get('case_id')}",
        )
        selected = case["selected_routes"]
        _require(selected == sorted(set(selected)), f"noncanonical route selection: {case['case_id']}")
        _require(all(route_id in routes for route_id in selected), f"unknown selected route: {case['case_id']}")
        source_paths = sorted({path for route_id in selected for path in routes[route_id]["sources"]})
        _require(source_paths == case["expected_sources"], f"source union drift: {case['case_id']}")

        rule_owners: dict[str, str] = {rule_id: "AGENTS.md" for rule_id in always_ids}
        source_receipts = []
        for path in source_paths:
            text = _source_text(path, overrides)
            source_receipts.append({"path": path, **_metrics(text)})
            if path.endswith(".md"):
                for rule_id in RULE_ID_RE.findall(text):
                    _require(rule_id not in rule_owners, f"duplicate rule ID {rule_id} in {path} and {rule_owners.get(rule_id)}")
                    rule_owners[rule_id] = path

        required = {rule_id for route_id in selected for rule_id in routes[route_id]["required_rule_ids"]}
        _require(required <= set(rule_owners), f"required rule source missing: {case['case_id']}")
        _require(set(case["must_include_rule_ids"]) <= set(rule_owners), f"fixture include rule missing: {case['case_id']}")
        _require(not (set(case["must_exclude_rule_ids"]) & set(rule_owners)), f"irrelevant rule preloaded: {case['case_id']}")

        total_text = agent_text + "".join(_source_text(path, overrides) for path in source_paths)
        reports.append(
            {
                "case_id": case["case_id"],
                "routes": selected,
                "sources": source_receipts,
                "resolved_rule_ids": sorted(rule_owners),
                "context_observation": _metrics(total_text),
                "tokens": None,
                "tokenizer": None,
            }
        )

    return {
        "kind": "AgentRuleRoutingValidationReport",
        "status": "PROPOSED_ROUTING_ADMISSION",
        "hard_prompt_token_limit": False,
        "truncation_allowed": False,
        "root_observation": _metrics(agent_text),
        "case_count": len(reports),
        "cases": reports,
    }


def main() -> int:
    print(json.dumps(validate(), ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
