/**
 * The pure sha256 must agree with FIPS vectors and with node:crypto — the
 * producer is not the sole verifier of its own hash (invariant 9).
 */

import { createHash } from "node:crypto";
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { sha256Hex } from "../../src/contracts/sha256";

describe("sha256", () => {
  it("matches FIPS 180-4 vectors", () => {
    expect(sha256Hex(new Uint8Array())).toBe(
      "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    );
    expect(sha256Hex(new TextEncoder().encode("abc"))).toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    );
    expect(
      sha256Hex(
        new TextEncoder().encode("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"),
      ),
    ).toBe("248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1");
  });

  it("agrees with node:crypto on arbitrary input", () => {
    fc.assert(
      fc.property(fc.uint8Array({ maxLength: 300 }), (bytes) => {
        const expected = createHash("sha256").update(bytes).digest("hex");
        return sha256Hex(bytes) === expected;
      }),
    );
  });
});
