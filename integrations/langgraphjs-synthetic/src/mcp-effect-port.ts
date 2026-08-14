import {
  Client,
  type Implementation,
  type Transport,
} from "@modelcontextprotocol/client";
import { Effect } from "effect";
import * as z from "zod";

import {
  EffectIntentSchema,
  EffectObservationSchema,
  PortFailure,
  type EffectIntent,
  type EffectObservation,
  type EffectPort,
  type PortOperation,
} from "./contracts.js";
import { digestIntent } from "./pure.js";

type McpToolCaller = Pick<Client, "callTool">;

const controlledMcpToolCallerBrand: unique symbol = Symbol(
  "ControlledMcpToolCaller",
);

// @modelcontextprotocol/client@2.0.0 keeps LATEST_PROTOCOL_VERSION on the
// legacy initialize track. Its modern server/discover pin starts here.
const MCP_RUNTIME_PROTOCOL_VERSION = "2026-07-28";

export type ControlledMcpToolCaller = Readonly<
  McpToolCaller & {
    readonly [controlledMcpToolCallerBrand]: true;
  }
>;

export type UnsafeTestOnlyMcpToolCaller = McpToolCaller;

const controlledMcpToolCallers = new WeakSet<ControlledMcpToolCaller>();

const registerControlledMcpToolCaller = (
  callTool: McpToolCaller["callTool"],
): ControlledMcpToolCaller => {
  const caller: ControlledMcpToolCaller = Object.freeze({
    [controlledMcpToolCallerBrand]: true,
    callTool,
  });
  controlledMcpToolCallers.add(caller);
  return caller;
};

export const requireControlledMcpToolCaller = (
  caller: ControlledMcpToolCaller,
): ControlledMcpToolCaller => {
  if (!controlledMcpToolCallers.has(caller)) {
    throw new TypeError(
      "MCP production caller must be created by createControlledMcpClient",
    );
  }
  return caller;
};

export const unsafeCreateControlledMcpToolCallerForTest = (
  callTool: McpToolCaller["callTool"],
): ControlledMcpToolCaller => registerControlledMcpToolCaller(callTool);

const ControlledMcpConnectOptionsSchema = z
  .object({
    signal: z.instanceof(AbortSignal),
    timeoutMs: z.number().int().positive().max(300_000),
  })
  .strict();

export type ControlledMcpConnectOptions = z.infer<
  typeof ControlledMcpConnectOptionsSchema
>;

export type ControlledMcpClient = Readonly<{
  caller: ControlledMcpToolCaller;
  connect(
    transport: Transport,
    options: ControlledMcpConnectOptions,
  ): Promise<void>;
  close(): Promise<void>;
}>;

export const createControlledMcpClient = (
  clientInfo: Implementation,
): ControlledMcpClient => {
  const client = new Client(clientInfo, {
    capabilities: {},
    inputRequired: { autoFulfill: false, maxRounds: 1 },
    versionNegotiation: {
      mode: { pin: MCP_RUNTIME_PROTOCOL_VERSION },
      probe: { maxRetries: 0 },
    },
  });
  const controlledCallTool: McpToolCaller["callTool"] =
    client.callTool.bind(client);
  const caller = registerControlledMcpToolCaller(controlledCallTool);
  return Object.freeze({
    caller,
    connect: async (
      transport: Transport,
      rawOptions: ControlledMcpConnectOptions,
    ) => {
      const options = ControlledMcpConnectOptionsSchema.parse(rawOptions);
      if (transport.sessionId !== undefined) {
        throw new TypeError(
          "MCP controlled client rejects a transport with a pre-existing session",
        );
      }
      await client.connect(transport, {
        signal: options.signal,
        timeout: options.timeoutMs,
        maxTotalTimeout: options.timeoutMs,
        resetTimeoutOnProgress: false,
      });
    },
    close: () => client.close(),
  });
};

type McpEffectPortBaseOptions = {
  readonly componentId: string;
  readonly applyToolName: string;
  readonly queryToolName: string;
  readonly requestTimeoutMs: number;
};

export type McpEffectPortOptions = McpEffectPortBaseOptions & {
  readonly caller: ControlledMcpToolCaller;
};

export type UnsafeTestOnlyMcpEffectPortOptions = McpEffectPortBaseOptions & {
  readonly unsafeTestOnlyCaller: UnsafeTestOnlyMcpToolCaller;
};

const unknownObservation = (reason: string): EffectObservation => ({
  kind: "unknown",
  reason,
});

export class McpEffectPort implements EffectPort {
  readonly componentId: string;
  readonly #caller: McpToolCaller;
  readonly #applyToolName: string;
  readonly #queryToolName: string;
  readonly #requestTimeoutMs: number;

  constructor(options: McpEffectPortOptions) {
    this.componentId = z.string().min(1).parse(options.componentId);
    this.#caller = requireControlledMcpToolCaller(options.caller);
    this.#applyToolName = z.string().min(1).parse(options.applyToolName);
    this.#queryToolName = z.string().min(1).parse(options.queryToolName);
    this.#requestTimeoutMs = z
      .number()
      .int()
      .positive()
      .max(300_000)
      .parse(options.requestTimeoutMs);
    if (this.#applyToolName === this.#queryToolName) {
      throw new TypeError("MCP apply and query tools must be distinct");
    }
  }

  apply(intent: EffectIntent): Effect.Effect<EffectObservation, PortFailure> {
    return this.#call("apply", this.#applyToolName, intent);
  }

  query(intent: EffectIntent): Effect.Effect<EffectObservation, PortFailure> {
    return this.#call("query", this.#queryToolName, intent);
  }

  #call(
    operation: Extract<PortOperation, "apply" | "query">,
    toolName: string,
    intent: EffectIntent,
  ): Effect.Effect<EffectObservation, PortFailure> {
    const decodedIntent = EffectIntentSchema.parse(intent);
    return Effect.tryPromise({
      try: (signal) =>
        this.#caller.callTool(
          {
            name: toolName,
            arguments: { intent: decodedIntent },
          },
          {
            signal,
            timeout: this.#requestTimeoutMs,
            maxTotalTimeout: this.#requestTimeoutMs,
            resetTimeoutOnProgress: false,
            allowInputRequired: false,
          },
        ),
      catch: () =>
        new PortFailure({
          operation,
          reason: `MCP ${operation} call failed without a confirmed outcome`,
        }),
    }).pipe(
      Effect.map((result) => {
        if (result.isError === true) {
          return unknownObservation(
            `MCP ${operation} tool reported an unclassified error`,
          );
        }
        const decoded = EffectObservationSchema.safeParse(
          result.structuredContent,
        );
        if (!decoded.success) {
          return unknownObservation(
            `MCP ${operation} tool returned no valid structured observation`,
          );
        }
        if (
          decoded.data.kind === "confirmed_success" &&
          (decoded.data.receipt.producerComponentId !== this.componentId ||
            decoded.data.receipt.intentId !== decodedIntent.intentId ||
            decoded.data.receipt.idempotencyKey !==
              decodedIntent.idempotencyKey ||
            decoded.data.receipt.intentDigest !== digestIntent(decodedIntent))
        ) {
          return unknownObservation(
            `MCP ${operation} receipt named an unexpected producer`,
          );
        }
        return decoded.data;
      }),
    );
  }
}

export const unsafeCreateMcpEffectPortForTest = (
  options: UnsafeTestOnlyMcpEffectPortOptions,
): McpEffectPort => {
  const caller = registerControlledMcpToolCaller((params, callOptions) =>
    options.unsafeTestOnlyCaller.callTool(params, callOptions),
  );
  return new McpEffectPort({
    caller,
    componentId: options.componentId,
    applyToolName: options.applyToolName,
    queryToolName: options.queryToolName,
    requestTimeoutMs: options.requestTimeoutMs,
  });
};
