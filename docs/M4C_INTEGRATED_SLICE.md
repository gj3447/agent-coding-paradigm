# M4C Bounded Integrated Reference Slice

> Status: **PROPOSED_PENDING_MEASUREMENT**.

M4C is one deterministic application-runtime (`L_RT`) conformance slice. It calls the existing public boundaries in this exact order:

`step_f -> solve_l -> project_lr -> step_r -> project_h_intent -> DurableHarness`

The slice begins from the frozen M1 `observe-with-effect` input, uses a null prior materialization and full-recompute L, waits until every R source frontier is strictly beyond the epoch, grants demand for one stable batch, projects one low-risk authority decision, atomically commits one intent, dispatches through `FakeAdapter`, and independently verifies one exact M0 `ActionReceipt` with no pending outbox row.

## FSM projection

The trace is a projection of `spec/run-fsm.v1.json`, not a rival FSM:

`INIT -> INGEST -> STABILIZE -> PLAN_EFFECTS -> COMMIT_INTENT -> EXECUTE -> RECONCILE -> HONOR_PENDING_INTERRUPT`

The evidence label is `SLICE_CONFORMED`. The slice deliberately stops at `HONOR_PENDING_INTERRUPT`; it does not emit `NO_PENDING_INTERRUPT`, `VERIFIED_COMPLETE`, or `SUCCEEDED`. The durable M4B run remains `active`, so this is not outer completion.

The trace claim is exactly `FSM_CONFORMANCE_PROJECTION_ONLY`, and `outer_reducer_executed` is false. Every trace row is rebuilt from the digest-pinned FSM transition, event authority, guard reads, and required evidence. Only the public M4A control event is marked `PUBLIC_CONTROL_EVENT`; the receipt edge is marked `INDEPENDENT_READ_ONLY_VERIFIER`; the other rows are source requirements, not invented runtime emissions.

## Verification

`scripts/m4c_verifier.py` reconstructs the frozen inputs and independently re-executes every public F, L, LR, R, and H API. A stored result is never trusted as the input to the next stage. It then validates the full M0 `ActionReceipt` schema and bindings, the exact detached M4B consistency report, the source-bound FSM evidence projection, and the outer replay digest. Sixteen behavioral sensitivity cases include adjacent mutations, redigested cross-stage forgeries, deleted stage evidence, a forged crash summary, and a missing stage digest; each must fail at its exact boundary path.

The recovery profile crashes after the fake destination has mutated but before the response is durably recorded. The worker exits with real `os._exit(86)`, leaving SQLite WAL state for a fresh process to reopen at the injected epoch. Recovery must query and reconcile the destination, yielding exactly one apply, one query, one mutation, and one receipt. Both happy and crash modes must be byte-identical across two clean process environments.

The M4B report is detached after the temporary database closes. The verifier establishes its exact shape and lineage consistency, but does not treat that detached object as authenticated proof of a real destination. A later durable validation receipt must freeze the subject, database or verifier-input projection, runtime, and exact CI readback.

## Bounds and nonclaims

The reference profile is singleton-only, admits at most one pending intent, permits at most three attempts, uses `FakeAdapter`, and begins from `prior_materialization = null`. M4A and M4B remain separately proposed.

This evidence is not outer completion, persistent incremental L reuse, general eligibility correctness, multi-effect scheduling, receipt reingestion into F, a real destination safety result, exactly-once delivery, a production runtime, engine promotion, comparative efficacy, or Lakatos progress. Those require separately frozen subjects and independent evidence.
