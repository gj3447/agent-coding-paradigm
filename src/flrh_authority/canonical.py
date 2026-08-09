"""Self-contained deterministic flrh-cjson/1 support for M4A."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any, Set

INT64_MAX = 2**63 - 1


class CanonicalizationError(ValueError):
    def __init__(self, code: str, path: str) -> None:
        super().__init__(code)
        self.code, self.path = code, path or "/"


def _normalize(value: Any, path: str, set_paths: Set[str]) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        if not -(2**63) <= value <= INT64_MAX:
            raise CanonicalizationError("INTEGER_OUTSIDE_INT64", path)
        return value
    if isinstance(value, float):
        raise CanonicalizationError("FLOAT_FORBIDDEN", path)
    if isinstance(value, str):
        if unicodedata.normalize("NFC", value) != value or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise CanonicalizationError("INVALID_UNICODE", path)
        return value
    if isinstance(value, list):
        items = [_normalize(item, f"{path}/{index}", set_paths) for index, item in enumerate(value)]
        if path in set_paths:
            encoded = [json.dumps(item, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode() for item in items]
            if len(encoded) != len(set(encoded)):
                raise CanonicalizationError("DUPLICATE_SET_ELEMENT", path)
            items = [item for _, item in sorted(zip(encoded, items), key=lambda pair: pair[0])]
        return items
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise CanonicalizationError("NON_STRING_OBJECT_KEY", path)
        return {key: _normalize(value[key], f"{path}/{key}", set_paths) for key in sorted(value)}
    raise CanonicalizationError("UNSUPPORTED_JSON_TYPE", path)


def canonical_bytes(value: Any, set_paths: Set[str] | None = None) -> bytes:
    normalized = _normalize(value, "", set_paths or set())
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def digest(value: Any, set_paths: Set[str] | None = None) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value, set_paths)).hexdigest()


def thaw(value: Any) -> Any:
    return json.loads(canonical_bytes(value).decode())
