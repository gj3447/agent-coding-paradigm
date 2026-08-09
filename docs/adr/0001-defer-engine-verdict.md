# ADR 0001: Defer the engine verdict

- Status: ACCEPTED FOR THIS REPOSITORY
- Date: 2026-08-08
- Decision scope: repository architecture only; not external canon

## Context

The research proposes a reusable deterministic kernel, durable control shell, and graph contracts. Bounded sibling Python references now exist for pure F and ground stratified L, but there is no integrated F/L/R/H runtime, current production consumer, durable recovery evidence, persistent incremental evaluator, or demonstrated need for a shared runtime boundary. Calling the work an engine now would still turn an architecture hypothesis into an unsupported product claim.

## Decision

Treat the repository as a specification and mechanics incubator. The machine-readable decision remains `defer`, not `engine`. The completed M1 and M2 slices are evidence for two candidate seams, not permission to scaffold the broader framework.

## Candidate boundary

```text
evaluate(snapshot, accepted_event, rule_bundle, dataflow_profile)
  -> stable transition + stable effect proposals | typed rejection
```

The candidate owns deterministic transition, fixpoint, signed-delta stabilization, and typed output. Product policy, model choice, UI, credentials, external effect implementation, and cloud tenancy stay outside.

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
- Python is the M1/M2 reference language only; an eventual engine language remains open pending independent consumers and interoperability evidence.
- Documentation may use “runtime candidate” or “profile”; “engine” must be qualified as deferred/candidate.
- If consumers need incompatible policies or semantics, keep separate modules/adapters and reject engine promotion.
