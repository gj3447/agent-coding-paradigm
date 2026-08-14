import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { Effect, Layer } from "effect";

import {
  checkCases,
  CorpusFailure,
  loadCases,
  summarizeCaseCheck,
  validateHistory,
  type CorpusApplicationFailure,
} from "./corpus.js";
import { corpusMetadata } from "./domain.js";
import {
  makeNodeCommandExecutorLive,
  NodeFileStoreLive,
} from "./node-runtime.js";
import { CommandFailure, FileFailure } from "./ports.js";

type CliCommand = "list" | "validate" | "check";

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
