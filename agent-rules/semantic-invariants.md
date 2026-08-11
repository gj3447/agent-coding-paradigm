# FLR-H semantic invariants

> Rule source for the `semantic_change` and `evidence_change` routes. These are
> repository invariants, not efficacy claims.

- `RT1` — Keep `decide(snapshot, accepted_event)` deterministic and effect-free.
- `RT2` — Represent state change as accepted events or fact deltas; represent external work as effect intents.
- `RT3` — H owns continuation, runtime budgets, approval consumption, checkpointing, effect dispatch, reconciliation, and terminal state.
- `RT4` — L owns explicit rule and conflict semantics; R must not react to an unstable half-fixpoint.
- `RT5` — Every runtime queue is bounded and every runtime wait has timeout/cancellation behavior.
- `RT6` — Duplicate identity with different intent is a conflict, not a retry.
- `RT7` — Trace data is an observation projection, not truth, authority, or completion proof.
- `RT8` — Production and harness share one resolved composition root and may differ only by enumerated port-compatible adapters.
- `RT9` — A producer cannot be the sole verifier of its own success.
- `RT10` — Unknown effect outcome routes to reconciliation before retry or terminal state.
