# ADR 0001: Defer the engine verdict

- Status: ACCEPTED FOR THIS REPOSITORY
- Evidence status: bounded TypeScript/Effect experiments `PROPOSED`; engine verdict `defer`
- Date: 2026-08-08
- Decision scope: repository architecture only; not external canon

## Context

The research proposes a reusable deterministic kernel, durable control shell,
and graph contracts. Bounded Python references cover pure F, ground stratified
L, supplied-value scalar-frontier R, and a stateless direct L-to-R projection.
The TypeScript package contains bounded Effect-based synthetic experiments.
There is still no real adapter, production consumer, persistent incremental
evaluator, in-flight upgrade trial, two-consumer reuse record, or demonstrated
comparative need for a shared engine boundary.

## Decision

Treat the repository as a specification and mechanics incubator. The
machine-readable decision remains `defer`, not `engine`. A bounded control
slice may exercise one contract through typed ports and simulated Layers; it
is not permission to add a broad plugin framework, claim arbitrary consumer
reuse, durability, or production readiness.

## Candidate boundary

The following is a **PROPOSED future engine boundary**, not a current public
API:

```text
evaluate(snapshot, accepted_event, rule_bundle, dataflow_profile)
  -> stable transition + stable effect proposals | typed rejection
```

That future candidate would own deterministic transition, fixpoint,
signed-delta stabilization, and typed output. Product policy, model choice, UI,
credentials, external effect implementation, and cloud tenancy stay outside.

## Promotion gates

Reconsider an engine verdict only when all frozen gates pass:

1. two named independent consumers use the same narrow-waist contract for three compatible version cycles;
2. a fixed replay corpus produces byte-identical digests in two clean processes and incremental results equal clean recomputation;
3. one fenced writer, checkpoint compatibility, recovery, and effect reconciliation are operational requirements rather than speculation;
4. the M0–M5 mechanics gates pass with durable receipts, including zero duplicate confirmed mutations across the frozen crash matrix;
5. bounded ingress, queue capacity, deadline, backpressure, cancellation, timeout, schema evolution, security capabilities, and observability meet preregistered numeric limits;
6. policy variation is handled outside the mechanism without forking the core;
7. a frozen comparison shows the shared boundary reduces duplicated state/coordination relative to separate modules without increasing fault rate beyond its registered margin.

## Consequences

- No broad plugin framework or service topology is created in the first slice.
- Python remains the measured reference language for M1–M3 and LR. TypeScript/Effect is the bounded experiment direction; an eventual engine language remains open pending independent consumers and interoperability evidence.
- Documentation may use “runtime candidate” or “profile”; “engine” must be qualified as deferred/candidate.
- If consumers need incompatible policies or semantics, keep separate modules/adapters and reject engine promotion.
