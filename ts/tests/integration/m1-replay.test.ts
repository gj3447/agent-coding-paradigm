/**
 * M1 replay sequence: fold stepF over the frozen event sequence and compare
 * per-step transition digests and the final revision with the corpus.
 */

import { describe, expect, it } from "vitest";
import type { JsonObject, JsonValue } from "../../src/contracts/json-value";
import { stepF } from "../../src/domain/kernel";
import {
  asArr,
  asObj,
  asStr,
  loadFixture,
  materializeReplaySequence,
} from "../helpers/fixtures";

const corpus = asObj(loadFixture("fixtures/m1/cases.json"), "m1 corpus");

describe("m1 replay sequences", () => {
  for (const sequence of asArr(corpus.get("replay_sequences"), "replay_sequences")) {
    const sequenceValue = asObj(sequence, "sequence");
    const id = asStr(sequenceValue.get("id"), "id");
    it(id, () => {
      const { initial, events } = materializeReplaySequence(corpus, sequenceValue);
      const digests: JsonValue[] = [];
      let snapshot: JsonObject = initial;
      for (const event of events) {
        const result = stepF(snapshot, event);
        expect(result.get("kind"), id).toBe("FTransition");
        digests.push(result.get("transition_digest") as JsonValue);
        snapshot = asObj(result.get("next_snapshot"), "next_snapshot");
      }
      expect(digests, id).toEqual(asArr(sequenceValue.get("expected_transition_digests"), "expected"));
      expect(snapshot.get("revision"), id).toBe(sequenceValue.get("expected_final_revision"));
    });
  }
});
