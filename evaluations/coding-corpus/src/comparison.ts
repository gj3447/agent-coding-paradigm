import { randomUUID } from "node:crypto";
import { dirname, join } from "node:path";

import { Data, Effect, Either, ParseResult, Schema } from "effect";

import { parseJsonRejectingDuplicateKeys } from "./domain.js";
import {
  CommandExecutor,
  CommandFailure,
  type CommandExecutorService,
  type CommandResult,
  FileFailure,
  FileStore,
  type FileStoreService,
} from "./ports.js";

export const DGX_MODEL_ID = "qwen3.6-35b-a3b";
export const REACT_MODEL = `openai-api/dgx/${DGX_MODEL_ID}`;
export const AIDER_CONTROL_MODEL = "mockllm/model";

const TEXT_DECODER = new TextDecoder("utf-8", { fatal: false });
const TEXT_ENCODER = new TextEncoder();
const INSPECT_METADATA_TIMEOUT_MS = 30_000;
const INSPECT_EVAL_TIMEOUT_MS = 31 * 60 * 1_000;
const GIT_TIMEOUT_MS = 30_000;
const SMALL_OUTPUT_LIMIT = 4 * 1024 * 1024;
const EVAL_OUTPUT_LIMIT = 8 * 1024 * 1024;
const LOG_DUMP_OUTPUT_LIMIT = 32 * 1024 * 1024;

export type ComparisonArm = "react" | "aider";

export interface ComparisonRequest {
  readonly arm: string;
  readonly inspectExecutable: string;
  readonly taskPath: string;
  readonly corpusPath: string;
  readonly repositoryPath: string;
  readonly logDirectory: string;
  readonly dgxBaseUrl: string;
  readonly dgxKeyFile: string;
  readonly limit?: string;
  readonly workingDirectory?: string;
}

export interface OperatorEndpoint {
  readonly baseUrl: string;
  readonly host: string;
  readonly port: string;
}

export interface SecretBinding {
  readonly environmentName: "DGX_API_KEY";
  readonly source: "secret_value";
}

export interface ComparisonArmPlan {
  readonly schemaVersion: "coding-corpus-comparison-arm/v1";
  readonly arm: ComparisonArm;
  readonly inspectExecutable: string;
  readonly workingDirectory: string;
  readonly logDirectory: string;
  readonly command: readonly string[];
  readonly operatorEndpoint: OperatorEndpoint;
  readonly secretBinding: SecretBinding;
  readonly fixedEnvironment: Readonly<Record<string, string>>;
  readonly budgetSemantics:
    | "inspect_total_tokens"
    | "gateway_completion_tokens";
  readonly efficacyComparable: false;
}

export interface ComparisonPlanFailure {
  readonly reason: string;
}

export type ComparisonPlanResult =
  | { readonly ok: true; readonly value: ComparisonArmPlan }
  | { readonly ok: false; readonly error: ComparisonPlanFailure };

export class ComparisonFailure extends Data.TaggedError("ComparisonFailure")<{
  readonly phase:
    | "configuration"
    | "repository"
    | "log_list"
    | "execution"
    | "reconciliation"
    | "log_dump"
    | "log_decode";
  readonly arm: ComparisonArm | null;
  readonly reason: string;
}> {}

export interface ComparisonSampleSummary {
  readonly id: string | number;
  readonly verifier_value: "C" | "I";
  readonly total_time: number | null;
  readonly working_time: number | null;
  readonly turn_count: number | null;
  readonly token_limit_usage: number | null;
  readonly gateway_valid: boolean | null;
  readonly gateway_usage: {
    readonly prompt_tokens: number;
    readonly completion_tokens: number;
    readonly total_tokens: number;
  } | null;
}

export interface ComparisonArmSummary {
  readonly agent: ComparisonArm;
  readonly log: string;
  readonly status: "success";
  readonly task_version: string | number;
  readonly started_at: string;
  readonly completed_at: string;
  readonly samples: readonly ComparisonSampleSummary[];
  readonly command_exit: number;
  readonly command_stderr_tail?: string;
}

export interface AdmittedComparisonRequest {
  readonly arms: readonly ComparisonArm[];
  readonly inspectExecutable: string;
  readonly taskPath: string;
  readonly corpusPath: string;
  readonly corpusSourcePath: string;
  readonly corpusSha256: string;
  readonly repositoryPath: string;
  readonly logDirectory: string;
  readonly dgxBaseUrl: string;
  readonly dgxKeyFile: string;
  readonly limit?: string;
}

export interface ComparisonReport {
  readonly schema_version: "coding-corpus-comparison/v1";
  readonly corpus: string;
  readonly corpus_sha256: string;
  readonly repository: string;
  readonly repository_head: string;
  readonly efficacy_comparable: false;
  readonly non_comparability_reason: "arm_budget_semantics_differ";
  readonly arms: readonly ComparisonArmSummary[];
}

type ComparisonRuntimeFailure = ComparisonFailure | CommandFailure | FileFailure;

type DomainResult<A> =
  | { readonly ok: true; readonly value: A }
  | { readonly ok: false; readonly error: ComparisonPlanFailure };

const succeed = <A>(value: A): DomainResult<A> => ({ ok: true, value });

const fail = (reason: string): ComparisonPlanResult => ({
  ok: false,
  error: { reason },
});

const dataFail = <A>(reason: string): DomainResult<A> => ({
  ok: false,
  error: { reason },
});

const boundedSingleLine = (
  value: string,
  name: string,
  maximum: number,
): string | undefined => {
  if (value.length === 0 || value.length > maximum || /[\u0000\r\n]/u.test(value)) {
    return `${name} must be a non-empty single-line value of at most ${maximum} characters`;
  }
  return undefined;
};

const parseDgxBaseUrl = (
  value: string,
):
  | { readonly ok: true; readonly endpoint: OperatorEndpoint }
  | { readonly ok: false; readonly reason: string } => {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return { ok: false, reason: "DGX base URL is invalid" };
  }
  if (
    url.protocol !== "http:" ||
    url.username !== "" ||
    url.password !== "" ||
    url.hostname === "" ||
    url.hostname.includes(":") ||
    url.port === "" ||
    url.pathname !== "/v1" ||
    url.search !== "" ||
    url.hash !== ""
  ) {
    return {
      ok: false,
      reason: "DGX base URL must be http://<IPv4-or-DNS>:<port>/v1",
    };
  }
  const port = Number(url.port);
  if (!Number.isInteger(port) || port < 1 || port > 65_535) {
    return { ok: false, reason: "DGX base URL port is invalid" };
  }
  return {
    ok: true,
    endpoint: Object.freeze({
      baseUrl: url.href,
      host: url.hostname,
      port: url.port,
    }),
  };
};

export const buildComparisonArmPlan = (
  request: ComparisonRequest,
): ComparisonPlanResult => {
  if (request.arm !== "react" && request.arm !== "aider") {
    return fail(`unsupported arm: ${request.arm}`);
  }
  const dgx = parseDgxBaseUrl(request.dgxBaseUrl);
  if (!dgx.ok) return fail(dgx.reason);
  for (const [name, value] of [
    ["inspectExecutable", request.inspectExecutable],
    ["taskPath", request.taskPath],
    ["corpusPath", request.corpusPath],
    ["repositoryPath", request.repositoryPath],
    ["logDirectory", request.logDirectory],
    ["dgxKeyFile", request.dgxKeyFile],
  ] as const) {
    const reason = boundedSingleLine(value, name, 4_096);
    if (reason !== undefined) return fail(reason);
  }
  if (request.limit !== undefined) {
    const reason = boundedSingleLine(request.limit, "limit", 64);
    if (reason !== undefined) return fail(reason);
  }

  const model = request.arm === "react" ? REACT_MODEL : AIDER_CONTROL_MODEL;
  const command = [
    request.inspectExecutable,
    "eval",
    `${request.taskPath}@company_coding`,
    "-T",
    `corpus=${request.corpusPath}`,
    "-T",
    `repository=${request.repositoryPath}`,
    "-T",
    `agent=${request.arm}`,
    "-T",
    "split=calibration",
    "-T",
    "epochs=1",
    "--model",
    model,
    "--max-connections",
    "1",
    "--adaptive-connections",
    "false",
    "--max-retries",
    "0",
    "--timeout",
    "180",
    "--attempt-timeout",
    "300",
    "--max-samples",
    "1",
    "--max-tasks",
    "1",
    "--max-sandboxes",
    "1",
    "--token-limit",
    "32000",
    "--turn-limit",
    "8",
    "--time-limit",
    "1800",
    "--max-tokens",
    "4096",
    "--temperature",
    "0",
    "--log-dir",
    request.logDirectory,
    "--display",
    "none",
    "--no-log-model-api",
    "--no-fail-on-error",
  ];
  if (request.arm === "react") {
    command.push("--model-base-url", dgx.endpoint.baseUrl);
  }
  if (request.limit !== undefined) {
    command.push("--limit", request.limit);
  }

  return {
    ok: true,
    value: Object.freeze({
      schemaVersion: "coding-corpus-comparison-arm/v1",
      arm: request.arm,
      inspectExecutable: request.inspectExecutable,
      workingDirectory: request.workingDirectory ?? dirname(request.taskPath),
      logDirectory: request.logDirectory,
      command: Object.freeze(command),
      operatorEndpoint: dgx.endpoint,
      secretBinding: Object.freeze(
        {
          environmentName: "DGX_API_KEY" as const,
          source: "secret_value" as const,
        },
      ),
      fixedEnvironment: Object.freeze(
        request.arm === "aider"
          ? {
              MODEL_GATEWAY_UPSTREAM_HOST: dgx.endpoint.host,
              MODEL_GATEWAY_UPSTREAM_PORT: dgx.endpoint.port,
            }
          : {},
      ),
      budgetSemantics:
        request.arm === "react"
          ? "inspect_total_tokens"
          : "gateway_completion_tokens",
      efficacyComparable: false,
    }),
  };
};

export const readComparisonSecret = (
  path: string,
): Effect.Effect<string, ComparisonFailure | FileFailure, FileStoreService> =>
  Effect.gen(function* () {
    const files = yield* FileStore;
    const secret = (yield* files.readText(path, { maxBytes: 4_096 })).trim();
    if (
      secret.length === 0 ||
      secret.length > 4_096 ||
      /[\u0000\r\n]/u.test(secret)
    ) {
      return yield* Effect.fail(
        new ComparisonFailure({
          phase: "configuration",
          arm: null,
          reason: "DGX key file is empty or malformed",
        }),
      );
    }
    return secret;
  });

export const comparisonEnvironment = (
  plan: ComparisonArmPlan,
  secret: string,
): Readonly<Record<string, string>> =>
  Object.freeze({
    ...plan.fixedEnvironment,
    [plan.secretBinding.environmentName]: secret,
  });

export const selectComparisonControllerEnvironment = (
  source: Readonly<NodeJS.ProcessEnv>,
): Readonly<NodeJS.ProcessEnv> => {
  const selected: NodeJS.ProcessEnv = {
    PATH: `${dirname(process.execPath)}:/usr/local/bin:/usr/bin:/bin`,
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
  };
  const runtime = source["XDG_RUNTIME_DIR"];
  if (runtime !== undefined && !/[\u0000\r\n]/u.test(runtime)) {
    selected["XDG_RUNTIME_DIR"] = runtime;
  }
  const explicitHost = source["DOCKER_HOST"];
  if (explicitHost !== undefined && !/[\u0000\r\n]/u.test(explicitHost)) {
    selected["DOCKER_HOST"] = explicitHost;
  } else if (runtime !== undefined && !/[\u0000\r\n]/u.test(runtime)) {
    selected["DOCKER_HOST"] = `unix://${runtime}/docker.sock`;
  }
  for (const name of ["DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"] as const) {
    const value = source[name];
    if (value !== undefined && !/[\u0000\r\n]/u.test(value)) {
      selected[name] = value;
    }
  }
  return Object.freeze(selected);
};

const UnknownRecordSchema = Schema.Record({
  key: Schema.String,
  value: Schema.Unknown,
});
const NullableNumberSchema = Schema.NullOr(Schema.Number);
const InspectSampleSchema = Schema.Struct({
  id: Schema.Union(Schema.String, Schema.Number),
  scores: Schema.optional(Schema.NullOr(UnknownRecordSchema)),
  total_time: Schema.optional(NullableNumberSchema),
  working_time: Schema.optional(NullableNumberSchema),
  turn_count: Schema.optional(NullableNumberSchema),
  token_limit_usage: Schema.optional(NullableNumberSchema),
  model_usage: Schema.optional(UnknownRecordSchema),
  output: Schema.Struct({
    metadata: Schema.optional(Schema.NullOr(UnknownRecordSchema)),
  }),
  error: Schema.optional(
    Schema.NullOr(Schema.Struct({ message: Schema.String })),
  ),
});
const InspectLogSchema = Schema.Struct({
  status: Schema.Literal("started", "success", "cancelled", "error"),
  eval: Schema.Struct({
    task_version: Schema.Union(Schema.String, Schema.Number),
  }),
  stats: Schema.Struct({
    started_at: Schema.String,
    completed_at: Schema.String,
  }),
  samples: Schema.optional(Schema.NullOr(Schema.Array(InspectSampleSchema))),
});
const InspectLogListSchema = Schema.Array(
  Schema.Struct({ name: Schema.String }),
);

const isRecord = (value: unknown): value is Readonly<Record<string, unknown>> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const repositoryVerifierValue = (value: unknown): "C" | "I" | undefined => {
  if (!isRecord(value)) return undefined;
  const score = value["repository_verifier"];
  if (!isRecord(score)) return undefined;
  const verdict = score["value"];
  return verdict === "C" || verdict === "I" ? verdict : undefined;
};

const nonnegativeInteger = (value: unknown): value is number =>
  typeof value === "number" && Number.isInteger(value) && value >= 0;

const gatewayUsage = (
  metadata: unknown,
): ComparisonSampleSummary["gateway_usage"] | undefined => {
  if (!isRecord(metadata)) return undefined;
  const validation = metadata["gateway_validation"];
  if (
    !isRecord(validation) ||
    validation["schema_version"] !== "model-gateway-validation/v2" ||
    validation["valid"] !== true ||
    validation["error"] !== null
  ) {
    return undefined;
  }
  const gateway = validation["metrics"];
  if (
    !isRecord(gateway) ||
    gateway["schema_version"] !== "model-gateway-metrics/v2"
  ) {
    return undefined;
  }
  const usage = gateway["usage"];
  if (!isRecord(usage)) return undefined;
  const promptTokens = usage["prompt_tokens"];
  const completionTokens = usage["completion_tokens"];
  const totalTokens = usage["total_tokens"];
  if (
    !nonnegativeInteger(promptTokens) ||
    !nonnegativeInteger(completionTokens) ||
    !nonnegativeInteger(totalTokens) ||
    promptTokens + completionTokens !== totalTokens
  ) {
    return undefined;
  }
  return Object.freeze({
    prompt_tokens: promptTokens,
    completion_tokens: completionTokens,
    total_tokens: totalTokens,
  });
};

export const summarizeInspectLog = (
  arm: ComparisonArm,
  location: string,
  value: unknown,
): DomainResult<Omit<ComparisonArmSummary, "command_exit" | "command_stderr_tail">> => {
  const decoded = Schema.decodeUnknownEither(InspectLogSchema, {
    errors: "all",
  })(value);
  if (Either.isLeft(decoded)) {
    return dataFail(ParseResult.TreeFormatter.formatErrorSync(decoded.left));
  }
  const log = decoded.right;
  if (log.status !== "success") {
    return dataFail(`Inspect log status is ${log.status}, not success`);
  }
  const rawSamples = log.samples ?? [];
  if (rawSamples.length === 0) {
    return dataFail("Inspect success log contains no samples");
  }
  const samples: ComparisonSampleSummary[] = [];
  for (const sample of rawSamples) {
    if (sample.error !== null && sample.error !== undefined) {
      return dataFail("Inspect success log contains a sample error");
    }
    const verdict = repositoryVerifierValue(sample.scores);
    if (verdict === undefined) {
      return dataFail("Inspect sample lacks a closed repository verifier score");
    }
    const metadata = sample.output.metadata ?? null;
    const usage = arm === "aider" ? gatewayUsage(metadata) : null;
    if (arm === "aider" && usage === undefined) {
      return dataFail("Aider sample lacks valid TS gateway evidence");
    }
    samples.push(
      Object.freeze({
        id: sample.id,
        verifier_value: verdict,
        total_time: sample.total_time ?? null,
        working_time: sample.working_time ?? null,
        turn_count: sample.turn_count ?? null,
        token_limit_usage: sample.token_limit_usage ?? null,
        gateway_valid: arm === "aider" ? true : null,
        gateway_usage: usage ?? null,
      }),
    );
  }
  return succeed({
    agent: arm,
    log: location,
    status: log.status,
    task_version: log.eval.task_version,
    started_at: log.stats.started_at,
    completed_at: log.stats.completed_at,
    samples: Object.freeze(samples),
  });
};

const comparisonFailure = (
  phase: ComparisonFailure["phase"],
  arm: ComparisonArm | null,
  reason: string,
): ComparisonFailure => new ComparisonFailure({ phase, arm, reason });

const runCommand = (
  command: string,
  args: readonly string[],
  cwd: string,
  timeoutMs: number,
  maxOutputBytes: number,
  environment?: Readonly<Record<string, string>>,
): Effect.Effect<CommandResult, CommandFailure, CommandExecutorService> =>
  Effect.gen(function* () {
    const executor = yield* CommandExecutor;
    return yield* executor.run({
      command,
      args,
      cwd,
      timeoutMs,
      maxOutputBytes,
      ...(environment === undefined ? {} : { environment }),
    });
  });

const ensureZero = (
  result: CommandResult,
  phase: ComparisonFailure["phase"],
  arm: ComparisonArm | null,
  operation: string,
): Effect.Effect<CommandResult, ComparisonFailure> =>
  result.exitCode === 0
    ? Effect.succeed(result)
    : Effect.fail(
        comparisonFailure(
          phase,
          arm,
          `${operation} exited ${result.exitCode}: ${TEXT_DECODER.decode(result.stderr).trim().slice(-2_000)}`,
        ),
      );

const parseLogNames = (source: string): DomainResult<readonly string[]> => {
  const parsed = parseJsonRejectingDuplicateKeys(source);
  if (!parsed.ok) return dataFail(parsed.error.reason);
  const decoded = Schema.decodeUnknownEither(InspectLogListSchema, {
    errors: "all",
  })(parsed.value);
  if (Either.isLeft(decoded)) {
    return dataFail(ParseResult.TreeFormatter.formatErrorSync(decoded.left));
  }
  const names = decoded.right.map(({ name }) => name);
  if (new Set(names).size !== names.length) {
    return dataFail("Inspect log listing contains duplicate names");
  }
  return succeed(Object.freeze(names));
};

const listLogNames = (
  plan: ComparisonArmPlan,
): Effect.Effect<readonly string[], ComparisonRuntimeFailure, CommandExecutorService> =>
  runCommand(
    plan.inspectExecutable,
    [
      "log",
      "list",
      "--json",
      "--absolute",
      "--log-dir",
      plan.logDirectory,
      "--display",
      "none",
    ],
    plan.workingDirectory,
    INSPECT_METADATA_TIMEOUT_MS,
    SMALL_OUTPUT_LIMIT,
  ).pipe(
    Effect.flatMap((result) =>
      ensureZero(result, "log_list", plan.arm, "inspect log list"),
    ),
    Effect.flatMap((result) => {
      const parsed = parseLogNames(TEXT_DECODER.decode(result.stdout));
      return parsed.ok
        ? Effect.succeed(parsed.value)
        : Effect.fail(
            comparisonFailure("log_list", plan.arm, parsed.error.reason),
          );
    }),
  );

const findSingleNewLog = (
  before: readonly string[],
  after: readonly string[],
): DomainResult<string> => {
  const known = new Set(before);
  const candidates = after.filter((name) => !known.has(name));
  return candidates.length === 1 && candidates[0] !== undefined
    ? succeed(candidates[0])
    : dataFail(
        `expected one new eval log, found ${JSON.stringify([...candidates].sort())}`,
      );
};

const dumpLog = (
  plan: ComparisonArmPlan,
  location: string,
): Effect.Effect<unknown, ComparisonRuntimeFailure, CommandExecutorService> =>
  runCommand(
    plan.inspectExecutable,
    ["log", "dump", location],
    plan.workingDirectory,
    INSPECT_METADATA_TIMEOUT_MS,
    LOG_DUMP_OUTPUT_LIMIT,
  ).pipe(
    Effect.flatMap((result) =>
      ensureZero(result, "log_dump", plan.arm, "inspect log dump"),
    ),
    Effect.flatMap((result) => {
      const parsed = parseJsonRejectingDuplicateKeys(
        TEXT_DECODER.decode(result.stdout),
      );
      return parsed.ok
        ? Effect.succeed(parsed.value)
        : Effect.fail(
            comparisonFailure("log_decode", plan.arm, parsed.error.reason),
          );
    }),
  );

const redactSecret = (value: string, secret: string): string =>
  secret.length === 0 ? value : value.split(secret).join("[REDACTED]");

const redactRuntimeFailure = (
  error: ComparisonRuntimeFailure,
  secret: string,
): ComparisonRuntimeFailure => {
  if (error instanceof ComparisonFailure) {
    return new ComparisonFailure({
      phase: error.phase,
      arm: error.arm,
      reason: redactSecret(error.reason, secret),
    });
  }
  if (error instanceof CommandFailure) {
    return new CommandFailure({
      command: error.command,
      reason: error.reason,
      detail: redactSecret(error.detail, secret),
    });
  }
  return new FileFailure({
    operation: error.operation,
    path: redactSecret(error.path, secret),
    reason: redactSecret(error.reason, secret),
  });
};

const containsSecretString = (value: unknown, secret: string): boolean => {
  if (typeof value === "string") return value.includes(secret);
  if (Array.isArray(value)) {
    return value.some((item) => containsSecretString(item, secret));
  }
  if (isRecord(value)) {
    return Object.entries(value).some(
      ([key, item]) =>
        key.includes(secret) || containsSecretString(item, secret),
    );
  }
  return false;
};

const reconciliationDescription = (
  before: readonly string[],
  after: readonly string[],
): string => {
  const reconciled = findSingleNewLog(before, after);
  return reconciled.ok
    ? `one new log observed: ${reconciled.value}`
    : reconciled.error.reason;
};

const runArm = (
  plan: ComparisonArmPlan,
  secret: string,
): Effect.Effect<ComparisonArmSummary, ComparisonRuntimeFailure, CommandExecutorService> =>
  Effect.gen(function* () {
    const before = yield* listLogNames(plan);
    if (before.length !== 0) {
      return yield* Effect.fail(
        comparisonFailure(
          "reconciliation",
          plan.arm,
          "exclusive arm log directory was not empty",
        ),
      );
    }
    const evaluation = runCommand(
      plan.inspectExecutable,
      plan.command.slice(1),
      plan.workingDirectory,
      INSPECT_EVAL_TIMEOUT_MS,
      EVAL_OUTPUT_LIMIT,
      comparisonEnvironment(plan, secret),
    ).pipe(
      Effect.onInterrupt(() =>
        listLogNames(plan).pipe(Effect.ignore, Effect.uninterruptible),
      ),
    );
    const executed = yield* Effect.either(evaluation);
    const afterAttempt = yield* Effect.either(listLogNames(plan));
    if (Either.isLeft(executed)) {
      const reconciliation = Either.isRight(afterAttempt)
        ? reconciliationDescription(before, afterAttempt.right)
        : `log reconciliation failed: ${afterAttempt.left._tag}`;
      return yield* Effect.fail(
        comparisonFailure(
          "reconciliation",
          plan.arm,
          `${executed.left.reason}: ${redactSecret(executed.left.detail, secret)}; ${reconciliation}`,
        ),
      );
    }
    if (Either.isLeft(afterAttempt)) return yield* Effect.fail(afterAttempt.left);
    const location = findSingleNewLog(before, afterAttempt.right);
    if (!location.ok) {
      return yield* Effect.fail(
        comparisonFailure("reconciliation", plan.arm, location.error.reason),
      );
    }
    const rawLog = yield* dumpLog(plan, location.value);
    const summarized = summarizeInspectLog(plan.arm, location.value, rawLog);
    if (!summarized.ok) {
      return yield* Effect.fail(
        comparisonFailure(
          "log_decode",
          plan.arm,
          redactSecret(summarized.error.reason, secret),
        ),
      );
    }
    const stderr = TEXT_DECODER.decode(executed.right.stderr);
    return {
      ...summarized.value,
      command_exit: executed.right.exitCode,
      ...(executed.right.exitCode === 0
        ? {}
        : {
            command_stderr_tail: redactSecret(stderr, secret).slice(-2_000),
          }),
    };
  });

const buildPlans = (
  request: AdmittedComparisonRequest,
  workingDirectory: string,
  invocationLogDirectory: string,
): DomainResult<readonly ComparisonArmPlan[]> => {
  if (request.arms.length < 1 || request.arms.length > 2) {
    return dataFail("arms must contain one or two entries");
  }
  if (new Set(request.arms).size !== request.arms.length) {
    return dataFail("arms must not contain duplicates");
  }
  const plans: ComparisonArmPlan[] = [];
  for (const arm of request.arms) {
    const planned = buildComparisonArmPlan({
      arm,
      inspectExecutable: request.inspectExecutable,
      taskPath: request.taskPath,
      corpusPath: request.corpusPath,
      repositoryPath: request.repositoryPath,
      dgxBaseUrl: request.dgxBaseUrl,
      dgxKeyFile: request.dgxKeyFile,
      workingDirectory,
      logDirectory: join(invocationLogDirectory, arm),
      ...(request.limit === undefined ? {} : { limit: request.limit }),
    });
    if (!planned.ok) return dataFail(planned.error.reason);
    plans.push(planned.value);
  }
  const baseline = plans[0];
  if (
    baseline === undefined ||
    plans.some(
      (plan) =>
        plan.operatorEndpoint.baseUrl !== baseline.operatorEndpoint.baseUrl ||
        plan.operatorEndpoint.host !== baseline.operatorEndpoint.host ||
        plan.operatorEndpoint.port !== baseline.operatorEndpoint.port,
    )
  ) {
    return dataFail("comparison arms do not share one operator endpoint");
  }
  return succeed(Object.freeze(plans));
};

export const runAdmittedComparison = (
  request: AdmittedComparisonRequest,
): Effect.Effect<ComparisonReport, ComparisonRuntimeFailure, CommandExecutorService | FileStoreService> =>
  Effect.scoped(Effect.gen(function* () {
    const files = yield* FileStore;
    const workingDirectory = yield* Effect.acquireRelease(
      files.makeTempDirectory("coding-corpus-controller-"),
      (path) => files.remove(path).pipe(Effect.orDie),
    );
    yield* files.writeBytesAtomic(
      join(workingDirectory, ".env"),
      new Uint8Array(),
    );
    const invocationLogDirectory = join(
      request.logDirectory,
      randomUUID(),
    );
    yield* files.makeDirectory(invocationLogDirectory, { recursive: true });
    const plans = buildPlans(
      request,
      workingDirectory,
      invocationLogDirectory,
    );
    if (!plans.ok) {
      return yield* Effect.fail(
        comparisonFailure("configuration", null, plans.error.reason),
      );
    }
    yield* Effect.forEach(
      plans.value,
      (plan) => files.makeDirectory(plan.logDirectory, { recursive: true }),
      { concurrency: 1, discard: true },
    );
    const repositoryHead = yield* runCommand(
      "git",
      ["-C", request.repositoryPath, "rev-parse", "HEAD"],
      request.repositoryPath,
      GIT_TIMEOUT_MS,
      SMALL_OUTPUT_LIMIT,
    ).pipe(
      Effect.flatMap((result) =>
        ensureZero(result, "repository", null, "git rev-parse HEAD"),
      ),
      Effect.map((result) => TEXT_DECODER.decode(result.stdout).trim()),
    );
    if (!/^[0-9a-f]{40}$/u.test(repositoryHead)) {
      return yield* Effect.fail(
        comparisonFailure(
          "repository",
          null,
          "git rev-parse HEAD did not return a full lower-case SHA",
        ),
      );
    }
    const secret = yield* readComparisonSecret(request.dgxKeyFile);
    const arms = yield* Effect.forEach(
      plans.value,
      (plan) => runArm(plan, secret),
      { concurrency: 1 },
    ).pipe(Effect.mapError((error) => redactRuntimeFailure(error, secret)));
    const report = Object.freeze({
      schema_version: "coding-corpus-comparison/v1",
      corpus: request.corpusSourcePath,
      corpus_sha256: request.corpusSha256,
      repository: request.repositoryPath,
      repository_head: repositoryHead,
      efficacy_comparable: false,
      non_comparability_reason: "arm_budget_semantics_differ",
      arms: Object.freeze(arms),
    });
    if (containsSecretString(report, secret)) {
      return yield* Effect.fail(
        comparisonFailure(
          "log_decode",
          null,
          "comparison report contains the operator secret",
        ),
      );
    }
    return report;
  }));

export const isSuccessfulComparisonArm = (
  arm: ComparisonArmSummary,
): boolean =>
  arm.command_exit === 0 &&
  arm.status === "success" &&
  arm.samples.length > 0 &&
  arm.samples.every(
    (sample) =>
      sample.verifier_value === "C" || sample.verifier_value === "I",
  );

export const encodeComparisonReport = (report: ComparisonReport): Uint8Array =>
  TEXT_ENCODER.encode(
    `${JSON.stringify(report, undefined, 2)}\n`,
  );
