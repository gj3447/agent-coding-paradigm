"""Frozen flrh-cjson/1 helpers reused by the M4B durable reference."""

from __future__ import annotations

from typing import Any

from flrh_kernel.canonical import canonical_bytes as _canonical_bytes

def canonical_bytes(value: Any) -> bytes:
    return _canonical_bytes(value)


def digest(value: Any) -> str:
    import hashlib
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()
