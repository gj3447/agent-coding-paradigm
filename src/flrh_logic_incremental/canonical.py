"""Local ambient-free canonical JSON for the M2-IL adjunct."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any


def canonical_bytes(value: Any) -> bytes:
    def normalize(item: Any) -> Any:
        if item is None or isinstance(item, bool):
            return item
        if isinstance(item, int) and not isinstance(item, bool):
            if -(2**63) <= item <= 2**63 - 1:
                return item
            raise ValueError("INTEGER_OUTSIDE_INT64")
        if isinstance(item, float):
            raise ValueError("FLOAT_FORBIDDEN")
        if isinstance(item, str):
            if any(0xD800 <= ord(character) <= 0xDFFF for character in item):
                raise ValueError("NON_UNICODE_SCALAR")
            if unicodedata.normalize("NFC", item) != item:
                raise ValueError("NON_NFC_STRING")
            return item
        if isinstance(item, list):
            return [normalize(child) for child in item]
        if isinstance(item, dict) and all(isinstance(key, str) for key in item):
            for key in item:
                if any(0xD800 <= ord(character) <= 0xDFFF for character in key):
                    raise ValueError("NON_UNICODE_SCALAR")
                if unicodedata.normalize("NFC", key) != key:
                    raise ValueError("NON_NFC_OBJECT_KEY")
            return {key: normalize(item[key]) for key in sorted(item)}
        raise ValueError("UNSUPPORTED_JSON_TYPE")
    return json.dumps(normalize(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def canonical_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def closed_copy(value: Any) -> Any:
    return json.loads(canonical_bytes(value).decode("utf-8"))
