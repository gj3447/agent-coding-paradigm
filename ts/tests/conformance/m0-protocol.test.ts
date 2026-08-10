/**
 * M0 protocol-object conformance via JSON Schema Draft 2020-12 (Ajv).
 *
 * Checker-relative boundary: the Python oracle additionally matches
 * expected_keyword against jsonschema-4.25.1 message prose and requires
 * exactly one error; Ajv words errors differently, so this port asserts the
 * valid/invalid verdicts and the EffectIntent→ActionReceipt identity
 * preservation, which are the schema-level contract itself.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { Ajv2020 } from "ajv/dist/2020.js";
import { describe, expect, it } from "vitest";
import { asArr, asObj, asStr, repoRoot } from "../helpers/fixtures";

const protocolSchema = JSON.parse(
  readFileSync(path.join(repoRoot, "spec/schema/protocol.v1.schema.json"), "utf-8"),
) as Record<string, unknown>;

const validFixtures = JSON.parse(
  readFileSync(path.join(repoRoot, "fixtures/m0/valid/protocol-objects.json"), "utf-8"),
) as { cases: Array<{ id: string; instance: Record<string, unknown> }> };

const invalidFixtures = JSON.parse(
  readFileSync(path.join(repoRoot, "fixtures/m0/invalid/protocol-mutations.json"), "utf-8"),
) as { cases: Array<{ id: string; expected_keyword: string; instance: { kind: string } }> };

const ajv = new Ajv2020({ strict: false, allErrors: true, validateFormats: false });
const validateProtocol = ajv.compile(protocolSchema);

describe("m0 protocol fixtures", () => {
  it("accepts all valid protocol objects", () => {
    expect(validFixtures.cases.length).toBe(10);
    for (const { id, instance } of validFixtures.cases) {
      expect(validateProtocol(instance), `${id}: ${JSON.stringify(validateProtocol.errors)}`).toBe(
        true,
      );
    }
  });

  it("rejects every frozen protocol mutation via its kind branch", () => {
    expect(invalidFixtures.cases.length).toBe(13);
    for (const { id, instance } of invalidFixtures.cases) {
      const branchSchema = {
        $schema: "https://json-schema.org/draft/2020-12/schema",
        $ref: `#/$defs/${instance.kind}`,
        $defs: protocolSchema.$defs,
      };
      const validateBranch = new Ajv2020({
        strict: false,
        allErrors: true,
        validateFormats: false,
      }).compile(branchSchema);
      expect(validateBranch(instance), id).toBe(false);
    }
  });

  it("ActionReceipt preserves the committed EffectIntent identity fields", () => {
    const byKind = new Map(validFixtures.cases.map(({ instance }) => [instance.kind, instance]));
    const intent = byKind.get("EffectIntent") as Record<string, unknown>;
    const receipt = byKind.get("ActionReceipt") as Record<string, unknown>;
    const bindingFields = [
      "intent_id", "action_digest", "cause_id", "correlation_id", "capability",
      "authority_digest", "destination_digest", "goal_id", "obligation_id",
      "adapter_version", "assessed_risk", "approval_required", "approval_digest",
      "idempotency_key",
    ];
    for (const field of bindingFields) {
      expect(receipt[field], field).toEqual(intent[field]);
    }
  });
});
