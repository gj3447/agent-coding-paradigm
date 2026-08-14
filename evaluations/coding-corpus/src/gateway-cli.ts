import { createConnection } from "node:net";

import { Effect } from "effect";

import {
  GatewayRuntimeFailure,
  startGateway,
  type GatewayConfig,
} from "./model-gateway.js";
import { gatewayMetricsError } from "./gateway-domain.js";
import { parseJsonRejectingDuplicateKeys } from "./domain.js";
import { NodeFileStoreLive } from "./node-runtime.js";
import { FileFailure, FileStore } from "./ports.js";

const decimalPort = (raw: string, name: string): number => {
  if (!/^\d+$/.test(raw)) {
    throw new GatewayRuntimeFailure({
      operation: "configuration",
      reason: `${name} must be a decimal port`,
    });
  }
  const value = Number(raw);
  if (!Number.isInteger(value) || value < 1 || value > 65_535) {
    throw new GatewayRuntimeFailure({
      operation: "configuration",
      reason: `${name} must be from 1 through 65535`,
    });
  }
  return value;
};

const requiredEnvironment = (
  environment: Readonly<NodeJS.ProcessEnv>,
  name: string,
): string => {
  const value = environment[name];
  if (value === undefined || value.length === 0) {
    throw new GatewayRuntimeFailure({
      operation: "configuration",
      reason: `${name} is required`,
    });
  }
  return value;
};

const awaitShutdown = Effect.async<void>((resume) => {
  const stop = (): void => resume(Effect.void);
  process.once("SIGINT", stop);
  process.once("SIGTERM", stop);
  return Effect.sync(() => {
    process.off("SIGINT", stop);
    process.off("SIGTERM", stop);
  });
});

const serve = (
  environment: Readonly<NodeJS.ProcessEnv>,
): Effect.Effect<void, GatewayRuntimeFailure | FileFailure, never> =>
  Effect.scoped(
    Effect.gen(function* () {
      const files = yield* FileStore;
      const secretPath =
        environment["DGX_API_KEY_FILE"] ?? "/run/secrets/dgx_api_key";
      const secret = (yield* files.readText(secretPath)).trim();
      const config = yield* Effect.try({
        try: (): GatewayConfig => ({
          listenHost: environment["MODEL_GATEWAY_LISTEN_HOST"] ?? "0.0.0.0",
          listenPort: decimalPort(
            environment["MODEL_GATEWAY_LISTEN_PORT"] ?? "8080",
            "MODEL_GATEWAY_LISTEN_PORT",
          ),
          upstreamHost: requiredEnvironment(
            environment,
            "MODEL_GATEWAY_UPSTREAM_HOST",
          ),
          upstreamPort: decimalPort(
            requiredEnvironment(environment, "MODEL_GATEWAY_UPSTREAM_PORT"),
            "MODEL_GATEWAY_UPSTREAM_PORT",
          ),
          secret,
          metricsPath:
            environment["MODEL_GATEWAY_METRICS_FILE"] ??
            "/tmp/gateway/metrics.json",
        }),
        catch: (error) =>
          error instanceof GatewayRuntimeFailure
            ? error
            : new GatewayRuntimeFailure({
                operation: "configuration",
                reason: "gateway environment is invalid",
              }),
      });
      yield* startGateway(config);
      yield* awaitShutdown;
    }).pipe(Effect.provide(NodeFileStoreLive)),
  );

const healthcheck = (
  environment: Readonly<NodeJS.ProcessEnv>,
): Effect.Effect<void, GatewayRuntimeFailure> =>
  Effect.async((resume) => {
    let port: number;
    try {
      port = decimalPort(
        environment["MODEL_GATEWAY_LISTEN_PORT"] ?? "8080",
        "MODEL_GATEWAY_LISTEN_PORT",
      );
    } catch (error) {
      resume(
        Effect.fail(
          error instanceof GatewayRuntimeFailure
            ? error
            : new GatewayRuntimeFailure({
                operation: "configuration",
                reason: "healthcheck port is invalid",
              }),
        ),
      );
      return Effect.void;
    }
    const socket = createConnection({ host: "127.0.0.1", port });
    const timer = setTimeout(() => {
      socket.destroy();
      resume(
        Effect.fail(
          new GatewayRuntimeFailure({
            operation: "server",
            reason: "gateway healthcheck timed out",
          }),
        ),
      );
    }, 1_000);
    socket.once("connect", () => {
      clearTimeout(timer);
      socket.destroy();
      resume(Effect.void);
    });
    socket.once("error", () => {
      clearTimeout(timer);
      resume(
        Effect.fail(
          new GatewayRuntimeFailure({
            operation: "server",
            reason: "gateway healthcheck failed",
          }),
        ),
      );
    });
    return Effect.sync(() => {
      clearTimeout(timer);
      socket.destroy();
    });
  });

const validateMetrics = (
  environment: Readonly<NodeJS.ProcessEnv>,
): Effect.Effect<void, FileFailure, never> =>
  Effect.gen(function* () {
    const files = yield* FileStore;
    const path =
      environment["MODEL_GATEWAY_METRICS_FILE"] ??
      "/tmp/gateway/metrics.json";
    const source = yield* files.readText(path);
    const decoded = parseJsonRejectingDuplicateKeys(source.trim());
    const error = decoded.ok
      ? gatewayMetricsError(decoded.value)
      : decoded.error.reason;
    process.stdout.write(
      `${JSON.stringify({
        schema_version: "model-gateway-validation/v1",
        valid: error === undefined,
        error: error ?? null,
      })}\n`,
    );
  }).pipe(Effect.provide(NodeFileStoreLive));

const command = process.argv[2];
const program =
  command === "serve"
    ? serve(process.env)
    : command === "healthcheck"
      ? healthcheck(process.env)
      : command === "validate-metrics"
        ? validateMetrics(process.env)
      : Effect.fail(
          new GatewayRuntimeFailure({
            operation: "configuration",
            reason: "command must be serve, healthcheck, or validate-metrics",
          }),
        );

Effect.runPromise(
  program.pipe(
    Effect.match({
      onFailure: (error) => {
        process.stderr.write(
          `${JSON.stringify({
            schema_version: "model-gateway-error/v1",
            error: {
              kind: error._tag,
              reason: error.reason,
            },
          })}\n`,
        );
        return 1;
      },
      onSuccess: () => 0,
    }),
  ),
).then((exitCode) => {
  process.exitCode = exitCode;
});
