#!/usr/bin/env python3
"""Admit the frozen M3 semantic source mutants against the independent oracle.

The public invocation emits one canonical JSON report line.  Each semantic
mutant is compiled and loaded in a fresh, time-bounded child process, then its
real ``step_r`` is exercised by one fixed oracle-backed probe.  A source-anchor
drift, compile/load failure, timeout, or execution exception is an
``INVALID_MUTANT`` and is never credited as a kill.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import importlib.machinery
import json
import os
import subprocess
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "src/flrh_reactive/reactive.py"
ORACLE_PATH = ROOT / "scripts/m3_oracle.py"
CONTRACT_PATH = ROOT / "spec/m3-reactive-contract.v1.json"
SCHEMA_PATH = ROOT / "spec/schema/m3-reactive.v1.schema.json"
sys.path.insert(0, str(ROOT / "scripts"))

from m3_fixtures import load_cases  # noqa: E402
from m3_oracle import (  # noqa: E402
    canonical_bytes,
    delivery_id,
    profile_digest,
    run_sequence,
    value_digest,
)


REPORT_KIND = "M3SemanticMutationReport"
REPORT_SCHEMA_VERSION = "m3-semantic-mutation-report/1"
MUTANT_RECEIPT_KIND = "M3SemanticMutantReceipt"
BASELINE_RECEIPT_KIND = "M3SemanticBaselineReceipt"
PER_MUTANT_TIMEOUT_SECONDS = 10
EXPECTED_AXIS_COUNT = 10
MAX_STEPS_PER_PROBE = 4
COMPLETION_GATE_CLAUSE = (
    "Mutation tests must catch non-strict frontier publication, max instead of min "
    "frontier, partial-epoch publication, item rather than batch demand, accept/drop "
    "overflow, late acceptance, eligibility-status interpretation, nested-value "
    "rewriting, version drift, and authority-shaped output."
)

EXCEPTION_ANCHOR = '''    except Exception:
        return _rejection(
            _Reject("INVARIANT_VIOLATION", "", {"reason": "closed kernel failure"}),
            trusted_profile_digest,
        )
'''
EXCEPTION_REPLACEMENT = '''    except Exception:
        raise
'''


@dataclass(frozen=True)
class Probe:
    name: str
    profile: dict[str, Any]
    prior_state: dict[str, Any] | None
    commands: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class Mutation:
    name: str
    axis: str
    probe_name: str
    anchor: str
    replacement: str


MUTATIONS = (
    Mutation(
        name="frontier_non_strict",
        axis="non_strict_frontier_publication",
        probe_name="frontier_equal",
        anchor="(time for time in epochs if time < next_global)",
        replacement="(time for time in epochs if time <= next_global)",
    ),
    Mutation(
        name="frontier_global_max",
        axis="max_instead_of_min_frontier",
        probe_name="frontier_skew",
        anchor=(
            "            next_global = None if any(item is None for item in values) "
            "else min(values)"
        ),
        replacement=(
            "            next_global = None if any(item is None for item in values) "
            "else max(values)"
        ),
    ),
    Mutation(
        name="partial_epoch_publication",
        axis="partial_epoch_publication",
        probe_name="two_pair_epoch",
        anchor=(
            "    ordered_proposals = _sorted_wires(proposals)\n"
            "    ordered_verdicts = _sorted_wires(verdicts)"
        ),
        replacement=(
            "    ordered_proposals = _sorted_wires(proposals)[:1]\n"
            "    retained_proposal_ids = {\n"
            "        item[\"proposal_id\"] for item in ordered_proposals\n"
            "    }\n"
            "    ordered_verdicts = _sorted_wires(\n"
            "        [\n"
            "            item for item in verdicts\n"
            "            if item[\"proposal_id\"] in retained_proposal_ids\n"
            "        ]\n"
            "    )"
        ),
    ),
    Mutation(
        name="item_level_demand",
        axis="item_rather_than_batch_demand",
        probe_name="whole_batch_demand",
        anchor=(
            "    ready.sort(key=lambda item: (item[\"batch\"][\"logical_time\"], "
            "canonical_bytes(item)))\n"
            "    count = min(len(ready), demand)\n"
            "    published = [thaw(item) for item in ready[:count]]\n"
            "    return [thaw(item) for item in ready[count:]], demand - count, published"
        ),
        replacement=(
            "    ready.sort(key=lambda item: (item[\"batch\"][\"logical_time\"], "
            "canonical_bytes(item)))\n"
            "    count = 0\n"
            "    remaining_item_demand = demand\n"
            "    for item in ready:\n"
            "        item_cost = (\n"
            "            len(item[\"effect_proposals\"])\n"
            "            + len(item[\"eligibility_verdicts\"])\n"
            "        )\n"
            "        if item_cost > remaining_item_demand:\n"
            "            break\n"
            "        remaining_item_demand -= item_cost\n"
            "        count += 1\n"
            "    published = [thaw(item) for item in ready[:count]]\n"
            "    return (\n"
            "        [thaw(item) for item in ready[count:]],\n"
            "        remaining_item_demand,\n"
            "        published,\n"
            "    )"
        ),
    ),
    Mutation(
        name="overflow_accept_drop_max_open",
        axis="accept_or_drop_overflow_including_max_open",
        probe_name="max_open_overflow",
        anchor=(
            "            if len(next_epochs) > parsed_profile[\"limits\"]"
            "[\"max_open_epochs\"]:\n"
            "                raise _Reject(\n"
            "                    \"QUEUE_CAPACITY_EXCEEDED\",\n"
            "                    \"/command/deltas\",\n"
            "                    {\"limit\": parsed_profile[\"limits\"]"
            "[\"max_open_epochs\"], \"observed\": len(next_epochs)},\n"
            "                )"
        ),
        replacement=(
            "            if len(next_epochs) > parsed_profile[\"limits\"]"
            "[\"max_open_epochs\"]:\n"
            "                retained = parsed_profile[\"limits\"]"
            "[\"max_open_epochs\"]\n"
            "                next_epochs = dict(\n"
            "                    sorted(next_epochs.items())[:retained]\n"
            "                )"
        ),
    ),
    Mutation(
        name="late_delta_acceptance",
        axis="late_acceptance",
        probe_name="per_source_late",
        anchor=(
            "    if source_frontier is not None and "
            "delta[\"logical_time\"] < source_frontier:"
        ),
        replacement=(
            "    if False and source_frontier is not None and "
            "delta[\"logical_time\"] < source_frontier:"
        ),
    ),
    Mutation(
        name="eligibility_status_interpretation",
        axis="eligibility_status_interpretation",
        probe_name="all_status_transport",
        anchor="    ordered_proposals = _sorted_wires(proposals)",
        replacement=(
            "    ineligible_proposal_ids = {\n"
            "        item[\"proposal_id\"]\n"
            "        for item in verdicts\n"
            "        if item[\"status\"] == \"ineligible\"\n"
            "    }\n"
            "    proposals = [\n"
            "        item for item in proposals\n"
            "        if item[\"proposal_id\"] not in ineligible_proposal_ids\n"
            "    ]\n"
            "    verdicts = [\n"
            "        item for item in verdicts if item[\"status\"] != \"ineligible\"\n"
            "    ]\n"
            "    ordered_proposals = _sorted_wires(proposals)"
        ),
    ),
    Mutation(
        name="nested_value_rewrite",
        axis="nested_value_rewriting",
        probe_name="nested_value_preservation",
        anchor=(
            "    proposals = [item[\"value\"] for item in epoch[\"values\"] "
            "if item[\"value_kind\"] == \"effect_proposal\"]"
        ),
        replacement=(
            "    proposals = [item[\"value\"] for item in epoch[\"values\"] "
            "if item[\"value_kind\"] == \"effect_proposal\"]\n"
            "    for proposal in proposals:\n"
            "        proposal[\"preconditions\"] = []"
        ),
    ),
    Mutation(
        name="nested_dataflow_version_drift",
        axis="version_binding",
        probe_name="nested_version_preservation",
        anchor=(
            "    proposals = [item[\"value\"] for item in epoch[\"values\"] "
            "if item[\"value_kind\"] == \"effect_proposal\"]"
        ),
        replacement=(
            "    proposals = [item[\"value\"] for item in epoch[\"values\"] "
            "if item[\"value_kind\"] == \"effect_proposal\"]\n"
            "    for proposal in proposals:\n"
            "        proposal[\"versions\"][\"dataflow\"] = \"dataflow/other\""
        ),
    ),
    Mutation(
        name="authority_shaped_output",
        axis="authority_shaped_output",
        probe_name="all_status_authority_absence",
        anchor=(
            "        \"backpressure\": _backpressure(next_state, profile[\"limits\"]),"
        ),
        replacement=(
            "        **(\n"
            "            {\"effect_intents\": []}\n"
            "            if any(\n"
            "                verdict[\"status\"] == \"ineligible\"\n"
            "                for batch in published\n"
            "                for verdict in batch[\"eligibility_verdicts\"]\n"
            "            )\n"
            "            else {}\n"
            "        ),\n"
            "        \"backpressure\": _backpressure(next_state, profile[\"limits\"]),"
        ),
    ),
)


class LoadFailure(Exception):
    def __init__(self, phase: str) -> None:
        super().__init__(phase)
        self.phase = phase


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _command(profile: Mapping[str, Any], kind: str, **fields: Any) -> dict[str, Any]:
    return {
        "kind": kind,
        "schema_version": "flrh-r-command/1",
        "profile_digest": profile["profile_digest"],
        "dataflow_version": profile["dataflow_version"],
        **fields,
    }


def _delta(
    profile: Mapping[str, Any],
    source_id: str,
    logical_time: int,
    value_kind: str,
    value: Mapping[str, Any],
) -> dict[str, Any]:
    bound = value_digest(value_kind, value)
    return {
        "kind": "RValueDelta",
        "schema_version": "flrh-r-value-delta/1",
        "delivery_id": delivery_id(
            source_id,
            logical_time,
            profile["dataflow_version"],
            value_kind,
            bound,
        ),
        "source_id": source_id,
        "logical_time": logical_time,
        "diff": 1,
        "dataflow_version": profile["dataflow_version"],
        "value_kind": value_kind,
        "value_digest": bound,
        "value": copy.deepcopy(value),
    }


def _pair(
    profile: Mapping[str, Any],
    proposal_template: Mapping[str, Any],
    verdict_template: Mapping[str, Any],
    logical_time: int,
    suffix: str,
    *,
    status: str = "eligible",
) -> tuple[dict[str, Any], dict[str, Any]]:
    proposal = copy.deepcopy(proposal_template)
    proposal["proposal_id"] = f"proposal:m3:mutant:{suffix}"
    proposal["proposal_dedup_key"] = f"proposal-dedup:m3:mutant:{suffix}"
    proposal["cause_id"] = f"cause:m3:mutant:proposal:{suffix}"
    verdict = copy.deepcopy(verdict_template)
    verdict["proposal_id"] = proposal["proposal_id"]
    verdict["verdict_id"] = f"verdict:m3:mutant:{suffix}"
    verdict["cause_id"] = f"cause:m3:mutant:verdict:{suffix}"
    verdict["status"] = status
    return (
        _delta(profile, "source:m3:a", logical_time, "effect_proposal", proposal),
        _delta(profile, "source:m3:b", logical_time, "eligibility_verdict", verdict),
    )


def _profile_with_limits(base: Mapping[str, Any], **limits: int) -> dict[str, Any]:
    profile = copy.deepcopy(base)
    profile["limits"].update(limits)
    profile["profile_digest"] = profile_digest(profile)
    return profile


def _close(profile: Mapping[str, Any], watermark: int) -> tuple[dict[str, Any], ...]:
    return (
        _command(
            profile,
            "RAdvanceFrontier",
            source_id="source:m3:a",
            low_watermark=watermark,
        ),
        _command(
            profile,
            "RAdvanceFrontier",
            source_id="source:m3:b",
            low_watermark=watermark,
        ),
    )


def _build_probes() -> dict[str, Probe]:
    corpus = load_cases()
    base = copy.deepcopy(corpus["profile"])
    proposal = corpus["proposals"]["m1_effect_proposal"]
    verdict = corpus["verdicts"]["m3_verdict"]
    probes: dict[str, Probe] = {}

    p, v = _pair(base, proposal, verdict, 7, "equal")
    probes["frontier_equal"] = Probe(
        "frontier_equal",
        base,
        None,
        (
            _command(base, "RApplyDeltaBatch", deltas=[p, v]),
            *_close(base, 7),
        ),
    )

    p, v = _pair(base, proposal, verdict, 7, "skew")
    probes["frontier_skew"] = Probe(
        "frontier_skew",
        base,
        None,
        (
            _command(base, "RApplyDeltaBatch", deltas=[p, v]),
            _command(
                base,
                "RAdvanceFrontier",
                source_id="source:m3:a",
                low_watermark=10,
            ),
            _command(
                base,
                "RAdvanceFrontier",
                source_id="source:m3:b",
                low_watermark=5,
            ),
        ),
    )

    p1, v1 = _pair(base, proposal, verdict, 7, "partial-one")
    p2, v2 = _pair(base, proposal, verdict, 7, "partial-two")
    probes["two_pair_epoch"] = Probe(
        "two_pair_epoch",
        base,
        None,
        (
            _command(base, "RGrantDemand", batches=1),
            _command(base, "RApplyDeltaBatch", deltas=[p1, v1, p2, v2]),
            *_close(base, 8),
        ),
    )

    p, v = _pair(base, proposal, verdict, 7, "demand")
    probes["whole_batch_demand"] = Probe(
        "whole_batch_demand",
        base,
        None,
        (
            _command(base, "RApplyDeltaBatch", deltas=[p, v]),
            *_close(base, 8),
            _command(base, "RGrantDemand", batches=1),
        ),
    )

    max_open_profile = _profile_with_limits(base, max_open_epochs=1)
    p5, v5 = _pair(max_open_profile, proposal, verdict, 5, "open-five")
    p7, v7 = _pair(max_open_profile, proposal, verdict, 7, "open-seven")
    probes["max_open_overflow"] = Probe(
        "max_open_overflow",
        max_open_profile,
        None,
        (
            _command(
                max_open_profile,
                "RApplyDeltaBatch",
                deltas=[p5, v5, p7, v7],
            ),
        ),
    )

    late, _ = _pair(base, proposal, verdict, 7, "late")
    probes["per_source_late"] = Probe(
        "per_source_late",
        base,
        None,
        (
            _command(
                base,
                "RAdvanceFrontier",
                source_id="source:m3:a",
                low_watermark=10,
            ),
            _command(
                base,
                "RAdvanceFrontier",
                source_id="source:m3:b",
                low_watermark=5,
            ),
            _command(base, "RApplyDeltaBatch", deltas=[late]),
        ),
    )

    status_deltas: list[dict[str, Any]] = []
    for status in ("eligible", "ineligible", "conflicted"):
        p, v = _pair(
            base,
            proposal,
            verdict,
            7,
            f"all-status-transport-{status}",
            status=status,
        )
        status_deltas.extend((p, v))
    probes["all_status_transport"] = Probe(
        "all_status_transport",
        base,
        None,
        (
            _command(base, "RGrantDemand", batches=1),
            _command(base, "RApplyDeltaBatch", deltas=status_deltas),
            *_close(base, 8),
        ),
    )

    p, v = _pair(base, proposal, verdict, 7, "nested-preserve")
    probes["nested_value_preservation"] = Probe(
        "nested_value_preservation",
        base,
        None,
        (
            _command(base, "RGrantDemand", batches=1),
            _command(base, "RApplyDeltaBatch", deltas=[p, v]),
            *_close(base, 8),
        ),
    )

    p, v = _pair(base, proposal, verdict, 7, "nested-version")
    probes["nested_version_preservation"] = Probe(
        "nested_version_preservation",
        base,
        None,
        (
            _command(base, "RGrantDemand", batches=1),
            _command(base, "RApplyDeltaBatch", deltas=[p, v]),
            *_close(base, 8),
        ),
    )

    authority_status_deltas: list[dict[str, Any]] = []
    for status in ("eligible", "ineligible", "conflicted"):
        p, v = _pair(
            base,
            proposal,
            verdict,
            7,
            f"all-status-authority-{status}",
            status=status,
        )
        authority_status_deltas.extend((p, v))
    probes["all_status_authority_absence"] = Probe(
        "all_status_authority_absence",
        base,
        None,
        (
            _command(base, "RGrantDemand", batches=1),
            _command(base, "RApplyDeltaBatch", deltas=authority_status_deltas),
            *_close(base, 8),
        ),
    )

    if len(probes) != EXPECTED_AXIS_COUNT:
        raise AssertionError("probe closure drift")
    if any(len(probe.commands) > MAX_STEPS_PER_PROBE for probe in probes.values()):
        raise AssertionError("probe step bound exceeded")
    return probes


def _schema_validator() -> Draft202012Validator:
    resources = []
    for path in sorted((ROOT / "spec/schema").glob("*.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        if "$id" in schema:
            resources.append((schema["$id"], Resource.from_contents(schema)))
    registry = Registry().with_resources(resources)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(
        schema,
        registry=registry,
        format_checker=FormatChecker(),
    )


def _schema_valid(validator: Draft202012Validator, value: Any) -> bool:
    return next(validator.iter_errors(value), None) is None


def _instrument_exceptions(source: str) -> str:
    matches = source.count(EXCEPTION_ANCHOR)
    if matches != 1:
        raise LoadFailure("EXCEPTION_ANCHOR_MATCH_COUNT")
    return source.replace(EXCEPTION_ANCHOR, EXCEPTION_REPLACEMENT, 1)


def _load_mutant_step(
    source: str, label: str
) -> tuple[Callable[..., Any], Callable[[], None]]:
    instrumented = _instrument_exceptions(source)
    try:
        code = compile(
            instrumented,
            str(SOURCE_PATH),
            "exec",
            dont_inherit=True,
            optimize=0,
        )
    except BaseException as error:
        raise LoadFailure("COMPILE_ERROR") from error

    package_name = f"_flrh_m3_semantic_{label.replace('-', '_')}"
    module_name = package_name + ".reactive"
    package = types.ModuleType(package_name)
    package.__file__ = str(SOURCE_PATH.parent / "__init__.py")
    package.__package__ = package_name
    package.__path__ = [str(SOURCE_PATH.parent)]
    package_spec = importlib.machinery.ModuleSpec(
        package_name,
        loader=None,
        is_package=True,
    )
    package_spec.submodule_search_locations = [str(SOURCE_PATH.parent)]
    package.__spec__ = package_spec
    module = types.ModuleType(module_name)
    module.__file__ = str(SOURCE_PATH)
    module.__package__ = package_name
    module.__spec__ = importlib.machinery.ModuleSpec(module_name, loader=None)
    sys.modules[package_name] = package
    sys.modules[module_name] = module

    def cleanup() -> None:
        for key in tuple(sys.modules):
            if key == package_name or key.startswith(package_name + "."):
                sys.modules.pop(key, None)

    try:
        exec(code, module.__dict__)
    except BaseException as error:
        cleanup()
        raise LoadFailure("IMPORT_ERROR") from error
    step = getattr(module, "step_r", None)
    if not callable(step):
        cleanup()
        raise LoadFailure("IMPORT_ERROR")
    return step, cleanup


def _load_production_step() -> tuple[Callable[..., Any], Callable[[], None]]:
    """Load the uninstrumented package-root waist in the fresh baseline child."""

    package_prefix = "flrh_reactive"
    if any(
        key == package_prefix or key.startswith(package_prefix + ".")
        for key in sys.modules
    ):
        raise LoadFailure("PUBLIC_API_ALREADY_LOADED")
    source_root = str(ROOT / "src")
    sys.path.insert(0, source_root)

    def cleanup() -> None:
        for key in tuple(sys.modules):
            if key == package_prefix or key.startswith(package_prefix + "."):
                sys.modules.pop(key, None)
        try:
            sys.path.remove(source_root)
        except ValueError:
            pass

    try:
        package = importlib.import_module(package_prefix)
    except BaseException as error:
        cleanup()
        raise LoadFailure("PUBLIC_IMPORT_ERROR") from error
    if (
        Path(package.__file__).resolve() != (ROOT / "src/flrh_reactive/__init__.py")
        or getattr(package, "__all__", None) != ["step_r"]
    ):
        cleanup()
        raise LoadFailure("PUBLIC_API_DRIFT")
    step = getattr(package, "step_r", None)
    if not callable(step):
        cleanup()
        raise LoadFailure("PUBLIC_API_DRIFT")
    return step, cleanup


def _execute(
    step: Callable[..., Any],
    probe: Probe,
) -> list[dict[str, Any]]:
    state = copy.deepcopy(probe.prior_state)
    profile = copy.deepcopy(probe.profile)
    results: list[dict[str, Any]] = []
    for raw_command in probe.commands:
        command = copy.deepcopy(raw_command)
        result = step(state, profile, command)
        if not isinstance(result, dict):
            raise TypeError("step_r returned a non-object")
        results.append(result)
        if result.get("kind") == "RRejection":
            break
        if result.get("kind") != "RTransition" or not isinstance(
            result.get("next_state"), dict
        ):
            raise TypeError("step_r returned a malformed transition")
        state = copy.deepcopy(result["next_state"])
    return results


def _first_divergence(
    expected: Sequence[Mapping[str, Any]],
    actual: Sequence[Mapping[str, Any]],
) -> int | None:
    for index, (left, right) in enumerate(zip(expected, actual)):
        if left != right:
            return index
    if len(expected) != len(actual):
        return min(len(expected), len(actual))
    return None


def _expected_kind_at(
    expected: Sequence[Mapping[str, Any]],
    index: int | None,
) -> str | None:
    if index is None or index >= len(expected):
        return None
    value = expected[index].get("kind")
    return value if isinstance(value, str) else None


def _actual_kind_at(
    actual: Sequence[Mapping[str, Any]],
    index: int | None,
) -> str | None:
    if index is None or index >= len(actual):
        return None
    value = actual[index].get("kind")
    return value if isinstance(value, str) else None


def _mutant_receipt(
    mutation: Mutation,
    *,
    outcome: str,
    anchor_matches: int,
    step_count: int,
    divergence_step: int | None,
    expected_kind: str | None,
    actual_kind: str | None,
    result_schema_valid: bool | None,
    invalid_reason: str | None,
) -> dict[str, Any]:
    return {
        "kind": MUTANT_RECEIPT_KIND,
        "name": mutation.name,
        "axis": mutation.axis,
        "probe": mutation.probe_name,
        "outcome": outcome,
        "anchor_matches": anchor_matches,
        "step_count": step_count,
        "divergence_step": divergence_step,
        "expected_kind": expected_kind,
        "actual_kind": actual_kind,
        "result_schema_valid": result_schema_valid,
        "invalid_reason": invalid_reason,
    }


def _run_baseline_worker(expected_source_sha256: str) -> dict[str, Any]:
    if _sha256(SOURCE_PATH) != expected_source_sha256:
        return {
            "kind": BASELINE_RECEIPT_KIND,
            "status": "INVALID_BASELINE",
            "reason": "SOURCE_DRIFT",
            "source_sha256": _sha256(SOURCE_PATH),
            "probe_count": 0,
            "step_count": 0,
            "schema_document_count": 0,
        }
    probes = _build_probes()
    validator = _schema_validator()
    step_count = 0
    schema_document_count = 0
    try:
        step, cleanup = _load_production_step()
    except LoadFailure as error:
        return {
            "kind": BASELINE_RECEIPT_KIND,
            "status": "INVALID_BASELINE",
            "reason": error.phase,
            "source_sha256": expected_source_sha256,
            "probe_count": 0,
            "step_count": 0,
            "schema_document_count": 0,
        }
    try:
        for probe in probes.values():
            documents = [probe.profile, *probe.commands]
            if probe.prior_state is not None:
                documents.append(probe.prior_state)
            for document in documents:
                schema_document_count += 1
                if not _schema_valid(validator, document):
                    raise LoadFailure("BASELINE_INPUT_SCHEMA_INVALID")
                canonical_bytes(document)
            expected = run_sequence(
                copy.deepcopy(probe.prior_state),
                copy.deepcopy(probe.profile),
                copy.deepcopy(probe.commands),
            )
            actual = _execute(step, probe)
            step_count += len(actual)
            for result in [*expected, *actual]:
                schema_document_count += 1
                if not _schema_valid(validator, result):
                    raise LoadFailure("BASELINE_RESULT_SCHEMA_INVALID")
                canonical_bytes(result)
            if actual != expected:
                raise LoadFailure("BASELINE_ORACLE_MISMATCH")
    except LoadFailure as error:
        return {
            "kind": BASELINE_RECEIPT_KIND,
            "status": "INVALID_BASELINE",
            "reason": error.phase,
            "source_sha256": expected_source_sha256,
            "probe_count": len(probes),
            "step_count": step_count,
            "schema_document_count": schema_document_count,
        }
    except BaseException:
        return {
            "kind": BASELINE_RECEIPT_KIND,
            "status": "INVALID_BASELINE",
            "reason": "EXECUTION_EXCEPTION",
            "source_sha256": expected_source_sha256,
            "probe_count": len(probes),
            "step_count": step_count,
            "schema_document_count": schema_document_count,
        }
    finally:
        cleanup()
    return {
        "kind": BASELINE_RECEIPT_KIND,
        "status": "PASS",
        "reason": None,
        "source_sha256": expected_source_sha256,
        "probe_count": len(probes),
        "step_count": step_count,
        "schema_document_count": schema_document_count,
    }


def _run_mutant_worker(
    mutation: Mutation,
    expected_source_sha256: str,
) -> dict[str, Any]:
    current_source_sha256 = _sha256(SOURCE_PATH)
    probes = _build_probes()
    probe = probes[mutation.probe_name]
    expected = run_sequence(
        copy.deepcopy(probe.prior_state),
        copy.deepcopy(probe.profile),
        copy.deepcopy(probe.commands),
    )
    expected_final_kind = expected[-1]["kind"] if expected else None
    if current_source_sha256 != expected_source_sha256:
        return _mutant_receipt(
            mutation,
            outcome="INVALID_MUTANT",
            anchor_matches=0,
            step_count=0,
            divergence_step=None,
            expected_kind=expected_final_kind,
            actual_kind=None,
            result_schema_valid=None,
            invalid_reason="SOURCE_DRIFT",
        )
    source = SOURCE_PATH.read_text(encoding="utf-8")
    anchor_matches = source.count(mutation.anchor)
    if anchor_matches != 1:
        return _mutant_receipt(
            mutation,
            outcome="INVALID_MUTANT",
            anchor_matches=anchor_matches,
            step_count=0,
            divergence_step=None,
            expected_kind=expected_final_kind,
            actual_kind=None,
            result_schema_valid=None,
            invalid_reason="ANCHOR_MATCH_COUNT",
        )
    mutated_source = source.replace(mutation.anchor, mutation.replacement, 1)
    try:
        step, cleanup = _load_mutant_step(mutated_source, mutation.name)
    except LoadFailure as error:
        return _mutant_receipt(
            mutation,
            outcome="INVALID_MUTANT",
            anchor_matches=anchor_matches,
            step_count=0,
            divergence_step=None,
            expected_kind=expected_final_kind,
            actual_kind=None,
            result_schema_valid=None,
            invalid_reason=error.phase,
        )
    try:
        actual = _execute(step, probe)
    except BaseException:
        return _mutant_receipt(
            mutation,
            outcome="INVALID_MUTANT",
            anchor_matches=anchor_matches,
            step_count=0,
            divergence_step=None,
            expected_kind=expected_final_kind,
            actual_kind=None,
            result_schema_valid=None,
            invalid_reason="EXECUTION_EXCEPTION",
        )
    finally:
        cleanup()
    try:
        validator = _schema_validator()
        result_schema_valid = all(_schema_valid(validator, item) for item in actual)
        for item in actual:
            canonical_bytes(item)
    except BaseException:
        return _mutant_receipt(
            mutation,
            outcome="INVALID_MUTANT",
            anchor_matches=anchor_matches,
            step_count=len(actual),
            divergence_step=None,
            expected_kind=expected_final_kind,
            actual_kind=None,
            result_schema_valid=None,
            invalid_reason="RESULT_INSPECTION_EXCEPTION",
        )
    divergence = _first_divergence(expected, actual)
    outcome = "KILLED" if divergence is not None else "ESCAPED"
    return _mutant_receipt(
        mutation,
        outcome=outcome,
        anchor_matches=anchor_matches,
        step_count=len(actual),
        divergence_step=divergence,
        expected_kind=_expected_kind_at(expected, divergence),
        actual_kind=_actual_kind_at(actual, divergence),
        result_schema_valid=result_schema_valid,
        invalid_reason=None,
    )


def _emit(value: Mapping[str, Any]) -> None:
    sys.stdout.buffer.write(canonical_bytes(value) + b"\n")


def _child_main(arguments: Sequence[str]) -> int:
    try:
        if len(arguments) == 2 and arguments[0] == "--baseline":
            _emit(_run_baseline_worker(arguments[1]))
            return 0
        if len(arguments) == 3 and arguments[0] == "--worker":
            mutation = next(item for item in MUTATIONS if item.name == arguments[1])
            _emit(_run_mutant_worker(mutation, arguments[2]))
            return 0
    except BaseException:
        if arguments and arguments[0] == "--worker" and len(arguments) >= 2:
            mutation = next(
                (item for item in MUTATIONS if item.name == arguments[1]),
                MUTATIONS[0],
            )
            _emit(
                _mutant_receipt(
                    mutation,
                    outcome="INVALID_MUTANT",
                    anchor_matches=0,
                    step_count=0,
                    divergence_step=None,
                    expected_kind=None,
                    actual_kind=None,
                    result_schema_valid=None,
                    invalid_reason="WORKER_EXCEPTION",
                )
            )
            return 0
        _emit(
            {
                "kind": BASELINE_RECEIPT_KIND,
                "status": "INVALID_BASELINE",
                "reason": "WORKER_EXCEPTION",
                "source_sha256": None,
                "probe_count": 0,
                "step_count": 0,
                "schema_document_count": 0,
            }
        )
        return 0
    _emit({"kind": "M3SemanticWorkerError", "status": "INVALID_ARGUMENTS"})
    return 2


def _parse_child_output(raw: bytes) -> dict[str, Any] | None:
    if not raw.endswith(b"\n") or raw.count(b"\n") != 1:
        return None
    payload = raw[:-1]
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or canonical_bytes(value) != payload:
        return None
    return value


def _invoke_child(arguments: Sequence[str]) -> tuple[dict[str, Any] | None, str | None]:
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        completed = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve()), *arguments],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=PER_MUTANT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT"
    if completed.returncode != 0:
        return None, "WORKER_NONZERO"
    if completed.stderr != b"":
        return None, "WORKER_STDERR"
    parsed = _parse_child_output(completed.stdout)
    if parsed is None:
        return None, "WORKER_PROTOCOL"
    return parsed, None


def _closed_invalid_receipt(
    mutation: Mutation,
    anchor_matches: int,
    reason: str,
) -> dict[str, Any]:
    return _mutant_receipt(
        mutation,
        outcome="INVALID_MUTANT",
        anchor_matches=anchor_matches,
        step_count=0,
        divergence_step=None,
        expected_kind=None,
        actual_kind=None,
        result_schema_valid=None,
        invalid_reason=reason,
    )


def _main_report() -> tuple[dict[str, Any], int]:
    if len(MUTATIONS) != EXPECTED_AXIS_COUNT:
        raise AssertionError("mutation axis closure drift")
    if len({item.name for item in MUTATIONS}) != len(MUTATIONS):
        raise AssertionError("duplicate mutation name")
    if len({item.axis for item in MUTATIONS}) != len(MUTATIONS):
        raise AssertionError("duplicate mutation axis")
    oracle_source = ORACLE_PATH.read_text(encoding="utf-8")
    if "import flrh_reactive" in oracle_source:
        raise AssertionError("oracle imports production")
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if COMPLETION_GATE_CLAUSE not in contract.get("completion_gate", []):
        raise AssertionError("completion gate mutation clause drift")

    source = SOURCE_PATH.read_text(encoding="utf-8")
    source_sha256 = _sha256(SOURCE_PATH)
    baseline, baseline_error = _invoke_child(["--baseline", source_sha256])
    baseline_valid = (
        baseline_error is None
        and isinstance(baseline, dict)
        and baseline.get("kind") == BASELINE_RECEIPT_KIND
        and baseline.get("status") == "PASS"
        and baseline.get("source_sha256") == source_sha256
    )

    receipts: list[dict[str, Any]] = []
    if baseline_valid:
        for mutation in MUTATIONS:
            anchor_matches = source.count(mutation.anchor)
            if anchor_matches != 1:
                receipts.append(
                    _closed_invalid_receipt(
                        mutation,
                        anchor_matches,
                        "ANCHOR_MATCH_COUNT",
                    )
                )
                continue
            receipt, worker_error = _invoke_child(
                ["--worker", mutation.name, source_sha256]
            )
            required_keys = {
                "kind",
                "name",
                "axis",
                "probe",
                "outcome",
                "anchor_matches",
                "step_count",
                "divergence_step",
                "expected_kind",
                "actual_kind",
                "result_schema_valid",
                "invalid_reason",
            }
            if (
                worker_error is not None
                or not isinstance(receipt, dict)
                or set(receipt) != required_keys
                or receipt.get("kind") != MUTANT_RECEIPT_KIND
                or receipt.get("name") != mutation.name
                or receipt.get("axis") != mutation.axis
                or receipt.get("probe") != mutation.probe_name
                or receipt.get("outcome")
                not in {"KILLED", "ESCAPED", "INVALID_MUTANT"}
            ):
                receipts.append(
                    _closed_invalid_receipt(
                        mutation,
                        anchor_matches,
                        worker_error or "WORKER_PROTOCOL",
                    )
                )
            else:
                receipts.append(receipt)

    source_stable = _sha256(SOURCE_PATH) == source_sha256
    killed = sum(item["outcome"] == "KILLED" for item in receipts)
    escaped = sum(item["outcome"] == "ESCAPED" for item in receipts)
    invalid = sum(item["outcome"] == "INVALID_MUTANT" for item in receipts)
    passed = (
        baseline_valid
        and source_stable
        and len(receipts) == len(MUTATIONS)
        and killed == len(MUTATIONS)
        and escaped == 0
        and invalid == 0
    )
    report = {
        "kind": REPORT_KIND,
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "source": "src/flrh_reactive/reactive.py",
        "source_sha256": source_sha256,
        "source_stable": source_stable,
        "contract": "spec/m3-reactive-contract.v1.json",
        "contract_sha256": _sha256(CONTRACT_PATH),
        "wire_schema": "spec/schema/m3-reactive.v1.schema.json",
        "wire_schema_sha256": _sha256(SCHEMA_PATH),
        "oracle": "scripts/m3_oracle.py",
        "oracle_sha256": _sha256(ORACLE_PATH),
        "oracle_independent": True,
        "completion_gate_axis_count": EXPECTED_AXIS_COUNT,
        "per_mutant_timeout_seconds": PER_MUTANT_TIMEOUT_SECONDS,
        "baseline": baseline
        if baseline is not None
        else {
            "kind": BASELINE_RECEIPT_KIND,
            "status": "INVALID_BASELINE",
            "reason": baseline_error or "WORKER_PROTOCOL",
            "source_sha256": source_sha256,
            "probe_count": 0,
            "step_count": 0,
            "schema_document_count": 0,
        },
        "mutant_count": len(MUTATIONS),
        "killed_count": killed,
        "escaped_count": escaped,
        "invalid_mutant_count": invalid,
        "mutants": receipts,
    }
    return report, 0 if passed else 1


def main() -> int:
    sys.dont_write_bytecode = True
    if len(sys.argv) > 1:
        return _child_main(sys.argv[1:])
    try:
        report, returncode = _main_report()
    except BaseException:
        report = {
            "kind": REPORT_KIND,
            "schema_version": REPORT_SCHEMA_VERSION,
            "status": "FAIL",
            "source": "src/flrh_reactive/reactive.py",
            "failure": "RUNNER_EXCEPTION",
            "mutant_count": len(MUTATIONS),
            "killed_count": 0,
            "escaped_count": 0,
            "invalid_mutant_count": len(MUTATIONS),
            "mutants": [],
        }
        returncode = 1
    _emit(report)
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
