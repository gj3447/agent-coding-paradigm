import { createHash } from "node:crypto";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { Effect, Layer } from "effect";

import {
  ComparisonFailure,
  encodeComparisonReport,
  isSuccessfulComparisonArm,
  runAdmittedComparison,
  selectComparisonControllerEnvironment,
  type ComparisonArm,
} from "./comparison.js";
import {
  checkCases,
  CorpusFailure,
  loadCases,
  MAX_CORPUS_SOURCE_BYTES,
} from "./corpus.js";
import { isValidCaseCheck } from "./domain.js";
import {
  makeNodeCommandExecutorLive,
  NodeFileStoreLive,
} from "./node-runtime.js";
import {
  CommandFailure,
  FileFailure,
  FileStore,
} from "./ports.js";

interface CompareCliOptions {
  readonly corpus: string;
  readonly repository: string;
  readonly logDirectory: string;
  readonly dgxKeyFile: string;
  readonly dgxBaseUrl: string;
  readonly arms: readonly ComparisonArm[];
  readonly inspectExecutable: string;
  readonly pythonExecutable: string;
  readonly taskPath: string;
  readonly limit?: string;
  readonly summary?: string;
}

type ParseResult =
  | { readonly ok: true; readonly value: CompareCliOptions }
  | { readonly ok: false; readonly reason: string };

const HERE = dirname(fileURLToPath(import.meta.url));
const REQUIRED_OPTIONS = Object.freeze([
  "--corpus",
  "--repository",
  "--log-dir",
  "--dgx-key-file",
  "--dgx-base-url",
]);
const ALLOWED_OPTIONS = new Set([
  ...REQUIRED_OPTIONS,
  "--arms",
  "--inspect",
  "--python",
  "--limit",
  "--summary",
]);

const parseArms = (value: string): readonly ComparisonArm[] | undefined => {
  if (value === "both") return Object.freeze(["react", "aider"]);
  if (value === "react" || value === "aider") return Object.freeze([value]);
  return undefined;
};

const executable = (value: string): string =>
  value.includes("/") ? resolve(value) : value;

const parseCli = (argv: readonly string[]): ParseResult => {
  if (argv.length % 2 !== 0) {
    return { ok: false, reason: "options must be --name value pairs" };
  }
  const values = new Map<string, string>();
  for (let index = 0; index < argv.length; index += 2) {
    const flag = argv[index];
    const value = argv[index + 1];
    if (flag === undefined || value === undefined || !ALLOWED_OPTIONS.has(flag)) {
      return { ok: false, reason: `unknown option: ${flag ?? "<missing>"}` };
    }
    if (values.has(flag)) {
      return { ok: false, reason: `duplicate option: ${flag}` };
    }
    if (value.length === 0 || value.length > 4_096 || /[\u0000\r\n]/u.test(value)) {
      return { ok: false, reason: `invalid value for ${flag}` };
    }
    values.set(flag, value);
  }
  for (const flag of REQUIRED_OPTIONS) {
    if (!values.has(flag)) return { ok: false, reason: `missing option: ${flag}` };
  }
  const arms = parseArms(values.get("--arms") ?? "both");
  if (arms === undefined) {
    return { ok: false, reason: "--arms must be both, react, or aider" };
  }
  const corpus = values.get("--corpus");
  const repository = values.get("--repository");
  const logDirectory = values.get("--log-dir");
  const dgxKeyFile = values.get("--dgx-key-file");
  const dgxBaseUrl = values.get("--dgx-base-url");
  if (
    corpus === undefined ||
    repository === undefined ||
    logDirectory === undefined ||
    dgxKeyFile === undefined ||
    dgxBaseUrl === undefined
  ) {
    return { ok: false, reason: "required option resolution failed" };
  }
  const limit = values.get("--limit");
  const summary = values.get("--summary");
  return {
    ok: true,
    value: {
      corpus: resolve(corpus),
      repository: resolve(repository),
      logDirectory: resolve(logDirectory),
      dgxKeyFile: resolve(dgxKeyFile),
      dgxBaseUrl,
      arms,
      inspectExecutable: executable(
        values.get("--inspect") ?? resolve(HERE, "../.venv/bin/inspect"),
      ),
      pythonExecutable: executable(
        values.get("--python") ?? resolve(HERE, "../.venv/bin/python"),
      ),
      taskPath: resolve(HERE, "../task.py"),
      ...(limit === undefined ? {} : { limit }),
      ...(summary === undefined ? {} : { summary: resolve(summary) }),
    },
  };
};

const execute = (options: CompareCliOptions) => {
  const live = Layer.merge(
    NodeFileStoreLive,
    makeNodeCommandExecutorLive(
      selectComparisonControllerEnvironment(process.env),
    ),
  );
  const program = Effect.scoped(Effect.gen(function* () {
    const files = yield* FileStore;
    const snapshotRoot = yield* Effect.acquireRelease(
      files.makeTempDirectory("coding-corpus-snapshot-"),
      (path) => files.remove(path).pipe(Effect.orDie),
    );
    const corpusSource = yield* files.readText(options.corpus, {
      maxBytes: MAX_CORPUS_SOURCE_BYTES,
    });
    if (new TextEncoder().encode(corpusSource).byteLength > MAX_CORPUS_SOURCE_BYTES) {
      return yield* Effect.fail(
        new CorpusFailure({
          phase: "load",
          reason: `corpus exceeds ${MAX_CORPUS_SOURCE_BYTES} bytes`,
        }),
      );
    }
    const corpusSha256 = createHash("sha256")
      .update(corpusSource, "utf8")
      .digest("hex");
    const corpusSnapshot = join(snapshotRoot, "corpus.jsonl");
    yield* files.writeBytes(
      corpusSnapshot,
      new TextEncoder().encode(corpusSource),
    );
    const cases = yield* loadCases(corpusSnapshot);
    const checks = yield* checkCases(
      options.repository,
      cases,
      options.pythonExecutable,
    );
    const invalid = checks.filter((check) => !isValidCaseCheck(check));
    if (invalid.length > 0) {
      return yield* Effect.fail(
        new ComparisonFailure({
          phase: "configuration",
          arm: null,
          reason: `corpus admission failed for: ${invalid.map((check) => check.caseId).join(", ")}`,
        }),
      );
    }
    const report = yield* runAdmittedComparison({
      arms: options.arms,
      inspectExecutable: options.inspectExecutable,
      taskPath: options.taskPath,
      corpusPath: corpusSnapshot,
      corpusSourcePath: options.corpus,
      corpusSha256,
      repositoryPath: options.repository,
      logDirectory: options.logDirectory,
      dgxBaseUrl: options.dgxBaseUrl,
      dgxKeyFile: options.dgxKeyFile,
      ...(options.limit === undefined ? {} : { limit: options.limit }),
    });
    const encoded = encodeComparisonReport(report);
    if (options.summary !== undefined) {
      const files = yield* FileStore;
      yield* files.makeDirectory(dirname(options.summary), { recursive: true });
      yield* files.writeBytesAtomic(options.summary, encoded);
    }
    return { report, encoded };
  }));
  return program.pipe(Effect.provide(live));
};

const failureEnvelope = (error: unknown): Readonly<Record<string, unknown>> => {
  if (error instanceof ComparisonFailure) {
    return {
      kind: error._tag,
      phase: error.phase,
      arm: error.arm,
      reason: error.reason,
    };
  }
  if (error instanceof CorpusFailure) {
    return {
      kind: error._tag,
      phase: error.phase,
      reason: error.reason,
    };
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
          schema_version: "coding-corpus-comparison-error/v1",
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
            schema_version: "coding-corpus-comparison-error/v1",
            error: failureEnvelope(error),
          })}\n`,
        );
        return 1;
      },
      onSuccess: ({ report, encoded }) => {
        process.stdout.write(encoded);
        return report.arms.every(isSuccessfulComparisonArm) ? 0 : 1;
      },
    }),
  );
};

Effect.runPromise(main(process.argv.slice(2))).then((exitCode) => {
  process.exitCode = exitCode;
});
