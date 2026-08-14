# LangGraph.js synthetic consumer

`PROPOSED` — This repository-local, unpublished TypeScript package is one executable
public-synthetic FLR-H consumer. It tests a narrow integration shape; it is not
the repository engine, a production adapter, or evidence that FLR-H is better
than LangGraph.

## Ownership

| Layer | Role in this slice | Does not own |
|---|---|---|
| LangGraph.js `1.4.9` | typed state graph, ordered nodes, checkpoint cursor, bounded node invocation, and `interrupt`/resume | approval authentication, global budgets, external-effect truth, or completion proof |
| FLR-H H policy | intent admission, approval binding/deadline/nonce consumption, one dispatch, unknown-to-reconciliation routing, verifier consumption, terminal state | model inference, human-identity authentication, or destination I/O |
| Effect `3.22.1` | lazy port programs, typed port failures, per-call timeout, caller cancellation | a second agent loop or retry schedule |
| MCP client `2.0.0` | optional remote `apply`/`query` transport with fixed tool names, a pinned modern protocol, and schema-decoded structured output | arbitrary tool selection, automatic continuation, or success self-attestation |
| Neo4j KG MCP port | one fixed `ontology_fulltext` read query, explicit `public-research` scope, semantic-label projection, and provenance receipt | raw/model-generated Cypher, write authority, or truth |
| Neo4j activation contract | one repository-pinned two-row plan, fixed bounded Cypher, schema and UID-trigger preconditions, exact readback, and rollback proposal verification | Neo4j transport, credentials, schema/write authority, exclusive-writer fencing, or an ordered atomic executor receipt |
| LangChain OpenAI `1.5.6` / OpenAI SDK `6.49.0` | one tool-free strict structured-output call pinned to `gpt-5.4-mini-2026-03-17`, with SDK retries disabled | the outer loop, approval, action dispatch, verification, or terminal state |
| read-only verifier | independently observes the local artifact and checks its receipt | terminal-state ownership |

The package uses `@langchain/openai`, backed by the exact pinned OpenAI SDK, as
one bounded model node. It intentionally does not install LangChain's
`createAgent` meta-package or the OpenAI Agents SDK: either would introduce a
second model/tool loop competing with the explicit LangGraph/H controller.

Official role references:

- [LangChain overview](https://docs.langchain.com/oss/javascript/langchain/overview)
- [LangGraph overview](https://docs.langchain.com/oss/javascript/langgraph/overview)
- [LangGraph interrupts](https://docs.langchain.com/oss/javascript/langgraph/interrupts)
- [LangChain ChatOpenAI structured output](https://docs.langchain.com/oss/javascript/integrations/chat/openai)
- [OpenAI GPT-5.4 mini model snapshot/support](https://developers.openai.com/api/docs/models/gpt-5.4-mini)
- [Effect v3 introduction](https://effect.website/docs/v3/getting-started/introduction/)
- [MCP TypeScript v2 client](https://ts.sdk.modelcontextprotocol.io/v2/get-started/first-client.html)
- [Neo4j parameterized queries](https://neo4j.com/docs/javascript-manual/current/query-simple/)

## Agent Coding Paradigm skeleton

```text
unknown request
  -> repository-owned public-research manifest
       -> pure offline admission + canonical dry-run receipt
       -> no Neo4j write, model call, or model-context admission
  -> LangGraph retrieve_knowledge
       -> Effect -> fixed read_neo4j_cypher MCP call
       -> exact manifest ID/content/source/revision/digest checks
  -> LangGraph draft_plan
       -> one tool-free LangChain ChatOpenAI structured call
       -> strict schema + retrieved-evidence citation checks
  -> PROPOSED plan + deterministic effect intent
  -> existing H consumer
       -> required human approval
       -> effect dispatch / unknown reconciliation
       -> independent verification
       -> H terminal close
```

`createAgentCodingParadigm()` exposes only `propose()`. The compiled graph,
model client, KG query text, and checkpoint controls are not caller surfaces.
The resulting model plan is a candidate: `toSyntheticRunInput()` always maps it
to an approval-required H input, and only the existing verifier-bound H path may
produce `SUCCEEDED`.

`McpNeo4jKnowledgeGraphPort` accepts only a caller created by
`createControlledMcpClient()`. It always invokes `read_neo4j_cypher` with one
repository-owned query. Task text is a Cypher parameter, never query syntax.
Only rows with the exact `visibilityScope: "public-research"` marker and an
evidence ID admitted by the repository-owned manifest may enter model context.
The adapter recompiles the manifest rather than trusting a supplied receipt and
requires its projection identity and manifest digest to match the immutable
`REPOSITORY_OWNED_PUBLIC_RESEARCH_MANIFEST_PIN`; callers cannot replace that
pin. It passes only admitted IDs as query parameters and exact-compares title,
summary, semantic labels, HTTPS source, revision, and content digest. Generic
`public: true`, alternate scope fields, `elementId`, unknown revisions, and
internal `nodeRef` values are not fallbacks. KG strings are user data described
as untrusted evidence; they never become system instructions.

`compilePublicResearchProjection()` is the pure definition compiler;
`compileRepositoryOwnedPublicResearchProjection()` additionally enforces the
independent repository pin and is the only compiler used by the runtime and
dry-run CLI. The declared aggregate byte limit covers the complete returned
projection, including sources and entries. The checked-in synthetic manifest
and golden receipt prove only deterministic definition processing. Its receipt
fixes `liveNeo4jReadCount=0`,
`liveNeo4jWriteCount=0`, `modelCallCount=0`, and
`modelContextAdmission=false`; it is not an activation token.

## Public-research activation contract

`PROPOSED` — `compilePublicResearchActivationPlan()` converts only the exact
two-entry repository-owned manifest into a deeply frozen activation plan. The
independent `REPOSITORY_OWNED_PUBLIC_RESEARCH_ACTIVATION_PLAN_PIN` binds the
manifest, projection, plan, and six fixed query digests. Its current plan digest
is
`sha256:272177a97351479096ce13e5ff7469b90b49f83ac3b26ce09fd992682dfa45dd`.
Recomputing a digest after changing a row does not make a caller-supplied plan
admissible.

The contract requires an existing online Neo4j node-property uniqueness
constraint and its backing range index for `Concept(evidenceId)`. It also binds
a read-only preflight profile for one installed, unpaused
`t_uid_forward_gate_v3` `afterAsync` trigger. The fixed apply query checks both
global `evidenceId` and `uid` ownership, then uses only a static `Concept`
`MERGE`. `Concept` and `Technology` remain semantic values in the
`semanticLabels` property; `Technology` is not added as a physical label. A
separate global identity readback requires the exact 17-property map, the sole
physical `Concept` label, and zero relationships for each pinned row. A writer
summary alone cannot produce even the `PROPOSED` activation receipt.

`verifyPublicResearchActivation()` is a pure verifier over supplied, strictly
decoded observations. Its receipt remains `PROPOSED`; counter fields supplied
to the verifier do not by themselves prove a mutation or completion.

No live Neo4j observation is part of this package boundary. Any external
activation observation must be recorded and reviewed as a separate evidence
artifact; it cannot promote this `PROPOSED` integration or serve as an ordered,
atomic executor receipt merely because it reuses the same fixture and query
definitions.

The evidence-ID and UID checks are preflight observations, not a transactionally
closed identity reservation. Without an exclusive or fenced writer they retain
a time-of-check/time-of-use race. The admitted UID trigger is `afterAsync`, so a
node can be observed before its UID envelope is complete and trigger delay or
failure can leave partial state that requires reconciliation. The final
readback verifies the two rows only; it is not a proof of global UID uniqueness.

Rollback is deliberately narrower than transaction reversal. It proposes
deleting only identities reported as newly created by the bound activation
receipt, and only while their complete rows, exact labels, and zero-relationship
state remain unchanged. It uses plain `DELETE`, never `DETACH DELETE`, and
requires an independent absence readback. A zero-created activation produces a
zero-I/O rollback result. `rollbackProposalDigest` is a content binding with
`rollbackProposalIsAuthorization=false`: an external trusted coordinator must
authenticate the stored activation receipt and authorize any delete. Changed
or relationship-bound rows fail closed; the contract does not remove schema
objects, reverse concurrent work, or guarantee rollback or external
exactly-once behavior. Exact-byte comparison also does not close an ABA case in
which a row is removed and recreated with the same bytes; authenticated receipt
provenance, delete authority, and destination-side fencing remain required. No
rollback was executed in the live observation.

`createLangChainOpenAiPlanningPort()` accepts only the exact
`gpt-5.4-mini-2026-03-17` snapshot and uses strict Zod structured output,
`maxRetries: 0`, one graph attempt, a bounded wall-clock timeout, and caller
cancellation. A mocked transport fixture checks that the outbound Responses
request has JSON-schema output, no tools, and only one HTTP attempt. The port
sets no prompt-token ceiling and never truncates or rejects required context
based on a token count; call, record, graph-step, and wall-time bounds remain
runtime safety controls.

The reusable assembly point is deliberately small. The application supplies
the MCP transport and credential explicitly; neither is read from ambient state:

```ts
const mcp = createControlledMcpClient({ name: "agent-coding", version: "1" });
await mcp.connect(transport, {
  signal: AbortSignal.timeout(5_000),
  timeoutMs: 5_000,
});

const paradigm = createAgentCodingParadigm({
  knowledge: new McpNeo4jKnowledgeGraphPort({
    caller: mcp.caller,
    componentId: "knowledge:neo4j-public",
    database: "neo4j",
    requestTimeoutMs: 5_000,
    projectionManifest: publicResearchManifest,
  }),
  planner: createLangChainOpenAiPlanningPort({
    componentId: "planner:openai",
    model: OPENAI_PLANNING_MODEL,
    apiKey,
    requestTimeoutMs: 30_000,
  }),
  limits: { maxConcurrentRuns: 4, runRecordCapacity: 128 },
});

const proposal = await paradigm.propose(input, { signal });
// proposal is still PROPOSED; map it into H and obtain exact approval next.
```

## Executed path

```text
decode unknown input
  -> decide duplicate/conflict       (pure)
  -> derive headroom eligibility     (pure)
  -> stabilize + commit intent       (pure state updates)
  -> optional LangGraph interrupt    (intent digest + checkpoint nonce)
  -> trusted-clock deadline check    (no effect on stale approval)
  -> one Effect-wrapped apply        (external boundary)
       -> unknown: one read-only query, never blind re-apply
       -> unresolved: human reconciliation interrupt
  -> independent verification
  -> H terminal close
```

`LocalArtifactEffectPort` performs actual temporary local filesystem I/O. Its
unknown-after-write case creates one artifact, loses the acknowledgement, then
queries without a second write. `McpEffectPort` is a provider-neutral remote
port: it uses only configured `applyToolName` and `queryToolName`, validates
only `structuredContent`, binds a success receipt to the submitted intent, and
maps missing/invalid/error results to `unknown`.

Use `createControlledMcpClient()` for real clients. It pins the exact modern
`2026-07-28` protocol and constructs MCP v2 with
`inputRequired.autoFulfill=false`; every tool call also sets
`allowInputRequired=false`, a bounded timeout, a bounded whole-flow timeout,
and caller cancellation. This keeps continuation and approval in H instead of
letting the MCP SDK silently perform its default multi-round-trip loop. The
wrapper exposes only `connect`, `close`, and an opaque caller—not the raw client
or handler-registration APIs. Real in-memory protocol fixtures reject legacy
or unsupported negotiation, caller-supplied prior state, and transports with a
pre-existing unverified session before `tools/call`; they also prove that
`input_required` does not trigger an automatic second call. The raw-caller seam
used by tests is not exported from the package entry point.

`createAgentCodingParadigm()` defaults to at most eight concurrent proposal
runs and 128 process-local replay/failure records; callers may lower those
bounds explicitly. A full concurrency slot fails fast, the oldest record is
evicted at capacity, and a failed logical run is not implicitly retried. These
are runtime resource bounds, not prompt-token limits or durable deduplication.

The H consumer separately defaults to eight process-local concurrent graph
invocations, with an explicit maximum of 64. The same bound covers run, resume,
and cancellation-recovery calls; it is admission control, not cross-process
fencing.

The caller supplies one `runId`; the wrapper derives the internal LangGraph
thread identity from it. The raw compiled graph and checkpointer are not part
of the consumer surface, so callers cannot bypass run-identity conflict,
single-invocation fencing, typed resume checks, or H terminal closure. If caller
cancellation lands after dispatch has begun but before its result is
checkpointed, `recoverAfterCancellation()` records an unknown attempt and runs
the read-only query path without applying again. The same method may repeat a
cancelled read-only query or independent verification, but never dispatch.

`createSyntheticConsumer()` requires an explicit `TrustedClock`; there is no
ambient clock fallback. `systemTrustedClock` is the opt-in wall-clock adapter
used by executable runners, while deterministic fixtures inject a fixed clock.
H validates every reading as a finite nonnegative integer, performs no timer or
polling loop, and treats the exact deadline as expired. It checks once before
resume, again inside the resumed approval node, and immediately before apply.
An expired approval is consumed as `TIMED_OUT` without dispatch.

The approval interrupt carries the committed `intentDigest` and a deterministic
checkpoint nonce derived from the run, intent digest, and deadline. Resume must
return both values exactly. A successful, rejected, cancelled, or timed-out
resume advances the checkpoint, so the nonce cannot be consumed twice within
this process-local H instance. The nonce is a stale-content binding, not a
secret or proof of a human approver's identity.

## Verify

Requirements are pinned exactly in `package.json` and `pnpm-lock.yaml`.

```bash
pnpm install --frozen-lockfile --ignore-scripts
pnpm ignored-builds
pnpm verify
pnpm run kg-dry-run:fixture
pnpm run agent-smoke
pnpm exec tsx src/runner.ts --variant variant:happy-path
pnpm exec tsx src/runner.ts --variant variant:cancel-while-unknown
```

The tests cover all six variants from the repository's public synthetic
consumer corpus plus Effect laziness, timeout/cancellation, producer/verifier
separation, MCP allowlisting, structured-output rejection, receipt binding,
stable canonicalization, run-identity conflicts, closed graph authority,
phase-checked resume, approval deadline/digest/one-time-nonce binding,
apply-to-query recovery without apply retry, fixed-Cypher parameterization,
manifest-bound public evidence, offline dry-run golden replay, KG
prompt-injection isolation, provenance/citation binding, strict model authority
rejection, approval preservation, proposal replay, independently pinned
activation planning, online uniqueness preconditions, exact physical readback,
UID-trigger profile binding, global evidence-ID/UID conflict rejection, and
fail-closed rollback proposals. The current focused suite contains 91 tests,
including 12 activation-contract tests.

`skipLibCheck` is enabled because the exact LangChain/LangGraph declarations
currently conflict with `exactOptionalPropertyTypes`; all package source and
tests still compile under the remaining strict options.

## Explicit nonclaims

- The default `MemorySaver` is process memory, not restart durability and not
  completion evidence. It is created privately per consumer; a shared or remote
  checkpointer is not exposed by this slice.
- Same-run calls are serialized only inside one consumer instance. Multiple
  processes or consumer instances require a durable fenced runner; this slice
  does not claim one.
- `recoverAfterCancellation()` is a process-local quarantine/reconciliation path,
  not arbitrary crash recovery. Restarting the process loses `MemorySaver`.
- The H wrapper enforces its checkpoint-scoped approval binding and deadline,
  but does not authenticate a human identity or organization. That remains an
  adapter-level authority concern.
- A successful local artifact or MCP receipt is not external exactly-once.
- The injected verifier is structurally separate, but arbitrary caller code
  provenance or behavioral independence is not proven by JavaScript identity.
- `@langchain/openai` and its pinned OpenAI SDK are installed and the exact
  request shape is mock-transport tested, but no real provider call or
  credential is part of the gate.
- The Neo4j MCP adapter is covered by a controlled simulated caller. The
  manifest and receipt contain only original synthetic summaries. The gate does
  not prove the runtime read adapter against a deployed transport, Neo4j
  credential policy, data freshness, public-data curation, tenant isolation, or
  any specific infrastructure deployment.
- The checked-in live activation evidence is one bounded observation, not an
  immutable or ordered executor receipt. The first creating call returned only
  connector mutation metadata; exact row state was established later. The
  final-query write returned an empty connector result, while its `0/0/2`
  compatibility counters came from a separate read-only inspection. The final
  `PROPOSED` compatibility receipt is therefore not proof of either write's
  exact mutation result or first-write atomicity.
- Preflight does not close concurrent-writer TOCTOU. The admitted UID trigger is
  asynchronous, so trigger delay/failure and partial-state races remain. No
  global UID-uniqueness claim follows.
- No rollback was authorized or executed. A non-authorizing rollback proposal
  digest cannot substitute for authenticated receipt provenance, delete
  authority, fencing, or ABA-safe destination semantics.
- KG content and model output are candidate evidence, not truth, authority, or
  completion proof.
- Passing this package does not promote the deferred engine verdict.
