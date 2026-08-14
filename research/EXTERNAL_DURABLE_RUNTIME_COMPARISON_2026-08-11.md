# External Durable Runtime Comparison — 2026-08-11

> Sources rechecked: 2026-08-14.
>
> Epistemic status: **ACCEPTED — source-attributed official-document review**
> for the named products and **PROPOSED** for local FLR-H synthesis.
> `ACCEPTED` here means the maintainers' documentation or repository was
> checked; it is not a benchmark, local execution receipt, endorsement,
> dependency decision, or engine verdict. Nothing in this document is
> `MEASURED` evidence for this repository.

## Scope and method

**ACCEPTED — review method.** This review asks which shipped mechanisms can
inform a bounded, TypeScript-compatible agent/application control slice
without turning FLR-H into a broad framework. Only official product
documentation and official GitHub repositories were used. The linked pages
were rechecked on 2026-08-14.

The durable-runtime comparison covers Temporal, Restate, DBOS, and
LangGraph.js. A narrower comparison covers TypeScript functional and agent
assembly surfaces in Effect, Mastra, LangGraph.js, and the OpenAI Agents SDK.
Their names and claims remain those of their maintainers; none is treated as
FLR-H canon or local efficacy evidence.

## Comparison

| Runtime | ACCEPTED source-attributed control and persistence mechanism | ACCEPTED source-attributed external-work boundary | ACCEPTED source-attributed evolution mechanism | PROPOSED FLR-H lesson |
|---|---|---|---|---|
| Temporal | Workflow code must be deterministic for Event History replay; worker failure recovery is platform-managed. | Non-deterministic I/O belongs in Activities. An Activity whose completion Temporal has recorded is not re-executed during Workflow replay. Work that finishes but never reports completion can be retried, so Temporal recommends idempotent Activities. | Worker Versioning supports pinned or auto-upgrade behavior; patching keeps auto-upgrade paths replay-safe. | Keep the control transition pure, external work behind a port, and workflow/profile versions explicit. |
| Restate | An execution log records operations; `ctx.run` stores non-deterministic results for deterministic replay. The architecture uses journal commits and attempt epochs. | `ctx.run` can retry with count/time limits. Official Saga guidance still requires idempotent compensations or an external API idempotency key. | Existing requests remain pinned to the deployment where they began. Manual deployments should remain available until invocations drain before removal; automatic draining is an Operator-specific facility, and forced removal is possible. | Use a durable journal and fencing, but never transpose Restate's internal delivery guarantees into a claim about arbitrary external mutation. |
| DBOS | Durable workflows resume after the last completed step. Steps are attempted at least once and are not re-executed after DBOS records completion. | Transactions commit exactly once within DBOS's transaction boundary; datasource exactly-once requires the completion checkpoint in the same database transaction. HTTP or other unreliable work belongs in retryable steps. | Patching records history markers; application versioning recovers a workflow only on the matching version. | State the atomicity boundary precisely. Same-database transaction closure is not generic external exactly-once. |
| LangGraph.js | Checkpointers persist thread state; Functional API task/subgraph results are restored while the entrypoint replays from a checkpoint boundary. | Non-determinism and side effects belong in tasks. The docs require idempotent design because a task that started but did not finish may execute again. | The latest graph runs against existing checkpoints, so checkpoint schema, node identity, and Functional API call order require explicit compatibility handling. | Treat receipt reingestion and checkpoint/profile version as public state transitions, not hidden resume magic. |

### Temporal sources

- [Workflow Definition and deterministic replay](https://docs.temporal.io/workflow-definition)
- [Activity Definition and idempotency guidance](https://docs.temporal.io/activity-definition)
- [Workers and task queues](https://docs.temporal.io/workers)
- [Worker Versioning](https://docs.temporal.io/worker-versioning)
- [Official TypeScript SDK repository](https://github.com/temporalio/sdk-typescript)

**ACCEPTED — source-attributed summary.** A Workflow must reproduce the same
command sequence from the same history. API calls, model calls, database
access, and other external work belong in Activities outside the replay path.
Temporal distinguishes durable Workflow replay from Activity retry and
therefore recommends idempotent Activities rather than promising arbitrary
external exactly-once mutation.

### Restate sources

- [TypeScript durable steps](https://docs.restate.dev/develop/ts/durable-steps)
- [Restate architecture](https://docs.restate.dev/references/architecture)
- [Service versioning](https://docs.restate.dev/services/versioning)
- [Sagas and external idempotency](https://docs.restate.dev/guides/sagas)
- [Official TypeScript SDK repository](https://github.com/restatedev/sdk-typescript)

**ACCEPTED — source-attributed summary.** Restate uses an execution log to
replay operations, and `ctx.run` journals non-deterministic results. Its
architecture documents log-first steps, monotonically increasing attempt
epochs, and internal cross-partition deduplication. The same documentation set
separately tells applications to make compensations idempotent or use the
destination API's idempotency key. Those scopes must not be collapsed.

### DBOS sources

- [TypeScript workflow tutorial and guarantees](https://docs.dbos.dev/typescript/tutorials/workflow-tutorial)
- [TypeScript workflows and steps reference](https://docs.dbos.dev/typescript/reference/workflows-steps)
- [Transactions and datasources](https://docs.dbos.dev/typescript/reference/datasource)
- [Datasource plugin transaction mechanism](https://docs.dbos.dev/typescript/reference/plugins)
- [Upgrading workflow code](https://docs.dbos.dev/typescript/tutorials/upgrading-workflows)
- [Official TypeScript repository](https://github.com/dbos-inc/dbos-transact-ts)

**ACCEPTED — source-attributed summary.** DBOS distinguishes workflow
recovery, step retry, and database transaction commit. Its datasource
documentation conditions exactly-once transaction processing on a checkpoint
stored in the same database transaction as the application mutation. Its step
API exposes bounded attempts and a cooperative timeout signal; a timed-out
operation that ignores the signal can continue in the background even though
its result is discarded.

### LangGraph.js sources

- [JavaScript Functional API](https://docs.langchain.com/oss/javascript/langgraph/functional-api)
- [JavaScript persistence](https://docs.langchain.com/oss/javascript/langgraph/persistence)
- [Backward compatibility](https://docs.langchain.com/oss/javascript/langgraph/backward-compatibility)
- [Official LangGraph.js repository](https://github.com/langchain-ai/langgraphjs)

**ACCEPTED — source-attributed summary.** Functional API entrypoints replay
from their beginning after a pause while persisted task results are restored.
Checkpointers retain thread-scoped state; stores hold application data across
threads. The official compatibility guide warns that existing checkpoints are
an API surface and that adding, removing, or reordering replay-positioned
task/interrupt calls can break in-flight Functional API runs.

## TypeScript functional and agent assembly references

| Project | ACCEPTED source-attributed assembly surface | ACCEPTED source-attributed persistence/effect boundary | PROPOSED use here |
|---|---|---|---|
| Effect | In Effect v3.22.1, `Effect` represents success, typed failure, and required services; `Layer` constructs service graphs. Schema and Scope APIs support decoded boundaries and resource lifetime control. | Effect v4's prerelease source also contains Workflow and Activity APIs under `unstable`. The v4 migration policy permits breaking changes in unstable modules, and this surface is a different major from the repository-pinned v3.22.1 core. | A bounded Effect v3 control vertical slice may use stable v3 as a functional-core/effect-shell substrate behind existing ports. Do not make v4 Workflow/Cluster APIs or any prerelease surface the normative FLR-H contract. |
| Mastra | Workflows compose schema-declared steps, branches, parallel paths, agents, and tools. | Workflow snapshots support suspend/resume through configured storage; eval datasets and scorers are a separate product surface. | Study its developer-facing workflow and evaluation ergonomics, while keeping local durability and claim semantics independent. |
| LangGraph.js | `StateGraph` and Functional API `entrypoint`/`task` are two public ways to assemble stateful agent flows. | Checkpointers persist thread state; side effects belong in replay-aware tasks and must tolerate re-execution before completion is recorded. | Use its checkpoint and human-in-the-loop fault cases as comparison fixtures, not as evidence that local terminal closure is correct. |
| OpenAI Agents SDK | Agents, a runner-managed loop, tools, handoffs, guardrails, and approvals form a compact agent-loop API. | The SDK documents application-owned history, Sessions, Conversations, response chaining, and resumable state for interrupted approvals. These are agent run/conversation continuation surfaces, not a generic durable workflow-step journal. | Study the small agent/tool/handoff/state API. Keep durable effect intent, reconciliation, and completion authority in the local H contract. |

### Effect sources

- [Official Effect repository](https://github.com/Effect-TS/effect)
- [Effect v3.22.1 source tag](https://github.com/Effect-TS/effect/tree/effect%403.22.1)
- [`Effect` source at v3.22.1](https://github.com/Effect-TS/effect/blob/effect%403.22.1/packages/effect/src/Effect.ts)
- [`Layer` source at v3.22.1](https://github.com/Effect-TS/effect/blob/effect%403.22.1/packages/effect/src/Layer.ts)
- [`Schema` source at v3.22.1](https://github.com/Effect-TS/effect/blob/effect%403.22.1/packages/effect/src/Schema.ts)
- [`Scope` source at v3.22.1](https://github.com/Effect-TS/effect/blob/effect%403.22.1/packages/effect/src/Scope.ts)
- [v4 migration and `unstable` compatibility policy at the rechecked commit](https://github.com/Effect-TS/effect/blob/9761c3c4787b3815346c1b650d8984efec8f1051/MIGRATION.md)
- [Unstable v4 Workflow source at the rechecked commit](https://github.com/Effect-TS/effect/blob/9761c3c4787b3815346c1b650d8984efec8f1051/packages/effect/src/unstable/workflow/Workflow.ts)
- [Unstable v4 Activity source at the rechecked commit](https://github.com/Effect-TS/effect/blob/9761c3c4787b3815346c1b650d8984efec8f1051/packages/effect/src/unstable/workflow/Activity.ts)

### Mastra sources

- [Workflow overview](https://mastra.ai/docs/workflows/overview)
- [Workflow snapshots](https://mastra.ai/docs/workflows/snapshots)
- [Suspend and resume](https://mastra.ai/docs/workflows/suspend-and-resume)
- [Evaluation overview](https://mastra.ai/docs/evals/overview)
- [Official repository and licensing boundary](https://github.com/mastra-ai/mastra)

### OpenAI Agents SDK sources

- [Agents SDK overview](https://developers.openai.com/api/docs/guides/agents)
- [Running agents and conversation-state strategies](https://developers.openai.com/api/docs/guides/agents/running-agents)
- [Multi-agent orchestration](https://developers.openai.com/api/docs/guides/agents/orchestration)
- [Guardrails and approvals](https://developers.openai.com/api/docs/guides/agents/guardrails-approvals)
- [Results and state](https://developers.openai.com/api/docs/guides/agents/results)

## Local synthesis

**PROPOSED — mechanism selection.** A future bounded control slice should
reuse the shared pattern, not any one product API: deterministic control,
explicit versioned history, durable operation records where durability is in
scope, I/O behind typed ports, idempotency identities, reconciliation for
unknown outcomes, and an independent completion boundary.

**PROPOSED — smallest TypeScript direction.** The next bounded experiment may
be an Effect v3.22.1 control vertical slice with schema-decoded values, typed
errors, exact port descriptors, finite retry/wait/concurrency budgets, and one
explicit composition root. Any such slice would remain a `PROPOSED`
experiment, not durable-runtime evidence. This direction does not authorize a
plugin ecosystem, universal scheduler, broad runtime framework, or v4
migration.

**PROPOSED — exactly-once vocabulary.** A future local store may claim only
the atomic local control transition and receipt boundary that a named fixture
and receipt validate. A simulated Layer or external service must not inherit
that claim. Unknown outcomes route to query/reconciliation before retry or
terminal state.

**PROPOSED — versioning gate.** A future real adapter profile should pin its
workflow version, state schema version, resolver version, Effect major and
package version, and adapter contract. Recovery tests should cross an actual
deployment upgrade before in-flight compatibility becomes a claim.

**PROPOSED — comparator role.** LangGraph.js, Mastra, and the OpenAI Agents SDK
are useful API and fault-fixture comparators, not automatic dependencies or
evidence that local conformance, recovery, or completion authority is correct.

## What remains unestablished

**ACCEPTED — evidence boundary.** An official-source review cannot demonstrate
local conformance, durability, performance, security, external safety,
comparative agent efficacy, or engine completeness. A local claim can move to
`MEASURED` only through a named command, frozen fixture, environment, and
receipt. The repository engine verdict remains `defer`.
