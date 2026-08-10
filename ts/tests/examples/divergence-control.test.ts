/** Positive controls for the two repaired divergences: the audit's exact NFC
 * repro and a depth-200 document must now match the Python verdicts. */
import { describe, expect, it } from "vitest";
import type { JsonObject, JsonValue } from "../../src/contracts/json-value";
import { deepCopyJson } from "../../src/contracts/json-value";
import { jsonObject } from "../../src/contracts/json-value";
import { stepF } from "../../src/domain/kernel";
import { asObj, loadFixture } from "../helpers/fixtures";

const corpus = asObj(loadFixture("fixtures/m1/cases.json"), "m1 corpus");
const base = () =>
  asObj(
    deepCopyJson(asObj(asObj(corpus.get("base_inputs"), "base").get("observe-no-effect"), "doc")),
    "doc",
  );

describe("repaired divergence controls (Python verdicts from the same repro)", () => {
  it("accepts the audit's unassigned-codepoint NFC string with the oracle digest", () => {
    const document = base();
    const payload = asObj(asObj(document.get("accepted_event"), "evt").get("payload"), "payload");
    payload.set("observation", jsonObject([["note", "̖ࢗ"]]));
    const result = stepF(document.get("snapshot") as JsonValue, document.get("accepted_event") as JsonValue);
    expect(result.get("kind")).toBe("FTransition");
    expect(result.get("transition_digest")).toBe(
      "sha256:51a42a18a53a6333fe54b1605af3f471716fca507ca667b04332e33b0981f54e",
    );
  });

  it("rejects depth-200 nesting exactly like the oracle", () => {
    const document = base();
    const payload = asObj(asObj(document.get("accepted_event"), "evt").get("payload"), "payload");
    let deep: JsonValue = null;
    for (let i = 0; i < 200; i += 1) {
      deep = [deep];
    }
    payload.set("observation", jsonObject([["deep", deep]]));
    const result = stepF(document.get("snapshot") as JsonValue, document.get("accepted_event") as JsonValue) as JsonObject;
    expect(result.get("kind")).toBe("FRejection");
    expect(result.get("code")).toBe("CANONICALIZATION_VIOLATION");
    expect((result.get("context") as JsonObject).get("canonical_code")).toBe(
      "NESTING_DEPTH_EXCEEDED",
    );
    expect((result.get("path") as string).startsWith("/accepted_event/payload/observation/deep")).toBe(
      true,
    );
  });
});
