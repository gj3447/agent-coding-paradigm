# M2-IL persistent incremental L candidate

> Status: **PROPOSED_PENDING_MEASUREMENT**.

M2-IL is an additive sibling profile, `flrh-l-persistent-incremental/1`. Its
sole public function is
`step_incremental_l(prior_checkpoint, rule_bundle, fact_delta_inputs,
logical_time)`. The checkpoint is an explicit immutable JSON value; persistent
means caller-managed checkpoint reuse, not filesystem or database persistence.

An accepted `LPersistentLStep` wraps the exact public M2 `LFixpointResult`, a
complete next checkpoint, a reuse receipt, and a step digest. Candidate output
is constructed before the public `solve_l` differential comparison. A first
public M2 pass establishes exact rejection precedence only; its successful
payload does not construct the candidate. A mismatch closes as
`EQUIVALENCE_VIOLATION`; no partial checkpoint is returned. Exact M2 rejection
objects pass through unchanged.

The evaluation cache retains only the immediately preceding accepted prefix.
Its context binds rule, bundle, stratum, trigger, required-literal presence and
depth, default-positive presence, and completed lower-stratum digest. The
receipt binds both checkpoints, candidate and oracle fixpoints, lookups, hits,
misses, reused and executed candidate body evaluations, accounting, and reused
entry digests. These counters exclude the two public M2 full-recompute passes
and do not claim reduced total runtime. Limits are 10,000 active base supports, 65,536 cache entries/body
evaluations, and 67,108,864 canonical checkpoint bytes.

This candidate does **not** claim performance superiority, integrated R or H,
durable storage, production readiness, engine promotion, comparative efficacy,
or Lakatos progress. Use of exact-SHA-pinned M2 private helpers is an internal
adjunct dependency and is not an ownership or stability claim over M2.
