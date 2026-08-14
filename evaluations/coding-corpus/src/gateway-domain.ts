export const GATEWAY_METRICS_SCHEMA = "model-gateway-metrics/v2";
export const ALLOWED_MODEL = "qwen3.6-35b-a3b";
export const UPSTREAM_PATH = "/v1/chat/completions";

export interface GatewayLimits {
  readonly maxBodyBytes: number;
  readonly maxResponseBytes: number;
  readonly maxTokensPerRequest: number;
  readonly maxRequests: number;
  readonly requestBudgetBasis:
    "react_turn_limit_ceiling_not_call_equivalence";
  readonly maxCompletionTokens: number;
  readonly maxConcurrency: number;
}

export const DEFAULT_GATEWAY_LIMITS: GatewayLimits = Object.freeze({
  maxBodyBytes: 2 * 1024 * 1024,
  maxResponseBytes: 8 * 1024 * 1024,
  maxTokensPerRequest: 4_096,
  maxRequests: 8,
  requestBudgetBasis: "react_turn_limit_ceiling_not_call_equivalence",
  maxCompletionTokens: 32_000,
  maxConcurrency: 1,
});

export interface TokenUsage {
  readonly promptTokens: number;
  readonly completionTokens: number;
  readonly totalTokens: number;
}

export interface GatewayMetrics {
  readonly schemaVersion: typeof GATEWAY_METRICS_SCHEMA;
  readonly requestsSeen: number;
  readonly requestsAdmitted: number;
  readonly requestsCompleted: number;
  readonly requestsRejected: number;
  readonly requestsInFlight: number;
  readonly peakConcurrency: number;
  readonly upstreamRequests: number;
  readonly upstreamFailures: number;
  readonly requestBytes: number;
  readonly responseBytes: number;
  readonly statusCounts: Readonly<Record<string, number>>;
  readonly usage: TokenUsage;
  readonly completionTokensReserved: number;
  readonly completionTokensUnknown: number;
  readonly completionBudgetOvershoot: number;
  readonly lastErrorCode: string | null;
  readonly limits: GatewayLimits;
}

export type GatewayDomainResult<A> =
  | { readonly ok: true; readonly value: A }
  | { readonly ok: false; readonly status: number; readonly code: string };

const accepted = <A>(value: A): GatewayDomainResult<A> => ({ ok: true, value });
const rejected = (status: number, code: string): GatewayDomainResult<never> => ({
  ok: false,
  status,
  code,
});

const nonnegativeInteger = (value: unknown): value is number =>
  typeof value === "number" && Number.isInteger(value) && value >= 0;

const positiveInteger = (value: unknown): value is number =>
  nonnegativeInteger(value) && value > 0;

const incrementStatus = (
  statuses: Readonly<Record<string, number>>,
  status: number,
): Readonly<Record<string, number>> => {
  const key = String(status);
  return Object.freeze({ ...statuses, [key]: (statuses[key] ?? 0) + 1 });
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const hasOnlyKeys = (
  value: Readonly<Record<string, unknown>>,
  allowed: ReadonlySet<string>,
): boolean => Object.keys(value).every((key) => allowed.has(key));

const isBoundedText = (value: unknown, maximum = 1_000_000): value is string =>
  typeof value === "string" &&
  value.length <= maximum &&
  !/[\u0000]/u.test(value);

const MESSAGE_KEYS = new Set([
  "role",
  "content",
  "name",
  "tool_call_id",
  "tool_calls",
  "reasoning_content",
]);
const TOOL_CALL_KEYS = new Set(["id", "type", "function"]);
const TOOL_CALL_FUNCTION_KEYS = new Set(["name", "arguments"]);
const TOOL_DEFINITION_KEYS = new Set(["type", "function"]);
const TOOL_FUNCTION_KEYS = new Set([
  "name",
  "description",
  "parameters",
  "strict",
]);

const validToolCalls = (value: unknown): boolean =>
  Array.isArray(value) &&
  value.length > 0 &&
  value.length <= 32 &&
  value.every((item) => {
    if (!isRecord(item) || !hasOnlyKeys(item, TOOL_CALL_KEYS)) return false;
    if (!isBoundedText(item["id"], 256) || item["type"] !== "function") {
      return false;
    }
    const fn = item["function"];
    return (
      isRecord(fn) &&
      hasOnlyKeys(fn, TOOL_CALL_FUNCTION_KEYS) &&
      isBoundedText(fn["name"], 256) &&
      isBoundedText(fn["arguments"])
    );
  });

const validMessages = (value: unknown): value is readonly unknown[] =>
  Array.isArray(value) &&
  value.length > 0 &&
  value.length <= 256 &&
  value.every((item) => {
    if (!isRecord(item) || !hasOnlyKeys(item, MESSAGE_KEYS)) return false;
    const role = item["role"];
    if (
      role !== "system" &&
      role !== "developer" &&
      role !== "user" &&
      role !== "assistant" &&
      role !== "tool"
    ) {
      return false;
    }
    if (item["name"] !== undefined && !isBoundedText(item["name"], 256)) {
      return false;
    }
    if (
      item["reasoning_content"] !== undefined &&
      !isBoundedText(item["reasoning_content"])
    ) {
      return false;
    }
    if (role === "assistant") {
      if (item["content"] !== null && !isBoundedText(item["content"])) {
        return false;
      }
      return item["tool_calls"] === undefined || validToolCalls(item["tool_calls"]);
    }
    if (!isBoundedText(item["content"])) return false;
    if (role === "tool") {
      return isBoundedText(item["tool_call_id"], 256) && item["tool_calls"] === undefined;
    }
    return item["tool_call_id"] === undefined && item["tool_calls"] === undefined;
  });

const validTools = (value: unknown): value is readonly unknown[] =>
  Array.isArray(value) &&
  value.length > 0 &&
  value.length <= 128 &&
  value.every((item) => {
    if (!isRecord(item) || !hasOnlyKeys(item, TOOL_DEFINITION_KEYS)) return false;
    if (item["type"] !== "function") return false;
    const fn = item["function"];
    if (!isRecord(fn) || !hasOnlyKeys(fn, TOOL_FUNCTION_KEYS)) return false;
    if (!isBoundedText(fn["name"], 256)) return false;
    if (fn["description"] !== undefined && !isBoundedText(fn["description"])) {
      return false;
    }
    if (fn["parameters"] !== undefined && !isRecord(fn["parameters"])) {
      return false;
    }
    return fn["strict"] === undefined || typeof fn["strict"] === "boolean";
  });

export const initialGatewayMetrics = (
  limits: GatewayLimits = DEFAULT_GATEWAY_LIMITS,
): GatewayMetrics =>
  Object.freeze({
    schemaVersion: GATEWAY_METRICS_SCHEMA,
    requestsSeen: 0,
    requestsAdmitted: 0,
    requestsCompleted: 0,
    requestsRejected: 0,
    requestsInFlight: 0,
    peakConcurrency: 0,
    upstreamRequests: 0,
    upstreamFailures: 0,
    requestBytes: 0,
    responseBytes: 0,
    statusCounts: Object.freeze({}),
    usage: Object.freeze({
      promptTokens: 0,
      completionTokens: 0,
      totalTokens: 0,
    }),
    completionTokensReserved: 0,
    completionTokensUnknown: 0,
    completionBudgetOvershoot: 0,
    lastErrorCode: null,
    limits,
  });

export interface AdmissionTransition {
  readonly metrics: GatewayMetrics;
  readonly admitted: boolean;
  readonly reason?: string;
}

export const admitGatewayRequest = (
  state: GatewayMetrics,
): AdmissionTransition => {
  const requestsSeen = state.requestsSeen + 1;
  const reject = (reason: string): AdmissionTransition => ({
    admitted: false,
    reason,
    metrics: Object.freeze({
      ...state,
      requestsSeen,
      requestsRejected: state.requestsRejected + 1,
      lastErrorCode: reason,
      statusCounts: incrementStatus(state.statusCounts, 429),
    }),
  });
  if (state.completionTokensUnknown > 0) {
    return reject("unknown_completion_outcome_requires_reconciliation");
  }
  if (requestsSeen > state.limits.maxRequests) {
    return reject("request_budget_exhausted");
  }
  if (state.requestsInFlight >= state.limits.maxConcurrency) {
    return reject("concurrency_limit");
  }
  const inFlight = state.requestsInFlight + 1;
  return {
    admitted: true,
    metrics: Object.freeze({
      ...state,
      requestsSeen,
      requestsAdmitted: state.requestsAdmitted + 1,
      requestsInFlight: inFlight,
      peakConcurrency: Math.max(state.peakConcurrency, inFlight),
    }),
  };
};

export const rejectUnadmittedRequest = (
  state: GatewayMetrics,
  status: number,
  code: string,
): GatewayMetrics =>
  Object.freeze({
    ...state,
    requestsSeen: state.requestsSeen + 1,
    requestsRejected: state.requestsRejected + 1,
    lastErrorCode: code,
    statusCounts: incrementStatus(state.statusCounts, status),
  });

export interface CompletionReservationTransition {
  readonly metrics: GatewayMetrics;
  readonly reserved: boolean;
  readonly reason?: string;
}

export const reserveCompletionTokens = (
  state: GatewayMetrics,
  requested: number,
): CompletionReservationTransition => {
  if (!positiveInteger(requested) || requested > state.limits.maxTokensPerRequest) {
    return { metrics: state, reserved: false, reason: "completion_reservation_invalid" };
  }
  if (
      state.usage.completionTokens +
      state.completionTokensReserved +
      state.completionTokensUnknown +
      requested >
    state.limits.maxCompletionTokens
  ) {
    return {
      metrics: state,
      reserved: false,
      reason: "completion_token_budget_exhausted",
    };
  }
  return {
    reserved: true,
    metrics: Object.freeze({
      ...state,
      completionTokensReserved: state.completionTokensReserved + requested,
    }),
  };
};

export interface FinishGatewayRequest {
  readonly status: number;
  readonly rejected: boolean;
  readonly upstreamStarted: boolean;
  readonly upstreamFailed: boolean;
  readonly requestBytes: number;
  readonly responseBytes: number;
  readonly usage: Partial<TokenUsage>;
  readonly reservedCompletionTokens: number;
  readonly completionOutcomeUnknown: boolean;
  readonly errorCode: string | null;
}

export const finishGatewayRequest = (
  state: GatewayMetrics,
  event: FinishGatewayRequest,
): GatewayDomainResult<GatewayMetrics> => {
  if (state.requestsInFlight < 1) {
    return rejected(500, "metrics_lost_admitted_request");
  }
  const promptTokens = event.usage.promptTokens ?? 0;
  const completionTokens = event.usage.completionTokens ?? 0;
  const totalTokens = event.usage.totalTokens ?? 0;
  if (
    !nonnegativeInteger(promptTokens) ||
    !nonnegativeInteger(completionTokens) ||
    !nonnegativeInteger(totalTokens)
  ) {
    return rejected(500, "metrics_usage_invalid");
  }
  if (
    !nonnegativeInteger(event.reservedCompletionTokens) ||
    event.reservedCompletionTokens > state.completionTokensReserved ||
    completionTokens > event.reservedCompletionTokens
  ) {
    return rejected(500, "metrics_completion_reservation_invalid");
  }
  const usage = Object.freeze({
    promptTokens: state.usage.promptTokens + promptTokens,
    completionTokens: state.usage.completionTokens + completionTokens,
    totalTokens: state.usage.totalTokens + totalTokens,
  });
  return accepted(
    Object.freeze({
      ...state,
      requestsCompleted: state.requestsCompleted + 1,
      requestsRejected: state.requestsRejected + (event.rejected ? 1 : 0),
      requestsInFlight: state.requestsInFlight - 1,
      upstreamRequests: state.upstreamRequests + (event.upstreamStarted ? 1 : 0),
      upstreamFailures: state.upstreamFailures + (event.upstreamFailed ? 1 : 0),
      requestBytes: state.requestBytes + event.requestBytes,
      responseBytes: state.responseBytes + event.responseBytes,
      statusCounts: incrementStatus(state.statusCounts, event.status),
      usage,
      completionTokensReserved:
        state.completionTokensReserved - event.reservedCompletionTokens,
      completionTokensUnknown:
        state.completionTokensUnknown +
        (event.completionOutcomeUnknown ? event.reservedCompletionTokens : 0),
      completionBudgetOvershoot: Math.max(
        0,
        usage.completionTokens - state.limits.maxCompletionTokens,
      ),
      lastErrorCode: event.errorCode,
    }),
  );
};

const FORBIDDEN_ROUTING_FIELDS = new Set([
  "api_base",
  "api_key",
  "auth",
  "authorization",
  "base_url",
  "credential",
  "endpoint",
  "host",
  "port",
  "token",
  "upstream",
  "url",
]);

const ALLOWED_PAYLOAD_FIELDS = new Set([
  "model",
  "messages",
  "tools",
  "tool_choice",
  "parallel_tool_calls",
  "max_tokens",
  "max_completion_tokens",
  "temperature",
  "stream",
  "n",
]);

export const validateGatewayPayload = (
  value: unknown,
  limits: GatewayLimits = DEFAULT_GATEWAY_LIMITS,
): GatewayDomainResult<Readonly<Record<string, unknown>>> => {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return rejected(400, "body_not_object");
  }
  const payload = value as Record<string, unknown>;
  if (Object.keys(payload).some((key) => FORBIDDEN_ROUTING_FIELDS.has(key))) {
    return rejected(400, "routing_field_not_allowed");
  }
  if (Object.keys(payload).some((key) => !ALLOWED_PAYLOAD_FIELDS.has(key))) {
    return rejected(400, "payload_field_not_allowed");
  }
  if (payload["model"] !== ALLOWED_MODEL) {
    return rejected(400, "model_not_allowed");
  }
  const messages = payload["messages"];
  if (!validMessages(messages)) {
    return rejected(400, "messages_invalid");
  }
  const tools = payload["tools"];
  if (tools !== undefined && !validTools(tools)) {
    return rejected(400, "tools_invalid");
  }
  const toolChoice = payload["tool_choice"];
  if (
    toolChoice !== undefined &&
    toolChoice !== "auto" &&
    toolChoice !== "none" &&
    toolChoice !== "required" &&
    (!isRecord(toolChoice) ||
      !hasOnlyKeys(toolChoice, new Set(["type", "function"])) ||
      toolChoice["type"] !== "function" ||
      !isRecord(toolChoice["function"]) ||
      !hasOnlyKeys(toolChoice["function"], new Set(["name"])) ||
      !isBoundedText(toolChoice["function"]["name"], 256))
  ) {
    return rejected(400, "tool_choice_invalid");
  }
  if (
    payload["parallel_tool_calls"] !== undefined &&
    payload["parallel_tool_calls"] !== false
  ) {
    return rejected(400, "parallel_tool_calls_not_allowed");
  }
  if (payload["stream"] !== undefined && payload["stream"] !== false) {
    return rejected(400, "stream_not_allowed");
  }
  const temperature = payload["temperature"];
  if (
    temperature !== undefined &&
    (typeof temperature !== "number" || !Number.isFinite(temperature) || temperature !== 0)
  ) {
    return rejected(400, "temperature_not_allowed");
  }
  const tokenFields = ["max_tokens", "max_completion_tokens"].filter(
    (key) => payload[key] !== undefined,
  );
  if (tokenFields.length > 1) {
    return rejected(400, "max_tokens_ambiguous");
  }
  if (tokenFields.length === 1) {
    const tokens = payload[tokenFields[0] as string];
    if (
      !positiveInteger(tokens) ||
      tokens > limits.maxTokensPerRequest
    ) {
      return rejected(400, "max_tokens_invalid");
    }
  }
  if (payload["n"] !== undefined && payload["n"] !== 1) {
    return rejected(400, "choice_count_invalid");
  }
  const normalized: Record<string, unknown> = {
    model: ALLOWED_MODEL,
    messages,
    stream: false,
    temperature: 0,
    n: 1,
  };
  if (tools !== undefined) normalized["tools"] = tools;
  if (toolChoice !== undefined) normalized["tool_choice"] = toolChoice;
  if (tools !== undefined || payload["parallel_tool_calls"] !== undefined) {
    normalized["parallel_tool_calls"] = false;
  }
  if (tokenFields.length === 0) {
    normalized["max_tokens"] = limits.maxTokensPerRequest;
  } else {
    const field = tokenFields[0];
    if (field !== undefined) normalized[field] = payload[field];
  }
  return accepted(Object.freeze(normalized));
};

export const decodeUpstreamUsage = (
  value: unknown,
): GatewayDomainResult<TokenUsage> => {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return rejected(502, "upstream_usage_invalid");
  }
  const record = value as Record<string, unknown>;
  const promptTokens = record["prompt_tokens"];
  const completionTokens = record["completion_tokens"];
  const totalTokens = record["total_tokens"];
  if (
    !nonnegativeInteger(promptTokens) ||
    !nonnegativeInteger(completionTokens) ||
    !nonnegativeInteger(totalTokens) ||
    promptTokens + completionTokens !== totalTokens
  ) {
    return rejected(502, "upstream_usage_invalid");
  }
  return accepted(Object.freeze({ promptTokens, completionTokens, totalTokens }));
};

export const serializeGatewayMetrics = (
  state: GatewayMetrics,
): Readonly<Record<string, unknown>> => ({
  schema_version: state.schemaVersion,
  requests_seen: state.requestsSeen,
  requests_admitted: state.requestsAdmitted,
  requests_completed: state.requestsCompleted,
  requests_rejected: state.requestsRejected,
  requests_in_flight: state.requestsInFlight,
  peak_concurrency: state.peakConcurrency,
  upstream_requests: state.upstreamRequests,
  upstream_failures: state.upstreamFailures,
  request_bytes: state.requestBytes,
  response_bytes: state.responseBytes,
  status_counts: state.statusCounts,
  usage: {
    prompt_tokens: state.usage.promptTokens,
    completion_tokens: state.usage.completionTokens,
    total_tokens: state.usage.totalTokens,
  },
  completion_tokens_reserved: state.completionTokensReserved,
  completion_tokens_unknown: state.completionTokensUnknown,
  completion_budget_overshoot: state.completionBudgetOvershoot,
  last_error_code: state.lastErrorCode,
  limits: {
    max_body_bytes: state.limits.maxBodyBytes,
    max_response_bytes: state.limits.maxResponseBytes,
    max_tokens_per_request: state.limits.maxTokensPerRequest,
    max_requests: state.limits.maxRequests,
    request_budget_basis: state.limits.requestBudgetBasis,
    max_completion_tokens: state.limits.maxCompletionTokens,
    max_concurrency: state.limits.maxConcurrency,
  },
});

export const gatewayMetricsError = (value: unknown): string | undefined => {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return "metrics are not an object";
  }
  const record = value as Record<string, unknown>;
  if (record["schema_version"] !== GATEWAY_METRICS_SCHEMA) {
    return "schema version differs";
  }
  const limits = record["limits"];
  if (typeof limits !== "object" || limits === null || Array.isArray(limits)) {
    return "limits differ";
  }
  const limitRecord = limits as Record<string, unknown>;
  const expectedLimits = serializeGatewayMetrics(
    initialGatewayMetrics(),
  )["limits"] as Readonly<Record<string, unknown>>;
  if (
    Object.entries(expectedLimits).some(
      ([key, expected]) => limitRecord[key] !== expected,
    )
  ) {
    return "limits differ";
  }
  const counters = [
    "requests_seen",
    "requests_admitted",
    "requests_completed",
    "requests_rejected",
    "requests_in_flight",
    "peak_concurrency",
    "upstream_requests",
    "upstream_failures",
    "request_bytes",
    "response_bytes",
    "completion_tokens_reserved",
    "completion_tokens_unknown",
    "completion_budget_overshoot",
  ] as const;
  for (const name of counters) {
    if (!nonnegativeInteger(record[name])) return `counter ${name} is invalid`;
  }
  const requestsSeen = record["requests_seen"] as number;
  const requestsAdmitted = record["requests_admitted"] as number;
  const requestsCompleted = record["requests_completed"] as number;
  const requestsRejected = record["requests_rejected"] as number;
  const upstreamRequests = record["upstream_requests"] as number;
  const upstreamFailures = record["upstream_failures"] as number;
  if (
    requestsSeen < 1 ||
    requestsSeen > DEFAULT_GATEWAY_LIMITS.maxRequests ||
    requestsAdmitted < 1 ||
    requestsAdmitted > requestsSeen ||
    requestsCompleted !== requestsAdmitted ||
    requestsRejected > requestsSeen ||
    record["requests_in_flight"] !== 0 ||
    record["peak_concurrency"] !== 1 ||
    upstreamRequests < 1 ||
    upstreamRequests > requestsCompleted ||
    upstreamFailures > upstreamRequests ||
    record["completion_tokens_reserved"] !== 0 ||
    record["completion_tokens_unknown"] !== 0 ||
    record["completion_budget_overshoot"] !== 0
  ) {
    return "request lifecycle or budget invariant differs";
  }
  const usage = record["usage"];
  if (typeof usage !== "object" || usage === null || Array.isArray(usage)) {
    return "usage is not an object";
  }
  const usageRecord = usage as Record<string, unknown>;
  for (const name of ["prompt_tokens", "completion_tokens", "total_tokens"] as const) {
    if (!nonnegativeInteger(usageRecord[name])) return `usage ${name} is invalid`;
  }
  if (
    usageRecord["total_tokens"] !==
      (usageRecord["prompt_tokens"] as number) +
        (usageRecord["completion_tokens"] as number) ||
    (usageRecord["total_tokens"] as number) < 1 ||
    (usageRecord["completion_tokens"] as number) >
      DEFAULT_GATEWAY_LIMITS.maxCompletionTokens
  ) {
    return "usage total or token budget differs";
  }
  const statuses = record["status_counts"];
  if (typeof statuses !== "object" || statuses === null || Array.isArray(statuses)) {
    return "status counts are unavailable";
  }
  const entries = Object.entries(statuses);
  if (
    entries.length === 0 ||
    entries.some(
      ([key, count]) => {
        if (!/^\d{3}$/.test(key) || !positiveInteger(count)) return true;
        const status = Number(key);
        return !(
          (status >= 200 && status <= 299) ||
          (status >= 400 && status <= 599)
        );
      },
    )
  ) {
    return "status counts are invalid";
  }
  const statusTotal = entries.reduce(
    (sum, [, count]) => sum + (count as number),
    0,
  );
  const successTotal = entries.reduce((sum, [key, count]) => {
    const status = Number(key);
    return sum + (status >= 200 && status <= 299 ? (count as number) : 0);
  }, 0);
  if (
    statusTotal !== requestsCompleted + (requestsSeen - requestsAdmitted) ||
    successTotal !== requestsSeen - requestsRejected ||
    statusTotal - successTotal !== requestsRejected
  ) {
    return "status counts disagree with request counters";
  }
  return undefined;
};
