# Harness Contract

> Status: PROPOSED / L_RT TARGET / NO EXECUTABLE EVIDENCE YET

## Tier

The core is an `L_RT` application runtime. `L_IDE` may provide local developer integration and `L_MC` may later provide a hosted control plane. Tier adapters cannot weaken core evidence or effect rules.

## Inform, Constrain, Verify, Correct

| Lens | Required evidence for a mature instance |
|---|---|
| Inform | versioned F/L/R semantics; Observation/Event/Fact/Goal/Command/Effect/Receipt distinctions; rule, provenance, time, authority, platform, and resolved-composition manifests |
| Constrain | pure-core/effect-shell boundary; typed FSM; hard budgets; bounded queues; no-progress cutoff; fenced runner; exact-hash approval; durable outbox/effect ledger |
| Verify | Scenario + Driver + Probe + Oracle + Gate; production/harness composition identity; property/state-machine tests; independent verifier; causal and platform receipts |
| Correct | typed failures; bounded retry/correction; checkpoint migration; unknown-outcome reconciliation; duplicate suppression; deferred interrupts; residual-evidence handoff |

Inform/Constrain/Verify/Correct are diagnostic lenses inside a harness instance. They do not define a separate harness tier.

## Generic control FSM

```text
INGEST
  -> REDUCE_F
  -> SOLVE_L
  -> PROPAGATE_R
  -> PLAN_EFFECTS
  -> WAIT_APPROVAL?
  -> COMMIT_INTENT
  -> EXECUTE
  -> RECONCILE
  -> INGEST_RESULT
  -> VERIFY_COMPLETION
  -> CONTINUE | TERMINAL
```

Minimum typed terminal outcomes:

```text
SUCCEEDED
FAILED_PERMANENT
RETRY_EXHAUSTED
BUDGET_EXHAUSTED
TIMED_OUT
CANCELLED
SUSPENDED
POLICY_BLOCKED
APPROVAL_REJECTED
APPROVAL_EXPIRED
NO_PROGRESS
RULE_CONFLICT
DEADLOCK
CHECKPOINT_CORRUPT
CHECKPOINT_INCOMPATIBLE
EFFECT_OUTCOME_UNKNOWN
```

## Effect ledger

```text
PLANNED
  -> INTENT_COMMITTED
  -> DISPATCHED
  -> RESULT_RECORDED

DISPATCHED
  -> OUTCOME_UNKNOWN
  -> RECONCILED
  -> RESULT_RECORDED
```

Approval consumption, intent/outbox commit, budget reservation, and checkpoint sequence advancement belong to one transaction boundary. External success followed by a crash before receipt recording must enter reconciliation, not blind retry.

## Checkpoint payload

A compatible checkpoint includes:

- F state hash and accepted-event cursor;
- L facts, rules, derivations, conflicts, and rule-set version;
- R ready queue, dependency index, timers, watermarks/frontier, demand, and backpressure state;
- H budgets, attempts, deadlines, approvals, outbox/effect ledger, and evaluator state;
- workflow/state/rule/graph/tool/model/oracle/gate/composition version envelope;
- monotonic sequence, checksum, runner lease generation, and fencing token.

## Strong completion predicate

```text
DONE(change, profile) :=
  Pure
  AND Contract
  AND Flow
  AND Launcher
  AND Platform
  AND Regression
  AND reachable_in_resolved_production_graph(change)
  AND production_graph_sha == harness_graph_sha
       modulo approved adapter substitutions
  AND required causal trace reaches a terminal receipt
  AND every effect binds goal, authority, idempotency key, attempt, and result
  AND no required effect remains UNKNOWN or unreconciled
  AND every high-risk effect has an exact, valid, one-time approval
  AND budgets and invariants hold
  AND every required target is PASS or an explicit unexpired waiver
  AND an independent verifier signs the closure receipt
```

`NOT_RUN`, import success, unit green, source-substring presence, model confidence, trace export, or harness-only reachability cannot satisfy `DONE`.

## Current evidence score

| Lens | Score | Current evidence |
|---|---:|---|
| Inform | 2/3 | versioned proposal documents exist; executable schemas and resolved graphs do not |
| Constrain | 0/3 | no runtime enforces the boundaries or FSM |
| Verify | 0/3 | no target-repo mechanics test or platform receipt exists |
| Correct | 0/3 | no observed recovery, reconciliation, or bounded correction run exists |

This is evidence absence, not a negative efficacy verdict.
