# M3 scalar-frontier reactive kernel

> Status: **MEASURED_REFERENCE_CONFORMANCE**. This document records a bounded reference slice; it is not itself the validation receipt.

M3 realizes one pure API:

```text
step_r(prior_state, profile, command) -> RTransition | RRejection
```

The accepted commands are `RApplyDeltaBatch`, `RAdvanceFrontier`, and `RGrantDemand`. An `RValueDelta` carries a source, delivery identity, logical epoch, unit sign, exact dataflow version, and an exact nested M0 `EffectProposal` or `EligibilityVerdict`. M3 does not accept an M2 materialization or infer an eligibility verdict from a fact delta.

## Frontier and atomicity

Each profile declares the complete non-empty source set. Each source has a nullable scalar low watermark; the global low watermark is null until every source has advanced and otherwise equals their minimum. An epoch stabilizes only when the global low watermark is strictly greater than the epoch. Equality is insufficient. A delta behind its named source's current watermark is rejected as late; the global minimum is the stabilization boundary, not the per-source late-event boundary.

A source watermark is caller-asserted progress for that source. M3 validates its identity and monotonicity, not the truth of upstream progress. General antichain time, distributed watermark coordination, and persistent streaming are outside this profile.

All supplied values for a stable epoch move as one ready batch. Demand is counted only in whole batches. Publication order is epoch then canonical bytes. `RPublishedBatch` embeds the exact proposal and verdict values around the ID-only M0 `StableProposalBatch`; their ID sets must agree exactly.

## Supplied verdict boundary

R transports `eligible`, `ineligible`, and `conflicted` verdicts identically. An open epoch may temporarily contain either side alone. When stabilization is attempted, proposals and supplied verdicts must form a total one-to-one relation by `proposal_id` in that epoch, with unique nested `proposal_id` and `verdict_id` identities across its distinct deliveries; missing, orphan, or duplicate relations reject. R does not decide whether the verdict status, supporting derivations, or eligibility reasoning is correct. The batch and embedded arrays include every paired value regardless of status. The M1 proposal golden and M2 support golden are pinned as seam provenance, not evidence of direct M2-to-M3 integration.

Identity uniqueness here is epoch-local. M3 retains no published-history ledger and does not promise lifetime or cross-epoch deduplication of `proposal_id` or `verdict_id`; persistent idempotency and reconciliation remain ingress/H responsibilities.

No object in this slice authorizes or performs an effect. `EffectIntent`, approval, capability, dispatch, retry, compensation, reconciliation, persistence, and receipts remain H-owned.

## Retraction, bounds, and failure

`value_digest` binds only the exact nested value and its kind. `delivery_id` is deterministically derived from source, epoch, dataflow version, value kind, and value digest. An exact repeated `+1` delivery is idempotent only while its epoch is not behind the named source watermark; once it is late, `LATE_DELTA` takes precedence. A `-1` must target the active exact delivery. Mixed signs or repeated retractions for one delivery in a command reject atomically. Permuting a valid delta batch cannot change its command or transition digest.

The profile explicitly bounds command deltas, aggregate active values, open epochs, ready batches, demand per command, and total outstanding demand. Ready capacity applies to the retained next-state queue after already-granted demand is satisfied; batches published in the same pure step never occupy that queue. Demand addition itself is checked before draining. The sole overflow policy is `reject_new`: a violating command returns a typed rejection and no partial state. The aggregate active-value limit makes a separate per-epoch value limit redundant.

## Measured gate

The bounded gate passed with three frozen success sequences containing seven transitions, two full-object rejection fixtures, 32 seeded order trials, 64 independent-oracle comparisons, 16 slow-consumer trials, and four randomized capacity rejections. Two clean replay processes, two clean ambient processes, and two clean semantic-mutation processes produced byte-identical canonical output across distinct cwd, HOME, hash seed, timezone, and poison environments. Thirteen guarded real kernel paths recorded zero ambient or caller-input mutation attempts, fourteen ambient/control mutants were caught, and ten exact source-level semantic mutants were killed with zero escapes or invalid mutants.

This result does not establish eligibility correctness, direct M2 integration, irreversible-effect safety, durability, production readiness, comparative efficacy, engine promotion, or Lakatos progress.

Normative artifacts are [the contract](../spec/m3-reactive-contract.v1.json), [wire schema](../spec/schema/m3-reactive.v1.schema.json), and [manifest](../spec/m3-manifest.v1.json).
