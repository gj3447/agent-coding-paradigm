import assert from "node:assert/strict";
import test from "node:test";

import { Effect, Either } from "effect";

import {
  AIDER_CONTROL_MODEL,
  buildComparisonArmPlan,
  comparisonEnvironment,
  readComparisonSecret,
  REACT_MODEL,
  type ComparisonRequest,
} from "../src/comparison.js";
import { FileStore, type FileStoreService } from "../src/ports.js";

const request = (arm: string): ComparisonRequest => ({
  arm,
  inspectExecutable: "/venv/bin/inspect",
  taskPath: "/harness/task.py",
  corpusPath: "/harness/pilot.jsonl",
  repositoryPath: "/workspace/repository",
  logDirectory: "/logs",
  dgxBaseUrl: "http://dgx.internal:18000/v1",
  dgxKeyFile: "/run/secrets/dgx-key",
});

const admittedPlan = (arm: string) => {
  const result = buildComparisonArmPlan(request(arm));
  if (!result.ok) throw new Error(result.error.reason);
  assert.equal(result.ok, true);
  return result.value;
};

test("ReAct and Aider are bounded but remain ineligible for efficacy comparison", () => {
  const react = admittedPlan("react");
  const aider = admittedPlan("aider");
  for (const plan of [react, aider]) {
    const command = plan.command.join("\n");
    assert.match(command, /--max-samples\n1/u);
    assert.match(command, /--max-sandboxes\n1/u);
    assert.match(command, /--max-retries\n0/u);
    assert.match(command, /--token-limit\n32000/u);
    assert.match(command, /--temperature\n0/u);
    assert.doesNotMatch(command, /secret|api.?key/iu);
  }
  assert.equal(
    react.command[react.command.indexOf("--model") + 1],
    REACT_MODEL,
  );
  assert.equal(
    aider.command[aider.command.indexOf("--model") + 1],
    AIDER_CONTROL_MODEL,
  );
  assert.equal(react.command.includes("--model-base-url"), true);
  assert.equal(aider.command.includes("--model-base-url"), false);
  assert.equal(react.budgetSemantics, "inspect_total_tokens");
  assert.equal(aider.budgetSemantics, "gateway_completion_tokens");
  assert.equal(react.efficacyComparable, false);
  assert.equal(aider.efficacyComparable, false);
});

test("unknown arms and malformed operator endpoints fail closed", () => {
  const unknown = buildComparisonArmPlan(request("typo"));
  assert.equal(unknown.ok, false);
  if (!unknown.ok) assert.match(unknown.error.reason, /unsupported arm/u);

  for (const dgxBaseUrl of [
    "https://dgx.internal:18000/v1",
    "http://dgx.internal/v1",
    "http://[::1]:18000/v1",
    "http://dgx.internal:18000/other",
  ]) {
    const malformed = buildComparisonArmPlan({
      ...request("react"),
      dgxBaseUrl,
    });
    assert.equal(malformed.ok, false);
  }
});

test("secret binding stays outside argv and differs by execution arm", () => {
  const react = admittedPlan("react");
  const aider = admittedPlan("aider");
  const secret = "bounded-private-value";

  assert.deepEqual(comparisonEnvironment(react, secret), {
    DGX_API_KEY: secret,
  });
  assert.deepEqual(comparisonEnvironment(aider, secret), {
    MODEL_GATEWAY_UPSTREAM_HOST: "dgx.internal",
    MODEL_GATEWAY_UPSTREAM_PORT: "18000",
    DGX_API_KEY_FILE: "/run/secrets/dgx-key",
  });
  assert.equal(react.command.includes(secret), false);
  assert.equal(aider.command.includes(secret), false);
});

test("Effect secret read is lazy and rejects empty or multiline values", async () => {
  let reads = 0;
  const makeFiles = (content: string): FileStoreService => ({
    readText: () =>
      Effect.sync(() => {
        reads += 1;
        return content;
      }),
    writeBytes: () => Effect.die("unused"),
    writeBytesAtomic: () => Effect.die("unused"),
    makeDirectory: () => Effect.die("unused"),
    makeTempDirectory: () => Effect.die("unused"),
    remove: () => Effect.die("unused"),
  });

  const program = readComparisonSecret("/secret").pipe(
    Effect.provideService(FileStore, makeFiles("bounded-value\n")),
  );
  assert.equal(reads, 0);
  assert.equal(await Effect.runPromise(program), "bounded-value");
  assert.equal(reads, 1);

  for (const invalid of ["\n", "first\nsecond"]) {
    const result = await Effect.runPromise(
      readComparisonSecret("/secret").pipe(
        Effect.provideService(FileStore, makeFiles(invalid)),
        Effect.either,
      ),
    );
    assert.equal(Either.isLeft(result), true);
    if (Either.isLeft(result)) {
      assert.match(result.left.message, /empty or malformed/u);
    }
  }
});
