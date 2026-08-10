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
  SET_LIKE_PATHS_BY_KIND,
} from "../../src/contracts/canonical";
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

describe("frozen m1 corpus count gates", () => {
  const corpus = asObj(loadFixture("fixtures/m1/cases.json"), "m1 corpus");
  const gates: ReadonlyArray<readonly [string, number]> = [
    ["success_cases", 7],
    ["rejection_cases", 19],
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
