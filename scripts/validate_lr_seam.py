#!/usr/bin/env python3
"""Aggregate admission gate for the proposed direct L-to-R reference seam."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

import jsonschema
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[1]
JSONSCHEMA_SITE_PACKAGES = str(Path(jsonschema.__file__).resolve().parents[1])
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from check_lr_seam_ambient import _build_success_documents
from check_lr_seam_semantic_mutants import _publication
from flrh_lr_seam import project_lr
from lr_seam_fixtures import (
    canonical_bytes,
    load_cases,
    materialize_proposal,
    materialize_query,
    materialize_query_batch,
    materialize_requirement,
)
from lr_seam_oracle import project_expected


PROPOSED_STATUS = "PROPOSED_PENDING_MEASUREMENT"
MEASURED_STATUS = "MEASURED_REFERENCE_CONFORMANCE"
EXPECTED_PUBLIC_EXPORT = "flrh_lr_seam.project_lr"
INHERITED_GATES = (
    "scripts/validate_m0.py", "scripts/validate_m1.py",
    "scripts/validate_m2.py", "scripts/validate_m3.py",
)
CLEAN_PROFILES = (
    {"label": "clean-a", "hash_seed": "41", "timezone": "UTC"},
    {"label": "clean-b", "hash_seed": "97", "timezone": "Asia/Seoul"},
)
CLEAN_PROCESS_KINDS = ("replay", "ambient", "semantic")
EXPECTED_TOOLS = (
    "scripts/lr_seam_fixtures.py", "scripts/lr_seam_oracle.py",
    "scripts/run_lr_seam_replay.py", "scripts/lr_seam_guard.py",
    "scripts/check_lr_seam_ambient.py",
    "scripts/check_lr_seam_semantic_mutants.py",
    "scripts/validate_lr_seam.py", "tests/test_lr_seam.py",
    "scripts/validate_m0.py", "scripts/validate_m1.py",
    "scripts/validate_m2.py", "scripts/validate_m3.py",
)
FORBIDDEN_OUTPUT_KEYS = frozenset(
    {"effect_intent", "effect_intents", "authority", "approval", "capability",
     "frontier", "frontiers", "demand", "backpressure", "checkpoint", "receipt"}
)
ARGUMENT_KEYS = (
    "l_result", "rule_bundle", "r_profile", "binding_profile", "query_batch"
)
LR_ADMISSION_EVIDENCE = (
    "spec/lr-seam-contract.v1.json",
    "spec/lr-seam-manifest.v1.json",
    "fixtures/lr-seam/cases.json",
    "fixtures/lr-seam/golden/eligible.projection.json",
    "fixtures/lr-seam/golden/mismatch.rejection.json",
    "scripts/lr_seam_oracle.py",
    "scripts/check_lr_seam_semantic_mutants.py",
    "scripts/validate_lr_seam.py",
    "tests/test_lr_seam.py",
    "docs/LR_SEAM.md",
)
MEASURED_PROMOTION_SURFACES = {
    "README.md": "DIRECT L-R PROJECTION MEASURED",
    "docs/ARCHITECTURE.md": "DIRECT L-R PROJECTION MEASURED",
    "docs/CLAIMS_AND_STATUS.md": (
        "| one stateless direct L-to-R projection can bind explicit proposal "
        "preconditions to exact four-valued M2 fact states and produce paired "
        "M3 proposal/verdict deltas | MEASURED |"
    ),
    "docs/ROADMAP.md": "## M3-LR adjunct — Direct L-to-R projection ✅ MEASURED",
    "docs/SEMANTICS.md": "DIRECT L-R PROJECTION MEASURED",
    "docs/LR_SEAM.md": "> Status: **MEASURED_REFERENCE_CONFORMANCE**.",
    "docs/adr/0001-defer-engine-verdict.md": (
        "DIRECT L-R PROJECTION MEASURED; ENGINE VERDICT DEFERRED"
    ),
    "spec/engine-decision.v1.json": (
        "Direct L-to-R projection is measured while the engine verdict remains defer"
    ),
}
MEASURED_PROMOTION_LINES = {
    "README.md": (
        "> Status: **RESEARCH INCUBATOR / SEPARATE M1 PURE-F + M2 STRATIFIED-L "
        "+ M3 SCALAR-FRONTIER-R REFERENCES MEASURED / DIRECT L-R PROJECTION "
        "MEASURED / NO INTEGRATED RUNTIME / EFFICACY UNJUDGED**"
    ),
    "docs/ARCHITECTURE.md": (
        "> Status: SEPARATE M1 PURE-F + M2 STRATIFIED-L + M3 "
        "SCALAR-FRONTIER-R REFERENCE MECHANICS MEASURED / DIRECT L-R "
        "PROJECTION MEASURED / H NOT IMPLEMENTED"
    ),
    "docs/SEMANTICS.md": (
        "> Status: SEPARATE M1 PURE-F + M2 STRATIFIED-L + M3 "
        "SCALAR-FRONTIER-R REFERENCE MECHANICS MEASURED / DIRECT L-R "
        "PROJECTION MEASURED / H NOT IMPLEMENTED / NOT EXTERNAL CANON"
    ),
    "docs/LR_SEAM.md": "> Status: **MEASURED_REFERENCE_CONFORMANCE**.",
}
MEASURED_PROMOTION_REQUIRED_FRAGMENTS = {
    "README.md": (
        "# Agent Coding Paradigm",
        "## Current admission gate",
        "## Non-claims",
    ),
    "docs/ARCHITECTURE.md": (
        "# Architecture",
        "## System boundary",
        "## Authority and single writers",
        "## Security stance",
    ),
    "docs/CLAIMS_AND_STATUS.md": (
        "# Claims and Status",
        "## Falsifiers",
        "## Residual risks",
        "## Exclusion",
    ),
    "docs/ROADMAP.md": (
        "# Roadmap",
        "## M0 — Freeze vocabulary and contracts",
        "## M4 — Durable H control shell",
        "## Immediate next slice",
    ),
    "docs/SEMANTICS.md": (
        "# FLR-H Execution Semantics v0",
        "## F — functional semantics",
        "## L — logic semantics",
        "## R — reactive semantics",
        "## H — control semantics",
        "## Version envelope",
    ),
    "docs/LR_SEAM.md": (
        "# Direct L-to-R Projection Seam",
        "## Explicit binding",
        "## Output boundary",
        "## Measurement gate",
        "## Non-claims",
    ),
}
STALE_LR_PROMOTION_FRAGMENTS = {
    "README.md": "DIRECT L-R PROJECTION PROPOSED",
    "docs/ARCHITECTURE.md": "DIRECT L-R PROJECTION PROPOSED",
    "docs/CLAIMS_AND_STATUS.md": (
        "| one stateless direct L-to-R projection can bind explicit proposal "
        "preconditions to exact four-valued M2 fact states and produce paired "
        "M3 proposal/verdict deltas | PROPOSED |"
    ),
    "docs/ROADMAP.md": "## M3-LR adjunct — Direct L-to-R projection ⏳ PROPOSED",
    "docs/SEMANTICS.md": "DIRECT L-R PROJECTION PROPOSED",
    "docs/LR_SEAM.md": "> Status: **PROPOSED_PENDING_MEASUREMENT**.",
    "spec/engine-decision.v1.json": "bind the direct L-to-R seam",
}
STRICT_CI_STEPS = (
    "python scripts/validate_m0.py",
    "python scripts/validate_m1.py",
    "python scripts/validate_m2.py",
    "python scripts/validate_m3.py",
    "python scripts/validate_lr_seam.py",
    "python -m unittest discover -s tests -v",
)
PROPOSED_CI_STEPS = (
    *STRICT_CI_STEPS[:4],
    "python scripts/validate_lr_seam.py --allow-proposed",
    STRICT_CI_STEPS[-1],
)
LR_PROMOTION_PATHS = (
    "README.md",
    "docs/ARCHITECTURE.md",
    "docs/CLAIMS_AND_STATUS.md",
    "docs/ROADMAP.md",
    "docs/SEMANTICS.md",
    "docs/LR_SEAM.md",
    "docs/adr/0001-defer-engine-verdict.md",
    "spec/engine-decision.v1.json",
    ".github/workflows/ci.yml",
    "spec/lr-seam-contract.v1.json",
    "spec/lr-seam-manifest.v1.json",
    "spec/claims.v1.json",
)
PROPOSED_PROMOTION_SHA256 = {
    "README.md": "sha256:801e2d95adb2e463a7d506c1fe18c5063c010adf4cbda2a603bcae18d6359f35",
    "docs/ARCHITECTURE.md": "sha256:6a5734abeec39b7607519e7a3ace91c89a6322bd47d97e3ae819c148d7200ed7",
    "docs/CLAIMS_AND_STATUS.md": "sha256:53ef53d0ec7f2d5ecdf1ae67ca4cdeb56a96c1a866dd99d72efd109facc8b946",
    "docs/ROADMAP.md": "sha256:9c757531a4309ce7d797a5f447f617254b8a2834c4614e199e3fc12281625ad1",
    "docs/SEMANTICS.md": "sha256:ec28119f4e4a60c46536106c10dc5915a35e38d69b649962b9e0174848da5fa9",
    "docs/LR_SEAM.md": "sha256:a697020b334a5025f794d2efdccfa3fc1bff9f68c6b2afef339e62ffc1df97e7",
    "docs/adr/0001-defer-engine-verdict.md": "sha256:19b0b1227323d8b7e6ddf008b53e9b21ffa0345255d4a79c293da01a2d3a5d7d",
    "spec/engine-decision.v1.json": "sha256:38d8149732d9f9258c89e1c141c926bbbc9f543835250b8a1eeafc4b7f792edb",
    ".github/workflows/ci.yml": "sha256:a7865d541bae7e1003efcc57b5df3442c6a321f3de12fc57feb17fa77c6f10d7",
    "spec/lr-seam-contract.v1.json": "sha256:9182eb695545decb92f2423c5ba7b1be2a426b508d90af41776c89d232a05c99",
    "spec/lr-seam-manifest.v1.json": "sha256:f2979c5907f24b2d1e9ac31489256c6107b0d44bfdb0f4994afec63d744ae9d5",
    "spec/claims.v1.json": "sha256:a956711d2c93ea4c27de95de472fd09f4140257398d9c877ece631288138040b",
}
MEASURED_PROMOTION_SHA256 = {
    "README.md": "sha256:2db649295835e9b107fc5e44d98f38c08c2cfcca13fcfff0c1969c620d2002ea",
    "docs/ARCHITECTURE.md": "sha256:94eded60e4198c2026ef1e7388b6b92560fc11d5d2716a1d7e5ef43c7e006c08",
    "docs/CLAIMS_AND_STATUS.md": "sha256:8278753c50d7941c800d9774dfe55079ebb324667cf439aa7f234dfe17664aa7",
    "docs/ROADMAP.md": "sha256:1c9b9e4b7cd65240d3a26cbd90f592cf24aef654ad8c4d15996eec1951f36504",
    "docs/SEMANTICS.md": "sha256:b54be50a202635fe392b4e8d8283996e44325c67f35563902211843abb8efe26",
    "docs/LR_SEAM.md": "sha256:8d5a67c8ddca1ac0d31ed72fa1aeb2afb9c2a4b54daf516946b22506bc32c413",
    "docs/adr/0001-defer-engine-verdict.md": "sha256:c2ea82105737c2b62af32128e802c73d92323999ca8bd02e4c11ff0bc667e284",
    "spec/engine-decision.v1.json": "sha256:14c50ee2fddb5f0788e80ae5a43aa184a454a19ccb8241f4cb76d1b33e4ef32d",
    ".github/workflows/ci.yml": "sha256:31456c64cbca63fa502ea94875f6596c556b83027504273520ff845d2783819e",
    "spec/lr-seam-contract.v1.json": "sha256:64e89e638231cdc3fb0616fc64765aa12f89f1cca7488327268ec84e75bc3bff",
    "spec/lr-seam-manifest.v1.json": "sha256:ad82acbdf5d7204cd6f7bc481f6003de9bdfba6741fb0030b769c6db4c370dca",
    "spec/claims.v1.json": "sha256:9e3ed5e8f600c41f846752c598be3e208ee8d4ab99be60d6b0b0d4f1b3397633",
}
LR_RECEIPT_RELATIVE = "research/LR_SEAM_VALIDATION_2026-08-09.md"
LR_RECEIPT_ANCHOR_LINE = (
    "- [M3 validation receipt](research/M3_VALIDATION_2026-08-09.md) — frozen "
    "subject tree, scalar-frontier digests, clean-process and semantic-mutation "
    "gates, and exact CI readback"
)
LR_RECEIPT_LINK_LINE = (
    "- [Direct L-to-R seam validation receipt](research/LR_SEAM_VALIDATION_2026-08-09.md) "
    "— frozen measured subject, local evidence, and exact CI readback"
)
EXPECTED_MEASURED_GATE_REPORT = {
    "ambient_paths": 10,
    "clean_process_descriptors": [
        "replay:clean-a", "replay:clean-b",
        "ambient:clean-a", "ambient:clean-b",
        "semantic:clean-a", "semantic:clean-b",
    ],
    "clean_processes": 6,
    "inherited_nonregression_gates": 4,
    "lr_conformance_test_gate": 1,
    "manifest_artifacts": 34,
    "oracle_comparisons": 8,
    "public_step_r_publication_chains": 8,
    "rejection_paths": 24,
    "semantic_axes": 14,
    "status": MEASURED_STATUS,
    "success_paths": 8,
}
LR_RECEIPT_KEYS = frozenset({
    "schema_version",
    "candidate_commit", "candidate_tree",
    "measured_commit", "measured_tree",
    "candidate_validator_sha256", "measured_validator_sha256",
    "candidate_ci_run_id", "candidate_ci_head_sha", "candidate_ci_conclusion",
    "measured_ci_run_id", "measured_ci_head_sha", "measured_ci_conclusion",
    "promotion_paths", "admission_evidence", "gate_report",
})


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load_json(relative: str) -> Any:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def sha256_file(relative: str) -> str:
    return "sha256:" + hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def registry() -> Registry:
    resources = []
    for path in sorted((ROOT / "spec/schema").glob("*.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        if "$id" in schema:
            resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def validate(instance: Any, schema: dict[str, Any], schemas: Registry) -> None:
    errors = sorted(
        Draft202012Validator(
            schema, registry=schemas, format_checker=FormatChecker()
        ).iter_errors(instance),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        error = errors[0]
        path = "/" + "/".join(str(item) for item in error.absolute_path)
        raise AssertionError(f"schema rejection at {path}: {error.message}")


def _run_gate(relative: str) -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / relative)], cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    require(
        completed.returncode == 0,
        f"inherited gate failed: {relative}: {completed.stderr or completed.stdout}",
    )


def _clean_environment(home: Path, temporary: Path, profile: Mapping[str, str], poison: str):
    environment = {
        "FLRH_LR_PROCESS_POISON": poison,
        "HOME": str(home), "LANG": "C", "LC_ALL": "C", "PATH": os.defpath,
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": profile["hash_seed"],
        "PYTHONPATH": os.pathsep.join(
            (str(ROOT / "src"), str(ROOT / "scripts"), JSONSCHEMA_SITE_PACKAGES)
        ),
        "TMPDIR": str(temporary), "TZ": profile["timezone"],
    }
    if "SystemRoot" in os.environ:
        environment["SystemRoot"] = os.environ["SystemRoot"]
    return environment


def _parse_canonical_line(raw: bytes, label: str) -> Any:
    require(raw.endswith(b"\n"), f"{label} stdout lacks one terminal newline")
    require(raw.count(b"\n") == 1, f"{label} emitted multiple stdout lines")
    payload = raw[:-1]
    require(bool(payload), f"{label} emitted empty stdout")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AssertionError(f"{label} emitted invalid UTF-8 JSON: {error}") from error
    require(canonical_bytes(value) == payload, f"{label} stdout is not canonical")
    return value


def _run_clean_pair(relative: str, *, stdin: bytes, descriptor: str) -> Any:
    stdout_values: list[bytes] = []
    stderr_values: list[bytes] = []
    parsed = []
    roots: set[str] = set()
    for profile in CLEAN_PROFILES:
        with tempfile.TemporaryDirectory(prefix=f"flrh-lr-{descriptor}-{profile['label']}-") as raw:
            root = Path(raw)
            require(str(root) not in roots, f"{descriptor} reused clean root")
            roots.add(str(root))
            cwd, home, temporary = root / "cwd", root / "home", root / "tmp"
            cwd.mkdir(); home.mkdir(); temporary.mkdir()
            completed = subprocess.run(
                [sys.executable, "-B", str(ROOT / relative)], cwd=cwd,
                env=_clean_environment(home, temporary, profile,
                                       f"{descriptor}:{profile['label']}"),
                input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=60,
            )
            require(
                completed.returncode == 0,
                f"{descriptor} {profile['label']} failed: "
                f"{completed.stderr.decode('utf-8', 'replace') or completed.stdout.decode('utf-8', 'replace')}",
            )
            stdout_values.append(completed.stdout)
            stderr_values.append(completed.stderr)
            parsed.append(_parse_canonical_line(completed.stdout, f"{descriptor} {profile['label']}"))
    require(stdout_values[0] == stdout_values[1], f"{descriptor} stdout bytes drifted")
    require(stderr_values[0] == stderr_values[1] == b"", f"{descriptor} stderr bytes drifted")
    require(parsed[0] == parsed[1], f"{descriptor} parsed reports drifted")
    return parsed[0]


def _walk_forbidden(value: Any, path: str = "") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            require(key not in FORBIDDEN_OUTPUT_KEYS,
                    f"forbidden H/frontier/demand output at {path}/{key}")
            _walk_forbidden(item, f"{path}/{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_forbidden(item, f"{path}/{index}")


def _project(document: Mapping[str, Any]) -> dict[str, Any]:
    before = copy.deepcopy(document)
    result = project_lr(*(document[key] for key in ARGUMENT_KEYS))
    require(document == before, "public project_lr mutated caller inputs")
    require(isinstance(result, dict), "public project_lr did not return one object")
    _walk_forbidden(result)
    return result


def _mismatch_document(document: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(document)
    atom = next(
        item["atom"] for item in result["l_result"]["next_materialization"]["fact_states"]
        if item["state"] == "TRUE_ONLY"
    )
    requirement = materialize_requirement("precondition:golden:fact", atom)
    proposal = materialize_proposal(
        "golden-mismatch",
        ["precondition:golden:fact", "precondition:golden:orphan"],
    )
    mismatched_query = materialize_query(proposal, [requirement])
    result["query_batch"] = materialize_query_batch(
        binding_profile=result["binding_profile"], l_result=result["l_result"],
        rule_bundle=result["rule_bundle"], r_profile=result["r_profile"],
        queries=[mismatched_query],
    )
    return result


def _promotion_artifact_drift(label: str, relative: str) -> None:
    raise AssertionError(f"{label} LR promotion artifact drift: {relative}")


def _read_promotion_bytes(root: Path, relative: str, label: str) -> tuple[bytes, str]:
    """Read one governed file without newline normalization."""
    path = root / relative
    if path.is_symlink() or not path.is_file():
        _promotion_artifact_drift(label, relative)
    raw = path.read_bytes()
    if b"\r" in raw or not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
        _promotion_artifact_drift(label, relative)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        _promotion_artifact_drift(label, relative)
    return raw, text


def _receipt_drift() -> None:
    raise AssertionError("measured LR promotion receipt drift")


def _exact_json_equal(left: Any, right: Any) -> bool:
    """Compare JSON-shaped values without Python's bool/int coercions."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return (
            left.keys() == right.keys()
            and all(_exact_json_equal(left[key], right[key]) for key in left)
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _exact_json_equal(left_item, right_item)
            for left_item, right_item in zip(left, right)
        )
    return left == right


def _parse_lr_receipt(raw: bytes) -> dict[str, Any]:
    if b"\r" in raw or not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
        _receipt_drift()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        _receipt_drift()
    match = re.fullmatch(
        r"# Direct L-to-R Seam Validation Receipt\n\n"
        r"This follow-up receipt freezes the measured subject and exact CI readback\.\n\n"
        r"## Machine-readable receipt\n\n"
        r"```json\n([^\n]+)\n```\n",
        text,
    )
    if match is None:
        _receipt_drift()
    payload_text = match.group(1)
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        _receipt_drift()
    if not isinstance(payload, dict) or set(payload) != LR_RECEIPT_KEYS:
        _receipt_drift()
    canonical = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    if payload_text != canonical:
        _receipt_drift()
    if payload.get("schema_version") != "lr-seam-validation-receipt/v1":
        _receipt_drift()
    for key in (
        "candidate_commit", "candidate_tree", "measured_commit", "measured_tree"
    ):
        if not isinstance(payload.get(key), str) or re.fullmatch(
            r"[0-9a-f]{40}", payload[key]
        ) is None:
            _receipt_drift()
    if payload["candidate_commit"] == payload["measured_commit"]:
        _receipt_drift()
    for key in ("candidate_validator_sha256", "measured_validator_sha256"):
        if not isinstance(payload.get(key), str) or re.fullmatch(
            r"[0-9a-f]{64}", payload[key]
        ) is None:
            _receipt_drift()
    if payload["candidate_validator_sha256"] != payload["measured_validator_sha256"]:
        _receipt_drift()
    for prefix in ("candidate", "measured"):
        run_id = payload.get(f"{prefix}_ci_run_id")
        if not isinstance(run_id, str) or re.fullmatch(r"[1-9][0-9]*", run_id) is None:
            _receipt_drift()
        if payload.get(f"{prefix}_ci_head_sha") != payload[f"{prefix}_commit"]:
            _receipt_drift()
        if payload.get(f"{prefix}_ci_conclusion") != "success":
            _receipt_drift()
    if payload["candidate_ci_run_id"] == payload["measured_ci_run_id"]:
        _receipt_drift()
    if payload.get("promotion_paths") != list(LR_PROMOTION_PATHS):
        _receipt_drift()
    if payload.get("admission_evidence") != list(LR_ADMISSION_EVIDENCE):
        _receipt_drift()
    if not _exact_json_equal(
        payload.get("gate_report"), EXPECTED_MEASURED_GATE_REPORT
    ):
        _receipt_drift()
    return payload


def _git_output(root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", *arguments], cwd=root, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False,
    )
    if completed.returncode != 0:
        raise AssertionError("measured LR promotion receipt git drift")
    return completed.stdout


def _git_changed_records(
    root: Path, before: str, after: str
) -> list[tuple[str, str]]:
    raw = _git_output(
        root, "diff", "--name-status", "-z", "--no-renames",
        before, after, "--",
    )
    fields = raw.split(b"\0")
    if not fields or fields[-1] != b"":
        raise AssertionError
    fields.pop()
    if len(fields) % 2:
        raise AssertionError
    records: list[tuple[str, str]] = []
    for offset in range(0, len(fields), 2):
        status = fields[offset].decode("ascii")
        path = fields[offset + 1].decode("utf-8")
        records.append((status, path))
    return records


def _git_regular_blob(root: Path, revision: str, relative: str) -> bytes:
    raw = _git_output(
        root, "ls-tree", "-z", "--full-tree", revision, "--", relative
    )
    records = raw.split(b"\0")
    if len(records) != 2 or records[1] != b"" or b"\t" not in records[0]:
        raise AssertionError
    metadata, encoded_path = records[0].split(b"\t", 1)
    fields = metadata.split()
    if len(fields) != 3 or fields[0] != b"100644" or fields[1] != b"blob":
        raise AssertionError
    if encoded_path.decode("utf-8") != relative:
        raise AssertionError
    object_id = fields[2].decode("ascii")
    return _git_output(root, "cat-file", "blob", object_id)


def _validate_historical_promotion_blobs(
    root: Path, revision: str, expected: Mapping[str, str]
) -> None:
    if tuple(expected) != LR_PROMOTION_PATHS:
        raise AssertionError
    for relative in LR_PROMOTION_PATHS:
        raw = _git_regular_blob(root, revision, relative)
        actual = "sha256:" + hashlib.sha256(raw).hexdigest()
        if actual != expected[relative]:
            raise AssertionError


def _require_no_published_receipt_ancestor(root: Path) -> None:
    shallow = _git_output(root, "rev-parse", "--is-shallow-repository")
    if shallow.strip() != b"false":
        raise AssertionError("measured LR promotion receipt git drift")
    history = _git_output(
        root, "rev-list", "HEAD", "--", LR_RECEIPT_RELATIVE
    )
    if history.strip():
        raise AssertionError("measured LR promotion receipt git drift")


def _validate_lr_receipt_git(root: Path, receipt: Mapping[str, Any]) -> None:
    """Bind the follow-up receipt to one exact candidate -> measured -> receipt DAG."""
    try:
        head = _git_output(root, "rev-parse", "HEAD").decode("ascii").strip()
        measured = _git_output(root, "rev-parse", "HEAD^").decode("ascii").strip()
        candidate = _git_output(root, "rev-parse", "HEAD^^").decode("ascii").strip()
        head_parents = _git_output(
            root, "rev-list", "--parents", "-n", "1", head
        ).decode("ascii").split()
        measured_parents = _git_output(
            root, "rev-list", "--parents", "-n", "1", measured
        ).decode("ascii").split()
        if head_parents != [head, measured] or measured_parents != [measured, candidate]:
            raise AssertionError
        if receipt["candidate_commit"] != candidate or receipt["measured_commit"] != measured:
            raise AssertionError
        if receipt["candidate_tree"] != _git_output(
            root, "rev-parse", f"{candidate}^{{tree}}"
        ).decode("ascii").strip():
            raise AssertionError
        if receipt["measured_tree"] != _git_output(
            root, "rev-parse", f"{measured}^{{tree}}"
        ).decode("ascii").strip():
            raise AssertionError
        candidate_to_measured = _git_changed_records(
            root, candidate, measured
        )
        if (
            len(candidate_to_measured) != len(LR_PROMOTION_PATHS)
            or set(candidate_to_measured)
            != {("M", relative) for relative in LR_PROMOTION_PATHS}
        ):
            raise AssertionError
        measured_to_receipt = _git_changed_records(root, measured, head)
        if (
            len(measured_to_receipt) != 2
            or set(measured_to_receipt)
            != {("M", "README.md"), ("A", LR_RECEIPT_RELATIVE)}
        ):
            raise AssertionError
        _validate_historical_promotion_blobs(
            root, candidate, PROPOSED_PROMOTION_SHA256
        )
        _validate_historical_promotion_blobs(
            root, measured, MEASURED_PROMOTION_SHA256
        )
        for revision in (candidate, measured):
            absent = subprocess.run(
                ["git", "cat-file", "-e", f"{revision}:{LR_RECEIPT_RELATIVE}"],
                cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            )
            if absent.returncode == 0:
                raise AssertionError
        receipt_tree = _git_output(
            root, "ls-tree", head, "--", LR_RECEIPT_RELATIVE
        ).decode("utf-8").strip().split()
        if not receipt_tree or receipt_tree[0] != "100644":
            raise AssertionError
        validator_hashes = []
        for revision in (candidate, measured, head):
            validator = _git_output(
                root, "show", f"{revision}:scripts/validate_lr_seam.py"
            )
            validator_hashes.append(hashlib.sha256(validator).hexdigest())
            checked = subprocess.run(
                ["git", "show", "--check", "--format=", revision], cwd=root,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            )
            if checked.returncode != 0:
                raise AssertionError
        current_validator = (root / "scripts/validate_lr_seam.py").read_bytes()
        validator_hashes.append(hashlib.sha256(current_validator).hexdigest())
        if any(
            value != receipt["candidate_validator_sha256"]
            for value in validator_hashes
        ):
            raise AssertionError
        if _git_output(root, "status", "--porcelain=v1", "-z") != b"":
            raise AssertionError
    except (AssertionError, UnicodeDecodeError, KeyError, OSError):
        raise AssertionError("measured LR promotion receipt git drift") from None


def _project_readme_for_promotion(
    root: Path, raw: bytes, label: str, *, verify_receipt_git: bool
) -> bytes:
    anchor = (LR_RECEIPT_ANCHOR_LINE + "\n").encode("utf-8")
    link = (LR_RECEIPT_LINK_LINE + "\n").encode("utf-8")
    receipt_reference = LR_RECEIPT_RELATIVE.encode("utf-8")
    receipt_path = root / LR_RECEIPT_RELATIVE
    receipt_exists = receipt_path.exists() or receipt_path.is_symlink()
    if label == "proposed":
        if link in raw or receipt_reference in raw or receipt_exists:
            _promotion_artifact_drift(label, "README.md")
        if verify_receipt_git:
            _require_no_published_receipt_ancestor(root)
        return raw
    if raw.count(anchor) != 1 or raw.count(link) > 1:
        _promotion_artifact_drift(label, "README.md")
    link_count = raw.count(link)
    if raw.count(receipt_reference) != link_count:
        _promotion_artifact_drift(label, "README.md")
    if link_count == 0:
        if receipt_exists:
            _receipt_drift()
        if verify_receipt_git:
            _require_no_published_receipt_ancestor(root)
        return raw
    if raw.count(anchor + link) != 1:
        _promotion_artifact_drift(label, "README.md")
    if receipt_path.is_symlink() or not receipt_path.is_file():
        _receipt_drift()
    receipt = _parse_lr_receipt(receipt_path.read_bytes())
    validator_path = root / "scripts/validate_lr_seam.py"
    if validator_path.is_symlink() or not validator_path.is_file():
        _receipt_drift()
    validator_hash = hashlib.sha256(validator_path.read_bytes()).hexdigest()
    if (
        receipt["candidate_validator_sha256"] != validator_hash
        or receipt["measured_validator_sha256"] != validator_hash
    ):
        _receipt_drift()
    if verify_receipt_git:
        _validate_lr_receipt_git(root, receipt)
    return raw.replace(anchor + link, anchor, 1)


def _validate_promotion_governance(
    root: Path,
    manifest: Mapping[str, Any],
    contract: Mapping[str, Any],
    claim: Mapping[str, Any],
    *,
    verify_receipt_git: bool = False,
) -> None:
    """Fail closed on both exact candidate and measured promotion states."""
    status = manifest.get("status")
    require(status in {PROPOSED_STATUS, MEASURED_STATUS},
            "LR promotion manifest status drift")
    label = "measured" if status == MEASURED_STATUS else "proposed"
    expected_hashes = (
        MEASURED_PROMOTION_SHA256 if label == "measured"
        else PROPOSED_PROMOTION_SHA256
    )
    require(tuple(PROPOSED_PROMOTION_SHA256) == LR_PROMOTION_PATHS,
            "proposed LR promotion digest closure drift")
    require(tuple(MEASURED_PROMOTION_SHA256) == LR_PROMOTION_PATHS,
            "measured LR promotion digest closure drift")

    documents: dict[str, tuple[bytes, str]] = {}
    for relative in LR_PROMOTION_PATHS:
        raw, text = _read_promotion_bytes(root, relative, label)
        if relative == "README.md":
            raw = _project_readme_for_promotion(
                root, raw, label, verify_receipt_git=verify_receipt_git
            )
            text = raw.decode("utf-8")
        actual = "sha256:" + hashlib.sha256(raw).hexdigest()
        if actual != expected_hashes[relative]:
            _promotion_artifact_drift(label, relative)
        documents[relative] = (raw, text)

    try:
        disk_manifest = json.loads(documents["spec/lr-seam-manifest.v1.json"][1])
        disk_contract = json.loads(documents["spec/lr-seam-contract.v1.json"][1])
        disk_claims = json.loads(documents["spec/claims.v1.json"][1])
    except json.JSONDecodeError as error:
        raise AssertionError(f"{label} LR promotion governance JSON drift") from error
    disk_lr_claims = [
        item for item in disk_claims.get("claims", [])
        if isinstance(item, dict) and item.get("id") == "lr-direct-l-to-r-projection"
    ]
    require(len(disk_lr_claims) == 1, "on-disk LR claim-ledger entry drift")
    disk_claim = disk_lr_claims[0]
    require(_exact_json_equal(manifest, disk_manifest),
            "manifest argument differs from on-disk LR promotion file")
    require(_exact_json_equal(contract, disk_contract),
            "contract argument differs from on-disk LR promotion file")
    require(_exact_json_equal(claim, disk_claim),
            "claim argument differs from on-disk LR promotion file")
    require(disk_contract.get("status") == status,
            "contract and manifest status are incoherent")
    expected_claim_status = "MEASURED" if label == "measured" else "PROPOSED"
    require(disk_claim.get("epistemic_status") == expected_claim_status,
            "LR claim-ledger status drift")
    require(
        disk_claim.get("evidence") == list(LR_ADMISSION_EVIDENCE),
        f"{label} LR claim evidence differs from frozen admission evidence",
    )

    ci_relative = ".github/workflows/ci.yml"
    ci_text = documents[ci_relative][1]
    run_steps = re.findall(r"^\s*-\s+run:\s+(.+?)\s*$", ci_text, re.MULTILINE)
    expected_steps = STRICT_CI_STEPS if label == "measured" else PROPOSED_CI_STEPS
    if (
        len(run_steps) < len(expected_steps)
        or tuple(run_steps[-len(expected_steps):]) != expected_steps
    ):
        _promotion_artifact_drift(label, ci_relative)


def _validate_engine_defer_boundary(root: Path) -> None:
    decision = json.loads(
        (root / "spec/engine-decision.v1.json").read_text(encoding="utf-8")
    )
    require(decision.get("verdict") == "defer",
            "LR admission must preserve the deferred engine verdict")
    gates = decision.get("promotion_gates")
    require(isinstance(gates, list) and bool(gates),
            "engine promotion gates missing during LR admission")
    for gate in gates:
        require(gate.get("status") in {"OPEN", "BLOCKED"},
                "engine promotion gate closed during LR admission")
        require(gate.get("evidence") == [],
                "engine promotion gate gained evidence during LR admission")
    adr = (root / "docs/adr/0001-defer-engine-verdict.md").read_text(
        encoding="utf-8"
    )
    require(adr.startswith("# ADR 0001: Defer the engine verdict\n"),
            "deferred engine ADR boundary drift")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--allow-proposed", action="store_true",
        help="admit PROPOSED_PENDING_MEASUREMENT while assembling candidate evidence",
    )
    args = parser.parse_args()
    require(len(CLEAN_PROFILES) == 2, "LR admission requires exactly two clean profiles")

    manifest = load_json("spec/lr-seam-manifest.v1.json")
    contract = load_json("spec/lr-seam-contract.v1.json")
    claim_ledger = load_json("spec/claims.v1.json")
    allowed_statuses = {MEASURED_STATUS}
    if args.allow_proposed:
        allowed_statuses.add(PROPOSED_STATUS)
    require(manifest["status"] in allowed_statuses,
            f"LR manifest status {manifest['status']} is not admitted; use --allow-proposed only during candidate assembly")
    require(contract["status"] in allowed_statuses,
            f"LR contract status {contract['status']} is not admitted")
    require(contract["status"] == manifest["status"],
            "contract and manifest status are incoherent")
    require(contract["public_api"].replace(",", ", ") ==
            "project_lr(l_result, rule_bundle, r_profile, binding_profile, query_batch)",
            "contract public API drift")
    claim = next(
        (item for item in claim_ledger["claims"]
         if item["id"] == "lr-direct-l-to-r-projection"),
        None,
    )
    require(claim is not None, "LR claim-ledger entry missing")
    expected_claim_status = (
        "MEASURED" if manifest["status"] == MEASURED_STATUS else "PROPOSED"
    )
    require(claim["epistemic_status"] == expected_claim_status,
            "LR claim-ledger status drift")
    _validate_promotion_governance(
        ROOT, manifest, contract, claim, verify_receipt_git=True
    )
    _validate_engine_defer_boundary(ROOT)
    lr_doc_path = ROOT / "docs/LR_SEAM.md"
    require(lr_doc_path.is_file(), "LR seam document missing")
    status_markers = re.findall(
        r"^> Status: \*\*([^*]+)\*\*\.$",
        lr_doc_path.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    require(bool(status_markers), "LR seam document has no exact status marker")
    require(status_markers[0] == manifest["status"],
            "LR seam document first status marker drift")
    if manifest["status"] == MEASURED_STATUS:
        for relative in LR_ADMISSION_EVIDENCE:
            require((ROOT / relative).is_file(),
                    f"measured LR claim evidence missing: {relative}")

    declared_paths = set(manifest["normative_contracts"])
    declared_paths.update(manifest["self_validating_schemas"])
    declared_paths.update(item["artifact"] for item in manifest["schema_bindings"])
    declared_paths.update(item["schema"] for item in manifest["schema_bindings"])
    declared_paths.update(item["artifact"] for item in manifest["inherited_normative_dependencies"])
    declared_paths.update(item["artifact"] for item in manifest["inherited_fixture_dependencies"])
    declared_paths.update(manifest["golden_outputs"])
    declared_paths.update(manifest["reference_implementation"])
    declared_paths.update(manifest["non_normative_tools"])
    declared_paths.add(manifest["conformance_fixture"])
    for relative in sorted(declared_paths):
        require((ROOT / relative).is_file(), f"manifest artifact missing: {relative}")
    require(tuple(manifest["non_normative_tools"]) == EXPECTED_TOOLS,
            "manifest tool closure differs from frozen expected paths")

    for dependency in (
        manifest["inherited_normative_dependencies"]
        + manifest["inherited_fixture_dependencies"]
    ):
        require(sha256_file(dependency["artifact"]) == dependency["sha256"],
                f"inherited dependency drift: {dependency['artifact']}")

    schemas = registry()
    for relative in manifest["self_validating_schemas"]:
        schema = load_json(relative)
        Draft202012Validator.check_schema(schema)
        require(schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema",
                f"schema dialect drift: {relative}")
    for binding in manifest["schema_bindings"]:
        validate(load_json(binding["artifact"]), load_json(binding["schema"]), schemas)

    lr_schema = load_json("spec/schema/lr-seam.v1.schema.json")
    corpus = load_cases()
    documents = _build_success_documents()
    by_label = {label: (document, expected) for label, document, expected in documents}
    successes = oracle_comparisons = 0
    production_results: dict[str, dict[str, Any]] = {}
    for label, document, expected in documents:
        result = _project(document)
        validate(result, lr_schema, schemas)
        production_results[label] = result
        require(expected == "success", f"unexpected success descriptor kind: {label}")
        require(result["kind"] == "LRProjectionResult", f"success rejected: {label}")
        oracle = project_expected(*(document[key] for key in ARGUMENT_KEYS))
        require(result == oracle, f"independent oracle mismatch: {label}")
        oracle_comparisons += 1
        successes += 1

    truth_result = production_results["success:truth-matrix"]
    truth_statuses = {
        item["proposal_id"].removeprefix("proposal:lr:"): item["status"]
        for item in truth_result["verdicts"]
    }
    require(truth_statuses == {
        "positive-true": "eligible", "positive-false": "ineligible",
        "positive-both": "conflicted", "positive-neither": "ineligible",
        "negative-true": "ineligible", "negative-false": "eligible",
    }, "four-valued truth/polarity matrix drift")

    actual_chain_result = production_results["success:actual-chain"]
    actual_publication = _publication(
        by_label["success:actual-chain"][0], actual_chain_result
    )
    require(actual_publication is not None,
            "actual public solve_l->project_lr->step_r chain did not publish")

    mismatch_document = _mismatch_document(by_label["success:eligible-golden"][0])
    mismatch_result = _project(mismatch_document)
    validate(mismatch_result, lr_schema, schemas)
    require(mismatch_result.get("code") == "PRECONDITION_BINDING_MISMATCH",
            "exact mismatch probe did not fail at precondition binding")

    golden_paths = {item["id"]: item["path"] for item in corpus["goldens"]}
    eligible_golden_path = golden_paths["golden:eligible-projection"]
    mismatch_golden_path = golden_paths["golden:mismatch-rejection"]
    require(eligible_golden_path == manifest["golden_outputs"][0], "eligible golden path drift")
    require(mismatch_golden_path == manifest["golden_outputs"][1], "mismatch golden path drift")
    eligible_golden = load_json(eligible_golden_path)
    mismatch_golden = load_json(mismatch_golden_path)
    validate(eligible_golden, lr_schema, schemas)
    validate(mismatch_golden, lr_schema, schemas)
    require(eligible_golden == production_results["success:eligible-golden"], "eligible golden mismatch")
    require(mismatch_golden == mismatch_result, "mismatch rejection golden mismatch")

    for rejection in corpus["rejection_cases"]:
        validate(rejection["expected"], lr_schema, schemas)
        require(rejection["expected"]["kind"] == "LRProjectionRejection",
                f"non-rejection expected result: {rejection['id']}")
        require("command" not in rejection["expected"] and "verdicts" not in rejection["expected"],
                f"atomic rejection descriptor leaked output: {rejection['id']}")

    replay_cases = [document for _label, document, expected in documents if expected == "success"]
    replay_cases.append(mismatch_document)
    replay_input = canonical_bytes({"mode": "sequence", "cases": replay_cases}) + b"\n"
    replay_report = _run_clean_pair(
        "scripts/run_lr_seam_replay.py", stdin=replay_input, descriptor="replay"
    )
    expected_replay = [production_results[label] for label, _document, expected in documents
                       if expected == "success"] + [mismatch_result]
    require(replay_report == {"mode": "sequence", "results": expected_replay},
            "clean replay differs from public production results")

    ambient = _run_clean_pair(
        "scripts/check_lr_seam_ambient.py", stdin=b"", descriptor="ambient"
    )
    require(ambient["public_export"] == EXPECTED_PUBLIC_EXPORT, "ambient public export drift")
    require(ambient["kernel_ambient_attempts"] == 0, "ambient checker observed kernel authority")
    require(ambient["kernel_input_mutation_attempts"] == 0, "ambient checker observed mutation")
    require(ambient["guard_self_tests"] ==
            len(ambient["ambient_categories"]) + ambient["audit_guard_self_tests"],
            "ambient self-test count is not data-derived")
    require(ambient["kernel_path_executions"] ==
            ambient["kernel_path_successes"] + ambient["kernel_path_rejections"],
            "ambient path count mismatch")
    require(ambient["mutants_detected"] >= 5, "ambient control mutant coverage regressed")

    semantic = _run_clean_pair(
        "scripts/check_lr_seam_semantic_mutants.py", stdin=b"", descriptor="semantic"
    )
    require(semantic["mutant_count"] == semantic["killed"], "semantic mutants survived")
    require(semantic["survived"] == semantic["invalid"] == 0,
            "invalid mutants must not count as killed")
    require(semantic["axis_count"] == semantic["mutant_count"],
            "semantic axis receipts are not one-to-one")
    require(len(semantic["receipts"]) == semantic["mutant_count"],
            "semantic receipt count mismatch")
    require(semantic["public_step_r_publication_chains"] > 0,
            "semantic baseline bypassed public step_r publication")

    for gate in INHERITED_GATES:
        _run_gate(gate)
    _run_gate("tests/test_lr_seam.py")

    report = {
        "status": manifest["status"], "manifest_artifacts": len(declared_paths),
        "success_paths": successes, "rejection_paths": len(corpus["rejection_cases"]),
        "oracle_comparisons": oracle_comparisons,
        "clean_processes": len(CLEAN_PROFILES) * len(CLEAN_PROCESS_KINDS),
        "clean_process_descriptors": [
            f"{kind}:{profile['label']}"
            for kind in CLEAN_PROCESS_KINDS for profile in CLEAN_PROFILES
        ],
        "ambient_paths": ambient["kernel_path_executions"],
        "semantic_axes": semantic["axis_count"],
        "public_step_r_publication_chains": semantic["public_step_r_publication_chains"],
        "inherited_nonregression_gates": len(INHERITED_GATES),
        "lr_conformance_test_gate": 1,
    }
    if manifest["status"] == MEASURED_STATUS:
        require(
            _exact_json_equal(report, EXPECTED_MEASURED_GATE_REPORT),
            "measured LR gate report drift",
        )
    print("OK " + canonical_bytes(report).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
