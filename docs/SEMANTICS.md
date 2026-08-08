# FLR-H Execution Semantics v0

> Status: PROPOSED / NOT CANON / NOT IMPLEMENTED

## Boundary types

```text
type LogicalTime
type Frontier = Antichain<LogicalTime>
type RuleSetVersion
type DataflowVersion
type SchemaVersion
type CauseId
type DerivationId
type Weight = Int64

AcceptedEvent<E> = {
  payload: E,
  occurred_at: EventTime,
  received_at: ProcessingTime,
  logical_time: LogicalTime,
  correlation_id: Id,
  causation_id: CauseId?,
  idempotency_key: Id,
  schema_version: SchemaVersion
}

FactDelta<F> = {
  tuple: F,
  time: LogicalTime,
  diff: Weight,
  derivation: DerivationId,
  provenance_delta: ProvenanceExpr,
  rule_set_version: RuleSetVersion
}

EffectIntent<Eff, Cap> = {
  effect: Eff,
  capability: Cap,
  cause: CauseId,
  idempotency_key: Id,
  preconditions: PredicateSet
}
```

## F — functional semantics

`step_F(snapshot, event)` has no ambient effects. Clock, randomness, filesystem, network, credentials, model responses, and tool results enter as recorded inputs. Identical snapshot, event, and version inputs must yield byte-stable canonical transition output.

F may emit an effect intent; it may not execute the effect. It may reject malformed or incompatible inputs with a typed reason and no mutation.

## L — logic semantics

The v0 core uses:

- stratified negation;
- semi-naive least-fixpoint evaluation within a stratum;
- explicit four-valued evidence state: `NEITHER`, `TRUE_ONLY`, `FALSE_ONLY`, `BOTH`;
- derivation counts or equivalent support tracking;
- qualified provenance that changes with each signed delta;
- explicit conflict results instead of arbitrary rule order;
- versioned rule bundles and deterministic worklist ordering.

Negative recursion is outside the v0 core. A Well-Founded Semantics profile may be promoted only when a real task corpus requires it and conformance fixtures specify every truth state.

Retraction removes a support derivation, not blindly the derived tuple. If `a -> c` and `b -> c`, retracting `a` must retain `c` through `b`. The final support removal retracts `c` and its affected reverse closure.

## R — reactive semantics

R consumes versioned signed deltas shaped as `(tuple, logical_time, diff)`. Positive weights add support; negative weights retract support. R owns dependency readiness, invalidation, timer/watermark inputs, demand, bounded queues, and backpressure policy.

R publishes one stable reaction batch only after the frontier passes the logical epoch. No irreversible effect may observe an intermediate half-fixpoint. A late event follows an explicit correction, retraction, rejection, or compensation policy.

Continuous FRP `Behavior` values are not required in the core. They belong in UI/sensor adapters when a task needs continuous time-varying values.

## H — control semantics

H owns continuation and real-world closure. It decides when accepted transitions commit, when an authorized intent is dispatched, how an unknown outcome is reconciled, and whether evidence satisfies a terminal predicate.

Model output may propose goals, commands, facts, rules, or diagnostics. It cannot directly commit authoritative state, mint capabilities, or sign terminal success.

## Atomic epoch protocol

```text
accepted event at epoch t
  -> pure F transition
  -> base FactDelta(+/-)
  -> L semi-naive fixpoint at t
  -> frontier passes t
  -> R publishes one stable reaction batch
  -> L authorization
  -> H atomically commits state/events + outbox intent
  -> external effect attempt
  -> durable receipt or unknown outcome
  -> reconciliation
  -> receipt re-enters as accepted event at t+1
```

Signed delta is a calculation retraction. It is not automatic rollback of an already executed external mutation. External reversal is a separate compensating effect with its own authorization and receipt.

## Version envelope

Every resumable run pins at least:

- workflow and state schema versions;
- event and graph schema versions;
- rule-set and dataflow versions;
- tool, model, oracle, and gate versions;
- resolver and composition profile digests;
- canonicalization algorithm and media type.

Mismatch yields an explicit migration or `CHECKPOINT_INCOMPATIBLE`; it never silently resumes.
