/**
 * flrh-cjson/1 canonicalization, ported from src/flrh_kernel/canonical.py —
 * the canonical profile shared by the M0 oracle and the M1 kernel. Byte
 * identity with the Python reference is enforced by the conformance suite.
 */

import { JsonFloat, type JsonObject, type JsonValue } from "./json-value";
import { sha256Hex } from "./sha256";
import { isAssignedAt15_1 } from "./unicode-15-1-assigned";

export const INT64_MIN = -(2n ** 63n);
export const INT64_MAX = 2n ** 63n - 1n;
export const MAX_NESTING_DEPTH = 128;

export const CANONICAL_ALGORITHM = "flrh-cjson";
export const CANONICAL_ALGORITHM_VERSION = "1";
export const CANONICAL_MEDIA_TYPE = "application/vnd.flrh.canonical+json;version=1";

export const SET_LIKE_PATHS_BY_KIND: ReadonlyMap<string, ReadonlySet<string>> = new Map([
  ["EffectProposal", new Set(["/preconditions"])],
  ["EligibilityVerdict", new Set(["/support_derivation_ids"])],
  ["StableProposalBatch", new Set(["/proposal_ids", "/eligibility_verdict_ids"])],
  ["EffectIntent", new Set(["/preconditions"])],
  ["GraphEnvelope", new Set(["/provenance_refs"])],
  ["GraphDelta", new Set(["/causal_parent_delta_ids"])],
  ["ActionReceipt", new Set(["/output_digests"])],
]);

export class CanonicalizationError extends Error {
  readonly code: string;
  readonly path: string;
  constructor(code: string, path: string) {
    super(code);
    this.code = code;
    this.path = path === "" ? "/" : path;
  }
}

const childPath = (path: string, key: string): string =>
  `${path}/${key.replaceAll("~", "~0").replaceAll("/", "~1")}`;

/** True when the string contains an unpaired UTF-16 surrogate — the JS
 * equivalent of a Python str holding a scalar in U+D800..U+DFFF. */
const hasLoneSurrogate = (value: string): boolean => {
  for (let i = 0; i < value.length; i += 1) {
    const code = value.charCodeAt(i);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(i + 1);
      if (next >= 0xdc00 && next <= 0xdfff) {
        i += 1;
        continue;
      }
      return true;
    }
    if (code >= 0xdc00 && code <= 0xdfff) {
      return true;
    }
  }
  return false;
};

/**
 * NFC per the Unicode 15.1.0 pin (spec/canonicalization-clarifications.v1.json).
 * Fast path: if the runtime tables say the string is NFC-stable, the pinned
 * tables agree (normalization stability — assigned-character behavior never
 * changes, and 15.1 transformations are a subset of newer-table ones). Slow
 * path: codepoints unassigned at 15.1 are normalization-inert starters, so
 * they act as barriers; the string is pin-NFC iff every segment between
 * barriers is runtime-NFC-stable.
 */
const isNfcPerPin = (value: string): boolean => {
  if (value.normalize("NFC") === value) {
    return true;
  }
  let segment = "";
  let sawBarrier = false;
  for (const character of value) {
    const codePoint = character.codePointAt(0) as number;
    if (!isAssignedAt15_1(codePoint)) {
      sawBarrier = true;
      if (segment.normalize("NFC") !== segment) {
        return false;
      }
      segment = "";
    } else {
      segment += character;
    }
  }
  return sawBarrier && segment.normalize("NFC") === segment;
};

const isAscii = (value: string): boolean => {
  for (let i = 0; i < value.length; i += 1) {
    if (value.charCodeAt(i) > 0x7f) {
      return false;
    }
  }
  return true;
};

/** Unicode-code-point order — equals Python's str comparison, unlike the
 * UTF-16 code-unit order of the JS `<` operator. */
export const compareCodePoints = (a: string, b: string): number => {
  const left = [...a];
  const right = [...b];
  const length = Math.min(left.length, right.length);
  for (let i = 0; i < length; i += 1) {
    const l = (left[i] as string).codePointAt(0) as number;
    const r = (right[i] as string).codePointAt(0) as number;
    if (l !== r) {
      return l < r ? -1 : 1;
    }
  }
  return left.length - right.length;
};

export const compareBytes = (a: Uint8Array, b: Uint8Array): number => {
  const length = Math.min(a.length, b.length);
  for (let i = 0; i < length; i += 1) {
    const diff = (a[i] as number) - (b[i] as number);
    if (diff !== 0) {
      return diff;
    }
  }
  return a.length - b.length;
};

const encoder = new TextEncoder();

const serialize = (value: JsonValue): string => {
  if (value === null) {
    return "null";
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  if (typeof value === "bigint") {
    return value.toString();
  }
  if (typeof value === "string") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map(serialize).join(",")}]`;
  }
  if (value instanceof Map) {
    const parts: string[] = [];
    for (const [key, item] of value) {
      parts.push(`${JSON.stringify(key)}:${serialize(item)}`);
    }
    return `{${parts.join(",")}}`;
  }
  throw new CanonicalizationError("UNSUPPORTED_JSON_TYPE", "");
};

const normalize = (
  value: JsonValue,
  path: string,
  setLikePaths: ReadonlySet<string>,
  depth = 0,
): JsonValue => {
  if (value === null || typeof value === "boolean") {
    return value;
  }
  if (typeof value === "bigint") {
    if (value < INT64_MIN || value > INT64_MAX) {
      throw new CanonicalizationError("INTEGER_OUTSIDE_INT64", path);
    }
    return value;
  }
  if (value instanceof JsonFloat) {
    throw new CanonicalizationError("FLOAT_FORBIDDEN", path);
  }
  if (typeof value === "string") {
    if (hasLoneSurrogate(value)) {
      throw new CanonicalizationError("NON_UNICODE_SCALAR", path);
    }
    if (!isNfcPerPin(value)) {
      throw new CanonicalizationError("NON_NFC_STRING", path);
    }
    return value;
  }
  if (Array.isArray(value)) {
    if (depth >= MAX_NESTING_DEPTH) {
      throw new CanonicalizationError("NESTING_DEPTH_EXCEEDED", path);
    }
    let items = value.map((item, index) =>
      normalize(item, `${path}/${index}`, setLikePaths, depth + 1),
    );
    if (setLikePaths.has(path)) {
      const encoded = items.map((item) => encoder.encode(serialize(item)));
      const texts = encoded.map((bytes) => bytes.join(","));
      if (new Set(texts).size !== encoded.length) {
        throw new CanonicalizationError("DUPLICATE_SET_ELEMENT", path);
      }
      items = encoded
        .map((bytes, index) => ({ bytes, item: items[index] as JsonValue }))
        .sort((left, right) => compareBytes(left.bytes, right.bytes))
        .map((pair) => pair.item);
    }
    return items;
  }
  if (value instanceof Map) {
    if (depth >= MAX_NESTING_DEPTH) {
      throw new CanonicalizationError("NESTING_DEPTH_EXCEEDED", path);
    }
    const normalized: JsonObject = new Map();
    for (const [key, item] of value) {
      if (typeof key !== "string") {
        throw new CanonicalizationError("NON_STRING_OBJECT_KEY", path);
      }
      if (!isAscii(key)) {
        throw new CanonicalizationError("NON_ASCII_OBJECT_KEY", childPath(path, key));
      }
      if (key.normalize("NFC") !== key) {
        throw new CanonicalizationError("NON_NFC_OBJECT_KEY", childPath(path, key));
      }
      if (normalized.has(key)) {
        throw new CanonicalizationError("DUPLICATE_OBJECT_KEY", childPath(path, key));
      }
      normalized.set(key, normalize(item, childPath(path, key), setLikePaths, depth + 1));
    }
    const sorted: JsonObject = new Map();
    for (const key of [...normalized.keys()].sort(compareCodePoints)) {
      sorted.set(key, normalized.get(key) as JsonValue);
    }
    return sorted;
  }
  throw new CanonicalizationError("UNSUPPORTED_JSON_TYPE", path);
};

export const canonicalBytes = (value: JsonValue): Uint8Array => {
  const rootKind = value instanceof Map ? value.get("kind") : null;
  const setLikePaths =
    typeof rootKind === "string"
      ? (SET_LIKE_PATHS_BY_KIND.get(rootKind) ?? new Set<string>())
      : new Set<string>();
  const normalized = normalize(value, "", setLikePaths);
  return encoder.encode(serialize(normalized));
};

export const canonicalDigest = (value: JsonValue): string =>
  `sha256:${sha256Hex(canonicalBytes(value))}`;
