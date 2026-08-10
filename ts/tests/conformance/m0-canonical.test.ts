/**
 * M0 canonicalization conformance against fixtures/m0/canonical/cases.json.
 *
 * reject_cases carry prose fragments from the Python M0 oracle's messages
 * (checker-relative); this suite maps them to the kernel-profile error codes,
 * which spec/canonicalization.v1.json fixes as the wire contract.
 */

import { describe, expect, it } from "vitest";
import {
  CanonicalizationError,
  canonicalBytes,
  canonicalDigest,
} from "../../src/contracts/canonical";
import type { JsonValue } from "../../src/contracts/json-value";
import { asArr, asObj, asStr, loadFixture } from "../helpers/fixtures";

const corpus = asObj(loadFixture("fixtures/m0/canonical/cases.json"), "canonical cases");

const FRAGMENT_TO_CODE: Record<string, string> = {
  "floating-point": "FLOAT_FORBIDDEN",
  NFC: "NON_NFC_STRING",
  int64: "INTEGER_OUTSIDE_INT64",
  "duplicate set-like": "DUPLICATE_SET_ELEMENT",
  "nesting depth": "NESTING_DEPTH_EXCEEDED",
};

describe("m0 canonical fixtures", () => {
  it("equal_pairs digest to the frozen value", () => {
    for (const pair of asArr(corpus.get("equal_pairs"), "equal_pairs")) {
      const pairValue = asObj(pair, "pair");
      const left = canonicalDigest(pairValue.get("left") as JsonValue);
      const right = canonicalDigest(pairValue.get("right") as JsonValue);
      const expected = asStr(pairValue.get("expected_digest"), "expected_digest");
      expect(left, asStr(pairValue.get("id"), "id")).toBe(expected);
      expect(right, asStr(pairValue.get("id"), "id")).toBe(expected);
    }
  });

  it("different_pairs digest differently", () => {
    for (const pair of asArr(corpus.get("different_pairs"), "different_pairs")) {
      const pairValue = asObj(pair, "pair");
      const left = canonicalDigest(pairValue.get("left") as JsonValue);
      const right = canonicalDigest(pairValue.get("right") as JsonValue);
      expect(left, asStr(pairValue.get("id"), "id")).not.toBe(right);
    }
  });

  it("reject_cases raise the mapped canonicalization code", () => {
    for (const rejectCase of asArr(corpus.get("reject_cases"), "reject_cases")) {
      const caseValue = asObj(rejectCase, "reject case");
      const id = asStr(caseValue.get("id"), "id");
      const expectedFragment = asStr(caseValue.get("expected"), "expected");
      const expectedCode = FRAGMENT_TO_CODE[expectedFragment];
      expect(expectedCode, `unmapped oracle fragment: ${expectedFragment}`).toBeDefined();
      let thrown: unknown = null;
      try {
        canonicalBytes(caseValue.get("input") as JsonValue);
      } catch (error) {
        thrown = error;
      }
      expect(thrown, id).toBeInstanceOf(CanonicalizationError);
      expect((thrown as CanonicalizationError).code, id).toBe(expectedCode);
    }
  });

  it("reproduces the documented golden bytes for the ordering pair", () => {
    const pairValue = asObj(
      asArr(corpus.get("equal_pairs"), "equal_pairs")[0],
      "first equal pair",
    );
    const bytes = canonicalBytes(pairValue.get("left") as JsonValue);
    expect(Buffer.from(bytes).toString("utf-8")).toBe(
      '{"causal_parent_delta_ids":["delta:1","delta:2"],"kind":"GraphDelta","logical_time":8,"producer_id":"producer:1"}',
    );
  });
});
