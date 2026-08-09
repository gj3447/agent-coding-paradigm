# Direct L-to-R Projection Seam

> Status: **MEASURED_REFERENCE_CONFORMANCE**.

## Purpose

This adjunct slice measures one deterministic, stateless projection from an exact
M2 `LFixpointResult` and explicit proposal-to-query bindings into exact M3
proposal and `EligibilityVerdict` insertion deltas. It is a sibling module; it
does not widen the measured `flrh_logic.solve_l` or `flrh_reactive.step_r`
public waists.

The public Python boundary is:

```python
project_lr(l_result, rule_bundle, r_profile, binding_profile, query_batch)
    -> LRProjectionResult | LRProjectionRejection
```

Only `project_lr` is exported from `flrh_lr_seam`.

## Explicit binding

Each `LRProjectionQuery` carries one exact `EffectProposal`, zero or more typed
`LRFactRequirement` values, and the proposal preconditions owned by a later R
frontier. Fact-precondition identifiers plus frontier-precondition identifiers
must partition `proposal.preconditions` exactly. Every fact requirement names an
atom declared by the supplied M2 rule bundle and reads the complete fact state
from the supplied materialization; the seam does not parse opaque precondition
strings or invent missing facts.

The frozen profile maps required literals as follows:

| Required polarity | M2 state | Requirement outcome | Evidence |
|---|---|---|---|
| positive | `TRUE_ONLY` | satisfied | positive supports |
| positive | `FALSE_ONLY` | unsatisfied | negative supports |
| negative | `TRUE_ONLY` | unsatisfied | positive supports |
| negative | `FALSE_ONLY` | satisfied | negative supports |
| either | `BOTH` | conflict | positive and negative supports |
| either | `NEITHER` | unsatisfied | none |

Conflict dominates aggregation, otherwise every requirement must be satisfied
for `eligible`; the remaining result is `ineligible`. This is a frozen reference
mapping over explicit inputs, not proof that the chosen query expresses correct
domain eligibility policy.

## Output boundary

A non-empty accepted query batch returns one derived verdict per proposal and an
exact M3 `RApplyDeltaBatch` containing one `+1` proposal delta and one `+1`
verdict delta per query at the M2 logical time. An empty batch returns no verdicts
and a null command. The projection emits no frontier advance, demand grant,
retraction, `EffectIntent`, capability, approval, authority, checkpoint, receipt,
or external action.

All inputs, versions, digests, identities, set order, and result bytes are closed
by [`lr-seam-contract.v1.json`](../spec/lr-seam-contract.v1.json) and
[`lr-seam.v1.schema.json`](../spec/schema/lr-seam.v1.schema.json). Rejection is
typed, atomic, and contains no partial command or verdict set.

## Measurement gate

Run the measured admission gate with:

```bash
python3 scripts/validate_lr_seam.py --allow-proposed
python3 -m unittest tests.test_lr_seam -v
```

The measured gate binds the closed schemas and dependency digests, exact success
and rejection goldens, a separately implemented oracle, clean-process replay,
guarded non-empty paths, source-level semantic mutants, a public
`solve_l -> project_lr -> step_r` publication chain, and all existing M0–M3
non-regression gates. Default `validate_lr_seam.py` admits this status only when the contract,
manifest, claim ledger, public governance surfaces, exact CI command, and frozen
evidence closure remain coherent.

## Non-claims

This measured gate does not establish general eligibility-rule
correctness, proposal provenance truth, frontier truth, persistent incremental L,
durable R, an integrated F/L/R runtime, H authority or effects, irreversible
effect safety, production readiness, comparative efficacy, an engine verdict, or
Lakatos progress. The repository engine decision remains `defer`.
