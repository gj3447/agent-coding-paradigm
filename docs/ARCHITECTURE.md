# Architecture

> Status: M0 BOUNDARY CONTRACT PRESENT / NOT IMPLEMENTED

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
  -> LogicFixpoint + EligibilityVerdict[]
  -> StableProposalBatch
  -> H policy/capability/approval gate
  -> EffectIntent[] | Rejection[]
  -> EffectAttempt -> ActionReceipt
  -> AcceptedEvent
```

The commit boundary atomically accepts state/events plus effect intent/outbox metadata. Effect execution happens after that boundary.

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
  -> Transition(next_state, base_fact_deltas, effect_proposals, diagnostics)

solve_L(rule_set_version, materialization, fact_deltas, logical_time)
  -> FixpointResult(derived_deltas, eligibility_verdicts, conflicts, provenance)

propagate_R(dataflow_version, derived_deltas, frontier, demand)
  -> StableProposalBatch(effect_proposals, eligibility_verdicts, invalidations)

authorize(stable_proposal_batch, policy_snapshot, capability, approval?)
  -> EffectIntent | Rejection

execute_effect_shell(authorized_effect)
  -> ActionReceipt | UnknownOutcome
```

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
