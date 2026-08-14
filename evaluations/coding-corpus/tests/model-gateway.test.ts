import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { createServer, type IncomingMessage, type Server } from "node:http";
import { createConnection } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { Effect, Either } from "effect";

import {
  ALLOWED_MODEL,
  DEFAULT_GATEWAY_LIMITS,
  type GatewayLimits,
} from "../src/gateway-domain.js";
import {
  GatewayRuntimeFailure,
  startGateway,
  validateUpstreamHost,
} from "../src/model-gateway.js";
import { NodeFileStoreLive } from "../src/node-runtime.js";

interface UpstreamRecord {
  readonly path: string;
  readonly authorization: string | undefined;
  readonly candidateRoutingHeader: string | undefined;
  readonly body: Uint8Array;
}

interface StubUpstream {
  readonly server: Server;
  readonly port: number;
  readonly records: UpstreamRecord[];
  readonly setBody: (value: Uint8Array) => void;
  readonly block: () => { readonly entered: Promise<void>; readonly release: () => void };
}

const listen = (server: Server): Promise<number> =>
  new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      server.off("error", reject);
      const address = server.address();
      if (address === null || typeof address === "string") {
        reject(new Error("listener address unavailable"));
        return;
      }
      resolve(address.port);
    });
  });

const close = (server: Server): Promise<void> =>
  new Promise((resolve) => {
    server.close(() => resolve());
    server.closeAllConnections();
  });

const readRequest = async (request: IncomingMessage): Promise<Uint8Array> => {
  const chunks: Buffer[] = [];
  for await (const chunk of request) chunks.push(Buffer.from(chunk));
  return Buffer.concat(chunks);
};

const makeUpstream = async (): Promise<StubUpstream> => {
  const records: UpstreamRecord[] = [];
  let body = Buffer.from(
    JSON.stringify({
      id: "local-test",
      choices: [{ message: { role: "assistant", content: "ok" } }],
      usage: { prompt_tokens: 11, completion_tokens: 7, total_tokens: 18 },
    }),
  );
  let enteredResolve: (() => void) | undefined;
  let releasePromise: Promise<void> | undefined;
  const server = createServer(async (request, response) => {
    const requestBody = await readRequest(request);
    records.push({
      path: request.url ?? "",
      authorization: request.headers["authorization"],
      candidateRoutingHeader: request.headers["x-upstream-host"] as
        | string
        | undefined,
      body: requestBody,
    });
    enteredResolve?.();
    if (releasePromise !== undefined) await releasePromise;
    response.writeHead(200, {
      "Content-Length": String(body.byteLength),
      "Content-Type": "application/json",
    });
    response.end(body);
  });
  const port = await listen(server);
  return {
    server,
    port,
    records,
    setBody: (value) => {
      body = Buffer.from(value);
    },
    block: () => {
      let release: (() => void) | undefined;
      const entered = new Promise<void>((resolve) => {
        enteredResolve = resolve;
      });
      releasePromise = new Promise<void>((resolve) => {
        release = resolve;
      });
      return {
        entered,
        release: () => {
          release?.();
          releasePromise = undefined;
          enteredResolve = undefined;
        },
      };
    },
  };
};

const validPayload = (updates: Readonly<Record<string, unknown>> = {}) => ({
  model: ALLOWED_MODEL,
  messages: [{ role: "user", content: "fix private bug" }],
  max_tokens: 128,
  stream: false,
  ...updates,
});

const post = (
  port: number,
  value: unknown,
  path = "/v1/chat/completions",
): Promise<Response> =>
  fetch(`http://127.0.0.1:${port}${path}`, {
    method: "POST",
    body: typeof value === "string" ? value : JSON.stringify(value),
    headers: {
      Authorization: "Bearer candidate-value",
      "Content-Type": "application/json",
      "X-Upstream-Host": "attacker.invalid:4444",
    },
  });

const withGateway = async <A>(
  upstream: StubUpstream,
  body: (port: number, metricsPath: string) => Promise<A>,
  options?: {
    readonly secret?: string;
    readonly limits?: GatewayLimits;
    readonly clientReadTimeoutMs?: number;
    readonly upstreamTimeoutMs?: number;
  },
): Promise<A> => {
  const temporary = await mkdtemp(join(tmpdir(), "coding-corpus-gateway-"));
  const metricsPath = join(temporary, "metrics.json");
  try {
    return await Effect.runPromise(
      Effect.scoped(
        Effect.gen(function* () {
          const gateway = yield* startGateway({
            listenHost: "127.0.0.1",
            listenPort: 0,
            upstreamHost: "127.0.0.1",
            upstreamPort: upstream.port,
            secret: options?.secret ?? "real-gateway-secret",
            metricsPath,
            limits: options?.limits ?? DEFAULT_GATEWAY_LIMITS,
            clientReadTimeoutMs: options?.clientReadTimeoutMs ?? 1_000,
            upstreamTimeoutMs: options?.upstreamTimeoutMs ?? 2_000,
          });
          return yield* Effect.tryPromise({
            try: () => body(gateway.port, metricsPath),
            catch: (error) => (error instanceof Error ? error : new Error("test failed")),
          });
        }),
      ).pipe(Effect.provide(NodeFileStoreLive)),
    );
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
};

test("TS gateway forwards only the fixed contract and rewrites authorization", async () => {
  const upstream = await makeUpstream();
  const secret = "real-gateway-secret";
  try {
    await withGateway(
      upstream,
      async (port, metricsPath) => {
        const response = await post(port, validPayload());
        assert.equal(response.status, 200);
        const responseBody = (await response.json()) as {
          readonly choices: readonly [{ readonly message: { readonly content: string } }];
        };
        assert.equal(responseBody.choices[0].message.content, "ok");
        assert.equal(upstream.records.length, 1);
        const record = upstream.records[0];
        assert.ok(record !== undefined);
        assert.equal(record.path, "/v1/chat/completions");
        assert.equal(record.authorization, `Bearer ${secret}`);
        assert.equal(record.candidateRoutingHeader, undefined);
        const forwarded = JSON.parse(new TextDecoder().decode(record.body)) as Record<
          string,
          unknown
        >;
        assert.equal(forwarded["temperature"], 0);
        assert.equal(forwarded["stream"], false);
        assert.equal(forwarded["n"], 1);

        const metrics = await readFile(metricsPath, "utf8");
        assert.equal(JSON.parse(metrics).usage.total_tokens, 18);
        assert.doesNotMatch(metrics, /real-gateway-secret|candidate-value|fix private bug/u);
      },
      { secret },
    );
  } finally {
    await close(upstream.server);
  }
});

test("TS gateway rejects invalid paths and payloads before upstream", async () => {
  const upstream = await makeUpstream();
  try {
    await withGateway(upstream, async (port) => {
      const cases: ReadonlyArray<readonly [string, unknown, number]> = [
        ["/v1/models", validPayload(), 404],
        ["/v1/chat/completions", validPayload({ model: "other" }), 400],
        ["/v1/chat/completions", validPayload({ stream: true }), 400],
        ["/v1/chat/completions", validPayload({ temperature: 0.1 }), 400],
        ["/v1/chat/completions", validPayload({ max_tokens: 4_097 }), 400],
        ["/v1/chat/completions", validPayload({ n: 2 }), 400],
        [
          "/v1/chat/completions",
          validPayload({ base_url: "http://attacker.invalid" }),
          400,
        ],
        ["/v1/chat/completions", validPayload({ top_p: 0.5 }), 400],
      ];
      for (const [path, value, status] of cases) {
        const response = await post(port, value, path);
        assert.equal(response.status, status);
      }
      assert.equal(upstream.records.length, 0);
    });
  } finally {
    await close(upstream.server);
  }
});

test("TS gateway bounds request count and concurrent upstream work", async () => {
  const upstream = await makeUpstream();
  try {
    await withGateway(
      upstream,
      async (port) => {
        assert.equal((await post(port, validPayload())).status, 200);
        assert.equal((await post(port, validPayload())).status, 429);
      },
      { limits: { ...DEFAULT_GATEWAY_LIMITS, maxRequests: 1 } },
    );
    assert.equal(upstream.records.length, 1);

    const blocked = upstream.block();
    await withGateway(upstream, async (port) => {
      const first = post(port, validPayload());
      await blocked.entered;
      const second = await post(port, validPayload());
      assert.equal(second.status, 429);
      blocked.release();
      assert.equal((await first).status, 200);
    });
  } finally {
    await close(upstream.server);
  }
});

test("TS gateway reserves cumulative completion budget before upstream dispatch", async () => {
  const upstream = await makeUpstream();
  try {
    await withGateway(
      upstream,
      async (port, metricsPath) => {
        assert.equal((await post(port, validPayload({ max_tokens: 10 }))).status, 200);
        assert.equal((await post(port, validPayload({ max_tokens: 10 }))).status, 200);
        const crossing = await post(port, validPayload({ max_tokens: 10 }));
        assert.equal(crossing.status, 429);
        assert.match(await crossing.text(), /completion_token_budget_exhausted/u);
        const metrics = JSON.parse(await readFile(metricsPath, "utf8"));
        assert.equal(metrics.usage.completion_tokens, 14);
        assert.equal(metrics.completion_tokens_reserved, 0);
        assert.equal(metrics.completion_budget_overshoot, 0);
      },
      { limits: { ...DEFAULT_GATEWAY_LIMITS, maxCompletionTokens: 20 } },
    );
    assert.equal(upstream.records.length, 2);
  } finally {
    await close(upstream.server);
  }
});

test("TS gateway never reflects its upstream bearer", async () => {
  const upstream = await makeUpstream();
  const secret = "never-return-this-secret";
  upstream.setBody(Buffer.from(JSON.stringify({ value: secret })));
  try {
    await withGateway(
      upstream,
      async (port) => {
        const response = await post(port, validPayload());
        assert.equal(response.status, 502);
        assert.doesNotMatch(await response.text(), new RegExp(secret, "u"));
      },
      { secret },
    );
  } finally {
    await close(upstream.server);
  }
});

test("TS gateway rejects JSON-escaped bearer reflection", async () => {
  const upstream = await makeUpstream();
  const secret = "private<gateway>secret";
  upstream.setBody(
    Buffer.from(
      `{"value":"private\\u003cgateway\\u003esecret","usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}`,
    ),
  );
  try {
    await withGateway(
      upstream,
      async (port) => {
        const response = await post(port, validPayload());
        assert.equal(response.status, 502);
        assert.doesNotMatch(await response.text(), new RegExp(secret, "u"));
      },
      { secret },
    );
  } finally {
    await close(upstream.server);
  }
});

test("TS gateway body timeout releases the admission slot", async () => {
  const upstream = await makeUpstream();
  try {
    await withGateway(
      upstream,
      async (port) => {
        const response = await new Promise<string>((resolve, reject) => {
          const socket = createConnection({ host: "127.0.0.1", port }, () => {
            socket.write(
              "POST /v1/chat/completions HTTP/1.1\r\n" +
                "Host: model-gateway\r\n" +
                "Content-Type: application/json\r\n" +
                "Content-Length: 10\r\n\r\n",
            );
          });
          socket.setEncoding("utf8");
          let received = "";
          socket.on("data", (chunk) => {
            received += chunk;
          });
          socket.on("end", () => resolve(received));
          socket.on("error", reject);
        });
        assert.match(response.split("\r\n", 1)[0] ?? "", / 408 /u);
        assert.equal((await post(port, validPayload())).status, 200);
      },
      { clientReadTimeoutMs: 50 },
    );
  } finally {
    await close(upstream.server);
  }
});

test("slow upstream work is not cut off by the client body deadline", async () => {
  const upstream = await makeUpstream();
  const blocked = upstream.block();
  try {
    await withGateway(
      upstream,
      async (port) => {
        const pending = post(port, validPayload());
        await blocked.entered;
        setTimeout(blocked.release, 1_200);
        assert.equal((await pending).status, 200);
      },
      { clientReadTimeoutMs: 50, upstreamTimeoutMs: 2_000 },
    );
  } finally {
    blocked.release();
    await close(upstream.server);
  }
});

test("unknown upstream outcome burns the reservation and blocks retry", async () => {
  const upstream = await makeUpstream();
  const blocked = upstream.block();
  try {
    await withGateway(
      upstream,
      async (port, metricsPath) => {
        const first = post(port, validPayload({ max_tokens: 10 }));
        await blocked.entered;
        assert.equal((await first).status, 504);
        const retry = await post(port, validPayload({ max_tokens: 10 }));
        assert.equal(retry.status, 429);
        assert.match(
          await retry.text(),
          /unknown_completion_outcome_requires_reconciliation/u,
        );
        const metrics = JSON.parse(await readFile(metricsPath, "utf8"));
        assert.equal(metrics.completion_tokens_reserved, 0);
        assert.equal(metrics.completion_tokens_unknown, 10);
        assert.equal(metrics.usage.completion_tokens, 0);
      },
      {
        upstreamTimeoutMs: 50,
        limits: { ...DEFAULT_GATEWAY_LIMITS, maxCompletionTokens: 20 },
      },
    );
  } finally {
    blocked.release();
    await close(upstream.server);
  }
});

test("operator upstream host remains a plain host", () => {
  assert.equal(validateUpstreamHost("192.168.0.23"), "192.168.0.23");
  assert.equal(validateUpstreamHost("dgx-stub"), "dgx-stub");
  for (const host of [
    "http://192.168.0.23",
    "192.168.0.23:18000",
    " bad",
    "a/b",
    "::1",
  ]) {
    assert.throws(() => validateUpstreamHost(host));
  }
});

test("programmatic gateway configuration rejects unbounded limits", async () => {
  const upstream = await makeUpstream();
  const evaluate = async (
    updates: Partial<Parameters<typeof startGateway>[0]>,
  ) => {
    const root = await mkdtemp(join(tmpdir(), "coding-corpus-invalid-config-"));
    try {
      return await Effect.runPromise(
        Effect.scoped(
          startGateway({
            listenHost: "127.0.0.1",
            listenPort: 0,
            upstreamHost: "127.0.0.1",
            upstreamPort: upstream.port,
            secret: "bounded-test-secret",
            metricsPath: join(root, "metrics.json"),
            ...updates,
          }),
        ).pipe(Effect.provide(NodeFileStoreLive), Effect.either),
      );
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  };
  try {
    const invalidLimits = await evaluate({
      limits: { ...DEFAULT_GATEWAY_LIMITS, maxResponseBytes: 0 },
    });
    assert.equal(Either.isLeft(invalidLimits), true);
    if (Either.isLeft(invalidLimits)) {
      assert.equal(invalidLimits.left instanceof GatewayRuntimeFailure, true);
      assert.match(invalidLimits.left.reason, /gateway limits/u);
    }
    const invalidTimeout = await evaluate({ clientReadTimeoutMs: 0 });
    assert.equal(Either.isLeft(invalidTimeout), true);
    if (Either.isLeft(invalidTimeout)) {
      assert.equal(invalidTimeout.left instanceof GatewayRuntimeFailure, true);
      assert.match(invalidTimeout.left.reason, /gateway timeouts/u);
    }
  } finally {
    await close(upstream.server);
  }
});
