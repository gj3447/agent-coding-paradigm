/**
 * Conformance-corpus loading and materialization, ported from
 * scripts/m1_fixtures.py. Fixtures are parsed with the lexical parser so
 * int64 values and float lexemes survive exactly as the Python oracle sees
 * them.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseJsonText } from "../../src/contracts/json-text";
import {
  deepCopyJson,
  type JsonObject,
  type JsonValue,
} from "../../src/contracts/json-value";

const here = path.dirname(fileURLToPath(import.meta.url));
export const repoRoot = path.resolve(here, "..", "..", "..");

export const readFixtureBytes = (relative: string): Buffer =>
  readFileSync(path.join(repoRoot, relative));

export const loadFixture = (relative: string): JsonValue =>
  parseJsonText(readFixtureBytes(relative).toString("utf-8"));

export const asObj = (value: JsonValue | undefined, label: string): JsonObject => {
  if (!(value instanceof Map)) {
    throw new Error(`${label} is not an object`);
  }
  return value;
};

export const asArr = (value: JsonValue | undefined, label: string): JsonValue[] => {
  if (!Array.isArray(value)) {
    throw new Error(`${label} is not an array`);
  }
  return value;
};

export const asStr = (value: JsonValue | undefined, label: string): string => {
  if (typeof value !== "string") {
    throw new Error(`${label} is not a string`);
  }
  return value;
};

const pointerTokens = (pointer: string): string[] => {
  if (!pointer.startsWith("/")) {
    throw new Error("mutation pointer must be absolute");
  }
  return pointer
    .slice(1)
    .split("/")
    .map((token) => token.replaceAll("~1", "/").replaceAll("~0", "~"));
};

export const applyMutation = (document: JsonObject, mutation: JsonObject): void => {
  const tokens = pointerTokens(asStr(mutation.get("path"), "mutation.path"));
  if (tokens.length === 0) {
    throw new Error("root mutation is not supported");
  }
  let parent: JsonValue = document;
  for (const token of tokens.slice(0, -1)) {
    parent = Array.isArray(parent)
      ? (parent[Number.parseInt(token, 10)] as JsonValue)
      : asObj(parent, "mutation parent").get(token) as JsonValue;
  }
  const leaf = tokens[tokens.length - 1] as string;
  const operation = asStr(mutation.get("op"), "mutation.op");
  if (operation === "remove") {
    if (Array.isArray(parent)) {
      parent.splice(Number.parseInt(leaf, 10), 1);
    } else {
      asObj(parent, "mutation parent").delete(leaf);
    }
    return;
  }
  const value = deepCopyJson(mutation.get("value") ?? null);
  if (Array.isArray(parent)) {
    const index = Number.parseInt(leaf, 10);
    if (operation === "add") {
      parent.splice(index, 0, value);
    } else {
      parent[index] = value;
    }
  } else {
    asObj(parent, "mutation parent").set(leaf, value);
  }
};

export const materializeCase = (corpus: JsonObject, caseValue: JsonObject): JsonObject => {
  const baseInputs = asObj(corpus.get("base_inputs"), "base_inputs");
  const inputRef = asStr(caseValue.get("input_ref"), "input_ref");
  const document = asObj(
    deepCopyJson(asObj(baseInputs.get(inputRef), `base_inputs.${inputRef}`)),
    "document",
  );
  for (const mutation of (caseValue.get("mutations") as JsonValue[] | undefined) ?? []) {
    applyMutation(document, asObj(mutation, "mutation"));
  }
  const single = caseValue.get("mutation");
  if (single !== undefined) {
    applyMutation(document, asObj(single, "mutation"));
  }
  return document;
};

export const findCase = (corpus: JsonObject, caseId: string): JsonObject => {
  for (const group of ["success_cases", "rejection_cases"]) {
    for (const caseValue of asArr(corpus.get(group), group)) {
      const candidate = asObj(caseValue, "case");
      if (candidate.get("id") === caseId) {
        return candidate;
      }
    }
  }
  throw new Error(`unknown case ${caseId}`);
};

export const materializeReplaySequence = (
  corpus: JsonObject,
  sequence: JsonObject,
): { initial: JsonObject; events: JsonObject[] } => {
  const baseInputs = asObj(corpus.get("base_inputs"), "base_inputs");
  const initialRef = asStr(sequence.get("initial_input_ref"), "initial_input_ref");
  const initial = asObj(
    deepCopyJson(
      asObj(
        asObj(baseInputs.get(initialRef), "initial base input").get("snapshot"),
        "initial snapshot",
      ),
    ),
    "initial snapshot",
  );
  const events: JsonObject[] = [];
  for (const step of asArr(sequence.get("steps"), "steps")) {
    const stepValue = asObj(step, "step");
    const inputRef = asStr(stepValue.get("input_ref"), "step.input_ref");
    const document = asObj(
      deepCopyJson(asObj(baseInputs.get(inputRef), `base_inputs.${inputRef}`)),
      "step document",
    );
    for (const mutation of asArr(stepValue.get("event_mutations"), "event_mutations")) {
      applyMutation(document, asObj(mutation, "mutation"));
    }
    events.push(asObj(document.get("accepted_event"), "accepted_event"));
  }
  return { initial, events };
};
