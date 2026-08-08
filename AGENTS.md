# Repository operating contract

## Purpose

This repository is a research incubator for the provisional FLR-H agent runtime profile. Preserve the boundary between sourced mechanism, local synthesis, executable evidence, and efficacy claims.

## Scope

In scope:

- functional transition kernels and explicit effect intents;
- logic programming semantics, fixpoints, conflict, provenance, and retraction;
- incremental/reactive dependency propagation, logical time, frontiers, and backpressure;
- L_RT harness control, durable loops, approvals, checkpoints, effects, reconciliation, and verification;
- typed semantic, dependency, composition, action, trace, provenance, and schema graphs;
- conformance, fault injection, and comparative evaluation.

Out of scope:

- Jaebaeman, planning doctrine, or agent dispatch mythology;
- claims of canon, standardization, originality, or superiority without evidence;
- a single graph model that erases graph-kind-specific semantics;
- hidden I/O, clock, randomness, credentials, or model calls inside the pure kernel;
- exactly-once claims for external systems.

## Claim labels

Use one of these labels on material assertions:

- `HYPOTHESIS`: plausible and falsifiable, not yet implemented;
- `PROPOSED`: specified locally, not an external standard or canon;
- `MEASURED`: backed by a named command, fixture, environment, and receipt;
- `FALSIFIED`: contradicted by a reproducible counterexample;
- `ACCEPTED`: accepted only inside this repository's engineering governance.

Do not upgrade a claim based on prose agreement, import success, a model verdict, or a trace span.

## Architecture invariants

1. Keep `decide(snapshot, accepted_event)` deterministic and effect-free.
2. Represent state change as accepted events or fact deltas; represent external work as effect intents.
3. H owns continuation, budgets, approval consumption, checkpointing, effect dispatch, reconciliation, and terminal state.
4. L owns explicit rule and conflict semantics; R must not react to an unstable half-fixpoint.
5. Every queue is bounded and every wait has timeout/cancellation behavior.
6. Duplicate identity with different intent is a conflict, not a retry.
7. Trace data is an observation projection, not truth, authority, or completion proof.
8. Production and harness share one resolved composition root and may differ only by enumerated port-compatible adapters.
9. A producer cannot be the sole verifier of its own success.
10. Unknown effect outcome routes to reconciliation before retry or terminal state.

## Change protocol

- Update claim/status documents when implementation evidence changes.
- Add a failing conformance or fault fixture before repairing a semantic bug.
- Validate machine-readable contracts and JSON before committing.
- Record exact test commands and outcomes; distinguish simulated adapters from real platform evidence.
- Keep commits scoped. Do not stage unrelated files.
- Do not add a license, make the repository public, publish packages, or create releases without explicit user direction.

## Engine promotion

The repository currently defers an engine verdict. Do not create a broad runtime framework until the promotion gates in `docs/adr/0001-defer-engine-verdict.md` and `spec/engine-decision.v1.json` are met.
