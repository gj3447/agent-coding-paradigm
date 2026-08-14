import { Effect } from "effect";

import { FileStore, type FileStoreService } from "./ports.js";

export const DGX_MODEL_ID = "qwen3.6-35b-a3b";
export const REACT_MODEL = `openai-api/dgx/${DGX_MODEL_ID}`;
export const AIDER_CONTROL_MODEL = "mockllm/model";

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
}

export interface SecretBinding {
  readonly environmentName: "DGX_API_KEY" | "DGX_API_KEY_FILE";
  readonly source: "secret_value" | "secret_file";
  readonly filePath: string;
}

export interface ComparisonArmPlan {
  readonly schemaVersion: "coding-corpus-comparison-arm/v1";
  readonly arm: ComparisonArm;
  readonly command: readonly string[];
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

const fail = (reason: string): ComparisonPlanResult => ({
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
  | { readonly ok: true; readonly host: string; readonly port: string }
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
  return { ok: true, host: url.hostname, port: url.port };
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
    command.push("--model-base-url", request.dgxBaseUrl);
  }
  if (request.limit !== undefined) {
    command.push("--limit", request.limit);
  }

  return {
    ok: true,
    value: Object.freeze({
      schemaVersion: "coding-corpus-comparison-arm/v1",
      arm: request.arm,
      command: Object.freeze(command),
      secretBinding: Object.freeze(
        request.arm === "react"
          ? {
              environmentName: "DGX_API_KEY" as const,
              source: "secret_value" as const,
              filePath: request.dgxKeyFile,
            }
          : {
              environmentName: "DGX_API_KEY_FILE" as const,
              source: "secret_file" as const,
              filePath: request.dgxKeyFile,
            },
      ),
      fixedEnvironment: Object.freeze(
        request.arm === "aider"
          ? {
              MODEL_GATEWAY_UPSTREAM_HOST: dgx.host,
              MODEL_GATEWAY_UPSTREAM_PORT: dgx.port,
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
): Effect.Effect<string, Error, FileStoreService> =>
  Effect.gen(function* () {
    const files = yield* FileStore;
    const secret = (yield* files.readText(path)).trim();
    if (
      secret.length === 0 ||
      secret.length > 4_096 ||
      /[\u0000\r\n]/u.test(secret)
    ) {
      return yield* Effect.fail(
        new Error("DGX key file is empty or malformed"),
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
    [plan.secretBinding.environmentName]:
      plan.secretBinding.source === "secret_value"
        ? secret
        : plan.secretBinding.filePath,
  });
