import assert from "node:assert/strict";
import test from "node:test";

import {
  admitGatewayRequest,
  ALLOWED_MODEL,
  decodeUpstreamUsage,
  DEFAULT_GATEWAY_LIMITS,
  finishGatewayRequest,
  gatewayMetricsError,
  initialGatewayMetrics,
  rejectUnadmittedRequest,
  reserveCompletionTokens,
  serializeGatewayMetrics,
  validateGatewayPayload,
  type GatewayLimits,
} from "../src/gateway-domain.js";

const payload = (updates: Readonly<Record<string, unknown>> = {}) => ({
  model: ALLOWED_MODEL,
  messages: [{ role: "user", content: "fix private bug" }],
  max_tokens: 128,
  stream: false,
  ...updates,
});

const limits = (updates: Partial<GatewayLimits> = {}): GatewayLimits => ({
  ...DEFAULT_GATEWAY_LIMITS,
  ...updates,
});

test("gateway payload fixes routing, temperature, streaming, and choice count", () => {
  const result = validateGatewayPayload(
    payload({
      tools: [{ type: "function", function: { name: "read_file" } }],
      tool_choice: "auto",
    }),
  );
  assert.equal(result.ok, true);
  if (!result.ok) return;
  assert.equal(result.value["model"], ALLOWED_MODEL);
  assert.equal(result.value["stream"], false);
  assert.equal(result.value["temperature"], 0);
  assert.equal(result.value["n"], 1);
  assert.equal(result.value["parallel_tool_calls"], false);
});

test("gateway payload rejects the untrusted routing and budget surface", () => {
  const cases: ReadonlyArray<readonly [Readonly<Record<string, unknown>>, string]> = [
    [payload({ model: "other" }), "model_not_allowed"],
    [payload({ stream: true }), "stream_not_allowed"],
    [payload({ temperature: 0.1 }), "temperature_not_allowed"],
    [payload({ max_tokens: 4_097 }), "max_tokens_invalid"],
    [payload({ max_completion_tokens: 1 }), "max_tokens_ambiguous"],
    [payload({ n: 2 }), "choice_count_invalid"],
    [payload({ base_url: "http://attacker.invalid" }), "routing_field_not_allowed"],
    [payload({ top_p: 0.1 }), "payload_field_not_allowed"],
    [payload({ parallel_tool_calls: true }), "parallel_tool_calls_not_allowed"],
    [
      payload({
        messages: [
          {
            role: "user",
            content: [{ type: "image_url", image_url: { url: "http://internal" } }],
          },
        ],
      }),
      "messages_invalid",
    ],
  ];
  for (const [value, code] of cases) {
    const result = validateGatewayPayload(value);
    assert.equal(result.ok, false);
    if (!result.ok) assert.equal(result.code, code);
  }
});

test("request, concurrency, and cumulative token budgets are deterministic", () => {
  const oneRequest = limits({ maxRequests: 1 });
  let state = initialGatewayMetrics(oneRequest);
  const first = admitGatewayRequest(state);
  assert.equal(first.admitted, true);
  state = first.metrics;
  const concurrent = admitGatewayRequest(state);
  assert.equal(concurrent.admitted, false);
  assert.equal(concurrent.reason, "request_budget_exhausted");

  const reservation = reserveCompletionTokens(state, 7);
  assert.equal(reservation.reserved, true);
  state = reservation.metrics;
  const finished = finishGatewayRequest(state, {
    status: 200,
    rejected: false,
    upstreamStarted: true,
    upstreamFailed: false,
    requestBytes: 10,
    responseBytes: 20,
    usage: { promptTokens: 11, completionTokens: 7, totalTokens: 18 },
    reservedCompletionTokens: 7,
    completionOutcomeUnknown: false,
    errorCode: null,
  });
  assert.equal(finished.ok, true);
  if (!finished.ok) return;
  assert.equal(finished.value.requestsInFlight, 0);
  assert.equal(finished.value.usage.totalTokens, 18);

  const tokenLimited = initialGatewayMetrics(
    limits({ maxCompletionTokens: 20, maxTokensPerRequest: 15 }),
  );
  const admitted = admitGatewayRequest(tokenLimited);
  assert.equal(admitted.admitted, true);
  const firstReservation = reserveCompletionTokens(admitted.metrics, 15);
  assert.equal(firstReservation.reserved, true);
  const firstFinished = finishGatewayRequest(firstReservation.metrics, {
    status: 200,
    rejected: false,
    upstreamStarted: true,
    upstreamFailed: false,
    requestBytes: 10,
    responseBytes: 10,
    usage: { promptTokens: 100, completionTokens: 10, totalTokens: 110 },
    reservedCompletionTokens: 15,
    completionOutcomeUnknown: false,
    errorCode: null,
  });
  assert.equal(firstFinished.ok, true);
  if (!firstFinished.ok) return;
  const crossing = reserveCompletionTokens(firstFinished.value, 11);
  assert.equal(crossing.reserved, false);
  assert.equal(crossing.reason, "completion_token_budget_exhausted");
});

test("finishing without an admitted request fails closed", () => {
  const result = finishGatewayRequest(initialGatewayMetrics(), {
    status: 200,
    rejected: false,
    upstreamStarted: true,
    upstreamFailed: false,
    requestBytes: 1,
    responseBytes: 1,
    usage: { promptTokens: 1, completionTokens: 1, totalTokens: 2 },
    reservedCompletionTokens: 0,
    completionOutcomeUnknown: false,
    errorCode: null,
  });
  assert.equal(result.ok, false);
  if (!result.ok) assert.equal(result.code, "metrics_lost_admitted_request");
});

test("upstream usage requires a truthful additive total", () => {
  assert.deepEqual(
    decodeUpstreamUsage({
      prompt_tokens: 11,
      completion_tokens: 7,
      total_tokens: 18,
    }),
    {
      ok: true,
      value: { promptTokens: 11, completionTokens: 7, totalTokens: 18 },
    },
  );
  const invalid = decodeUpstreamUsage({
    prompt_tokens: 11,
    completion_tokens: 7,
    total_tokens: 99,
  });
  assert.equal(invalid.ok, false);
});

test("serialized metrics contain no request, prompt, or credential data", () => {
  let state = initialGatewayMetrics();
  state = rejectUnadmittedRequest(state, 405, "method_not_allowed");
  const serialized = JSON.stringify(serializeGatewayMetrics(state));
  assert.doesNotMatch(serialized, /fix private bug|candidate-value|secret/u);
  assert.equal(JSON.parse(serialized).requests_rejected, 1);
});

test("comparison metric validator accepts only completed bounded evidence", () => {
  let state = initialGatewayMetrics();
  const admission = admitGatewayRequest(state);
  assert.equal(admission.admitted, true);
  const reservation = reserveCompletionTokens(admission.metrics, 7);
  assert.equal(reservation.reserved, true);
  state = reservation.metrics;
  const finished = finishGatewayRequest(state, {
    status: 200,
    rejected: false,
    upstreamStarted: true,
    upstreamFailed: false,
    requestBytes: 100,
    responseBytes: 200,
    usage: { promptTokens: 11, completionTokens: 7, totalTokens: 18 },
    reservedCompletionTokens: 7,
    completionOutcomeUnknown: false,
    errorCode: null,
  });
  assert.equal(finished.ok, true);
  if (!finished.ok) return;
  const serialized = serializeGatewayMetrics(finished.value);
  assert.equal(gatewayMetricsError(serialized), undefined);
  assert.equal(
    gatewayMetricsError({ ...serialized, completion_budget_overshoot: 1 }),
    "request lifecycle or budget invariant differs",
  );
  assert.equal(
    gatewayMetricsError({
      ...serialized,
      requests_rejected: 999,
      upstream_failures: 999,
      peak_concurrency: 0,
      status_counts: { "999": 1 },
    }),
    "request lifecycle or budget invariant differs",
  );
});
