/**
 * Pins the TS canonicalizer's constants to the normative profile in
 * spec/canonicalization.v1.json, and the frozen M1 corpus shape to the counts
 * the Python oracle gates on — so a spec or corpus drift fails here instead of
 * silently diverging.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  CANONICAL_ALGORITHM,
  CANONICAL_ALGORITHM_VERSION,
  CANONICAL_MEDIA_TYPE,
  MAX_NESTING_DEPTH,
  SET_LIKE_PATHS_BY_KIND,
} from "../../src/contracts/canonical";
import { isAssignedAt15_1 } from "../../src/contracts/unicode-15-1-assigned";
import { asArr, asObj, loadFixture, repoRoot } from "../helpers/fixtures";

const spec = JSON.parse(
  readFileSync(path.join(repoRoot, "spec/canonicalization.v1.json"), "utf-8"),
) as {
  algorithm: string;
  algorithm_version: string | number;
  media_type: string;
  set_like_paths_by_kind: Record<string, string[]>;
};

describe("spec/canonicalization.v1.json pin", () => {
  it("matches algorithm identity", () => {
    expect(CANONICAL_ALGORITHM).toBe(spec.algorithm);
    expect(CANONICAL_ALGORITHM_VERSION).toBe(String(spec.algorithm_version));
    expect(CANONICAL_MEDIA_TYPE).toBe(spec.media_type);
  });

  it("matches the set-like path table exactly", () => {
    const specTable = Object.fromEntries(
      Object.entries(spec.set_like_paths_by_kind).map(([kind, paths]) => [kind, [...paths].sort()]),
    );
    const tsTable = Object.fromEntries(
      [...SET_LIKE_PATHS_BY_KIND.entries()].map(([kind, paths]) => [kind, [...paths].sort()]),
    );
    expect(tsTable).toEqual(specTable);
  });
});

describe("spec/canonicalization-clarifications.v1.json pin", () => {
  const clarifications = JSON.parse(
    readFileSync(path.join(repoRoot, "spec/canonicalization-clarifications.v1.json"), "utf-8"),
  ) as {
    clarifies: string;
    algorithm: string;
    algorithm_version: string;
    unicode: { unicode_version: string };
    limits: { max_nesting_depth: number };
  };

  it("binds the active profile and pins Unicode 15.1.0 plus the depth limit", () => {
    expect(clarifications.clarifies).toBe("spec/canonicalization.v1.json");
    expect(clarifications.algorithm).toBe(CANONICAL_ALGORITHM);
    expect(clarifications.algorithm_version).toBe(CANONICAL_ALGORITHM_VERSION);
    expect(clarifications.unicode.unicode_version).toBe("15.1.0");
    expect(clarifications.limits.max_nesting_depth).toBe(MAX_NESTING_DEPTH);
  });

  it("carries pinned assignment data matching the audit's divergence surface", () => {
    expect(isAssignedAt15_1(0x0316)).toBe(true);
    for (const codePoint of [0x0897, 0x113ce, 0x113cf, 0x113d0, 0x1612f, 0x1e5ee]) {
      expect(isAssignedAt15_1(codePoint), `U+${codePoint.toString(16)}`).toBe(false);
    }
  });
});

describe("frozen m1 corpus count gates", () => {
  const corpus = asObj(loadFixture("fixtures/m1/cases.json"), "m1 corpus");
  const gates: ReadonlyArray<readonly [string, number]> = [
    ["success_cases", 7],
    ["rejection_cases", 22],
    ["sensitivity_mutations", 7],
    ["equivalence_pairs", 1],
    ["replay_sequences", 1],
  ];
  for (const [group, count] of gates) {
    it(`${group} = ${count}`, () => {
      expect(asArr(corpus.get(group), group).length).toBe(count);
    });
  }
  it("base_inputs = 3 and replay steps = 2", () => {
    expect(asObj(corpus.get("base_inputs"), "base_inputs").size).toBe(3);
    const sequence = asObj(asArr(corpus.get("replay_sequences"), "seq")[0], "sequence");
    expect(asArr(sequence.get("steps"), "steps").length).toBe(2);
    expect(asArr(sequence.get("expected_transition_digests"), "digests").length).toBe(2);
  });
});
