import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import {
  constants,
  lstat,
  mkdir,
  mkdtemp,
  open,
  rename,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";

import { Effect, Layer } from "effect";

import {
  CommandExecutor,
  CommandFailure,
  type CommandResult,
  type CommandSpec,
  FileFailure,
  FileStore,
  type FileStoreService,
} from "./ports.js";

const errorDetail = (error: unknown): string =>
  error instanceof Error ? error.message : "unknown failure";

const fileFailure = (
  operation: FileFailure["operation"],
  path: string,
) =>
  (error: unknown): FileFailure =>
    new FileFailure({ operation, path, reason: errorDetail(error) });

const NodeFileStore: FileStoreService = {
  readText: (path, options) =>
    Effect.tryPromise({
      try: async (signal) => {
        const handle = await open(path, constants.O_RDONLY);
        try {
          const status = await handle.stat();
          const maximum = options?.maxBytes;
          if (maximum !== undefined && status.size > maximum) {
            throw new Error(`file exceeds ${maximum} bytes`);
          }
          const content = await handle.readFile({ encoding: "utf8", signal });
          if (
            maximum !== undefined &&
            Buffer.byteLength(content, "utf8") > maximum
          ) {
            throw new Error(`file exceeds ${maximum} bytes`);
          }
          return content;
        } finally {
          await handle.close();
        }
      },
      catch: fileFailure("read_text", path),
    }),
  writeBytes: (path, content) =>
    Effect.tryPromise({
      try: (signal) => writeFile(path, content, { signal }),
      catch: fileFailure("write_bytes", path),
    }),
  writeBytesWithinRoot: (root, relativePath, content, mode = 0o644) =>
    Effect.tryPromise({
      try: async () => {
        const resolvedRoot = resolve(root);
        const target = resolve(resolvedRoot, relativePath);
        const fromRoot = relative(resolvedRoot, target);
        if (
          isAbsolute(relativePath) ||
          fromRoot === "" ||
          fromRoot === ".." ||
          fromRoot.startsWith(`..${sep}`)
        ) {
          throw new Error("target escapes the declared root");
        }
        const parent = dirname(target);
        const parentRelative = relative(resolvedRoot, parent);
        let cursor = resolvedRoot;
        for (const segment of parentRelative.split(sep).filter(Boolean)) {
          cursor = join(cursor, segment);
          try {
            const status = await lstat(cursor);
            if (!status.isDirectory() || status.isSymbolicLink()) {
              throw new Error("parent path is not a real directory");
            }
          } catch (error) {
            if (
              typeof error === "object" &&
              error !== null &&
              "code" in error &&
              error.code === "ENOENT"
            ) {
              await mkdir(cursor, { mode: 0o700 });
            } else {
              throw error;
            }
          }
        }
        const handle = await open(
          target,
          constants.O_WRONLY |
            constants.O_CREAT |
            constants.O_TRUNC |
            constants.O_NOFOLLOW,
          0o600,
        );
        try {
          const status = await handle.stat();
          if (!status.isFile()) throw new Error("target is not a regular file");
          await handle.chmod(mode);
          await handle.writeFile(content);
        } finally {
          await handle.close();
        }
      },
      catch: fileFailure(
        "write_bytes_within_root",
        `${root}:${relativePath}`,
      ),
    }),
  writeBytesAtomic: (path, content, mode = 0o600) =>
    Effect.tryPromise({
      try: async (signal) => {
        const temporary = `${path}.${randomUUID()}.tmp`;
        try {
          await writeFile(temporary, content, { mode, signal });
          await rename(temporary, path);
        } catch (error) {
          await rm(temporary, { force: true }).catch(() => undefined);
          throw error;
        }
      },
      catch: fileFailure("write_bytes_atomic", path),
    }),
  makeDirectory: (path, options) =>
    Effect.tryPromise({
      try: async () => {
        await mkdir(path, { recursive: options?.recursive ?? false });
      },
      catch: fileFailure("make_directory", path),
    }),
  makeTempDirectory: (prefix) =>
    Effect.tryPromise({
      try: () => mkdtemp(join(tmpdir(), prefix)),
      catch: fileFailure("make_temp_directory", prefix),
    }),
  remove: (path) =>
    Effect.tryPromise({
      try: async () => {
        await rm(path, { force: true, recursive: true });
      },
      catch: fileFailure("remove", path),
    }),
};

export const NodeFileStoreLive = Layer.succeed(FileStore, NodeFileStore);

const collectCommand = (
  spec: CommandSpec,
  baseEnvironment: Readonly<NodeJS.ProcessEnv>,
): Effect.Effect<CommandResult, CommandFailure> =>
  Effect.async<CommandResult, CommandFailure>((resume, signal) => {
    const stdout: Buffer[] = [];
    const stderr: Buffer[] = [];
    let outputBytes = 0;
    let finished = false;
    let forcedFailure: CommandFailure | undefined;
    let killTimer: NodeJS.Timeout | undefined;
    const detached = process.platform !== "win32";
    const child = spawn(spec.command, [...spec.args], {
      cwd: spec.cwd,
      env: { ...baseEnvironment, ...spec.environment },
      shell: false,
      detached,
      stdio: ["ignore", "pipe", "pipe"],
    });
    const kill = (signalName: NodeJS.Signals): void => {
      if (child.pid === undefined) return;
      try {
        if (detached) process.kill(-child.pid, signalName);
        else child.kill(signalName);
      } catch {
        // The process group has already exited.
      }
    };
    const terminate = (failure?: CommandFailure): void => {
      if (forcedFailure === undefined && failure !== undefined) {
        forcedFailure = failure;
      }
      kill("SIGTERM");
      killTimer ??= setTimeout(() => kill("SIGKILL"), 1_000);
    };
    const deadline = setTimeout(
      () =>
        terminate(
          new CommandFailure({
            command: spec.command,
            reason: "timeout",
            detail: `command exceeded ${spec.timeoutMs} ms`,
          }),
        ),
      spec.timeoutMs,
    );
    const cleanup = (): void => {
      clearTimeout(deadline);
      if (killTimer !== undefined) clearTimeout(killTimer);
      signal.removeEventListener("abort", onAbort);
    };
    const onAbort = (): void => terminate();
    signal.addEventListener("abort", onAbort, { once: true });
    const capture = (target: Buffer[]) => (chunk: Buffer): void => {
      if (forcedFailure !== undefined) return;
      outputBytes += chunk.byteLength;
      if (outputBytes > spec.maxOutputBytes) {
        terminate(
          new CommandFailure({
            command: spec.command,
            reason: "output_limit",
            detail: `combined output exceeded ${spec.maxOutputBytes} bytes`,
          }),
        );
        return;
      }
      target.push(chunk);
    };
    child.stdout.on("data", capture(stdout));
    child.stderr.on("data", capture(stderr));
    child.once("error", (error) => {
      if (finished) return;
      finished = true;
      cleanup();
      resume(
        Effect.fail(
          new CommandFailure({
            command: spec.command,
            reason: "spawn_failed",
            detail: errorDetail(error),
          }),
        ),
      );
    });
    child.once("close", (code) => {
      if (finished) return;
      finished = true;
      cleanup();
      if (forcedFailure !== undefined) {
        resume(Effect.fail(forcedFailure));
        return;
      }
      resume(
        Effect.succeed({
          exitCode: code ?? 128,
          stdout: Buffer.concat(stdout),
          stderr: Buffer.concat(stderr),
        }),
      );
    });
    return Effect.sync(() => {
      terminate();
      kill("SIGKILL");
    });
  });

export const makeNodeCommandExecutorLive = (
  baseEnvironment: Readonly<NodeJS.ProcessEnv>,
) =>
  Layer.succeed(CommandExecutor, {
    run: (spec) => collectCommand(spec, baseEnvironment),
  });
