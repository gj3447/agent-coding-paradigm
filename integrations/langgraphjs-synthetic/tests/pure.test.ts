import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  canonicalDigest,
  canonicalJson,
  decideIntent,
  hasVerifiedCompletion,
  type CompletionFacts,
} from "../src/index.js";

describe("deterministic functional core", () => {
  it("orders object keys by stable code units rather than ambient locale", () => {
    assert.equal(canonicalJson({ "ä": 1, z: 2 }), '{"z":2,"ä":1}');
  });

  it("rejects non-NFC strings and object keys", () => {
    assert.throws(() => canonicalJson("e\u0301"), /NFC/u);
    assert.throws(() => canonicalJson({ "e\u0301": 1 }), /NFC/u);
  });

  it("requires every positive prerequisite before verified completion", () => {
    const intent = {
      intentId: "intent:completion",
      idempotencyKey: "idempotency:completion",
      action: "write_synthetic_analysis_artifact",
      payload: { marker: "SYNTHETIC" },
    };
    const intentDigest = canonicalDigest(intent);
    const receipt = {
      kind: "action_receipt" as const,
      intentId: intent.intentId,
      idempotencyKey: intent.idempotencyKey,
      artifactId: "artifact:completion",
      artifactDigest: canonicalDigest({ artifact: "completion" }),
      intentDigest,
      producerComponentId: "effect:completion",
    };
    const base: CompletionFacts = {
      decision: "accepted",
      eligibility: "eligible",
      stable: true,
      intentCommitted: true,
      approvalStatus: "not_required",
      runId: "run:completion",
      intent,
      intentDigest,
      effectObservation: { kind: "confirmed_success", receipt },
      verification: {
        kind: "verified",
        verifierComponentId: "verifier:completion",
        runId: "run:completion",
        intentDigest,
        actionReceiptDigest: canonicalDigest(receipt),
        observedArtifactDigest: receipt.artifactDigest,
        reason: "independent observation matched",
      },
      expectedProducerComponentId: "effect:completion",
      expectedVerifierComponentId: "verifier:completion",
    };

    assert.equal(hasVerifiedCompletion(base), true);
    assert.equal(hasVerifiedCompletion({ ...base, stable: false }), false);
    assert.equal(
      hasVerifiedCompletion({ ...base, intentCommitted: false }),
      false,
    );
    assert.equal(
      hasVerifiedCompletion({ ...base, approvalStatus: "pending" }),
      false,
    );
    assert.equal(
      hasVerifiedCompletion({
        ...base,
        expectedProducerComponentId: "effect:other",
      }),
      false,
    );
  });

  it("treats either reused external identity with different intent as conflict", () => {
    const current = {
      intentId: "intent:new",
      idempotencyKey: "idempotency:shared",
      action: "write-new",
      payload: { marker: "NEW" },
    };
    const input = {
      schemaVersion: "flrh-langgraphjs-input/1" as const,
      profileVersion: "shared-accelerator-synthetic/1" as const,
      runId: "run:identity-axis",
      availableHeadroom: 8,
      requiredHeadroom: 4,
      timeoutMs: 5_000,
      approval: {
        required: false,
        deadlineAt: "2026-08-11T16:00:00Z",
      },
      intent: current,
      priorIntent: {
        intentId: "intent:old",
        idempotencyKey: current.idempotencyKey,
        action: "write-old",
        payload: { marker: "OLD" },
      },
    };

    assert.equal(decideIntent(input), "conflict");
    assert.equal(
      decideIntent({ ...input, priorIntent: { ...current } }),
      "accepted",
    );
  });
});
