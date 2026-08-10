"""Deterministic FLR-H canonical JSON profile used by the M1 reference kernel.

This implementation is intentionally independent from ``scripts/validate_m0.py``.
Both implementations are checked against the same frozen golden corpus.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any, Dict, Set


INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1
MAX_NESTING_DEPTH = 128

SET_LIKE_PATHS_BY_KIND = {
    "EffectProposal": {"/preconditions"},
    "EligibilityVerdict": {"/support_derivation_ids"},
    "StableProposalBatch": {"/proposal_ids", "/eligibility_verdict_ids"},
    "EffectIntent": {"/preconditions"},
    "GraphEnvelope": {"/provenance_refs"},
    "GraphDelta": {"/causal_parent_delta_ids"},
    "ActionReceipt": {"/output_digests"},
}


class CanonicalizationError(ValueError):
    """Stable canonicalization failure without implementation exception text."""

    def __init__(self, code: str, path: str) -> None:
        super().__init__(code)
        self.code = code
        self.path = path or "/"


def _child(path: str, key: str) -> str:
    escaped = key.replace("~", "~0").replace("/", "~1")
    return f"{path}/{escaped}"


def _normalize(value: Any, path: str, set_like_paths: Set[str], depth: int = 0) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        if not INT64_MIN <= value <= INT64_MAX:
            raise CanonicalizationError("INTEGER_OUTSIDE_INT64", path)
        return value
    if isinstance(value, float):
        raise CanonicalizationError("FLOAT_FORBIDDEN", path)
    if isinstance(value, str):
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise CanonicalizationError("NON_UNICODE_SCALAR", path)
        if unicodedata.normalize("NFC", value) != value:
            raise CanonicalizationError("NON_NFC_STRING", path)
        return value
    if isinstance(value, list):
        if depth >= MAX_NESTING_DEPTH:
            raise CanonicalizationError("NESTING_DEPTH_EXCEEDED", path)
        items = [
            _normalize(item, f"{path}/{index}", set_like_paths, depth + 1)
            for index, item in enumerate(value)
        ]
        if path in set_like_paths:
            encoded = [
                json.dumps(item, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
                for item in items
            ]
            if len(encoded) != len(set(encoded)):
                raise CanonicalizationError("DUPLICATE_SET_ELEMENT", path)
            items = [item for _, item in sorted(zip(encoded, items), key=lambda pair: pair[0])]
        return items
    if isinstance(value, dict):
        if depth >= MAX_NESTING_DEPTH:
            raise CanonicalizationError("NESTING_DEPTH_EXCEEDED", path)
        normalized: Dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError("NON_STRING_OBJECT_KEY", path)
            if not key.isascii():
                raise CanonicalizationError("NON_ASCII_OBJECT_KEY", _child(path, key))
            if unicodedata.normalize("NFC", key) != key:
                raise CanonicalizationError("NON_NFC_OBJECT_KEY", _child(path, key))
            if key in normalized:
                raise CanonicalizationError("DUPLICATE_OBJECT_KEY", _child(path, key))
            normalized[key] = _normalize(item, _child(path, key), set_like_paths, depth + 1)
        return {key: normalized[key] for key in sorted(normalized)}
    raise CanonicalizationError("UNSUPPORTED_JSON_TYPE", path)


def canonical_bytes(value: Any) -> bytes:
    """Return ``flrh-cjson/1`` bytes or raise ``CanonicalizationError``."""

    root_kind = value.get("kind") if isinstance(value, dict) else None
    set_like_paths = (
        SET_LIKE_PATHS_BY_KIND.get(root_kind, set()) if isinstance(root_kind, str) else set()
    )
    normalized = _normalize(value, "", set_like_paths)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()
