# Roadmap

> Roadmap status: M0–M3-LR MEASURED; M4–M7 PROPOSED. Milestone completion requires the listed receipt; prose updates do not close milestones.

## M0 — Freeze vocabulary and contracts ✅ MEASURED 2026-08-08

Deliverables:

- versioned `AcceptedEvent`, `FactDelta`, `EffectProposal`, `EligibilityVerdict`, `StableProposalBatch`, `EffectIntent`, graph envelope, delta, and receipt schemas;
- executable generic FSM and typed terminal outcomes;
- explicit logic truth tables and retraction semantics;
- deterministic canonical serialization rules;
- conformance fixture layout and claim ledger.

Gate: all schemas validate, golden fixtures parse, and semantic ambiguities are either resolved or marked outside v0.

Receipt boundary: the pinned repository checker reports nine valid Draft 2020-12 schemas, ten valid and thirteen invalid protocol fixtures, complete declared truth/default-negation tables, retraction/frontier/canonical cases, 25/25 declared transition coverage across 18 typed traces, nine terminal categories, three interrupt types, and a bounded-loop profile digest-bound to the sole-authority outer FSM. This is checker-relative M0 conformance only; it is not a global consistency proof, runtime evidence, or efficacy evidence.

## M1 — Pure F kernel ✅ MEASURED 2026-08-08

Deliverables: deterministic reducer/evolver, typed rejection, inert effect-proposal boundary, replay fixtures, ambient-effect guard.

Gate: purity and replay tests 1–3 pass in two clean processes.

Receipt boundary: one Python reference event profile produced seven schema-checked successful transitions, including mixed uppercase/lowercase RFC 3339 markers, nineteen closed typed rejections, seven sensitivity mutations, and two exact canonical result goldens. A two-step sequence and every frozen case produced byte-identical, independently canonicalized output across 54 spawned replay runs forming 27 comparisons in two distinct environment profiles. Two additional fresh processes locked filesystem reads before an `importlib` metadata-bearing import from precompiled source through a memory loader: eight explicit guarded categories and three audit-hook-only probes passed 11 positive self-tests, ten import-metadata checks passed, the kernel recorded zero attempts, and eight deliberate ambient/mutation mutants were caught. This is bounded reference-mechanism evidence, not a universal purity proof or an integrated runtime result.

## M2 — Stratified L kernel ✅ MEASURED 2026-08-09

Deliverables: facts/rules/materialization, semi-naive worklist, four-valued conflict state, derivation/provenance tracking, retraction.

Gate: logic tests 4–9 pass and stepwise delta-ledger results equal an independent clean full recomputation.

Receipt boundary: one Python ground/propositional profile produced ten successful materializations, fourteen closed typed rejections, three sequences with nine total steps, two permutation-equivalence pairs, and two exact canonical goldens. Every accepted step matched an independent naive full-recompute oracle. Two environment profiles produced 66 spawned runs forming 33 byte comparisons with zero mismatches. Two locked-import processes passed eleven guard self-tests and ten import-metadata checks; thirteen deliberate mutants were caught, and four non-empty kernel paths recorded zero ambient or caller-input mutation attempts. The evaluator intentionally rebuilds the complete derived projection on every invocation; persistent incremental maintenance, R/H integration, and engine promotion remain open.

## M3 — Signed-delta R kernel ✅ MEASURED 2026-08-09

Deliverables: dependency graph, logical epoch/frontier, stable reaction batch, demand, bounded queues, backpressure, late-event policy.

Gate: reactive tests 10–15 pass under randomized ordering and slow-consumer injection. The measured slice accepts only explicit signed `EffectProposal` and caller-supplied `EligibilityVerdict` values; it neither infers eligibility from M2 nor exercises H authority or effects.

Receipt boundary: one bounded Python scalar-frontier profile produced three frozen success sequences with seven transitions, two full-object rejections, one epoch-atomic publication, 32 seeded order trials, 64 independent-oracle comparisons, 16 slow-consumer trials, and four randomized capacity rejections. Two clean replay, ambient, and semantic-mutation process profiles reproduced exact canonical output; thirteen guarded real paths recorded zero ambient or caller-input mutation attempts, fourteen ambient/control mutants were caught, and ten exact source-level semantic mutants were killed with zero escapes or invalid mutants. This is standalone supplied-value R mechanics evidence, not eligibility correctness, direct M2 integration, persistent or distributed streaming, H/effect safety, integrated runtime, production, efficacy, engine, or Lakatos evidence.

## M3-LR adjunct — Direct L-to-R projection ✅ MEASURED

Deliverables: one versioned stateless `project_lr` boundary, explicit proposal/precondition-to-query bindings, frozen four-valued truth projection, exact M3 proposal/verdict insertion deltas, closed typed rejection, independent oracle, guards, semantic mutants, and an unchanged public `step_r` publication chain.

Receipt boundary: one bounded stateless Python projection profile produced eight successful descriptors, twenty-four full-object rejection descriptors, two exact goldens, two equivalence pairs, eight independent-oracle comparisons, six clean child processes, ten guarded ambient paths, fourteen killed semantic axes with zero escapes or invalid mutants, and eight unchanged-public-`step_r` publication chains. This adjunct is not M4 and does not establish domain eligibility correctness, persistent incremental L, durable R, H authority or effects, or an integrated runtime.

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

Keep the current TypeScript/Effect control experiment at one repository-owned
`run-fsm` Schema projection and pure decision kernel. Reuse the package's
existing H orchestration for effectful experiments rather than creating a
second store, dispatch loop, or public runtime. The slice remains `PROPOSED`
and must not recreate the archived Python candidate's manifests, receipts,
copied fixtures, or broad framework surface.

The next real-platform gate is a least-privilege fenced executor that binds an
intent to apply, reconciliation, and independent readback. The checked-in live
Neo4j observation remains narrow historical evidence; it is not an ordered
executor receipt or rollback authority.

A real model call, restart-durable state, operational consumers, upgrade and
crash trials, external-effect evidence, comparative efficacy, and engine
promotion remain separate gates.
