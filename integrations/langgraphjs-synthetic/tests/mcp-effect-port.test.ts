import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  Client,
  InMemoryTransport,
  type CallToolResult,
} from "@modelcontextprotocol/client";
import { Effect } from "effect";

import {
  McpEffectPort,
  createControlledMcpClient,
  createSyntheticConsumer,
  digestIntent,
  systemTrustedClock,
  type EffectIntent,
  type SyntheticRunInput,
  type VerificationPort,
} from "../src/index.js";
import {
  unsafeCreateMcpEffectPortForTest,
  type UnsafeTestOnlyMcpToolCaller,
} from "../src/mcp-effect-port.js";

const intent: EffectIntent = {
  intentId: "intent:mcp-1",
  idempotencyKey: "idempotency:mcp-1",
  action: "write_synthetic_analysis_artifact",
  payload: { marker: "SYNTHETIC" },
};

const graphInput: SyntheticRunInput = {
  schemaVersion: "flrh-langgraphjs-input/1",
  profileVersion: "shared-accelerator-synthetic/1",
  runId: "run:mcp-1",
  availableHeadroom: 8,
  requiredHeadroom: 4,
  timeoutMs: 2_000,
  approval: {
    required: false,
    deadlineAt: "2026-08-11T16:00:00Z",
  },
  intent,
};

const confirmedSuccess: CallToolResult = {
  content: [],
  structuredContent: {
    kind: "confirmed_success",
    receipt: {
      kind: "action_receipt",
      intentId: intent.intentId,
      idempotencyKey: intent.idempotencyKey,
      artifactId: "artifact:mcp-1",
      artifactDigest:
        "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      intentDigest:
        digestIntent(intent),
      producerComponentId: "effect:mcp-allowlisted",
    },
  },
};

describe("Effect-wrapped MCP effect port", () => {
  it("keeps the unsafe test seam out of the public entry point", async () => {
    const publicApi = await import("../src/index.js");

    assert.equal("unsafeCreateMcpEffectPortForTest" in publicApi, false);
  });

  it("rejects raw or spoofed callers at the production constructor", () => {
    const rawCaller = {
      callTool: async () => confirmedSuccess,
    };
    const defaultClient = new Client({
      name: "synthetic-default-client",
      version: "1.0.0",
    });
    const spoofedCaller = {
      inputRequiredMode: "manual" as const,
      callTool: defaultClient.callTool.bind(defaultClient),
    };
    const commonOptions = {
      componentId: "effect:mcp-constructor-boundary",
      applyToolName: "synthetic_apply",
      queryToolName: "synthetic_query",
      requestTimeoutMs: 2_000,
    };

    assert.throws(
      () =>
        new McpEffectPort({
          ...commonOptions,
          // @ts-expect-error production callers require an opaque runtime brand
          caller: spoofedCaller,
        }),
      /createControlledMcpClient/u,
    );
    assert.throws(
      () =>
        new McpEffectPort({
          ...commonOptions,
          // @ts-expect-error production callers require an opaque runtime brand
          caller: rawCaller,
        }),
      /createControlledMcpClient/u,
    );
  });

  it("accepts the opaque caller created by the controlled client factory", () => {
    const controlled = createControlledMcpClient({
      name: "synthetic-controlled-client",
      version: "1.0.0",
    });

    assert.equal("client" in controlled, false);
    assert.equal("setRequestHandler" in controlled, false);
    assert.equal("registerCapabilities" in controlled, false);
    assert.equal("setVersionNegotiation" in controlled, false);
    assert.deepEqual(Object.keys(controlled).sort(), ["caller", "close", "connect"]);

    assert.doesNotThrow(
      () =>
        new McpEffectPort({
          caller: controlled.caller,
          componentId: "effect:mcp-controlled",
          applyToolName: "synthetic_apply",
          queryToolName: "synthetic_query",
          requestTimeoutMs: 2_000,
        }),
    );

    const clonedCaller = { ...controlled.caller };
    assert.throws(
      () =>
        new McpEffectPort({
          caller: clonedCaller,
          componentId: "effect:mcp-cloned",
          applyToolName: "synthetic_apply",
          queryToolName: "synthetic_query",
          requestTimeoutMs: 2_000,
        }),
      /createControlledMcpClient/u,
    );
  });

  it("rejects legacy or unsupported negotiation without reaching a tool call", async (t) => {
    const negotiationReplies = [
      {
        name: "legacy method-not-found",
        reply: {
          code: -32601,
          message: "server/discover is unavailable",
        },
      },
      {
        name: "unsupported modern revision",
        reply: {
          code: -32022,
          message: "unsupported protocol version",
          data: {
            requested: "2026-07-28",
            supported: ["2026-08-01"],
          },
        },
      },
    ] as const;

    for (const scenario of negotiationReplies) {
      await t.test(scenario.name, async () => {
        const [clientTransport, serverTransport] =
          InMemoryTransport.createLinkedPair();
        const methods: Array<string> = [];
        serverTransport.onmessage = (message) => {
          if (!("method" in message) || !("id" in message)) return;
          methods.push(message.method);
          void serverTransport.send({
            jsonrpc: "2.0",
            id: message.id,
            error: scenario.reply,
          });
        };
        await serverTransport.start();
        const controlled = createControlledMcpClient({
          name: `synthetic-${scenario.name}`,
          version: "1.0.0",
        });

        await assert.rejects(
          controlled.connect(clientTransport, {
            signal: AbortSignal.timeout(250),
            timeoutMs: 250,
          }),
        );
        await assert.rejects(
          controlled.caller.callTool(
            { name: "synthetic_apply", arguments: {} },
            { timeout: 250 },
          ),
        );
        assert.deepEqual(methods, ["server/discover"]);
      });
    }
  });

  it("rejects a caller-supplied legacy prior before opening the transport", async () => {
    const [clientTransport, serverTransport] =
      InMemoryTransport.createLinkedPair();
    const methods: Array<string> = [];
    serverTransport.onmessage = (message) => {
      if (!("method" in message)) return;
      methods.push(message.method);
      if (!("id" in message) || message.method !== "initialize") return;
      void serverTransport.send({
        jsonrpc: "2.0",
        id: message.id,
        result: {
          protocolVersion: "2025-11-25",
          capabilities: { tools: {} },
          serverInfo: { name: "synthetic-legacy", version: "1" },
        },
      });
    };
    await serverTransport.start();
    const controlled = createControlledMcpClient({
      name: "synthetic-prior-rejection",
      version: "1.0.0",
    });

    try {
      await assert.rejects(
        async () =>
          controlled.connect(clientTransport, {
            signal: AbortSignal.timeout(250),
            timeoutMs: 250,
            prior: { kind: "legacy" },
          } as never),
      );
      assert.deepEqual(methods, []);
    } finally {
      await controlled.close();
    }
  });

  it("rejects a transport carrying a pre-existing unverified session", async () => {
    const [clientTransport, serverTransport] =
      InMemoryTransport.createLinkedPair();
    const methods: Array<string> = [];
    clientTransport.sessionId = "pre-existing-unverified-session";
    serverTransport.onmessage = (message) => {
      if ("method" in message) methods.push(message.method);
    };
    await serverTransport.start();
    const controlled = createControlledMcpClient({
      name: "synthetic-session-rejection",
      version: "1.0.0",
    });

    try {
      await assert.rejects(
        controlled.connect(clientTransport, {
          signal: AbortSignal.timeout(250),
          timeoutMs: 250,
        }),
        /pre-existing session/u,
      );
      assert.deepEqual(methods, []);
    } finally {
      await controlled.close();
    }
  });

  it("does not auto-continue an input-required tool result", async () => {
    const [clientTransport, serverTransport] =
      InMemoryTransport.createLinkedPair();
    const toolCalls: Array<unknown> = [];
    serverTransport.onmessage = (message) => {
      if (!("method" in message) || !("id" in message)) return;
      if (message.method === "server/discover") {
        void serverTransport.send({
          jsonrpc: "2.0",
          id: message.id,
          result: {
            supportedVersions: ["2026-07-28"],
            capabilities: { tools: {} },
          },
        });
        return;
      }
      if (message.method === "tools/call") {
        toolCalls.push(message.params);
        void serverTransport.send({
          jsonrpc: "2.0",
          id: message.id,
          result: {
            resultType: "input_required",
            requestState: "server-controlled-opaque-state",
          },
        });
      }
    };
    await serverTransport.start();
    const controlled = createControlledMcpClient({
      name: "synthetic-no-input-continuation",
      version: "1.0.0",
    });
    const port = new McpEffectPort({
      caller: controlled.caller,
      componentId: "effect:mcp-no-input-continuation",
      applyToolName: "synthetic_apply",
      queryToolName: "synthetic_query",
      requestTimeoutMs: 250,
    });

    try {
      await controlled.connect(clientTransport, {
        signal: AbortSignal.timeout(250),
        timeoutMs: 250,
      });
      await assert.rejects(Effect.runPromise(port.apply(intent)));
      assert.equal(toolCalls.length, 1);
    } finally {
      await controlled.close();
    }
  });

  it("uses only the configured apply and query tool names", async () => {
    const calls: Array<string> = [];
    let receivedOptions: Parameters<
      UnsafeTestOnlyMcpToolCaller["callTool"]
    >[1];
    const caller: UnsafeTestOnlyMcpToolCaller = {
      callTool: async (params, options) => {
        calls.push(params.name);
        receivedOptions = options;
        return confirmedSuccess;
      },
    };
    const port = unsafeCreateMcpEffectPortForTest({
      unsafeTestOnlyCaller: caller,
      componentId: "effect:mcp-allowlisted",
      applyToolName: "synthetic_apply",
      queryToolName: "synthetic_query",
      requestTimeoutMs: 2_000,
    });

    const applied = await Effect.runPromise(port.apply(intent));
    const queried = await Effect.runPromise(port.query(intent));

    assert.equal(applied.kind, "confirmed_success");
    assert.equal(queried.kind, "confirmed_success");
    assert.deepEqual(calls, ["synthetic_apply", "synthetic_query"]);
    assert.equal(calls.includes(intent.action), false);
    assert.equal(receivedOptions?.timeout, 2_000);
    assert.equal(receivedOptions?.maxTotalTimeout, 2_000);
    assert.equal(receivedOptions?.resetTimeoutOnProgress, false);
    assert.equal(receivedOptions?.allowInputRequired, false);
    assert.ok(receivedOptions?.signal instanceof AbortSignal);
  });

  it("maps a tool error or invalid structured output to unknown", async () => {
    const results: Array<CallToolResult> = [
      { content: [], isError: true },
      { content: [], structuredContent: { unexpected: true } },
    ];
    const caller: UnsafeTestOnlyMcpToolCaller = {
      callTool: async () => results.shift() ?? { content: [] },
    };
    const port = unsafeCreateMcpEffectPortForTest({
      unsafeTestOnlyCaller: caller,
      componentId: "effect:mcp-unknown",
      applyToolName: "synthetic_apply",
      queryToolName: "synthetic_query",
      requestTimeoutMs: 2_000,
    });

    const toolError = await Effect.runPromise(port.apply(intent));
    const invalidOutput = await Effect.runPromise(port.query(intent));

    assert.equal(toolError.kind, "unknown");
    assert.equal(invalidOutput.kind, "unknown");
  });

  it("rejects an MCP configuration that reuses the mutating tool for query", () => {
    const caller: UnsafeTestOnlyMcpToolCaller = {
      callTool: async () => confirmedSuccess,
    };

    assert.throws(
      () =>
        unsafeCreateMcpEffectPortForTest({
          unsafeTestOnlyCaller: caller,
          componentId: "effect:mcp-invalid",
          applyToolName: "same_tool",
          queryToolName: "same_tool",
          requestTimeoutMs: 2_000,
        }),
      /distinct/u,
    );
  });

  it("does not trust a success receipt that is not bound to the intent", async () => {
    const mismatched: CallToolResult = {
      ...confirmedSuccess,
      structuredContent: {
        kind: "confirmed_success",
        receipt: {
          kind: "action_receipt",
          intentId: "intent:other",
          idempotencyKey: intent.idempotencyKey,
          artifactId: "artifact:mcp-1",
          artifactDigest:
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          intentDigest: digestIntent(intent),
          producerComponentId: "effect:mcp-bound",
        },
      },
    };
    const caller: UnsafeTestOnlyMcpToolCaller = {
      callTool: async () => mismatched,
    };
    const port = unsafeCreateMcpEffectPortForTest({
      unsafeTestOnlyCaller: caller,
      componentId: "effect:mcp-bound",
      applyToolName: "synthetic_apply",
      queryToolName: "synthetic_query",
      requestTimeoutMs: 2_000,
    });

    const observation = await Effect.runPromise(port.apply(intent));

    assert.equal(observation.kind, "unknown");
  });

  it("routes an MCP call rejection to query without retrying apply", async () => {
    const calls: Array<string> = [];
    const caller: UnsafeTestOnlyMcpToolCaller = {
      callTool: async (params) => {
        calls.push(params.name);
        if (params.name === "synthetic_apply") {
          throw new Error("connection lost after destination boundary");
        }
        return {
          content: [],
          structuredContent: {
            kind: "unknown",
            reason: "destination remains unobservable",
          },
        };
      },
    };
    const effect = unsafeCreateMcpEffectPortForTest({
      unsafeTestOnlyCaller: caller,
      componentId: "effect:mcp-reject",
      applyToolName: "synthetic_apply",
      queryToolName: "synthetic_query",
      requestTimeoutMs: 2_000,
    });
    const verifier: VerificationPort = {
      componentId: "verifier:mcp-reject",
      verify: () =>
        Effect.succeed({
          kind: "rejected",
          verifierComponentId: "verifier:mcp-reject",
          reason: "no confirmed receipt",
        }),
    };
    const consumer = createSyntheticConsumer({
      effect,
      verifier,
      clock: systemTrustedClock,
    });

    const result = await consumer.run(graphInput, {
      signal: AbortSignal.timeout(5_000),
    });

    assert.equal(result.kind, "interrupted");
    if (result.kind !== "interrupted") return;
    assert.equal(result.interrupt.kind, "reconciliation_required");
    assert.deepEqual(calls, ["synthetic_apply", "synthetic_query"]);
  });
});
