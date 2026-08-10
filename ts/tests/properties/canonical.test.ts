/**
 * Property tests for the canonicalizer: insertion-order independence,
 * parse/serialize idempotence, and digest stability. These are the invariants
 * that the Python clean-process replay profile (--reverse-objects) checks
 * mechanically.
 */

import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { canonicalBytes, canonicalDigest } from "../../src/contracts/canonical";
import { parseJsonText } from "../../src/contracts/json-text";
import type { JsonObject, JsonValue } from "../../src/contracts/json-value";

const asciiKey = fc.stringMatching(/^[a-z][a-z0-9_]{0,8}$/);
const safeString = fc.stringMatching(/^[\x20-\x7e가-힣]{0,12}$/).filter(
  (value) => value.normalize("NFC") === value,
);
const int64 = fc.bigInt(-(2n ** 63n), 2n ** 63n - 1n);

const jsonValueArb = fc.letrec<{ value: JsonValue; object: JsonObject }>((tie) => ({
  value: fc.oneof(
    { maxDepth: 3, withCrossShrink: true },
    fc.constant(null as JsonValue),
    fc.boolean(),
    int64,
    safeString,
    fc.array(tie("value"), { maxLength: 4 }),
    tie("object"),
  ),
  object: fc
    .uniqueArray(fc.tuple(asciiKey, tie("value")), {
      maxLength: 4,
      selector: (entry) => entry[0],
    })
    .map((entries) => new Map(entries) as JsonObject),
})).value;

const shuffleInsertionOrder = (value: JsonValue, seed: number): JsonValue => {
  if (Array.isArray(value)) {
    return value.map((item) => shuffleInsertionOrder(item, seed));
  }
  if (value instanceof Map) {
    const entries = [...value.entries()].map(
      ([key, item]) => [key, shuffleInsertionOrder(item, seed)] as const,
    );
    const rotation = entries.length > 0 ? seed % entries.length : 0;
    const rotated = [...entries.slice(rotation), ...entries.slice(0, rotation)].reverse();
    return new Map(rotated);
  }
  return value;
};

describe("canonicalization properties", () => {
  it("is independent of object insertion order", () => {
    fc.assert(
      fc.property(jsonValueArb, fc.nat(), (value, seed) => {
        const shuffled = shuffleInsertionOrder(value, seed);
        return canonicalDigest(value) === canonicalDigest(shuffled);
      }),
    );
  });

  it("round-trips through its own bytes", () => {
    fc.assert(
      fc.property(jsonValueArb, (value) => {
        const bytes = canonicalBytes(value);
        const reparsed = parseJsonText(Buffer.from(bytes).toString("utf-8"));
        return Buffer.from(canonicalBytes(reparsed)).equals(Buffer.from(bytes));
      }),
    );
  });

  it("distinct digests imply distinct bytes", () => {
    fc.assert(
      fc.property(jsonValueArb, jsonValueArb, (left, right) => {
        const leftBytes = Buffer.from(canonicalBytes(left));
        const rightBytes = Buffer.from(canonicalBytes(right));
        return (
          leftBytes.equals(rightBytes) ===
          (canonicalDigest(left) === canonicalDigest(right))
        );
      }),
    );
  });

  it("never emits a trailing newline", () => {
    fc.assert(
      fc.property(jsonValueArb, (value) => {
        const bytes = canonicalBytes(value);
        return bytes.length === 0 || bytes[bytes.length - 1] !== 0x0a;
      }),
    );
  });
});
