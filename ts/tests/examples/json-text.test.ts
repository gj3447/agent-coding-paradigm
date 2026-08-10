/**
 * Lexical parser unit checks: the exact distinctions JSON.parse cannot make.
 */

import { describe, expect, it } from "vitest";
import { parseJsonText } from "../../src/contracts/json-text";
import { JsonFloat } from "../../src/contracts/json-value";

describe("lexical JSON parser", () => {
  it("keeps int64 boundary values exact", () => {
    expect(parseJsonText("9223372036854775807")).toBe(9223372036854775807n);
    expect(parseJsonText("9223372036854775808")).toBe(9223372036854775808n);
    expect(parseJsonText("-9223372036854775808")).toBe(-9223372036854775808n);
  });

  it("classifies float lexemes as floats even when integral", () => {
    for (const text of ["1.0", "0.5", "1e2", "1E2", "2e0"]) {
      const value = parseJsonText(text);
      expect(value, text).toBeInstanceOf(JsonFloat);
    }
    expect(parseJsonText("-0")).toBe(0n);
  });

  it("accepts NaN/Infinity constants as floats like Python json.loads", () => {
    for (const text of ["NaN", "Infinity", "-Infinity"]) {
      expect(parseJsonText(text), text).toBeInstanceOf(JsonFloat);
    }
    const nested = parseJsonText('{"a":NaN}') as Map<string, unknown>;
    expect(nested.get("a")).toBeInstanceOf(JsonFloat);
    expect(() => parseJsonText("Infinit")).toThrow();
  });

  it("preserves lone surrogate escapes for the canonicalizer to reject", () => {
    const value = parseJsonText('"\\ud800"') as string;
    expect(value.charCodeAt(0)).toBe(0xd800);
  });

  it("keeps the last duplicate key like Python json.loads", () => {
    const value = parseJsonText('{"a":1,"a":2}') as Map<string, bigint>;
    expect(value.get("a")).toBe(2n);
    expect(value.size).toBe(1);
  });

  it("rejects trailing content and bad escapes", () => {
    expect(() => parseJsonText("{} x")).toThrow();
    expect(() => parseJsonText('"\\q"')).toThrow();
    expect(() => parseJsonText("01")).toThrow();
  });
});
