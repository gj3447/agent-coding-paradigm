# FLR-H Execution Semantics v0

> Status: M1 PURE-F + M2 STRATIFIED-L REFERENCE MECHANICS MEASURED / R-H NOT IMPLEMENTED / NOT EXTERNAL CANON

## Boundary types

```text
type LogicalTime = Int64 where value >= 0
type FrontierV0 = LowWatermark<LogicalTime>
type RuleSetVersion
type DataflowVersion
type SchemaVersion
type CauseId
type DerivationId
type UnitDelta = -1 | +1

AcceptedEvent<E> = {
  payload: E,
  occurred_at: EventTime,
  received_at: ProcessingTime,
  logical_time: LogicalTime,
  correlation_id: Id,
  causation_id: CauseId?,
  idempotency_key: Id,
  versions: VersionEnvelope
}

FactDelta<F> = {
  tuple: F,
  logical_time: LogicalTime,
  diff: UnitDelta,
  derivation_id: DerivationId,
  causation_id: CauseId,
  provenance_delta: ProvenanceExpr,
  rule_set_version: RuleSetVersion
}

EffectProposal<Eff> = {
  proposal_id: Id,
  effect_type: Eff,
  cause_id: CauseId,
  action_digest: Digest,
  destination_digest: Digest,
  goal_id: Id,
  obligation_id: Id,
  correlation_id: Id,
  proposal_dedup_key: Id,
  declared_risk_hint: read_only | reversible | high_risk_external | unknown,
  preconditions: PredicateSet,
  versions: VersionEnvelope
}

EligibilityVerdict = { proposal_id, eligible | ineligible | conflicted, support_derivation_ids }
StableProposalBatch = { epoch, strict_low_watermark, proposal_ids, eligibility_verdict_ids, digest }
EffectIntent<Eff, Cap> = {
  intent_id, proposal_id, batch_id, effect_type: Eff, action_digest,
  cause_id, correlation_id, destination_digest, goal_id, obligation_id,
  capability: Cap, authority_digest, assessed_risk,
  adapter_version, idempotency_key, approval_digest?, approval_required,
  preconditions, versions
}
```

## F — functional semantics

`step_F(snapshot, event)` has no ambient effects. Clock, randomness, filesystem, network, credentials, model responses, and tool results enter as recorded inputs. Identical snapshot, event, and version inputs must yield byte-stable canonical transition output.

F may emit an authority-free effect proposal; it may neither authorize nor execute it. `declared_risk_hint` is untrusted input to H, and `proposal_dedup_key` only deduplicates proposal values. In M1, derivation and proposal identities bind the complete emitted value except their own identity field or fields, preventing distinct bytes from sharing an identity by construction. None of these fields is an approval decision or the final external-effect identity. F may reject malformed or incompatible inputs with a typed reason and no mutation.

The M1 reference realizes that boundary for one versioned observation event and a closed snapshot/transition/rejection vocabulary. It derives one `FactDelta`, zero or one `EffectProposal`, and a fresh snapshot. Transition identity is a digest projection over the individually root-canonicalized next snapshot, deltas, and proposals; this preserves `EffectProposal.preconditions` set semantics without sorting ordered arrays nested in arbitrary payloads. The measured result is limited to the frozen corpus and guarded Python surfaces.

## L — logic semantics

The v0 core uses:

- stratified negation;
- semi-naive least-fixpoint evaluation within a stratum;
- explicit four-valued evidence state: `NEITHER`, `TRUE_ONLY`, `FALSE_ONLY`, `BOTH`;
- derivation-identity support sets with unit `+1/-1` deltas;
- qualified provenance that changes with each signed delta;
- explicit conflict results instead of arbitrary rule order;
- versioned rule bundles and deterministic worklist ordering.

Default negation succeeds when positive support is absent in a completed lower stratum: `NEITHER` and `FALSE_ONLY` pass; `TRUE_ONLY` and `BOTH` fail. Negative recursion is outside the v0 core. A Well-Founded Semantics profile may be promoted only when a real task corpus requires it and conformance fixtures specify every truth state.

Retraction removes a support derivation, not blindly the derived tuple. If `a -> c` and `b -> c`, retracting `a` must retain `c` through `b`. The final support removal retracts `c` and its affected reverse closure.

The M2 reference realizes this boundary for one finite ground/propositional rule profile through `solve_l(prior_materialization, rule_bundle, fact_delta_inputs, logical_time)`. `LFactDeltaInput.polarity` is the object-language sign; nested `FactDelta.diff` is the support-ledger operation. Each accepted invocation applies the stepwise base-ledger update, then performs a bounded semi-naive full rebuild of the complete derived projection and emits its net change from the prior materialization. The independent oracle agreement is semantic evidence, not evidence of persistent incremental reuse or performance.

M2 deliberately emits no `EligibilityVerdict`. Proposal eligibility needs a separately typed, digest-bound query whose ownership at the L/R seam remains proposed.

## R — reactive semantics

R consumes versioned unit deltas shaped as `(tuple, logical_time, diff)` where `diff ∈ {-1,+1}`. `+1` inserts one named derivation support and `-1` retracts that same identity; repeated byte-identical insertion is idempotent, not multiplicity. R owns dependency readiness, invalidation, timer/watermark inputs, demand, bounded queues, and backpressure policy.

R publishes one stable reaction batch only when the v0 scalar low watermark is strictly greater than the logical epoch. No irreversible effect may observe an intermediate half-fixpoint. General partially ordered antichain time is outside v0. A late event follows an explicit correction, retraction, rejection, or compensation policy.

Continuous FRP `Behavior` values are not required in the core. They belong in UI/sensor adapters when a task needs continuous time-varying values.

## H — control semantics

H owns continuation, policy/capability enforcement, intent creation, approval binding, and real-world closure. It independently produces `assessed_risk` and the final effect `idempotency_key`; it must not trust the proposal hint as authority. H decides when accepted transitions commit, when an authorized intent is dispatched, how an unknown outcome is reconciled, and whether evidence satisfies a terminal predicate.

Model output may propose goals, commands, facts, rules, or diagnostics. It cannot directly commit authoritative state, mint capabilities, or sign terminal success.

## Atomic epoch protocol

```text
accepted event at epoch t
  -> pure F transition
  -> base FactDelta(+1/-1) + EffectProposal
  -> L semi-naive full-recompute fixpoint at t
  -> future typed eligibility seam (not implemented by M2)
  -> frontier passes t
  -> R publishes one StableProposalBatch
  -> H policy/capability/approval gate
  -> H atomically commits state/events + EffectIntent/outbox
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

The normative executable tables are [`logic-semantics.v0.json`](../spec/logic-semantics.v0.json), [`protocol.v1.schema.json`](../spec/schema/protocol.v1.schema.json), [`canonicalization.v1.json`](../spec/canonicalization.v1.json), and the bounded M1 and M2 contracts in [`m1-manifest.v1.json`](../spec/m1-manifest.v1.json) and [`m2-manifest.v1.json`](../spec/m2-manifest.v1.json). This prose is a view of those contracts.
