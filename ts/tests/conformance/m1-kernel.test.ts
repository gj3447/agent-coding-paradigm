/**
 * M1 kernel conformance against fixtures/m1/cases.json and the frozen golden
 * files. The judgement is byte identity of canonical output with the Python
 * reference (scripts/validate_m1.py is the oracle procedure being mirrored).
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { Ajv2020 } from "ajv/dist/2020.js";
import { describe, expect, it } from "vitest";
import { canonicalBytes } from "../../src/contracts/canonical";
import { parseJsonText } from "../../src/contracts/json-text";
import type { JsonObject, JsonValue } from "../../src/contracts/json-value";
import { stepF } from "../../src/domain/kernel";
import {
  asArr,
  asObj,
  asStr,
  findCase,
  loadFixture,
  materializeCase,
  readFixtureBytes,
  repoRoot,
} from "../helpers/fixtures";

const corpus = asObj(loadFixture("fixtures/m1/cases.json"), "m1 corpus");

const m1Schema = JSON.parse(
  readFileSync(path.join(repoRoot, "spec/schema/m1-kernel.v1.schema.json"), "utf-8"),
) as { $defs: Record<string, unknown> };
const protocolSchema = JSON.parse(
  readFileSync(path.join(repoRoot, "spec/schema/protocol.v1.schema.json"), "utf-8"),
) as Record<string, unknown>;
const ajv = new Ajv2020({ strict: false, allErrors: true, validateFormats: false });
ajv.addSchema(protocolSchema);
const resultValidators = {
  FTransition: ajv.compile({
    $schema: "https://json-schema.org/draft/2020-12/schema",
    $ref: "#/$defs/FTransition",
    $defs: m1Schema.$defs,
  }),
  FRejection: ajv.compile({
    $schema: "https://json-schema.org/draft/2020-12/schema",
    $ref: "#/$defs/FRejection",
    $defs: m1Schema.$defs,
  }),
};

/** Validate the wire result against the normative M1 schema. Skipped when the
 * canonical text carries integers beyond double precision — JSON.parse would
 * round them and produce false schema verdicts (int64-boundary cases). */
const expectSchemaValid = (result: JsonObject, label: string): void => {
  const text = Buffer.from(canonicalBytes(result)).toString("utf-8");
  if (/\d{16,}/.test(text)) {
    return;
  }
  const kind = result.get("kind") as "FTransition" | "FRejection";
  const validator = resultValidators[kind];
  expect(validator, `${label}: unknown result kind ${kind}`).toBeDefined();
  expect(
    validator(JSON.parse(text)),
    `${label}: ${JSON.stringify(validator.errors)}`,
  ).toBe(true);
};

/** Canonical bytes, or null when the input itself is non-canonicalizable
 * (those rejection cases are exactly what stepF must handle internally). */
const tryCanonical = (value: JsonValue): Buffer | null => {
  try {
    return Buffer.from(canonicalBytes(value));
  } catch {
    return null;
  }
};

const runCase = (caseValue: JsonObject): { result: JsonObject; document: JsonObject } => {
  const document = materializeCase(corpus, caseValue);
  const snapshot = document.get("snapshot") as JsonValue;
  const event = document.get("accepted_event") as JsonValue;
  const before: readonly [Buffer | null, Buffer | null] = [
    tryCanonical(snapshot),
    tryCanonical(event),
  ];
  const result = stepF(snapshot, event);
  const after: readonly [Buffer | null, Buffer | null] = [
    tryCanonical(snapshot),
    tryCanonical(event),
  ];
  for (const [beforeBytes, afterBytes, label] of [
    [before[0], after[0], "snapshot"],
    [before[1], after[1], "event"],
  ] as const) {
    if (beforeBytes === null) {
      expect(afterBytes, `${label} became canonicalizable after stepF`).toBeNull();
    } else {
      expect(afterBytes !== null && afterBytes.equals(beforeBytes), `${label} mutated by stepF`).toBe(
        true,
      );
    }
  }
  expectSchemaValid(result, (caseValue.get("id") as string | undefined) ?? "case");
  return { result, document };
};

describe("m1 success cases", () => {
  for (const caseValue of asArr(corpus.get("success_cases"), "success_cases")) {
    const successCase = asObj(caseValue, "case");
    const id = asStr(successCase.get("id"), "id");
    it(id, () => {
      const { result } = runCase(successCase);
      expect(result.get("kind"), id).toBe("FTransition");
      expect(result.get("transition_digest"), id).toBe(
        asStr(successCase.get("expected_transition_digest"), "expected_transition_digest"),
      );
      const nextSnapshot = asObj(result.get("next_snapshot"), "next_snapshot");
      expect(nextSnapshot.get("revision"), id).toBe(successCase.get("expected_next_revision"));
      expect(nextSnapshot.get("phase"), id).toBe(successCase.get("expected_next_phase"));
      expect(BigInt(asArr(result.get("fact_deltas"), "fact_deltas").length), id).toBe(
        successCase.get("expected_fact_delta_count"),
      );
      expect(BigInt(asArr(result.get("effect_proposals"), "effect_proposals").length), id).toBe(
        successCase.get("expected_effect_proposal_count"),
      );
    });
  }
});

describe("m1 rejection cases", () => {
  for (const caseValue of asArr(corpus.get("rejection_cases"), "rejection_cases")) {
    const rejectionCase = asObj(caseValue, "case");
    const id = asStr(rejectionCase.get("id"), "id");
    it(id, () => {
      const { result } = runCase(rejectionCase);
      expect(result.get("kind"), id).toBe("FRejection");
      expect(result.get("code"), id).toBe(rejectionCase.get("expected_code"));
      expect(result.get("path"), id).toBe(rejectionCase.get("expected_path"));
      const expectedContext = rejectionCase.get("expected_context") as JsonValue;
      const actualContext = result.get("context") as JsonValue;
      expect(
        Buffer.from(canonicalBytes(actualContext)).toString("utf-8"),
        id,
      ).toBe(Buffer.from(canonicalBytes(expectedContext)).toString("utf-8"));
    });
  }
});

describe("m1 exact result goldens", () => {
  const goldens: ReadonlyArray<readonly [string, string]> = [
    ["observe-with-effect", "fixtures/m1/golden/observe-with-effect.transition.json"],
    ["invalid-calendar-timestamp", "fixtures/m1/golden/invalid-calendar-timestamp.rejection.json"],
  ];
  for (const [caseId, goldenPath] of goldens) {
    it(`${caseId} matches ${goldenPath} byte-for-byte`, () => {
      const raw = readFixtureBytes(goldenPath);
      expect(raw[raw.length - 1], "golden must end with newline").toBe(0x0a);
      expect(raw.filter((byte) => byte === 0x0a).length, "exactly one newline").toBe(1);
      const body = raw.subarray(0, raw.length - 1);
      const parsedGolden = parseJsonText(body.toString("utf-8"));
      expect(
        Buffer.from(canonicalBytes(parsedGolden)).equals(body),
        "golden file is itself canonical",
      ).toBe(true);
      const { result } = runCase(findCase(corpus, caseId));
      expect(Buffer.from(canonicalBytes(result)).equals(body), "actual result bytes").toBe(true);
    });
  }
});

describe("m1 equivalence pairs", () => {
  for (const pair of asArr(corpus.get("equivalence_pairs"), "equivalence_pairs")) {
    const pairValue = asObj(pair, "pair");
    const leftId = asStr(pairValue.get("left_case_id"), "left_case_id");
    const rightId = asStr(pairValue.get("right_case_id"), "right_case_id");
    it(`${leftId} == ${rightId}`, () => {
      const left = runCase(findCase(corpus, leftId)).result;
      const right = runCase(findCase(corpus, rightId)).result;
      expect(Buffer.from(canonicalBytes(left)).equals(Buffer.from(canonicalBytes(right)))).toBe(
        true,
      );
    });
  }
});

/** JSON Pointer over wire values (Maps/arrays), mirroring validate_m1._at_pointer. */
const atPointer = (value: JsonValue, pointer: string): JsonValue => {
  let current: JsonValue = value;
  for (const rawToken of pointer.split("/").slice(1)) {
    const token = rawToken.replaceAll("~1", "/").replaceAll("~0", "~");
    current = Array.isArray(current)
      ? (current[Number.parseInt(token, 10)] as JsonValue)
      : (asObj(current, pointer).get(token) as JsonValue);
  }
  return current;
};

describe("m1 sensitivity mutations", () => {
  for (const caseValue of asArr(corpus.get("sensitivity_mutations"), "sensitivity_mutations")) {
    const sensitivityCase = asObj(caseValue, "case");
    const id = asStr(sensitivityCase.get("id"), "id");
    it(id, () => {
      const base = runCase(
        findCase(corpus, asStr(sensitivityCase.get("input_ref"), "input_ref")),
      ).result;
      const mutated = runCase(sensitivityCase).result;
      const relation = asStr(sensitivityCase.get("expected_relation"), "expected_relation");
      if (relation === "typed_rejection") {
        expect(mutated.get("kind"), id).toBe("FRejection");
      } else {
        expect(relation, id).toBe("different_transition");
        expect(mutated.get("kind"), id).toBe("FTransition");
        expect(mutated.get("transition_digest"), id).not.toBe(base.get("transition_digest"));
        for (const pointer of (sensitivityCase.get("identity_paths") as JsonValue[] | undefined) ??
          []) {
          const where = pointer as string;
          expect(
            Buffer.from(canonicalBytes(atPointer(base, where) ?? null)).toString("utf-8"),
            `${id}: identity collision at ${where}`,
          ).not.toBe(Buffer.from(canonicalBytes(atPointer(mutated, where) ?? null)).toString("utf-8"));
        }
      }
    });
  }
});
