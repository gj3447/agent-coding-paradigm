# Architecture

> Status: SEPARATE M1 PURE-F + M2 STRATIFIED-L + M3 SCALAR-FRONTIER-R REFERENCE MECHANICS MEASURED / DIRECT L-R AND H NOT IMPLEMENTED

## System boundary

FLR-H is proposed as a narrow application-runtime mechanism, not a complete agent product. Domain goals, product policy, model selection, UI, cloud tenancy, and editor integration remain outside the core.

The target tier is `L_RT`:

- `L_IDE`: optional CLI/editor adapter and developer feedback surface;
- `L_RT`: deterministic kernel, durable loop, effects, graphs, and verifier;
- `L_MC`: optional hosted control plane, tenancy, quotas, and managed credentials.

MCP or another tool protocol may connect tiers. It is an adapter, not a fourth tier.

## Five planes

| Plane | Owns | Must not own |
|---|---|---|
| Domain | goals, commands, facts, rules, policies | durable scheduling and raw infrastructure I/O |
| Data | immutable events, graph revisions, schemas, receipts | hidden mutable truth |
| State | accepted snapshot and derived materializations | ambient clocks or network state |
| Control | continuation, order, budget, retry, approval, terminal transitions | domain truth invented by the runner |
| Effects | external adapters, idempotency, reconciliation | direct mutation from F/L/R code |

## Narrow-waist protocol

```text
Command or AcceptedEvent
  -> Decision: DomainEvent[] | Rejection
  -> Evolution: Snapshot x DomainEvent -> Snapshot
  -> FactDelta[] + EffectProposal[]
  -> LogicFixpoint
  -> explicit supplied EligibilityVerdict[] seam
  -> StableProposalBatch
  -> H policy/capability/approval gate
  -> EffectIntent[] | Rejection[]
  -> EffectAttempt -> ActionReceipt
  -> AcceptedEvent
```

This is the proposed integrated protocol. M2 ends at `LogicFixpoint`, and the direct L-to-R eligibility seam remains unresolved and unimplemented. A standalone bounded M3 scalar-frontier reference is measured separately; it accepts caller-supplied verdicts rather than implementing that direct seam. The integrated boundaries after M3, including the future H commit boundary that would atomically accept state/events plus effect intent/outbox metadata, remain unimplemented. Effect execution would happen after that boundary.

## Inner and outer loops

### Inner stabilization loop

```text
F transition -> base deltas -> L semi-naive fixpoint -> frontier -> R batch
```

It terminates when the chosen logical epoch is stable, not when a work queue happens to be empty for an instant.

### Outer durable loop

```text
INGEST
  -> STABILIZE(F -> L -> R frontier)
  -> PLAN_EFFECTS
  -> WAIT_APPROVAL?
  -> COMMIT_INTENT
  -> EXECUTE
  -> RECONCILE
  -> HUMAN_RECONCILIATION? | HONOR_PENDING_INTERRUPT
  -> INGEST(receipt)
  -> VERIFY_COMPLETION
  -> CONTINUE | TERMINAL
```

The outer loop terminates only with a typed outcome and evidence closure.

[`run-fsm.v1.json`](../spec/run-fsm.v1.json) is the sole authoritative outer transition table. [`loop-contract.v1.json`](../spec/loop-contract.v1.json) is a digest-bound operational profile for budgets, checkpoints, effects, and replay; it does not define a second lifecycle. This diagram is explanatory.

## Core interfaces

```text
step_F(snapshot, accepted_event)
  -> FTransition(next_snapshot, fact_deltas, effect_proposals) | FRejection

solve_l(prior_materialization, rule_bundle, fact_delta_inputs, logical_time)
  -> LFixpointResult(next_materialization, derived_fact_deltas) | LRejection

step_r(prior_state, profile, command)
  -> RTransition(next_state, published_batches, backpressure) | RRejection

authorize(stable_proposal_batch, policy_snapshot, capability, approval?)
  -> EffectIntent | Rejection

execute_effect_shell(authorized_effect)
  -> ActionReceipt | UnknownOutcome
```

M1 realizes `step_F` for the version-pinned `flrh.m1.observation-recorded/1` event. The public Python waist is [`step_f`](../src/flrh_kernel/kernel.py); its output schemas are [`m1-kernel.v1.schema.json`](../spec/schema/m1-kernel.v1.schema.json).

M2 separately realizes `solve_l` for one ground/propositional stratified rule profile. It rebuilds a complete derived materialization from the active base ledger on every accepted invocation, exposes four-valued state/conflicts and provenance inside that materialization, and emits the net derived deltas. It does not construct or interpret `EligibilityVerdict`. M3 separately realizes the measured bounded supplied-value R contract: it transports exact proposals and caller-supplied verdicts but neither derives nor validates eligibility. The M1/M2 goldens are seam provenance, not measured direct integration. None of these slices owns durable state, a handler registry, adapter, authority, or execution port; H and the integrated interfaces remain proposed.

## Authority and single writers

- Accepted event/state store: one fenced transactional writer per aggregate/run.
- Logic materialization: derived projection rebuilt from accepted facts, rules, and versions.
- Reactive queue/frontier: owned by the active fenced runner and checkpointed.
- Effect ledger/outbox: mutated atomically with checkpoint sequence and approval consumption.
- Trace store: append-only observation projection; never authoritative for completion.

## Concurrency and backpressure

The pure reducer remains synchronous. Asynchronous boundaries expose demand, capacity, overflow policy, timeout, cancellation, ordering, and deterministic tie-breaking. Parallel work may complete out of order, but publication into an epoch is atomic after frontier stabilization.

## Failure stance

At-least-once delivery is assumed. `OUTCOME_UNKNOWN` never blind-retries. The reconciler first queries the destination using the action digest/idempotency key and records confirmed success, confirmed failure, still unknown, or human-required.

## Security stance

Capabilities authorize effects. Approval binds immutable action content, destination, scope, actor, nonce, expiry, and workflow version. Untrusted model or retrieved content cannot mint authority. Checkpoints, traces, receipts, and graph stores are security boundaries and require redaction/encryption policy.
