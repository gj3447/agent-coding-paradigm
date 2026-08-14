import assert from "node:assert/strict";
import { dirname } from "node:path";
import test from "node:test";

import { Deferred, Effect, Either, Fiber } from "effect";

import {
  AIDER_CONTROL_MODEL,
  buildComparisonArmPlan,
  ComparisonFailure,
  comparisonEnvironment,
  readComparisonSecret,
  REACT_MODEL,
  runAdmittedComparison,
  selectComparisonControllerEnvironment,
  summarizeInspectLog,
  type ComparisonRequest,
} from "../src/comparison.js";
import {
  CommandExecutor,
  CommandFailure,
  type CommandExecutorService,
  type CommandResult,
  type CommandSpec,
  FileStore,
  type FileStoreService,
} from "../src/ports.js";

const ENCODER = new TextEncoder();
const HEAD = "0123456789abcdef0123456789abcdef01234567";
const SECRET = "bounded-private-value";

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
  assert.deepEqual(react.operatorEndpoint, aider.operatorEndpoint);
  assert.deepEqual(react.operatorEndpoint, {
    baseUrl: "http://dgx.internal:18000/v1",
    host: "dgx.internal",
    port: "18000",
  });
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
    writeBytesWithinRoot: () => Effect.die("unused"),
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
      assert.equal(result.left instanceof ComparisonFailure, true);
      if (result.left instanceof ComparisonFailure) {
        assert.match(result.left.reason, /empty or malformed/u);
      }
    }
  }
});

test("controller environment drops ambient config and derives the rootless Docker socket", () => {
  const selected = selectComparisonControllerEnvironment({
    PATH: "/attacker/bin",
    HOME: "/home/ambient",
    XDG_CONFIG_HOME: "/ambient/config",
    XDG_RUNTIME_DIR: "/run/user/1000",
    OPENAI_API_KEY: "must-not-pass",
  });
  assert.equal(
    selected["PATH"],
    `${dirname(process.execPath)}:/usr/local/bin:/usr/bin:/bin`,
  );
  assert.equal(selected["HOME"], "/nonexistent");
  assert.equal(selected["XDG_CONFIG_HOME"], undefined);
  assert.equal(selected["OPENAI_API_KEY"], undefined);
  assert.equal(selected["GIT_NO_LAZY_FETCH"], "1");
  assert.equal(selected["GIT_NO_REPLACE_OBJECTS"], "1");
  assert.equal(selected["GIT_TERMINAL_PROMPT"], "0");
  assert.equal(selected["XDG_RUNTIME_DIR"], "/run/user/1000");
  assert.equal(
    selected["DOCKER_HOST"],
    "unix:///run/user/1000/docker.sock",
  );
});

const commandResult = (
  stdout: string,
  exitCode = 0,
  stderr = "",
): CommandResult => ({
  exitCode,
  stdout: ENCODER.encode(stdout),
  stderr: ENCODER.encode(stderr),
});

const logFixture = (
  arm: "react" | "aider",
): Readonly<Record<string, unknown>> => ({
  version: 2,
  status: "success",
  eval: { task_version: "fixture-v1" },
  stats: {
    started_at: "2026-08-14T00:00:00Z",
    completed_at: "2026-08-14T00:00:01Z",
  },
  samples: [
    {
      id: `${arm}-case`,
      scores: { repository_verifier: { value: "C" } },
      total_time: 1,
      working_time: 0.75,
      turn_count: 1,
      token_limit_usage: 100,
      model_usage: { model: { input_tokens: 80, output_tokens: 20 } },
      output: {
        metadata:
          arm === "aider"
            ? {
                gateway_validation: {
                  schema_version: "model-gateway-validation/v2",
                  valid: true,
                  error: null,
                  metrics: {
                    schema_version: "model-gateway-metrics/v2",
                    usage: {
                      prompt_tokens: 80,
                      completion_tokens: 20,
                      total_tokens: 100,
                    },
                  },
                },
              }
            : {},
      },
      error: null,
    },
  ],
});

const comparisonFiles = (
  atomicWrites: Array<{ path: string; mode: number | undefined }> = [],
): FileStoreService => ({
  readText: () => Effect.succeed(`${SECRET}\n`),
  writeBytes: () => Effect.die("unused"),
  writeBytesWithinRoot: () => Effect.die("unused"),
  writeBytesAtomic: (path, _content, mode) =>
    Effect.sync(() => {
      atomicWrites.push({ path, mode });
    }),
  makeDirectory: () => Effect.void,
  makeTempDirectory: () => Effect.succeed("/tmp/controller"),
  remove: () => Effect.void,
});

const admittedComparisonRequest = (arms: readonly ("react" | "aider")[]) => ({
  arms,
  inspectExecutable: "/venv/bin/inspect",
  taskPath: "/harness/task.py",
  corpusPath: "/harness/pilot.jsonl",
  corpusSourcePath: "/source/pilot.jsonl",
  corpusSha256: "a".repeat(64),
  repositoryPath: "/workspace/repository",
  logDirectory: "/logs",
  dgxBaseUrl: "http://dgx.internal:18000/v1",
  dgxKeyFile: "/run/secrets/dgx-key",
});

test("Effect orchestration runs both fake Inspect arms sequentially and summarizes their logs", async () => {
  const specs: CommandSpec[] = [];
  const atomicWrites: Array<{ path: string; mode: number | undefined }> = [];
  const listingSnapshots = [
    [],
    ["/logs/react.eval"],
    [],
    ["/logs/aider.eval"],
  ] as const;
  let listing = 0;
  const commands: CommandExecutorService = {
    run: (spec) =>
      Effect.sync(() => {
        specs.push(spec);
        if (spec.command === "git") return commandResult(`${HEAD}\n`);
        if (spec.args[0] === "log" && spec.args[1] === "list") {
          const snapshot = listingSnapshots[listing];
          listing += 1;
          if (snapshot === undefined) throw new Error("unexpected log listing");
          return commandResult(
            JSON.stringify(snapshot.map((name) => ({ name }))),
          );
        }
        if (spec.args[0] === "log" && spec.args[1] === "dump") {
          const arm = spec.args[2]?.includes("aider") === true ? "aider" : "react";
          return commandResult(JSON.stringify(logFixture(arm)));
        }
        if (spec.args[0] === "eval") return commandResult("");
        throw new Error(`unexpected command: ${spec.command} ${spec.args.join(" ")}`);
      }),
  };

  const report = await Effect.runPromise(
    runAdmittedComparison(admittedComparisonRequest(["react", "aider"])).pipe(
      Effect.provideService(CommandExecutor, commands),
      Effect.provideService(FileStore, comparisonFiles(atomicWrites)),
    ),
  );

  assert.equal(report.efficacy_comparable, false);
  assert.deepEqual(atomicWrites, [
    { path: "/tmp/controller/.env", mode: undefined },
    { path: "/tmp/controller/dgx-api-key", mode: 0o644 },
  ]);
  assert.equal(report.non_comparability_reason, "arm_budget_semantics_differ");
  assert.equal(report.repository_head, HEAD);
  assert.deepEqual(
    report.arms.map((arm) => [arm.agent, arm.log, arm.command_exit]),
    [
      ["react", "/logs/react.eval", 0],
      ["aider", "/logs/aider.eval", 0],
    ],
  );
  assert.deepEqual(report.arms[1]?.samples[0]?.gateway_usage, {
    prompt_tokens: 80,
    completion_tokens: 20,
    total_tokens: 100,
  });
  assert.equal(report.arms[1]?.samples[0]?.gateway_valid, true);

  const evals = specs.filter((spec) => spec.args[0] === "eval");
  assert.equal(evals.length, 2);
  const react = evals[0];
  const aider = evals[1];
  assert.ok(react !== undefined && aider !== undefined);
  assert.equal(react.timeoutMs, 1_860_000);
  assert.equal(aider.timeoutMs, 1_860_000);
  assert.equal(react.maxOutputBytes, 8 * 1024 * 1024);
  assert.equal(aider.maxOutputBytes, 8 * 1024 * 1024);
  assert.equal(react.cwd, "/tmp/controller");
  assert.equal(aider.cwd, "/tmp/controller");
  assert.equal(react.environment?.["DGX_API_KEY"], SECRET);
  assert.equal(
    aider.environment?.["DGX_API_KEY_FILE"],
    "/tmp/controller/dgx-api-key",
  );
  assert.equal(aider.environment?.["MODEL_GATEWAY_UPSTREAM_HOST"], "dgx.internal");
  assert.equal(aider.environment?.["MODEL_GATEWAY_UPSTREAM_PORT"], "18000");
  assert.equal(react.args.join("\n").includes(SECRET), false);
  assert.equal(aider.args.join("\n").includes(SECRET), false);
});

test("a timed-out arm reconciles the log surface before returning a typed failure", async () => {
  let listCalls = 0;
  const commands: CommandExecutorService = {
    run: (spec) => {
      if (spec.command === "git") return Effect.succeed(commandResult(`${HEAD}\n`));
      if (spec.args[0] === "log" && spec.args[1] === "list") {
        listCalls += 1;
        return Effect.succeed(commandResult("[]"));
      }
      if (spec.args[0] === "eval") {
        return Effect.fail(
          new CommandFailure({
            command: spec.command,
            reason: "timeout",
            detail: `deadline included ${SECRET}`,
          }),
        );
      }
      return Effect.die("unexpected command");
    },
  };
  const result = await Effect.runPromise(
    runAdmittedComparison(admittedComparisonRequest(["react"])).pipe(
      Effect.provideService(CommandExecutor, commands),
      Effect.provideService(FileStore, comparisonFiles()),
      Effect.either,
    ),
  );
  assert.equal(listCalls, 2);
  assert.equal(Either.isLeft(result), true);
  if (Either.isLeft(result)) {
    assert.equal(result.left instanceof ComparisonFailure, true);
    if (result.left instanceof ComparisonFailure) {
      assert.equal(result.left.phase, "reconciliation");
      assert.match(result.left.reason, /timeout/u);
      assert.match(result.left.reason, /\[REDACTED\]/u);
      assert.equal(result.left.reason.includes(SECRET), false);
    }
  }
});

test("interrupting an arm cancels execution and performs one bounded reconciliation listing", async () => {
  let listCalls = 0;
  await Effect.runPromise(
    Effect.gen(function* () {
      const started = yield* Deferred.make<void>();
      const commands: CommandExecutorService = {
        run: (spec) => {
          if (spec.command === "git") {
            return Effect.succeed(commandResult(`${HEAD}\n`));
          }
          if (spec.args[0] === "log" && spec.args[1] === "list") {
            listCalls += 1;
            return Effect.succeed(commandResult("[]"));
          }
          if (spec.args[0] === "eval") {
            return Deferred.succeed(started, undefined).pipe(
              Effect.zipRight(Effect.never),
            );
          }
          return Effect.die("unexpected command");
        },
      };
      const program = runAdmittedComparison(
        admittedComparisonRequest(["react"]),
      ).pipe(
        Effect.provideService(CommandExecutor, commands),
        Effect.provideService(FileStore, comparisonFiles()),
      );
      const fiber = yield* Effect.fork(program);
      yield* Deferred.await(started);
      yield* Fiber.interrupt(fiber);
    }),
  );
  assert.equal(listCalls, 2);
});

test("malformed Inspect log fixtures fail the typed summary boundary", () => {
  const malformed = summarizeInspectLog("react", "/logs/bad.eval", {
    ...logFixture("react"),
    samples: [{ id: "bad-scores", scores: "not-an-object", output: {} }],
  });
  assert.equal(malformed.ok, false);
  if (!malformed.ok) assert.match(malformed.error.reason, /scores/u);
});

test("non-success and unvalidated Aider logs fail closed", () => {
  const failedStatus = summarizeInspectLog("react", "/logs/error.eval", {
    ...logFixture("react"),
    status: "error",
  });
  assert.equal(failedStatus.ok, false);
  if (!failedStatus.ok) assert.match(failedStatus.error.reason, /not success/u);

  const aider = logFixture("aider");
  const samples = aider["samples"] as readonly Record<string, unknown>[];
  const missingValidation = summarizeInspectLog("aider", "/logs/aider.eval", {
    ...aider,
    samples: [
      {
        ...samples[0],
        output: {
          metadata: {
            gateway_validation: {
              schema_version: "model-gateway-validation/v2",
              valid: true,
              error: null,
              metrics: null,
            },
          },
        },
      },
    ],
  });
  assert.equal(missingValidation.ok, false);
  if (!missingValidation.ok) {
    assert.match(missingValidation.error.reason, /gateway evidence/u);
  }
});

test("the final closed report rejects secret reflection from even an identifier field", async () => {
  let listing = 0;
  const commands: CommandExecutorService = {
    run: (spec) => {
      if (spec.command === "git") {
        return Effect.succeed(commandResult(`${HEAD}\n`));
      }
      if (spec.args[0] === "log" && spec.args[1] === "list") {
        listing += 1;
        return Effect.succeed(
          commandResult(
            listing === 1
              ? "[]"
              : JSON.stringify([{ name: "/logs/react.eval" }]),
          ),
        );
      }
      if (spec.args[0] === "eval") return Effect.succeed(commandResult(""));
      if (spec.args[0] === "log" && spec.args[1] === "dump") {
        const fixture = logFixture("react");
        const samples = fixture["samples"] as readonly Record<string, unknown>[];
        return Effect.succeed(
          commandResult(
            JSON.stringify({
              ...fixture,
              samples: [{ ...samples[0], id: SECRET }],
            }),
          ),
        );
      }
      return Effect.die("unexpected command");
    },
  };
  const result = await Effect.runPromise(
    runAdmittedComparison(admittedComparisonRequest(["react"])).pipe(
      Effect.provideService(CommandExecutor, commands),
      Effect.provideService(FileStore, comparisonFiles()),
      Effect.either,
    ),
  );
  assert.equal(Either.isLeft(result), true);
  if (Either.isLeft(result)) {
    assert.equal(result.left instanceof ComparisonFailure, true);
    if (result.left instanceof ComparisonFailure) {
      assert.match(result.left.reason, /contains the operator secret/u);
      assert.equal(result.left.reason.includes(SECRET), false);
    }
  }
});
