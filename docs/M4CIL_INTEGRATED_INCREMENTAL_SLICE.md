# M4C-IL Bounded Integrated Incremental Reference Slice

> Status: **PROPOSED_PENDING_MEASUREMENT**.

M4C-IL is an additive application-runtime conformance profile. It replaces the
full-recompute L call in the existing M4C reference path with two public
`step_incremental_l` calls and otherwise preserves the inherited public waist:

`step_f -> step_incremental_l (bootstrap) -> step_incremental_l (reuse) -> project_lr -> step_r -> project_h_intent -> DurableHarness`

The bootstrap prefix applies the frozen accepted event at logical time 1 and
produces an explicit checkpoint. The reuse prefix consumes that exact checkpoint
at logical time 2 with an empty delta batch. The final M2-compatible fixpoint,
not a private candidate object, is the only input to `project_lr`.

## Incremental evidence boundary

The designated reuse prefix requires at least one `candidate_cache_hits` and
exactly zero `executed_candidate_body_evaluations`. Those counters describe
only the candidate schedule. Each public incremental call deliberately performs
two public M2 conformance calls that are excluded from the candidate counters.
They independently validate the prior materialization and compare the candidate
fixpoint byte-for-byte with the frozen M2 result.

This proves real checkpoint handoff and avoided candidate body work on one
bounded no-delta prefix. It makes no performance or reduced-total-runtime claim,
and it makes no persistent L storage claim: the checkpoint is an explicit pure
wire value, not a filesystem or database service.

The local replay schema is a structural envelope around inherited stage objects.
Exact stage semantics come from source-bound public-stage reexecution, not from
pretending that the envelope duplicates every upstream schema.

## Durable effect and crash profile

After LR projection, R waits for the source frontier to advance strictly beyond
the final incremental epoch, publishes one proposal, and M4A authorizes one
low-risk intent. M4B commits that intent and dispatches it through `FakeAdapter`.
The happy profile closes one exact M0 ActionReceipt. The recovery profile kills
the worker with real `os._exit(86)` after the fake destination mutation, opens
fresh durable objects, queries the destination, and reconciles without a second
mutation.

The M4B report embedded in replay evidence is detached after the temporary
database closes. Its verifier proves exact structural and lineage consistency;
it is not authenticated evidence for a real external destination.

## FSM projection and terminal boundary

The source-derived trace is explicitly `FSM_CONFORMANCE_PROJECTION_ONLY`:

`INIT -> INGEST -> STABILIZE -> PLAN_EFFECTS -> COMMIT_INTENT -> EXECUTE -> RECONCILE -> HONOR_PENDING_INTERRUPT`

The profile stops at `HONOR_PENDING_INTERRUPT`, labels only the bounded slice
`SLICE_CONFORMED`, and records `outer_reducer_executed=false`. It does not emit
`VERIFIED_COMPLETE` or `SUCCEEDED`, and the durable run remains active.

## Verification and nonclaims

The independent verifier re-executes every public stage from frozen inputs,
validates the bootstrap-to-reuse checkpoint lineage, binds the exact incremental
fixpoint into LR, checks the ActionReceipt and durable checkpoint lineage, and
reconstructs the seven FSM evidence rows from the pinned source. Happy and crash
replays must be byte-identical across two clean process profiles. Sixteen
redigested adversarial mutations must fail at their exact boundary.

This proposed slice makes no multi-event or multi-effect scheduling claim, no
durable R claim, no real-destination or exactly-once claim, no production
readiness claim, no engine promotion claim, no comparative efficacy claim, and
no Lakatos progress claim.
