import { dirname, join } from "node:path";

import { Data, Effect } from "effect";

import {
  type CaseCheck,
  type CorpusCase,
  decodeCorpusCase,
  isValidCaseCheck,
  parseJsonRejectingDuplicateKeys,
  type VerifierRun,
} from "./domain.js";
import {
  CommandExecutor,
  CommandFailure,
  type CommandExecutorService,
  type CommandResult,
  FileFailure,
  FileStore,
  type FileStoreService,
} from "./ports.js";

const TEXT_DECODER = new TextDecoder("utf-8", { fatal: false });
const GIT_TIMEOUT_MS = 30_000;
const GIT_OUTPUT_LIMIT = 8 * 1024 * 1024;

export class CorpusFailure extends Data.TaggedError("CorpusFailure")<{
  readonly phase:
    | "load"
    | "history"
    | "materialize"
    | "verifier"
    | "configuration";
  readonly reason: string;
}> {}

export type CorpusApplicationFailure =
  | CorpusFailure
  | FileFailure
  | CommandFailure;

const corpusFailure = (
  phase: CorpusFailure["phase"],
  reason: string,
): CorpusFailure => new CorpusFailure({ phase, reason });

export const loadCases = (
  path: string,
): Effect.Effect<readonly CorpusCase[], CorpusFailure | FileFailure, FileStoreService> =>
  Effect.gen(function* () {
    const files = yield* FileStore;
    const source = yield* files.readText(path);
    const cases: CorpusCase[] = [];
    const seen = new Set<string>();
    const lines = source.split(/\r?\n/u);
    for (let index = 0; index < lines.length; index += 1) {
      const raw = lines[index];
      if (raw === undefined || raw.trim().length === 0) continue;
      const lineNumber = index + 1;
      const parsed = parseJsonRejectingDuplicateKeys(raw);
      if (!parsed.ok) {
        return yield* Effect.fail(
          corpusFailure(
            "load",
            `${path}:${lineNumber}: ${parsed.error.reason}`,
          ),
        );
      }
      const decoded = decodeCorpusCase(parsed.value);
      if (!decoded.ok) {
        return yield* Effect.fail(
          corpusFailure(
            "load",
            `${path}:${lineNumber}: ${decoded.error.reason}`,
          ),
        );
      }
      if (seen.has(decoded.value.id)) {
        return yield* Effect.fail(
          corpusFailure(
            "load",
            `${path}:${lineNumber}: duplicate id ${decoded.value.id}`,
          ),
        );
      }
      seen.add(decoded.value.id);
      cases.push(decoded.value);
    }
    if (cases.length === 0) {
      return yield* Effect.fail(corpusFailure("load", `${path}: corpus is empty`));
    }
    return Object.freeze(cases);
  });

const runCommand = (
  command: string,
  args: readonly string[],
  cwd: string,
  options?: {
    readonly environment?: Readonly<Record<string, string>>;
    readonly timeoutMs?: number;
    readonly maxOutputBytes?: number;
  },
): Effect.Effect<CommandResult, CommandFailure, CommandExecutorService> =>
  Effect.gen(function* () {
    const executor = yield* CommandExecutor;
    return yield* executor.run({
      command,
      args,
      cwd,
      timeoutMs: options?.timeoutMs ?? GIT_TIMEOUT_MS,
      maxOutputBytes: options?.maxOutputBytes ?? GIT_OUTPUT_LIMIT,
      ...(options?.environment === undefined
        ? {}
        : { environment: options.environment }),
    });
  });

const runGit = (
  repository: string,
  args: readonly string[],
  options?: { readonly acceptNonzero?: boolean; readonly maxOutputBytes?: number },
): Effect.Effect<CommandResult, CorpusFailure | CommandFailure, CommandExecutorService> =>
  runCommand("git", ["-C", repository, ...args], repository, {
    maxOutputBytes: options?.maxOutputBytes ?? GIT_OUTPUT_LIMIT,
  }).pipe(
    Effect.flatMap((result) => {
      if (result.exitCode === 0 || options?.acceptNonzero === true) {
        return Effect.succeed(result);
      }
      const detail = TEXT_DECODER.decode(result.stderr).trim();
      return Effect.fail(
        corpusFailure(
          "history",
          `git ${args.join(" ")} failed: ${detail || `exit ${result.exitCode}`}`,
        ),
      );
    }),
  );

const requireRepository = (
  repository: string,
): Effect.Effect<void, CorpusFailure | CommandFailure, CommandExecutorService> =>
  runGit(repository, ["rev-parse", "--is-inside-work-tree"], {
    acceptNonzero: true,
  }).pipe(
    Effect.flatMap((result) =>
      result.exitCode === 0 && TEXT_DECODER.decode(result.stdout).trim() === "true"
        ? Effect.void
        : Effect.fail(
            corpusFailure("history", `not a Git worktree: ${repository}`),
          ),
    ),
  );

const requireCommit = (
  repository: string,
  revision: string,
): Effect.Effect<void, CorpusFailure | CommandFailure, CommandExecutorService> =>
  runGit(repository, ["cat-file", "-e", `${revision}^{commit}`], {
    acceptNonzero: true,
  }).pipe(
    Effect.flatMap((result) =>
      result.exitCode === 0
        ? Effect.void
        : Effect.fail(
            corpusFailure("history", `commit is unavailable: ${revision}`),
          ),
    ),
  );

const requireGitObject = (
  repository: string,
  object: string,
): Effect.Effect<void, CorpusFailure | CommandFailure, CommandExecutorService> =>
  runGit(repository, ["cat-file", "-e", object], {
    acceptNonzero: true,
  }).pipe(
    Effect.flatMap((result) =>
      result.exitCode === 0
        ? Effect.void
        : Effect.fail(
            corpusFailure("history", `Git object is unavailable: ${object}`),
          ),
    ),
  );

const validateCaseHistory = (
  repository: string,
  value: CorpusCase,
): Effect.Effect<void, CorpusFailure | CommandFailure, CommandExecutorService> =>
  Effect.gen(function* () {
    yield* requireCommit(repository, value.baseSha);
    yield* requireCommit(repository, value.oracleSha);
    const ancestor = yield* runGit(
      repository,
      ["merge-base", "--is-ancestor", value.baseSha, value.oracleSha],
      { acceptNonzero: true },
    );
    if (ancestor.exitCode !== 0) {
      return yield* Effect.fail(
        corpusFailure(
          "history",
          `${value.id}: base_sha is not an ancestor of oracle_sha`,
        ),
      );
    }
    yield* Effect.forEach(
      value.verifierPaths,
      (relative) =>
        requireGitObject(repository, `${value.oracleSha}:${relative}`),
      { concurrency: 1, discard: true },
    );
    yield* Effect.forEach(
      value.submissionPaths,
      (relative) =>
        requireGitObject(repository, `${value.baseSha}:${relative}`).pipe(
          Effect.zipRight(
            requireGitObject(repository, `${value.oracleSha}:${relative}`),
          ),
        ),
      { concurrency: 1, discard: true },
    );
  });

export const validateHistory = (
  repository: string,
  cases: readonly CorpusCase[],
): Effect.Effect<void, CorpusFailure | CommandFailure, CommandExecutorService> =>
  requireRepository(repository).pipe(
    Effect.zipRight(
      Effect.forEach(
        cases,
        (value) => validateCaseHistory(repository, value),
        { concurrency: 1, discard: true },
      ),
    ),
  );

const ensureSuccessful = (
  result: CommandResult,
  phase: CorpusFailure["phase"],
  operation: string,
): Effect.Effect<CommandResult, CorpusFailure> =>
  result.exitCode === 0
    ? Effect.succeed(result)
    : Effect.fail(
        corpusFailure(
          phase,
          `${operation} failed: ${TEXT_DECODER.decode(result.stderr).trim() || `exit ${result.exitCode}`}`,
        ),
      );

export const archiveRevision = (
  repository: string,
  revision: string,
  destination: string,
): Effect.Effect<void, CorpusApplicationFailure, CommandExecutorService | FileStoreService> =>
  Effect.gen(function* () {
    const files = yield* FileStore;
    yield* requireCommit(repository, revision);
    yield* files.makeDirectory(dirname(destination), { recursive: true });
    const archived = yield* runGit(repository, [
      "archive",
      "--format=tar",
      `--output=${destination}`,
      revision,
    ]);
    yield* ensureSuccessful(archived, "materialize", "git archive");
  });

const materializeRevision = (
  repository: string,
  revision: string,
  destination: string,
  archivePath: string,
): Effect.Effect<void, CorpusApplicationFailure, CommandExecutorService | FileStoreService> =>
  Effect.gen(function* () {
    const files = yield* FileStore;
    yield* files.makeDirectory(destination);
    yield* archiveRevision(repository, revision, archivePath);
    const extracted = yield* runCommand(
      "tar",
      [
        "--extract",
        "--file",
        archivePath,
        "--directory",
        destination,
        "--no-same-owner",
        "--no-same-permissions",
      ],
      repository,
    );
    yield* ensureSuccessful(extracted, "materialize", "tar extract");
  });

const gitShow = (
  repository: string,
  object: string,
): Effect.Effect<Uint8Array, CorpusFailure | CommandFailure, CommandExecutorService> =>
  runGit(repository, ["show", object], {
    maxOutputBytes: 1_100_000,
  }).pipe(Effect.map((result) => result.stdout));

const overlayFiles = (
  repository: string,
  revision: string,
  relativePaths: readonly string[],
  destination: string,
): Effect.Effect<void, CorpusApplicationFailure, CommandExecutorService | FileStoreService> =>
  Effect.gen(function* () {
    const files = yield* FileStore;
    yield* Effect.forEach(
      relativePaths,
      (relative) =>
        Effect.gen(function* () {
          const content = yield* gitShow(
            repository,
            `${revision}:${relative}`,
          );
          const target = join(destination, relative);
          yield* files.makeDirectory(dirname(target), { recursive: true });
          yield* files.writeBytes(target, content);
        }),
      { concurrency: 1, discard: true },
    );
  });

const runVerifier = (
  value: CorpusCase,
  checkout: string,
  revision: string,
  pythonExecutable: string,
): Effect.Effect<VerifierRun, CommandFailure, CommandExecutorService> =>
  runCommand(
    pythonExecutable,
    value.verifier.slice(1),
    checkout,
    {
      environment: {
        PYTHONPATH: `${join(checkout, "src")}:${join(checkout, "scripts")}`,
      },
      timeoutMs: value.timeoutSeconds * 1_000,
      maxOutputBytes: 8 * 1024 * 1024,
    },
  ).pipe(
    Effect.map(
      (result): VerifierRun => ({
        revision,
        returnCode: result.exitCode,
        stdout: TEXT_DECODER.decode(result.stdout),
        stderr: TEXT_DECODER.decode(result.stderr),
      }),
    ),
    Effect.catchTag("CommandFailure", (error) =>
      error.reason === "timeout"
        ? Effect.succeed({
            revision,
            returnCode: 124,
            stdout: "",
            stderr: "verifier timed out",
          })
        : Effect.fail(error),
    ),
  );

export const checkCase = (
  repository: string,
  value: CorpusCase,
  pythonExecutable: string,
): Effect.Effect<CaseCheck, CorpusApplicationFailure, CommandExecutorService | FileStoreService> =>
  Effect.scoped(
    Effect.gen(function* () {
      const files = yield* FileStore;
      const root = yield* Effect.acquireRelease(
        files.makeTempDirectory(`coding-corpus-${value.id}-`),
        (path) => files.remove(path).pipe(Effect.orDie),
      );
      const baselinePath = join(root, "baseline");
      const admittedPath = join(root, "admitted-solution");
      const oraclePath = join(root, "oracle");

      yield* materializeRevision(
        repository,
        value.baseSha,
        baselinePath,
        join(root, "baseline.tar"),
      );
      yield* overlayFiles(
        repository,
        value.oracleSha,
        value.verifierPaths,
        baselinePath,
      );
      const baseline = yield* runVerifier(
        value,
        baselinePath,
        value.baseSha,
        pythonExecutable,
      );

      yield* materializeRevision(
        repository,
        value.baseSha,
        admittedPath,
        join(root, "admitted.tar"),
      );
      yield* overlayFiles(
        repository,
        value.oracleSha,
        value.verifierPaths,
        admittedPath,
      );
      yield* overlayFiles(
        repository,
        value.oracleSha,
        value.submissionPaths,
        admittedPath,
      );
      const admittedSolution = yield* runVerifier(
        value,
        admittedPath,
        `${value.baseSha}+admitted-solution`,
        pythonExecutable,
      );

      yield* materializeRevision(
        repository,
        value.oracleSha,
        oraclePath,
        join(root, "oracle.tar"),
      );
      yield* overlayFiles(
        repository,
        value.oracleSha,
        value.verifierPaths,
        oraclePath,
      );
      const oracle = yield* runVerifier(
        value,
        oraclePath,
        value.oracleSha,
        pythonExecutable,
      );
      return Object.freeze({
        caseId: value.id,
        verifier: value.verifier,
        baseline,
        admittedSolution,
        oracle,
      });
    }),
  );

export const checkCases = (
  repository: string,
  cases: readonly CorpusCase[],
  pythonExecutable: string,
): Effect.Effect<
  readonly CaseCheck[],
  CorpusApplicationFailure,
  CommandExecutorService | FileStoreService
> =>
  validateHistory(repository, cases).pipe(
    Effect.zipRight(
      Effect.forEach(
        cases,
        (value) => checkCase(repository, value, pythonExecutable),
        { concurrency: 1 },
      ),
    ),
    Effect.map((checks) => Object.freeze(checks)),
  );

export interface CaseCheckSummary {
  readonly case_id: string;
  readonly baseline_returncode: number;
  readonly admitted_solution_returncode: number;
  readonly oracle_returncode: number;
  readonly valid: boolean;
}

export const summarizeCaseCheck = (value: CaseCheck): CaseCheckSummary => ({
  case_id: value.caseId,
  baseline_returncode: value.baseline.returnCode,
  admitted_solution_returncode: value.admittedSolution.returnCode,
  oracle_returncode: value.oracle.returnCode,
  valid: isValidCaseCheck(value),
});
