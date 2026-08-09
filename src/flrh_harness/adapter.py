"""Fence- and idempotency-aware fake destination adapter."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from .canonical import canonical_bytes, digest


class AdapterConflictError(RuntimeError):
    pass


class AdapterStaleFenceError(RuntimeError):
    pass


class FakeAdapter:
    """Observable fake only; it is not evidence of a real destination's safety."""

    def __init__(self, *, outcomes: Optional[Dict[str, Iterable[str]]] = None, durable_path: Optional[Path] = None):
        self._outcomes = {key: list(value) for key, value in (outcomes or {}).items()}
        self._path = Path(durable_path) if durable_path is not None else None
        self.apply_count = 0
        self.query_count = 0
        self.mutation_count = 0
        self._applied: Dict[str, Dict[str, Any]] = {}
        self._max_generation: Dict[str, int] = {}
        if self._path is not None:
            self._initialize()

    def _connect(self):
        connection = sqlite3.connect(str(self._path), isolation_level=None)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA trusted_schema=OFF")
        return connection

    def _initialize(self):
        connection = self._connect()
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS adapter_meta(name TEXT PRIMARY KEY, value INTEGER NOT NULL) STRICT;
            CREATE TABLE IF NOT EXISTS applied(
              idempotency_key TEXT PRIMARY KEY, intent_digest TEXT NOT NULL,
              intent_json TEXT NOT NULL, destination_digest TEXT NOT NULL,
              generation INTEGER NOT NULL
            ) STRICT;
            CREATE TABLE IF NOT EXISTS fences(destination_digest TEXT PRIMARY KEY, generation INTEGER NOT NULL) STRICT;
            INSERT OR IGNORE INTO adapter_meta VALUES('apply_count',0),('query_count',0),('mutation_count',0);
        """)
        connection.close()

    @staticmethod
    def inspect(path: Path) -> Dict[str, int]:
        if not Path(path).exists():
            return {"apply_count": 0, "query_count": 0, "mutation_count": 0}
        connection = sqlite3.connect(str(path))
        values = dict(connection.execute("SELECT name,value FROM adapter_meta"))
        connection.close()
        return {key: int(values.get(key, 0)) for key in ("apply_count", "query_count", "mutation_count")}

    def _increment(self, name: str):
        if self._path is None:
            setattr(self, name, getattr(self, name) + 1)
        else:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("UPDATE adapter_meta SET value=value+1 WHERE name=?", (name,))
            connection.commit(); connection.close()

    def apply(self, intent: Dict[str, Any], generation: int) -> Dict[str, Any]:
        self._increment("apply_count")
        intent_digest = digest(intent)
        key = intent["idempotency_key"]
        destination = intent["destination_digest"]
        planned = self._outcomes.get(intent["intent_id"], [])
        outcome = planned.pop(0) if planned else "success"
        if self._path is not None:
            connection = self._connect(); connection.execute("BEGIN IMMEDIATE")
            fence = connection.execute("SELECT generation FROM fences WHERE destination_digest=?", (destination,)).fetchone()
            if fence and generation < fence[0]:
                connection.rollback(); connection.close(); raise AdapterStaleFenceError("stale adapter fence")
            connection.execute("INSERT INTO fences VALUES(?,?) ON CONFLICT(destination_digest) DO UPDATE SET generation=excluded.generation WHERE excluded.generation>generation", (destination, generation))
            existing = connection.execute("SELECT intent_digest FROM applied WHERE idempotency_key=?", (key,)).fetchone()
            if existing and existing[0] != intent_digest:
                connection.rollback(); connection.close(); raise AdapterConflictError("idempotency identity conflict")
            if outcome in ("transient", "permanent", "unknown_not_applied"):
                connection.commit(); connection.close()
                if outcome == "unknown_not_applied": return {"outcome": "outcome_unknown"}
                return {"outcome": "transient" if outcome == "transient" else "confirmed_failure"}
            mutated = existing is None
            if mutated:
                connection.execute("INSERT INTO applied VALUES(?,?,?,?,?)", (key, intent_digest, canonical_bytes(intent).decode(), destination, generation))
                connection.execute("UPDATE adapter_meta SET value=value+1 WHERE name='mutation_count'")
            connection.commit(); connection.close()
        else:
            maximum = self._max_generation.get(destination, -1)
            if generation < maximum:
                raise AdapterStaleFenceError("stale adapter fence")
            self._max_generation[destination] = max(maximum, generation)
            existing = self._applied.get(key)
            if existing is not None and existing["digest"] != intent_digest:
                raise AdapterConflictError("idempotency identity conflict")
            if outcome in ("transient", "permanent", "unknown_not_applied"):
                if outcome == "unknown_not_applied": return {"outcome": "outcome_unknown"}
                return {"outcome": "transient" if outcome == "transient" else "confirmed_failure"}
            mutated = existing is None
            if mutated:
                self._applied[key] = {"digest": intent_digest, "intent": intent}
                self.mutation_count += 1
        if outcome == "unknown":
            return {"outcome": "outcome_unknown"}
        return {"outcome": "confirmed_success", "mutated": mutated}

    def query(self, intent: Dict[str, Any], generation: int) -> str:
        self._increment("query_count")
        key = intent["idempotency_key"]
        wanted = digest(intent)
        if self._path is not None:
            connection = self._connect()
            row = connection.execute("SELECT intent_digest FROM applied WHERE idempotency_key=?", (key,)).fetchone()
            connection.close()
            if row is None: return "not_applied"
            if row[0] != wanted: raise AdapterConflictError("destination identity conflict")
            return "confirmed_success"
        row = self._applied.get(key)
        if row is None: return "not_applied"
        if row["digest"] != wanted: raise AdapterConflictError("destination identity conflict")
        return "confirmed_success"
