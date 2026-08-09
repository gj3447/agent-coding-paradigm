"""Deterministic ``flrh-cjson/1`` support for the M2 logic kernel.

The implementation is deliberately local to :mod:`flrh_logic`.  It performs
no I/O and does not depend on the private canonicalization helper of the M1
package.  Set-like M2 collections are normalized by ``logic.py`` before they
reach this byte encoder.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any, Dict, Set, Tuple


INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1


class CanonicalizationError(ValueError):
    """Stable canonicalization failure without interpreter exception text."""

    def __init__(self, code: str, path: str) -> None:
        super().__init__(code)
        self.code = code
        self.path = path or "/"


def _child(path: str, key: str) -> str:
    escaped = key.replace("~", "~0").replace("/", "~1")
    return f"{path}/{escaped}"


def diagnostic_order_key(value: Any) -> Tuple[Any, ...]:
    """Return an ambient-free total key for deterministic validation order.

    This key is not a canonical encoding and is never hashed.  It only makes
    the first typed rejection independent of caller mapping/set insertion
    order, including when an element is outside the canonical JSON domain.
    """

    if value is None:
        return (0,)
    if isinstance(value, bool):
        return (1, int(value))
    if isinstance(value, int):
        return (2, value)
    if isinstance(value, float):
        return (3, value.hex())
    if isinstance(value, str):
        return (4, tuple(ord(character) for character in value))
    if isinstance(value, list):
        return (5, tuple(diagnostic_order_key(item) for item in value))
    if isinstance(value, dict):
        entries = sorted(
            (
                (diagnostic_order_key(key), diagnostic_order_key(item))
                for key, item in value.items()
            ),
            key=lambda pair: pair[0],
        )
        return (6, tuple(entries))
    value_type = type(value)
    return (7, value_type.__module__, value_type.__qualname__)


def _normalize(value: Any, path: str, set_like_paths: Set[str]) -> Any:
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
        items = [
            _normalize(item, f"{path}/{index}", set_like_paths)
            for index, item in enumerate(value)
        ]
        if path in set_like_paths:
            encoded = [
                json.dumps(
                    item,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
                for item in items
            ]
            if len(encoded) != len(set(encoded)):
                raise CanonicalizationError("DUPLICATE_SET_ELEMENT", path)
            items = [item for _, item in sorted(zip(encoded, items), key=lambda pair: pair[0])]
        return items
    if isinstance(value, dict):
        normalized: Dict[str, Any] = {}
        if any(not isinstance(key, str) for key in value):
            raise CanonicalizationError("NON_STRING_OBJECT_KEY", path)
        for key in sorted(value):
            item = value[key]
            if unicodedata.normalize("NFC", key) != key:
                # The invalid key cannot itself be copied into a canonical
                # rejection path.  Point at its containing object instead.
                raise CanonicalizationError("NON_NFC_OBJECT_KEY", path)
            if any(0xD800 <= ord(character) <= 0xDFFF for character in key):
                raise CanonicalizationError("NON_UNICODE_SCALAR", path)
            if key in normalized:
                raise CanonicalizationError("DUPLICATE_OBJECT_KEY", _child(path, key))
            normalized[key] = _normalize(item, _child(path, key), set_like_paths)
        return {key: normalized[key] for key in sorted(normalized)}
    raise CanonicalizationError("UNSUPPORTED_JSON_TYPE", path)


def canonical_bytes(value: Any, set_like_paths: Set[str] = frozenset()) -> bytes:
    """Return deterministic canonical JSON bytes for an explicit value."""

    normalized = _normalize(value, "", set(set_like_paths))
    return json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_digest(value: Any, set_like_paths: Set[str] = frozenset()) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value, set_like_paths)).hexdigest()
