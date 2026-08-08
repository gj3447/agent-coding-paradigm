"""Read-only materialization helpers for the M1 conformance corpus."""

from __future__ import annotations

import copy
from typing import Any, Dict, Iterable, Mapping


def _tokens(pointer: str) -> Iterable[str]:
    if not pointer.startswith("/"):
        raise ValueError("mutation pointer must be absolute")
    for token in pointer[1:].split("/"):
        yield token.replace("~1", "/").replace("~0", "~")


def apply_mutation(document: Dict[str, Any], mutation: Mapping[str, Any]) -> None:
    tokens = list(_tokens(mutation["path"]))
    if not tokens:
        raise ValueError("root mutation is not supported")
    parent: Any = document
    for token in tokens[:-1]:
        parent = parent[int(token)] if isinstance(parent, list) else parent[token]
    leaf = tokens[-1]
    operation = mutation["op"]
    if operation == "remove":
        if isinstance(parent, list):
            del parent[int(leaf)]
        else:
            del parent[leaf]
        return
    value = copy.deepcopy(mutation.get("value"))
    if isinstance(parent, list):
        index = int(leaf)
        if operation == "add":
            parent.insert(index, value)
        else:
            parent[index] = value
    else:
        parent[leaf] = value


def materialize_case(corpus: Mapping[str, Any], case: Mapping[str, Any]) -> Dict[str, Any]:
    document = copy.deepcopy(corpus["base_inputs"][case["input_ref"]])
    for mutation in case.get("mutations", ()):  # success and rejection share the same shape
        apply_mutation(document, mutation)
    if "mutation" in case:  # sensitivity cases use one mutation
        apply_mutation(document, case["mutation"])
    return document


def find_case(corpus: Mapping[str, Any], case_id: str) -> Mapping[str, Any]:
    for group in ("success_cases", "rejection_cases"):
        for case in corpus[group]:
            if case["id"] == case_id:
                return case
    raise KeyError(case_id)


def find_replay_sequence(corpus: Mapping[str, Any], sequence_id: str) -> Mapping[str, Any]:
    for sequence in corpus["replay_sequences"]:
        if sequence["id"] == sequence_id:
            return sequence
    raise KeyError(sequence_id)


def materialize_replay_sequence(
    corpus: Mapping[str, Any], sequence: Mapping[str, Any]
) -> tuple[Dict[str, Any], list[Dict[str, Any]]]:
    initial = copy.deepcopy(corpus["base_inputs"][sequence["initial_input_ref"]]["snapshot"])
    events: list[Dict[str, Any]] = []
    for step in sequence["steps"]:
        document = copy.deepcopy(corpus["base_inputs"][step["input_ref"]])
        for mutation in step["event_mutations"]:
            apply_mutation(document, mutation)
        events.append(document["accepted_event"])
    return initial, events
