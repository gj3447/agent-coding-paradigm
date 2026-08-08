# ADR 0001: Defer the engine verdict

- Status: ACCEPTED FOR THIS REPOSITORY
- Date: 2026-08-08
- Decision scope: repository architecture only; not external canon

## Context

The research proposes a reusable deterministic kernel, durable control shell, and graph contracts. However, there is no implementation, current production consumer, durable recovery evidence, or demonstrated need for a shared runtime boundary. Calling the work an engine now would turn an architecture hypothesis into an unsupported product claim.

## Decision

Treat the repository as a specification and mechanics incubator. The initial machine-readable decision is `defer`, not `engine`. Implement only the smallest vertical mechanics slice needed to falsify or support the boundary.

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
- Language selection remains open until M0 constraints are compared.
- Documentation may use “runtime candidate” or “profile”; “engine” must be qualified as deferred/candidate.
- If consumers need incompatible policies or semantics, keep separate modules/adapters and reject engine promotion.
