# Roadmap

> Roadmap status: PROPOSED. Milestone completion requires the listed receipt; prose updates do not close milestones.

## M0 — Freeze vocabulary and contracts ✅ MEASURED 2026-08-08

Deliverables:

- versioned `AcceptedEvent`, `FactDelta`, `EffectProposal`, `EligibilityVerdict`, `StableProposalBatch`, `EffectIntent`, graph envelope, delta, and receipt schemas;
- executable generic FSM and typed terminal outcomes;
- explicit logic truth tables and retraction semantics;
- deterministic canonical serialization rules;
- conformance fixture layout and claim ledger.

Gate: all schemas validate, golden fixtures parse, and semantic ambiguities are either resolved or marked outside v0.

Receipt boundary: the pinned repository checker reports nine valid Draft 2020-12 schemas, ten valid and thirteen invalid protocol fixtures, complete declared truth/default-negation tables, retraction/frontier/canonical cases, 25/25 declared transition coverage across 18 typed traces, nine terminal categories, three interrupt types, and a bounded-loop profile digest-bound to the sole-authority outer FSM. This is checker-relative M0 conformance only; it is not a global consistency proof, runtime evidence, or efficacy evidence.

## M1 — Pure F kernel

Deliverables: deterministic reducer/evolver, typed rejection, inert effect-proposal boundary, replay fixtures, ambient-effect guard.

Gate: purity and replay tests 1–3 pass in two clean processes.

## M2 — Stratified L kernel

Deliverables: facts/rules/materialization, semi-naive worklist, four-valued conflict state, derivation/provenance tracking, retraction.

Gate: logic tests 4–9 pass and incremental results equal full recomputation.

## M3 — Signed-delta R kernel

Deliverables: dependency graph, logical epoch/frontier, stable reaction batch, demand, bounded queues, backpressure, late-event policy.

Gate: reactive tests 10–15 pass under randomized ordering and slow-consumer injection.

## M4 — Durable H control shell

Deliverables: SQLite event/checkpoint/outbox/effect-ledger store, fenced runner, exact-hash approvals, fake effect adapter, reconciliation, independent verifier.

Gate: crash/approval/interrupt tests 16–25 pass with durable receipts.

## M5 — Typed graph federation

Deliverables: `G_sem`, `G_dep`, `G_comp`, `G_action`, `G_trace`, `G_prov`, `G_schema`; canonicalization; SHACL validation; resolved composition receipt.

Gate: graph/harness tests 26–33 pass, including mutation tests and production-root reachability.

## M6 — Interoperability and engine decision

Deliverables: second implementation or independent conformance runner, adapter SDK candidate, two real consumers, updated engine ADR.

Gate: test 34 passes and the engine promotion gates are reviewed with operational evidence.

## M7 — Comparative efficacy

Deliverables: preregistered held-out corpus, equal-budget baselines, outcome metrics, blinded/independent scoring, long-horizon maintenance follow-up, failure publication.

Gate: report effect sizes and uncertainty. A null or negative result is valid and must downgrade the paradigm claim.

## Immediate next slice

Start one M1 vertical slice only: accepted event → pure transition → signed fact delta plus inert effect proposal, with deterministic replay in two clean processes and an ambient-effect failure test. `EffectIntent` remains an H-owned, authority-bound object for M4. Do not scaffold a broad engine; the engine decision remains deferred.
