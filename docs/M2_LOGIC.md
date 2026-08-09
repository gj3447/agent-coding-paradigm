# M2 Stratified-L Kernel

> Status: **MEASURED REFERENCE MECHANICS / GROUND RULE PROFILE / NO R OR H RUNTIME**
>
> Measurement date: 2026-08-09

## Boundary

M2 adds one sibling public waist without widening the M1 package:

```text
solve_l(prior_materialization, rule_bundle, fact_delta_inputs, logical_time)
  -> LFixpointResult | LRejection
```

`flrh_kernel` continues to export only `step_f`; `flrh_logic` exports only
`solve_l`.  Both functions exchange fresh closed JSON values.  The boundary
promises copy/no-alias value semantics and caller-input non-mutation, not that a
returned Python `dict` is intrinsically unmodifiable.

The first profile is deliberately finite and ground.  Rules contain no parser,
variables, unification, functions, aggregates, disjunction, callbacks, external
predicates, registry lookup, or model/tool execution.  A rule has one signed
head, a conjunction of signed required literals, and zero or more
`not positive` tests against explicitly completed lower strata.

## Two independent signs

M2 does not infer logical negation from a predicate name or from
`FactDelta.diff`.

- `LFactDeltaInput.polarity` is object-language evidence: `positive` or
  `negative`.
- `FactDelta.diff` is a support-ledger operation: `+1` inserts one named
  support and `-1` retracts that same support.

The exact M1 `FactDelta` remains nested unchanged inside the positive wrapper.
An inserted base support gets a stable content digest over its signed atom,
qualified provenance, rule-set version, and dataflow version.  Operation-only
fields (`diff`, delivery logical time, and delivery causation) are excluded so a
later `-1` can refer to the existing support identity.  M1's derivation ID is
otherwise opaque to L.

## Fixpoint and provenance

Rules are normalized and evaluated by stratum.  Within one stratum, a
deterministically ordered semi-naive presence worklist evaluates a ground rule
only when a required signed literal becomes available.  Default negation is
checked only after the referenced lower stratum is complete.  It succeeds for
`NEITHER` and `FALSE_ONLY`, and fails for `TRUE_ONLY` and `BOTH`.

One finite ground rule instantiation can create at most one derived support.
Its identity is based on the signed head, normalized signed premise keys,
normalized lower-stratum absence witnesses, rule and bundle identity, and
rule/dataflow versions.  It is not a recursively expanding hash of parent proof
IDs.  This makes positive recursion finite: an unseeded positive strongly
connected component cannot create its own evidence, while a seeded component
converges.

Provenance names literal dependencies and completed-lower-stratum absence
witnesses.  Every materialized derived support must therefore remain reachable
from a base support or a valid absence witness.  The support sets for each atom
produce one of four explicit states: `NEITHER`, `TRUE_ONLY`, `FALSE_ONLY`, or
`BOTH`.  `BOTH` is a successful conflict value, not an arbitrary rule-order
winner and not a whole-call rejection.

## Recomputation and retraction profile

The input batch is preflighted atomically before a next materialization exists.
Exact duplicate `+1` delivery is idempotent.  Reusing an identity with different
stable support content, retracting an unknown or derived support, repeating a
`-1`, or mixing `+1/-1` for one identity in a batch returns a typed rejection.

Every accepted invocation first applies the input batch to the active base
ledger and then rebuilds the complete derived registry with the bounded
semi-naive worklist.  It diffs the prior and rebuilt derived support identities
to emit signed derived deltas.  This deliberately simple reference algorithm is
full recomputation for insertions and retractions alike; it is not a claim to
persistent incremental maintenance, DRed, or differential-dataflow deletion.

## Determinism and limits

Rule order, required-body order, query-atom order, and input batch order are
semantically set-like and normalized by canonical bytes.  Output arrays are
emitted in a declared canonical order, and malformed set-like inputs use the
same normalized order for typed-rejection precedence.  One invocation admits
at most 10,000 raw FactDelta inputs before exact duplicate collapse.  The rule
bundle declares limits no greater than 1,000 rule firings and derivation depth
8.  Exceeding an input or evaluation bound returns a typed rejection with no
partial materialization.

All IDs and digests use domain-separated `flrh-cjson/1` preimages.  The kernel
reads no clock, RNG, UUID source, environment, filesystem, network, subprocess,
credential, model, or tool adapter.  Logical time and every causal value are
explicit arguments or input fields.

## Measured gate

The aggregate M2 admission command validated four self-validating schemas,
three schema bindings, five exact inherited dependencies, ten successful
cases, fourteen full-object typed rejections, three sequences with nine total
steps, two permutation-equivalence pairs, and two exact canonical goldens.  It
then ran 66 spawned clean-process executions forming 33 byte comparisons with
zero mismatches.

Two guarded processes passed eleven positive guard self-tests and ten import
metadata checks.  Thirteen deliberate ambient or mutation mutants were caught.
Four non-empty real-kernel paths—rule firing, default absence, prior
retraction, and a prior-dependent late rejection—ran under the locked guard
with zero kernel ambient or caller-input mutation attempts.  These are named
CPython surfaces and corpus evidence, not a universal purity or security proof.

The closed boundary is defined by the [M2 contract](../spec/m2-logic-contract.v1.json),
[wire schema](../spec/schema/m2-logic.v1.schema.json),
[manifest](../spec/m2-manifest.v1.json), and
[fixture corpus](../fixtures/m2/cases.json).  Re-run the aggregate admission with:

```bash
python3 scripts/validate_m2.py
python3 -m unittest tests.test_m2_logic -v
```

## Exclusions

M2 does not emit `EligibilityVerdict`, `StableProposalBatch`, or `EffectIntent`.
The M1 proposal precondition set contains identifiers owned by more than L, so
interpreting it without a separately typed eligibility query would cross into R
or H policy.  Frontiers, scheduling, backpressure, durability, authority,
approval, dispatch, reconciliation, and terminal evidence remain later
milestones.

Passing the M2 gate measures only this Python ground-rule profile and frozen
corpus.  It does not establish a general Datalog engine, universal purity,
incremental performance superiority, an integrated FLR-H runtime, production
readiness, comparative efficacy, originality, or Lakatos progress.  The engine
promotion decision remains deferred.
