import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { Effect, Layer } from "effect";

import {
  checkCases,
  CorpusFailure,
  loadCases,
  prepareCorpus,
  scoreCandidate,
  summarizeCaseCheck,
  validateHistory,
  type CorpusApplicationFailure,
} from "./corpus.js";
import {
  type BridgeRequest,
  corpusCaseWire,
  corpusMetadata,
  decodeBridgeRequest,
  parseJsonRejectingDuplicateKeys,
} from "./domain.js";
import {
  makeNodeCommandExecutorLive,
  NodeFileStoreLive,
} from "./node-runtime.js";
import { CommandFailure, FileFailure } from "./ports.js";

type CliCommand = "list" | "validate" | "check";

const BRIDGE_REQUEST_LIMIT = 4 * 1024 * 1024;
const BRIDGE_READ_TIMEOUT_MS = 5_000;
const BRIDGE_VALIDATE_TIMEOUT_MS = 4 * 60 * 1_000;
const BRIDGE_OPERATION_TIMEOUT_MS = 40 * 60 * 1_000;

interface CliOptions {
  readonly command: CliCommand;
  readonly corpus: string;
  readonly repository: string;
  readonly pythonExecutable: string;
}

type CliParseResult =
  | { readonly ok: true; readonly value: CliOptions }
  | { readonly ok: false; readonly reason: string };

const HERE = dirname(fileURLToPath(import.meta.url));

const COMMAND_ENVIRONMENT: Readonly<Record<string, string>> = Object.freeze({
  PATH: "/usr/local/bin:/usr/bin:/bin",
  HOME: "/nonexistent",
  LANG: "C.UTF-8",
  LC_ALL: "C.UTF-8",
  GIT_CONFIG_GLOBAL: "/dev/null",
  GIT_CONFIG_NOSYSTEM: "1",
  GIT_NO_LAZY_FETCH: "1",
  GIT_NO_REPLACE_OBJECTS: "1",
  GIT_TERMINAL_PROMPT: "0",
  PYTHONDONTWRITEBYTECODE: "1",
  PYTHONNOUSERSITE: "1",
});

const parseCli = (argv: readonly string[]): CliParseResult => {
  const [rawCommand, ...rest] = argv;
  if (
    rawCommand !== "list" &&
    rawCommand !== "validate" &&
    rawCommand !== "check"
  ) {
    return { ok: false, reason: "command must be list, validate, or check" };
  }
  const values = new Map<string, string>();
  for (let index = 0; index < rest.length; index += 2) {
    const flag = rest[index];
    const value = rest[index + 1];
    if (flag === undefined || value === undefined || !flag.startsWith("--")) {
      return { ok: false, reason: "options must be --name value pairs" };
    }
    if (flag !== "--corpus" && flag !== "--repo" && flag !== "--python") {
      return { ok: false, reason: `unknown option: ${flag}` };
    }
    if (values.has(flag)) {
      return { ok: false, reason: `duplicate option: ${flag}` };
    }
    if (value.length === 0 || /[\u0000\r\n]/.test(value)) {
      return { ok: false, reason: `invalid value for ${flag}` };
    }
    values.set(flag, value);
  }
  return {
    ok: true,
    value: {
      command: rawCommand,
      corpus: resolve(values.get("--corpus") ?? resolve(HERE, "../pilot.jsonl")),
      repository: resolve(values.get("--repo") ?? resolve(HERE, "../../..")),
      pythonExecutable: (() => {
        const configured = values.get("--python") ?? "python3";
        return configured.includes("/") ? resolve(configured) : configured;
      })(),
    },
  };
};

const execute = (
  options: CliOptions,
): Effect.Effect<unknown, CorpusApplicationFailure, never> => {
  const program = Effect.gen(function* () {
    const cases = yield* loadCases(options.corpus);
    if (options.command === "list") {
      return {
        schema_version: "coding-corpus-cli/v1",
        command: options.command,
        corpus: options.corpus,
        cases: cases.map(corpusMetadata),
      };
    }
    yield* validateHistory(options.repository, cases);
    if (options.command === "validate") {
      return {
        schema_version: "coding-corpus-cli/v1",
        command: options.command,
        corpus: options.corpus,
        repository: options.repository,
        status: "valid",
        cases: cases.length,
      };
    }
    const checks = yield* checkCases(
      options.repository,
      cases,
      options.pythonExecutable,
    );
    return {
      schema_version: "coding-corpus-cli/v1",
      command: options.command,
      corpus: options.corpus,
      repository: options.repository,
      checks: checks.map(summarizeCaseCheck),
    };
  });
  const live = Layer.merge(
    NodeFileStoreLive,
    makeNodeCommandExecutorLive(COMMAND_ENVIRONMENT),
  );
  return program.pipe(Effect.provide(live));
};

const liveLayer = () =>
  Layer.merge(
    NodeFileStoreLive,
    makeNodeCommandExecutorLive(COMMAND_ENVIRONMENT),
  );

const readBridgeRequest = (): Effect.Effect<BridgeRequest, CorpusFailure> =>
  Effect.async<BridgeRequest, CorpusFailure>((resume, signal) => {
    const chunks: Buffer[] = [];
    let bytes = 0;
    let done = false;
    const fail = (reason: string): void => {
      finish(Effect.fail(new CorpusFailure({ phase: "configuration", reason })));
    };
    const onData = (chunk: Buffer): void => {
      bytes += chunk.byteLength;
      if (bytes > BRIDGE_REQUEST_LIMIT) {
        fail(`bridge request exceeds ${BRIDGE_REQUEST_LIMIT} bytes`);
        return;
      }
      chunks.push(chunk);
    };
    const onEnd = (): void => {
      const parsed = parseJsonRejectingDuplicateKeys(
        Buffer.concat(chunks).toString("utf8"),
      );
      if (!parsed.ok) {
        fail(parsed.error.reason);
        return;
      }
      const decoded = decodeBridgeRequest(parsed.value);
      if (!decoded.ok) {
        fail(decoded.error.reason);
        return;
      }
      finish(Effect.succeed(decoded.value));
    };
    const onError = (): void => fail("bridge request stream failed");
    const onAbort = (): void => finish(Effect.interrupt);
    const cleanup = (): void => {
      clearTimeout(deadline);
      process.stdin.off("data", onData);
      process.stdin.off("end", onEnd);
      process.stdin.off("error", onError);
      signal.removeEventListener("abort", onAbort);
      process.stdin.pause();
      if (!process.stdin.destroyed) process.stdin.destroy();
    };
    const finish = (effect: Effect.Effect<BridgeRequest, CorpusFailure>): void => {
      if (done) return;
      done = true;
      cleanup();
      resume(effect);
    };
    const deadline = setTimeout(
      () => fail(`bridge request exceeded ${BRIDGE_READ_TIMEOUT_MS} ms`),
      BRIDGE_READ_TIMEOUT_MS,
    );
    process.stdin.on("data", onData);
    process.stdin.once("end", onEnd);
    process.stdin.once("error", onError);
    signal.addEventListener("abort", onAbort, { once: true });
    process.stdin.resume();
    return Effect.sync(() => {
      finish(Effect.interrupt);
    });
  });

const executeBridge = (
  request: BridgeRequest,
): Effect.Effect<unknown, CorpusApplicationFailure, never> => {
  const corpus = resolve(request.corpus);
  const program = Effect.gen(function* () {
    if (request.operation === "catalog") {
      const cases = yield* loadCases(corpus);
      return { cases: cases.map(corpusCaseWire) };
    }
    if (request.operation === "score") {
      return yield* scoreCandidate(
        corpus,
        request.case_id,
        request.metadata,
        request.oracle,
        request.candidate,
      );
    }
    const repository = resolve(request.repository);
    if (request.operation === "validate") {
      const cases = yield* loadCases(corpus);
      yield* validateHistory(repository, cases);
      return { status: "valid", cases: cases.length };
    }
    if (request.operation === "admit") {
      const cases = yield* loadCases(corpus);
      const checks = yield* checkCases(
        repository,
        cases,
        request.python_executable,
      );
      return { checks: checks.map(summarizeCaseCheck) };
    }
    const prepared = yield* prepareCorpus(
      corpus,
      repository,
      request.python_executable,
      resolve(request.archive_directory),
      request.split,
    );
    return {
      cases: prepared.selected.map((value) => ({
        case: corpusCaseWire(value.case),
        metadata: value.metadata,
        base_archive: value.baseArchive,
        oracle_archive: value.oracleArchive,
        verifier_archive: value.verifierArchive,
      })),
    };
  });
  const bounded =
    request.operation === "validate"
      ? program.pipe(
          Effect.timeoutFail({
            duration: BRIDGE_VALIDATE_TIMEOUT_MS,
            onTimeout: () =>
              new CorpusFailure({
                phase: "configuration",
                reason: "history validation exceeded the 4 minute bridge deadline",
              }),
          }),
        )
      : request.operation === "admit" || request.operation === "prepare"
        ? program.pipe(
            Effect.timeoutFail({
              duration: BRIDGE_OPERATION_TIMEOUT_MS,
              onTimeout: () =>
                new CorpusFailure({
                  phase: "configuration",
                  reason: `${request.operation} exceeded the 40 minute bridge deadline`,
                }),
            }),
          )
        : program;
  return bounded.pipe(Effect.provide(liveLayer()));
};

const failureEnvelope = (
  error: CorpusApplicationFailure,
): Readonly<Record<string, unknown>> => {
  if (error instanceof CorpusFailure) {
    return { kind: error._tag, phase: error.phase, reason: error.reason };
  }
  if (error instanceof FileFailure) {
    return {
      kind: error._tag,
      operation: error.operation,
      path: error.path,
      reason: error.reason,
    };
  }
  if (error instanceof CommandFailure) {
    return {
      kind: error._tag,
      command: error.command,
      reason: error.reason,
      detail: error.detail,
    };
  }
  return { kind: "UnknownFailure", reason: "unclassified failure" };
};

const main = (argv: readonly string[]): Effect.Effect<number> => {
  if (argv.length === 1 && argv[0] === "bridge") {
    return readBridgeRequest().pipe(
      Effect.flatMap((request) =>
        executeBridge(request).pipe(
          Effect.map((value) => ({ request, value })),
        ),
      ),
      Effect.match({
        onFailure: (error) => {
          process.stdout.write(
            `${JSON.stringify({
              schema_version: "coding-corpus-bridge-response/v1",
              ok: false,
              error: failureEnvelope(error),
            })}\n`,
          );
          return 1;
        },
        onSuccess: ({ request, value }) => {
          process.stdout.write(
            `${JSON.stringify({
              schema_version: "coding-corpus-bridge-response/v1",
              ok: true,
              operation: request.operation,
              value,
            })}\n`,
          );
          return 0;
        },
      }),
    );
  }
  const parsed = parseCli(argv);
  if (!parsed.ok) {
    return Effect.sync(() => {
      process.stderr.write(
        `${JSON.stringify({
          schema_version: "coding-corpus-cli-error/v1",
          error: { kind: "CliFailure", reason: parsed.reason },
        })}\n`,
      );
      return 2;
    });
  }
  return execute(parsed.value).pipe(
    Effect.match({
      onFailure: (error) => {
        process.stderr.write(
          `${JSON.stringify({
            schema_version: "coding-corpus-cli-error/v1",
            error: failureEnvelope(error),
          })}\n`,
        );
        return 1;
      },
      onSuccess: (value) => {
        process.stdout.write(`${JSON.stringify(value)}\n`);
        return 0;
      },
    }),
  );
};

Effect.runPromise(main(process.argv.slice(2))).then((exitCode) => {
  process.exitCode = exitCode;
});
