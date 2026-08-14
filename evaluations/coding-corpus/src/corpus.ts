import { dirname, join } from "node:path";

import { Data, Effect } from "effect";

import {
  type CandidateScoreDecision,
  type CaseCheck,
  type CorpusCase,
  type CorpusMetadata,
  type CorpusSplit,
  corpusMetadata,
  decodeCorpusCase,
  evaluateCandidateScore,
  isValidCaseCheck,
  parseJsonRejectingDuplicateKeys,
  type VerifierObservation,
  type VerifierRun,
  verifierEntryPaths,
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
export const MAX_CORPUS_SOURCE_BYTES = 512 * 1024;
const MAX_CORPUS_CASES = 64;
const MAX_ADMISSION_VERIFIER_BUDGET_MS = 36 * 60 * 1_000;
const MAX_BASE_ARCHIVE_BYTES = 64 * 1024 * 1024;
const MAX_VERIFIER_ARCHIVE_BYTES = 16 * 1024 * 1024;
const MAX_VERIFIER_SERVICE_BYTES = 96 * 1024 * 1024;

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
    const source = yield* files.readText(path, {
      maxBytes: MAX_CORPUS_SOURCE_BYTES,
    });
    if (new TextEncoder().encode(source).byteLength > MAX_CORPUS_SOURCE_BYTES) {
      return yield* Effect.fail(
        corpusFailure(
          "load",
          `${path}: corpus exceeds ${MAX_CORPUS_SOURCE_BYTES} bytes`,
        ),
      );
    }
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
      if (cases.length > MAX_CORPUS_CASES) {
        return yield* Effect.fail(
          corpusFailure("load", `${path}: corpus exceeds ${MAX_CORPUS_CASES} cases`),
        );
      }
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
  Effect.gen(function* () {
    const worktree = yield* runGit(repository, ["rev-parse", "--is-inside-work-tree"], {
      acceptNonzero: true,
    });
    if (
      worktree.exitCode !== 0 ||
      TEXT_DECODER.decode(worktree.stdout).trim() !== "true"
    ) {
      return yield* Effect.fail(
        corpusFailure("history", `not a Git worktree: ${repository}`),
      );
    }
    const configuredAttributes = yield* runGit(
      repository,
      ["config", "--local", "--get", "core.attributesFile"],
      { acceptNonzero: true },
    );
    if (configuredAttributes.exitCode === 0) {
      return yield* Effect.fail(
        corpusFailure("history", "repository-local core.attributesFile is not admitted"),
      );
    }
    const infoAttributes = yield* runGit(
      repository,
      ["rev-parse", "--git-path", "info/attributes"],
    );
    const attributesPath = TEXT_DECODER.decode(infoAttributes.stdout).trim();
    if (attributesPath.length === 0 || /[\u0000\r\n]/u.test(attributesPath)) {
      return yield* Effect.fail(
        corpusFailure("history", "repository info/attributes path is malformed"),
      );
    }
    const empty = yield* runCommand(
      "test",
      ["!", "-s", attributesPath],
      repository,
    );
    if (empty.exitCode !== 0) {
      return yield* Effect.fail(
        corpusFailure("history", "non-empty repository info/attributes is not admitted"),
      );
    }
  });

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

const regularBlobMode = (
  repository: string,
  revision: string,
  relativePath: string,
  phase: CorpusFailure["phase"],
): Effect.Effect<0o644 | 0o755, CorpusFailure | CommandFailure, CommandExecutorService> =>
  runGit(repository, ["ls-tree", "-z", revision, "--", relativePath], {
    maxOutputBytes: 4_096,
  }).pipe(
    Effect.flatMap((result) => {
      const entry = TEXT_DECODER.decode(result.stdout);
      const expectedSuffix = `\t${relativePath}\u0000`;
      if (entry.endsWith(expectedSuffix) && entry.startsWith("100644 blob ")) {
        return Effect.succeed(0o644);
      }
      if (entry.endsWith(expectedSuffix) && entry.startsWith("100755 blob ")) {
        return Effect.succeed(0o755);
      }
      return Effect.fail(
        corpusFailure(
          phase,
          `path is not one regular file blob at ${revision}: ${relativePath}`,
        ),
      );
    }),
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
      verifierEntryPaths(value.verifier),
      (relative) =>
        Effect.gen(function* () {
          const base = yield* runGit(repository, [
            "rev-parse",
            `${value.baseSha}:${relative}`,
          ], { acceptNonzero: true });
          const oracle = yield* runGit(repository, [
            "rev-parse",
            `${value.oracleSha}:${relative}`,
          ], { acceptNonzero: true });
          if (
            oracle.exitCode !== 0 ||
            (base.exitCode === 0 &&
              TEXT_DECODER.decode(base.stdout).trim() ===
                TEXT_DECODER.decode(oracle.stdout).trim())
          ) {
            return yield* Effect.fail(
              corpusFailure(
                "history",
                `${value.id}: verifier entry must exist and differ from base: ${relative}`,
              ),
            );
          }
        }),
      { concurrency: 1, discard: true },
    );
    yield* Effect.forEach(
      value.submissionPaths,
      (relative) =>
        Effect.gen(function* () {
          const baseMode = yield* regularBlobMode(
            repository,
            value.baseSha,
            relative,
            "history",
          );
          const oracleMode = yield* regularBlobMode(
            repository,
            value.oracleSha,
            relative,
            "history",
          );
          if (baseMode !== 0o644 || oracleMode !== 0o644) {
            return yield* Effect.fail(
              corpusFailure(
                "history",
                `${value.id}: submission paths must remain regular 100644 blobs: ${relative}`,
              ),
            );
          }
        }),
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

const archivePaths = (
  repository: string,
  revision: string,
  relativePaths: readonly string[],
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
      "--",
      ...relativePaths,
    ]);
    yield* ensureSuccessful(archived, "materialize", "git archive paths");
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

const requireRegularArchiveBlob = (
  repository: string,
  revision: string,
  relativePath: string,
): Effect.Effect<0o644 | 0o755, CorpusFailure | CommandFailure, CommandExecutorService> =>
  regularBlobMode(repository, revision, relativePath, "materialize");

const archiveSize = (
  path: string,
  repository: string,
): Effect.Effect<number, CorpusFailure | CommandFailure, CommandExecutorService> =>
  runCommand("stat", ["--format=%s", "--", path], repository, {
    maxOutputBytes: 128,
  }).pipe(
    Effect.flatMap((result) =>
      ensureSuccessful(result, "materialize", "archive stat"),
    ),
    Effect.flatMap((result) => {
      const source = TEXT_DECODER.decode(result.stdout).trim();
      const size = Number(source);
      return /^\d+$/u.test(source) && Number.isSafeInteger(size)
        ? Effect.succeed(size)
        : Effect.fail(corpusFailure("materialize", "archive size is invalid"));
    }),
  );

const overlayFiles = (
  repository: string,
  revision: string,
  relativePaths: readonly string[],
  destination: string,
): Effect.Effect<void, CorpusApplicationFailure, CommandExecutorService | FileStoreService> =>
  Effect.scoped(
    Effect.gen(function* () {
      const files = yield* FileStore;
      const temporary = yield* Effect.acquireRelease(
        files.makeTempDirectory("coding-corpus-overlay-"),
        (path) => files.remove(path).pipe(Effect.orDie),
      );
      const archive = join(temporary, "overlay.tar");
      const modes = yield* Effect.forEach(
        relativePaths,
        (relative) => requireRegularArchiveBlob(repository, revision, relative),
        { concurrency: 1 },
      );
      yield* archivePaths(repository, revision, relativePaths, archive);
      yield* Effect.forEach(
        relativePaths,
        (relative, index) =>
          runCommand(
            "tar",
            [
              "--extract",
              "--to-stdout",
              "--file",
              archive,
              "--",
              relative,
            ],
            repository,
            { maxOutputBytes: 1_100_000 },
          ).pipe(
            Effect.flatMap((result) =>
              ensureSuccessful(result, "materialize", "tar extract path"),
            ),
            Effect.flatMap((result) =>
              files.writeBytesWithinRoot(
                destination,
                relative,
                result.stdout,
                modes[index],
              ),
            ),
          ),
        { concurrency: 1, discard: true },
      );
    }),
  );

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
        PYTEST_DISABLE_PLUGIN_AUTOLOAD: "1",
      },
      timeoutMs: value.timeoutSeconds * 1_000,
      maxOutputBytes: 64 * 1024,
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
  Effect.gen(function* () {
    const verifierBudget = cases.reduce(
      (total, value) => total + value.timeoutSeconds * 3 * 1_000,
      0,
    );
    if (verifierBudget > MAX_ADMISSION_VERIFIER_BUDGET_MS) {
      return yield* Effect.fail(
        corpusFailure(
          "configuration",
          "corpus verifier budget exceeds the 36 minute admission cap",
        ),
      );
    }
    yield* validateHistory(repository, cases);
    const checks = yield* Effect.forEach(
      cases,
      (value) => checkCase(repository, value, pythonExecutable),
      { concurrency: 1 },
    );
    return Object.freeze(checks);
  });

export interface PreparedCorpusCase {
  readonly case: CorpusCase;
  readonly metadata: CorpusMetadata;
  readonly baseArchive: string;
  readonly oracleArchive: string;
  readonly verifierArchive: string;
}

export interface PreparedCorpus {
  readonly selected: readonly PreparedCorpusCase[];
}

export const prepareCorpus = (
  corpusPath: string,
  repository: string,
  pythonExecutable: string,
  archiveDirectory: string,
  split: CorpusSplit,
): Effect.Effect<
  PreparedCorpus,
  CorpusApplicationFailure,
  CommandExecutorService | FileStoreService
> =>
  Effect.gen(function* () {
    const cases = yield* loadCases(corpusPath);
    const checks = yield* checkCases(repository, cases, pythonExecutable);
    const invalid = checks.filter((check) => !isValidCaseCheck(check));
    if (invalid.length > 0) {
      return yield* Effect.fail(
        corpusFailure(
          "configuration",
          `corpus admission failed for: ${invalid.map((check) => check.caseId).join(", ")}`,
        ),
      );
    }
    const selectedCases = cases.filter((value) => value.split === split);
    if (selectedCases.length === 0) {
      return yield* Effect.fail(
        corpusFailure("configuration", `corpus contains no ${split} cases`),
      );
    }
    const selected = yield* Effect.forEach(
      selectedCases,
      (value) =>
        Effect.gen(function* () {
          const baseArchive = join(archiveDirectory, `${value.id}-base.tar`);
          const oracleArchive = join(archiveDirectory, `${value.id}-oracle.tar`);
          const verifierArchive = join(
            archiveDirectory,
            `${value.id}-verifier.tar`,
          );
          yield* archiveRevision(repository, value.baseSha, baseArchive);
          yield* archiveRevision(repository, value.oracleSha, oracleArchive);
          yield* archivePaths(
            repository,
            value.oracleSha,
            value.verifierPaths,
            verifierArchive,
          );
          const [baseBytes, oracleBytes, verifierBytes] = yield* Effect.all(
            [
              archiveSize(baseArchive, repository),
              archiveSize(oracleArchive, repository),
              archiveSize(verifierArchive, repository),
            ],
            { concurrency: 1 },
          );
          if (
            baseBytes > MAX_BASE_ARCHIVE_BYTES ||
            oracleBytes > MAX_BASE_ARCHIVE_BYTES ||
            verifierBytes > MAX_VERIFIER_ARCHIVE_BYTES ||
            baseBytes + verifierBytes > MAX_VERIFIER_SERVICE_BYTES
          ) {
            return yield* Effect.fail(
              corpusFailure(
                "materialize",
                `${value.id}: prepared archives exceed the sandbox staging budget`,
              ),
            );
          }
          return Object.freeze({
            case: value,
            metadata: corpusMetadata(value),
            baseArchive,
            oracleArchive,
            verifierArchive,
          });
        }),
      { concurrency: 1 },
    );
    return Object.freeze({
      selected: Object.freeze(selected),
    });
  });

export const scoreCandidate = (
  corpusPath: string,
  caseId: string,
  metadata: unknown,
  oracle: VerifierObservation,
  candidate: VerifierObservation,
): Effect.Effect<CandidateScoreDecision, CorpusFailure | FileFailure, FileStoreService> =>
  loadCases(corpusPath).pipe(
    Effect.map((cases): CandidateScoreDecision => {
      const value = cases.find((entry) => entry.id === caseId);
      if (value === undefined) {
        return Object.freeze({
          kind: "scored",
          correct: false,
          explanation: "sample metadata is not corpus-bound",
          returncode: null,
          oracle_signature_match: false,
        });
      }
      return evaluateCandidateScore(value, metadata, oracle, candidate);
    }),
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
