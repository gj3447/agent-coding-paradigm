import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm, stat, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { Effect, Either } from "effect";

import {
  makeNodeCommandExecutorLive,
  NodeFileStoreLive,
} from "../src/node-runtime.js";
import { CommandExecutor, CommandFailure, FileStore } from "../src/ports.js";

const run = (
  args: readonly string[],
  timeoutMs: number,
  maxOutputBytes = 1024,
) =>
  Effect.gen(function* () {
    const executor = yield* CommandExecutor;
    return yield* executor.run({
      command: process.execPath,
      args,
      cwd: process.cwd(),
      timeoutMs,
      maxOutputBytes,
    });
  }).pipe(Effect.provide(makeNodeCommandExecutorLive(process.env)));

test("node command adapter preserves nonzero exits as observations", async () => {
  const result = await Effect.runPromise(
    run(["-e", "process.stderr.write('expected'); process.exit(7)"], 2_000),
  );
  assert.equal(result.exitCode, 7);
  assert.equal(new TextDecoder().decode(result.stderr), "expected");
});

test("node command adapter bounds time and output", async () => {
  const timeout = await Effect.runPromiseExit(
    run(["-e", "setTimeout(() => {}, 10_000)"], 50),
  );
  assert.equal(timeout._tag, "Failure");

  const output = await Effect.runPromise(
    run(["-e", "process.stdout.write('x'.repeat(2048))"], 2_000, 64).pipe(
      Effect.either,
    ),
  );
  assert.equal(Either.isLeft(output), true);
  if (Either.isLeft(output)) {
    assert.equal(output.left instanceof CommandFailure, true);
    assert.equal(output.left.reason, "output_limit");
  }
});

test("timeout terminates the subprocess group before it can mutate later", async () => {
  const root = await mkdtemp(join(tmpdir(), "coding-corpus-process-group-"));
  const marker = join(root, "late-write");
  const child = [
    "const {spawn}=require('node:child_process');",
    "const target=process.argv[1];",
    "spawn(process.execPath,['-e',`setTimeout(()=>require('node:fs').writeFileSync(process.argv[1],'late'),500)`,target],{stdio:'ignore'});",
    "setTimeout(()=>{},10000);",
  ].join("");
  try {
    const result = await Effect.runPromise(
      run(["-e", child, marker], 50).pipe(Effect.either),
    );
    assert.equal(Either.isLeft(result), true);
    if (Either.isLeft(result)) assert.equal(result.left.reason, "timeout");
    await new Promise((resolve) => setTimeout(resolve, 650));
    await assert.rejects(readFile(marker));
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("root-bounded writes reject symlink parents without touching the outside file", async () => {
  const root = await mkdtemp(join(tmpdir(), "coding-corpus-secure-write-"));
  const checkout = join(root, "checkout");
  const outside = join(root, "outside");
  const marker = join(outside, "marker.py");
  await mkdir(checkout);
  await mkdir(outside);
  await writeFile(marker, "original");
  await symlink(outside, join(checkout, "tests"));
  try {
    const result = await Effect.runPromise(
      Effect.gen(function* () {
        const files = yield* FileStore;
        return yield* files.writeBytesWithinRoot(
          checkout,
          "tests/marker.py",
          new TextEncoder().encode("replaced"),
        );
      }).pipe(Effect.provide(NodeFileStoreLive), Effect.either),
    );
    assert.equal(Either.isLeft(result), true);
    assert.equal(await readFile(marker, "utf8"), "original");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("root-bounded writes preserve the admitted executable mode", async () => {
  const root = await mkdtemp(join(tmpdir(), "coding-corpus-mode-"));
  try {
    await Effect.runPromise(
      Effect.gen(function* () {
        const files = yield* FileStore;
        yield* files.writeBytesWithinRoot(
          root,
          "scripts/check.py",
          new TextEncoder().encode("#!/usr/bin/env python3\n"),
          0o755,
        );
      }).pipe(Effect.provide(NodeFileStoreLive)),
    );
    assert.equal((await stat(join(root, "scripts/check.py"))).mode & 0o777, 0o755);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
