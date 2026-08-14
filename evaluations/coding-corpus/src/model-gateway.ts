import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import { isIP } from "node:net";
import { dirname } from "node:path";

import { Data, Effect, FiberSet, Ref, type Scope } from "effect";

import {
  admitGatewayRequest,
  ALLOWED_MODEL,
  decodeUpstreamUsage,
  DEFAULT_GATEWAY_LIMITS,
  finishGatewayRequest,
  type FinishGatewayRequest,
  type GatewayLimits,
  type GatewayMetrics,
  initialGatewayMetrics,
  rejectUnadmittedRequest,
  reserveCompletionTokens,
  serializeGatewayMetrics,
  UPSTREAM_PATH,
  validateGatewayPayload,
} from "./gateway-domain.js";
import { parseJsonRejectingDuplicateKeys } from "./domain.js";
import {
  FileStore,
  type FileStoreService,
  FileFailure,
} from "./ports.js";

const ENCODER = new TextEncoder();
const DNS_LABEL = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$/;

export class GatewayRuntimeFailure extends Data.TaggedError(
  "GatewayRuntimeFailure",
)<{
  readonly operation: "configuration" | "metrics" | "server";
  readonly reason: string;
}> {}

class RequestFailure extends Data.TaggedError("RequestFailure")<{
  readonly status: number;
  readonly code: string;
}> {}

class UpstreamFailure extends Data.TaggedError("UpstreamFailure")<{
  readonly status: number;
  readonly code: string;
}> {}

export interface GatewayConfig {
  readonly listenHost: string;
  readonly listenPort: number;
  readonly upstreamHost: string;
  readonly upstreamPort: number;
  readonly secret: string;
  readonly metricsPath: string;
  readonly limits?: GatewayLimits;
  readonly clientReadTimeoutMs?: number;
  readonly upstreamTimeoutMs?: number;
}

interface ResolvedGatewayConfig extends GatewayConfig {
  readonly limits: GatewayLimits;
  readonly clientReadTimeoutMs: number;
  readonly upstreamTimeoutMs: number;
}

export interface RunningGateway {
  readonly host: string;
  readonly port: number;
}

interface GatewayMetricsController {
  readonly admit: Effect.Effect<
    ReturnType<typeof admitGatewayRequest>,
    FileFailure
  >;
  readonly rejectUnadmitted: (
    status: number,
    code: string,
  ) => Effect.Effect<void, FileFailure>;
  readonly finish: (
    event: FinishGatewayRequest,
  ) => Effect.Effect<GatewayMetrics, FileFailure | GatewayRuntimeFailure>;
  readonly reserveCompletion: (
    requested: number,
  ) => Effect.Effect<ReturnType<typeof reserveCompletionTokens>, FileFailure>;
}

interface ValidatedRequest {
  readonly encoded: Uint8Array;
  readonly requestBytes: number;
  readonly reservedCompletionTokens: number;
}

interface UpstreamResponse {
  readonly body: Uint8Array;
  readonly usage: {
    readonly promptTokens: number;
    readonly completionTokens: number;
    readonly totalTokens: number;
  };
}

export const validateUpstreamHost = (raw: string): string => {
  if (raw.length === 0 || raw.length > 253 || raw.trim() !== raw) {
    throw new GatewayRuntimeFailure({
      operation: "configuration",
      reason: "upstream host must be a bounded plain host",
    });
  }
  const ipVersion = isIP(raw);
  if (ipVersion === 4) return raw;
  if (ipVersion === 6) {
    throw new GatewayRuntimeFailure({
      operation: "configuration",
      reason: "IPv6 upstream hosts are not supported by this gateway profile",
    });
  }
  const labels = raw.endsWith(".") ? raw.slice(0, -1).split(".") : raw.split(".");
  if (labels.length === 0 || labels.some((label) => !DNS_LABEL.test(label))) {
    throw new GatewayRuntimeFailure({
      operation: "configuration",
      reason: "upstream host must be a plain IP address or DNS name",
    });
  }
  return raw;
};

export const validateUpstreamPort = (value: number): number => {
  if (!Number.isInteger(value) || value < 1 || value > 65_535) {
    throw new GatewayRuntimeFailure({
      operation: "configuration",
      reason: "upstream port must be from 1 through 65535",
    });
  }
  return value;
};

const resolveConfig = (value: GatewayConfig): ResolvedGatewayConfig => {
  if (
    !Number.isInteger(value.listenPort) ||
    value.listenPort < 0 ||
    value.listenPort > 65_535
  ) {
    throw new GatewayRuntimeFailure({
      operation: "configuration",
      reason: "listen port must be from 0 through 65535",
    });
  }
  if (
    value.secret.length === 0 ||
    value.secret.length > 4_096 ||
    /[\r\n]/.test(value.secret)
  ) {
    throw new GatewayRuntimeFailure({
      operation: "configuration",
      reason: "gateway secret is malformed",
    });
  }
  const limits = value.limits ?? DEFAULT_GATEWAY_LIMITS;
  const positiveIntegerAtMost = (
    candidate: number,
    maximum: number,
  ): boolean =>
    Number.isInteger(candidate) && candidate >= 1 && candidate <= maximum;
  if (
    !positiveIntegerAtMost(limits.maxBodyBytes, 16 * 1024 * 1024) ||
    !positiveIntegerAtMost(limits.maxResponseBytes, 32 * 1024 * 1024) ||
    !positiveIntegerAtMost(limits.maxTokensPerRequest, 32_768) ||
    !positiveIntegerAtMost(limits.maxRequests, 1_000) ||
    !positiveIntegerAtMost(limits.maxCompletionTokens, 10_000_000) ||
    limits.maxConcurrency !== 1 ||
    limits.requestBudgetBasis !==
      "react_turn_limit_ceiling_not_call_equivalence"
  ) {
    throw new GatewayRuntimeFailure({
      operation: "configuration",
      reason: "gateway limits must be positive integers with maxConcurrency exactly 1",
    });
  }
  const clientReadTimeoutMs = value.clientReadTimeoutMs ?? 10_000;
  const upstreamTimeoutMs = value.upstreamTimeoutMs ?? 185_000;
  if (
    !positiveIntegerAtMost(clientReadTimeoutMs, 60_000) ||
    !positiveIntegerAtMost(upstreamTimeoutMs, 600_000)
  ) {
    throw new GatewayRuntimeFailure({
      operation: "configuration",
      reason: "gateway timeouts must be bounded positive integer milliseconds",
    });
  }
  return Object.freeze({
    ...value,
    upstreamHost: validateUpstreamHost(value.upstreamHost),
    upstreamPort: validateUpstreamPort(value.upstreamPort),
    limits,
    clientReadTimeoutMs,
    upstreamTimeoutMs,
  });
};

const persistMetrics = (
  files: FileStoreService,
  path: string,
  state: GatewayMetrics,
): Effect.Effect<void, FileFailure> =>
  Effect.gen(function* () {
    yield* files.makeDirectory(dirname(path), { recursive: true });
    yield* files.writeBytesAtomic(
      path,
      ENCODER.encode(`${JSON.stringify(serializeGatewayMetrics(state))}\n`),
    );
  });

const makeMetricsController = (
  path: string,
  limits: GatewayLimits,
): Effect.Effect<GatewayMetricsController, FileFailure, FileStoreService> =>
  Effect.gen(function* () {
    const files = yield* FileStore;
    const state = yield* Ref.make(initialGatewayMetrics(limits));
    const mutex = yield* Effect.makeSemaphore(1);
    yield* persistMetrics(files, path, yield* Ref.get(state));
    const update = <A>(
      transition: (current: GatewayMetrics) => {
        readonly value: A;
        readonly next: GatewayMetrics;
      },
    ): Effect.Effect<A, FileFailure> =>
      mutex.withPermits(1)(
        Effect.gen(function* () {
          const current = yield* Ref.get(state);
          const result = transition(current);
          yield* persistMetrics(files, path, result.next);
          yield* Ref.set(state, result.next);
          return result.value;
        }),
      );
    return {
      admit: update((current) => {
        const admission = admitGatewayRequest(current);
        return { value: admission, next: admission.metrics };
      }),
      rejectUnadmitted: (status, code) =>
        update((current) => ({
          value: undefined,
          next: rejectUnadmittedRequest(current, status, code),
        })),
      finish: (event) =>
        mutex.withPermits(1)(
          Effect.gen(function* () {
            const current = yield* Ref.get(state);
            const result = finishGatewayRequest(current, event);
            if (!result.ok) {
              return yield* Effect.fail(
                new GatewayRuntimeFailure({
                  operation: "metrics",
                  reason: result.code,
                }),
              );
            }
            yield* persistMetrics(files, path, result.value);
            yield* Ref.set(state, result.value);
            return result.value;
          }),
        ),
      reserveCompletion: (requested) =>
        update((current) => {
          const reservation = reserveCompletionTokens(current, requested);
          return { value: reservation, next: reservation.metrics };
        }),
    };
  });

const problemBody = (code: string): Uint8Array =>
  ENCODER.encode(
    JSON.stringify({ error: { type: "gateway_rejection", code } }),
  );

const sendBytes = (
  response: ServerResponse,
  status: number,
  body: Uint8Array,
): Effect.Effect<void> =>
  Effect.async((resume, signal) => {
    if (response.headersSent || response.destroyed) {
      resume(Effect.void);
      return Effect.void;
    }
    let completed = false;
    const finish = (): void => {
      if (completed) return;
      completed = true;
      cleanup();
      resume(Effect.void);
    };
    const cleanup = (): void => {
      response.off("close", finish);
      response.off("error", finish);
      signal.removeEventListener("abort", onAbort);
    };
    const onAbort = (): void => {
      response.destroy();
      finish();
    };
    response.once("close", finish);
    response.once("error", finish);
    signal.addEventListener("abort", onAbort, { once: true });
    response.writeHead(status, {
      "Cache-Control": "no-store",
      Connection: "close",
      "Content-Length": String(body.byteLength),
      "Content-Type": "application/json",
    });
    response.end(body, finish);
    return Effect.sync(() => {
      cleanup();
      if (!response.destroyed) response.destroy();
    });
  });

const readBody = (
  request: IncomingMessage,
  expectedLength: number,
  timeoutMs: number,
): Effect.Effect<Uint8Array, RequestFailure> =>
  Effect.tryPromise({
    try: (signal) =>
      new Promise<Uint8Array>((resolve, reject) => {
        const chunks: Buffer[] = [];
        let length = 0;
        let settled = false;
        const cleanup = (): void => {
          request.off("data", onData);
          request.off("end", onEnd);
          request.off("error", onError);
          request.off("aborted", onAborted);
          signal.removeEventListener("abort", onAbort);
        };
        const fail = (failure: RequestFailure): void => {
          if (settled) return;
          settled = true;
          cleanup();
          request.pause();
          reject(failure);
        };
        const onData = (chunk: Buffer): void => {
          length += chunk.byteLength;
          if (length > expectedLength) {
            fail(new RequestFailure({ status: 400, code: "body_length_mismatch" }));
            return;
          }
          chunks.push(chunk);
        };
        const onEnd = (): void => {
          if (settled) return;
          if (length !== expectedLength) {
            fail(new RequestFailure({ status: 400, code: "body_incomplete" }));
            return;
          }
          settled = true;
          cleanup();
          resolve(Buffer.concat(chunks));
        };
        const onError = (): void =>
          fail(new RequestFailure({ status: 400, code: "client_body_unavailable" }));
        const onAborted = (): void =>
          fail(new RequestFailure({ status: 400, code: "client_body_unavailable" }));
        const onAbort = (): void => {
          fail(new RequestFailure({ status: 408, code: "client_body_timeout" }));
        };
        request.on("data", onData);
        request.once("end", onEnd);
        request.once("error", onError);
        request.once("aborted", onAborted);
        signal.addEventListener("abort", onAbort, { once: true });
      }),
    catch: (error) =>
      error instanceof RequestFailure
        ? error
        : new RequestFailure({ status: 400, code: "client_body_unavailable" }),
  }).pipe(
    Effect.timeoutFail({
      duration: timeoutMs,
      onTimeout: () =>
        new RequestFailure({ status: 408, code: "client_body_timeout" }),
    }),
  );

const readValidatedRequest = (
  request: IncomingMessage,
  config: ResolvedGatewayConfig,
): Effect.Effect<ValidatedRequest, RequestFailure> =>
  Effect.gen(function* () {
    if (request.url !== UPSTREAM_PATH) {
      return yield* Effect.fail(
        new RequestFailure({ status: 404, code: "path_not_allowed" }),
      );
    }
    const contentType = request.headers["content-type"]
      ?.split(";", 1)[0]
      ?.trim()
      .toLowerCase();
    if (contentType !== "application/json") {
      return yield* Effect.fail(
        new RequestFailure({ status: 415, code: "content_type_not_allowed" }),
      );
    }
    const rawLength = request.headers["content-length"];
    if (rawLength === undefined) {
      return yield* Effect.fail(
        new RequestFailure({ status: 411, code: "content_length_required" }),
      );
    }
    if (Array.isArray(rawLength) || !/^\d+$/.test(rawLength)) {
      return yield* Effect.fail(
        new RequestFailure({ status: 400, code: "content_length_invalid" }),
      );
    }
    const length = Number(rawLength);
    if (length < 1) {
      return yield* Effect.fail(
        new RequestFailure({ status: 400, code: "body_empty" }),
      );
    }
    if (length > config.limits.maxBodyBytes) {
      return yield* Effect.fail(
        new RequestFailure({ status: 413, code: "body_too_large" }),
      );
    }
    const raw = yield* readBody(request, length, config.clientReadTimeoutMs);
    let text: string;
    try {
      text = new TextDecoder("utf-8", { fatal: true }).decode(raw);
    } catch {
      return yield* Effect.fail(
        new RequestFailure({ status: 400, code: "body_not_json" }),
      );
    }
    const parsed = parseJsonRejectingDuplicateKeys(text);
    if (!parsed.ok) {
      return yield* Effect.fail(
        new RequestFailure({ status: 400, code: "body_not_json" }),
      );
    }
    const decoded = parsed.value;
    const validated = validateGatewayPayload(decoded, config.limits);
    if (!validated.ok) {
      return yield* Effect.fail(
        new RequestFailure({ status: validated.status, code: validated.code }),
      );
    }
    const tokenField =
      validated.value["max_tokens"] ??
      validated.value["max_completion_tokens"];
    if (typeof tokenField !== "number" || !Number.isInteger(tokenField)) {
      return yield* Effect.fail(
        new RequestFailure({ status: 400, code: "max_tokens_invalid" }),
      );
    }
    return {
      encoded: ENCODER.encode(JSON.stringify(validated.value)),
      requestBytes: length,
      reservedCompletionTokens: tokenField,
    };
  });

const readBoundedResponse = async (
  response: Response,
  maximum: number,
): Promise<Uint8Array> => {
  if (response.body === null) return new Uint8Array();
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let length = 0;
  for (;;) {
    const next = await reader.read();
    if (next.done) break;
    length += next.value.byteLength;
    if (length > maximum) {
      await reader.cancel();
      throw new UpstreamFailure({
        status: 502,
        code: "upstream_response_too_large",
      });
    }
    chunks.push(next.value);
  }
  const result = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    result.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return result;
};

const includesBytes = (haystack: Uint8Array, needle: Uint8Array): boolean =>
  Buffer.from(haystack).includes(Buffer.from(needle));

const containsSecretString = (value: unknown, secret: string): boolean => {
  if (typeof value === "string") return value.includes(secret);
  if (Array.isArray(value)) {
    return value.some((item) => containsSecretString(item, secret));
  }
  if (typeof value === "object" && value !== null) {
    return Object.entries(value).some(
      ([key, item]) => key.includes(secret) || containsSecretString(item, secret),
    );
  }
  return false;
};

const forwardUpstream = (
  request: ValidatedRequest,
  config: ResolvedGatewayConfig,
): Effect.Effect<UpstreamResponse, UpstreamFailure> =>
  Effect.tryPromise({
    try: async (signal) => {
      const response = await fetch(
        `http://${config.upstreamHost}:${config.upstreamPort}${UPSTREAM_PATH}`,
        {
          method: "POST",
          body: request.encoded,
          headers: {
            Accept: "application/json",
            Authorization: `Bearer ${config.secret}`,
            "Content-Type": "application/json",
            "User-Agent": "flrh-model-gateway/1",
          },
          redirect: "error",
          signal,
        },
      );
      const body = await readBoundedResponse(
        response,
        config.limits.maxResponseBytes,
      );
      if (!response.ok) {
        throw new UpstreamFailure({ status: 502, code: "upstream_rejected" });
      }
      if (includesBytes(body, ENCODER.encode(config.secret))) {
        throw new UpstreamFailure({
          status: 502,
          code: "upstream_secret_reflection",
        });
      }
      let decoded: unknown;
      try {
        decoded = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(body));
      } catch {
        throw new UpstreamFailure({
          status: 502,
          code: "upstream_response_not_json",
        });
      }
      if (containsSecretString(decoded, config.secret)) {
        throw new UpstreamFailure({
          status: 502,
          code: "upstream_secret_reflection",
        });
      }
      const usage =
        typeof decoded === "object" && decoded !== null && !Array.isArray(decoded)
          ? decodeUpstreamUsage((decoded as Record<string, unknown>)["usage"])
          : decodeUpstreamUsage(undefined);
      if (!usage.ok) {
        throw new UpstreamFailure({ status: usage.status, code: usage.code });
      }
      return { body, usage: usage.value };
    },
    catch: (error) =>
      error instanceof UpstreamFailure
        ? error
        : new UpstreamFailure({ status: 502, code: "upstream_unavailable" }),
  }).pipe(
    Effect.timeoutFail({
      duration: config.upstreamTimeoutMs,
      onTimeout: () =>
        new UpstreamFailure({ status: 504, code: "upstream_timeout" }),
    }),
  );

const finishAndSend = (
  response: ServerResponse,
  controller: GatewayMetricsController,
  event: FinishGatewayRequest,
  body: Uint8Array,
): Effect.Effect<void, FileFailure | GatewayRuntimeFailure> =>
  controller.finish(event).pipe(
    Effect.zipRight(sendBytes(response, event.status, body)),
  );

const handleRequest = (
  request: IncomingMessage,
  response: ServerResponse,
  controller: GatewayMetricsController,
  config: ResolvedGatewayConfig,
): Effect.Effect<void, FileFailure | GatewayRuntimeFailure> =>
  Effect.gen(function* () {
    if (request.method !== "POST") {
      yield* controller.rejectUnadmitted(405, "method_not_allowed");
      yield* sendBytes(response, 405, problemBody("method_not_allowed"));
      return;
    }
    const admission = yield* controller.admit;
    if (!admission.admitted) {
      yield* sendBytes(
        response,
        429,
        problemBody(admission.reason ?? "request_rejected"),
      );
      return;
    }
    const validated = yield* readValidatedRequest(request, config).pipe(
      Effect.either,
    );
    if (validated._tag === "Left") {
      const failure = validated.left;
      const body = problemBody(failure.code);
      yield* finishAndSend(
        response,
        controller,
        {
          status: failure.status,
          rejected: true,
          upstreamStarted: false,
          upstreamFailed: false,
          requestBytes: 0,
          responseBytes: body.byteLength,
          usage: {},
          reservedCompletionTokens: 0,
          completionOutcomeUnknown: false,
          errorCode: failure.code,
        },
        body,
      );
      return;
    }
    const reservation = yield* controller.reserveCompletion(
      validated.right.reservedCompletionTokens,
    );
    if (!reservation.reserved) {
      const code = reservation.reason ?? "completion_token_budget_exhausted";
      const body = problemBody(code);
      yield* finishAndSend(
        response,
        controller,
        {
          status: 429,
          rejected: true,
          upstreamStarted: false,
          upstreamFailed: false,
          requestBytes: validated.right.requestBytes,
          responseBytes: body.byteLength,
          usage: {},
          reservedCompletionTokens: 0,
          completionOutcomeUnknown: false,
          errorCode: code,
        },
        body,
      );
      return;
    }
    const upstream = yield* forwardUpstream(validated.right, config).pipe(
      Effect.either,
    );
    if (upstream._tag === "Left") {
      const failure = upstream.left;
      const body = problemBody(failure.code);
      yield* finishAndSend(
        response,
        controller,
        {
          status: failure.status,
          rejected: false,
          upstreamStarted: true,
          upstreamFailed: true,
          requestBytes: validated.right.requestBytes,
          responseBytes: body.byteLength,
          usage: {},
          reservedCompletionTokens: validated.right.reservedCompletionTokens,
          completionOutcomeUnknown: true,
          errorCode: failure.code,
        },
        body,
      );
      return;
    }
    yield* finishAndSend(
      response,
      controller,
      {
        status: 200,
        rejected: false,
        upstreamStarted: true,
        upstreamFailed: false,
        requestBytes: validated.right.requestBytes,
        responseBytes: upstream.right.body.byteLength,
        usage: upstream.right.usage,
        reservedCompletionTokens: validated.right.reservedCompletionTokens,
        completionOutcomeUnknown: false,
        errorCode: null,
      },
      upstream.right.body,
    );
  });

const listen = (
  server: Server,
  host: string,
  port: number,
): Effect.Effect<RunningGateway, GatewayRuntimeFailure> =>
  Effect.async((resume) => {
    const onError = (error: Error): void => {
      resume(
        Effect.fail(
          new GatewayRuntimeFailure({
            operation: "server",
            reason: error.message,
          }),
        ),
      );
    };
    server.once("error", onError);
    server.listen({ port, host, backlog: 8 }, () => {
      server.off("error", onError);
      const address = server.address();
      if (address === null || typeof address === "string") {
        resume(
          Effect.fail(
            new GatewayRuntimeFailure({
              operation: "server",
              reason: "gateway listener address is unavailable",
            }),
          ),
        );
        return;
      }
      resume(Effect.succeed({ host, port: address.port }));
    });
    return Effect.sync(() => server.close());
  });

const closeServer = (server: Server): Effect.Effect<void> =>
  Effect.async((resume) => {
    server.close(() => resume(Effect.void));
    server.closeAllConnections();
    return Effect.void;
  });

export const startGateway = (
  rawConfig: GatewayConfig,
): Effect.Effect<
  RunningGateway,
  FileFailure | GatewayRuntimeFailure,
  FileStoreService | Scope.Scope
> =>
  Effect.gen(function* () {
    const config = yield* Effect.try({
      try: () => resolveConfig(rawConfig),
      catch: (error) =>
        error instanceof GatewayRuntimeFailure
          ? error
          : new GatewayRuntimeFailure({
              operation: "configuration",
              reason: "gateway configuration is invalid",
            }),
    });
    const controller = yield* makeMetricsController(
      config.metricsPath,
      config.limits,
    );
    const requestFibers = yield* FiberSet.make<void, never>();
    const runRequest = yield* FiberSet.runtime(requestFibers)<never>();
    let activeRequests = 0;
    const server = createServer((request, response) => {
      if (activeRequests >= 8) {
        const body = problemBody("gateway_busy");
        response.writeHead(503, {
          "Cache-Control": "no-store",
          Connection: "close",
          "Content-Length": String(body.byteLength),
          "Content-Type": "application/json",
        });
        response.end(body);
        return;
      }
      activeRequests += 1;
      runRequest(
        handleRequest(request, response, controller, config).pipe(
          Effect.catchAll(() =>
            Effect.sync(() => server.close()).pipe(
              Effect.zipRight(
                sendBytes(response, 500, problemBody("internal_gateway_failure")),
              ),
            ),
          ),
          Effect.ensuring(
            Effect.sync(() => {
              activeRequests -= 1;
            }),
          ),
        ),
      );
    });
    server.headersTimeout = config.clientReadTimeoutMs;
    server.requestTimeout = config.clientReadTimeoutMs + 1_000;
    server.timeout = config.upstreamTimeoutMs + 5_000;
    server.keepAliveTimeout = 1_000;
    server.maxRequestsPerSocket = 1;
    server.maxConnections = 8;
    return yield* Effect.acquireRelease(
      listen(server, config.listenHost, config.listenPort),
      () => closeServer(server),
    );
  });

export const expectedGatewayModel = ALLOWED_MODEL;
