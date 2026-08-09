# Agent Coding Paradigm

함수형·논리형·반응형 프로그래밍을 durable Harness와 typed graph engineering으로 결합하는 agent runtime 연구 저장소.

> Status: **RESEARCH INCUBATOR / SEPARATE M1 PURE-F + M2 STRATIFIED-L + M3 SCALAR-FRONTIER-R REFERENCES MEASURED / DIRECT L-R PROJECTION PROPOSED / NO INTEGRATED RUNTIME / EFFICACY UNJUDGED**
>
> Working profile: **FLR-H** — Functional, Logic, Reactive, Harness
>
> Primary tier: **L_RT** application runtime. `L_IDE` and `L_MC` are future adapters, not the core.
>
> Jaebaeman is explicitly out of scope. This repository does not model planning or dispatch doctrine.

## Core hypothesis

An agent runtime may become substantially more reliable if it separates four responsibilities instead of asking an LLM loop to own all of them:

- **F — Functional kernel:** deterministic state transition plus inert `EffectProposal` values.
- **L — Logic kernel:** facts, rules, constraints, eligibility, conflict, provenance, retraction, and fixpoint.
- **R — Reactive kernel:** versioned dependencies, signed deltas, logical time/frontiers, stable proposal batches, scheduling, and backpressure.
- **H — Harness/control shell:** authority and approval enforcement, `EffectIntent` creation, continuation, budgets, checkpoints, outbox, reconciliation, independent verification, and terminal receipts.

The working sentence is:

> 노드는 함수형, 제약은 논리형, 흐름은 반응형, 완료 조건은 하네스 폐쇄형.

This is a falsifiable architecture hypothesis, not evidence of originality or superiority.

## Runtime shape

```text
AcceptedEvent
    │
    ▼
pure F transition ──► FactDelta(+/-) + EffectProposal
                               │
                               ▼
                     L fixpoint/materialization
                               │
                               ▼ explicit verdict projection
                     (direct L-R candidate proposed; M3 remains separately measured)
                               │
                               ▼ frontier passes epoch
                     R StableProposalBatch
                               │
                               ▼
                     H authority/approval check
                               │
                               ▼
                     durable EffectIntent
                               │
                               ▼
                     commit/execute/reconcile
                               │
                               ▼
                     durable ActionReceipt
                               │
                               └──► next accepted event
```

This is the target runtime shape, not the current implementation. The inner loop stabilizes facts and deltas. The outer loop closes real-world effects and evidence. An empty queue is not success, a model final answer is not success, and a trace span marked `OK` is not success.

## Graph profile

The project deliberately rejects a single soup graph. It proposes a typed federation:

- `G_sem`: facts, goals, rules, constraints, authority, conflict
- `G_dep`: derivation, dependency, invalidation, incremental recomputation
- `G_comp`: resolved components, ports, handlers, adapters, schemas
- `G_action`: commands, declared inputs, platform, effect attempts, outputs
- `G_trace`: observed events and spans; never the sole correctness authority
- `G_prov`: source, activity, agent, responsibility, revision lineage
- `G_schema`: vocabularies, shapes, rule bundles, compatibility, migration

See [Graph Contract](docs/GRAPH_CONTRACT.md).

## Repository map

- [Architecture](docs/ARCHITECTURE.md) — planes, protocols, loops, ownership
- [Execution Semantics](docs/SEMANTICS.md) — F/L/R boundary and epoch semantics
- [Harness Contract](docs/HARNESS_CONTRACT.md) — L_RT control, IFCV, strong `DONE`
- [Graph Contract](docs/GRAPH_CONTRACT.md) — graph kinds, identity, envelopes, receipts
- [Fault Test Plan](docs/FAULT_TEST_PLAN.md) — mechanics admission tests
- [Claims and Status](docs/CLAIMS_AND_STATUS.md) — what is and is not supported
- [Roadmap](docs/ROADMAP.md) — M0 through comparative efficacy work
- [M0 contract and test boundary](docs/M0_CONTRACT.md) — what kind of theory this is, what passed, and what remains untested
- [M1 pure-F kernel](docs/M1_KERNEL.md) — the first implemented vertical slice, wire contract, replay gate, and non-claims
- [M2 stratified-L kernel](docs/M2_LOGIC.md) — ground fixpoint, four-valued support, provenance, retraction, and full-recompute oracle boundary
- [M3 reactive kernel](docs/M3_REACTIVE.md) — measured bounded supplied-value, scalar-frontier, epoch-atomic batch, demand, and backpressure reference
- [Direct L-to-R projection seam](docs/LR_SEAM.md) — proposed stateless binding from exact M2 materialization state to M3 proposal/verdict deltas
- [Engine decision ADR](docs/adr/0001-defer-engine-verdict.md) — why this is not yet called an engine
- [Research baseline](research/BASELINE_2026-08-08.md) — primary-source synthesis
- [M1 validation receipt](research/M1_VALIDATION_2026-08-08.md) — frozen commit, environment, corpus digests, local gate, and CI readback
- [M2 validation receipt](research/M2_VALIDATION_2026-08-09.md) — frozen subject tree, full-recompute digests, adversarial gates, and exact CI readback
- [M3 validation receipt](research/M3_VALIDATION_2026-08-09.md) — frozen subject tree, scalar-frontier digests, clean-process and semantic-mutation gates, and exact CI readback
- [Machine-readable engine decision](spec/engine-decision.v1.json) — validated defer decision
- [M0 manifest](spec/m0-manifest.v1.json) — normative contract set and non-claim boundary
- [M1 manifest](spec/m1-manifest.v1.json) — bounded pure-F implementation and conformance boundary
- [M2 manifest](spec/m2-manifest.v1.json) — bounded ground stratified-L implementation and conformance boundary
- [M3 manifest](spec/m3-manifest.v1.json) — measured bounded scalar-frontier R conformance boundary
- [Direct L-to-R seam manifest](spec/lr-seam-manifest.v1.json) — proposed projection contract and candidate evidence closure

## Current admission gate

The pinned M0 checker passed on 2026-08-08 for the declared contract corpus: nine Draft 2020-12 schemas, ten valid and thirteen invalid protocol fixtures, logic/canonicalization cases, all 25 declared FSM transitions across 18 typed traces, all nine terminal categories, and all three interrupt types. The supplemental bounded-loop profile is digest-bound to that sole-authority FSM.

The bounded M1 Python reference slice also passed its declared gate: seven schema-checked successful transitions, including mixed uppercase/lowercase RFC 3339 markers, nineteen typed rejections, seven sensitivity mutations, one two-step replay, two exact canonical result goldens, and 54 spawned clean-process replay executions forming 27 byte-equality comparisons with zero mismatches. Two additional fresh processes locked filesystem reads before performing an `importlib` metadata-bearing import from precompiled source through a memory loader; eight explicit guarded categories and three audit-hook-only probes passed 11 positive self-tests, ten import-metadata checks passed, the kernel recorded zero attempts, and eight deliberate ambient/mutation mutants were caught. This evidence covers one observation event profile and the named CPython surfaces; it is not a universal purity proof.

The bounded M2 Python reference slice passed its ground stratified-L gate: ten successful cases, fourteen full-object typed rejections, three sequences with nine total steps, two exact goldens, two permutation-equivalence pairs, and an independent naive semantic oracle. Two clean profiles produced 66 spawned executions forming 33 byte comparisons with zero mismatches. Two guarded processes passed eleven self-tests and ten import-metadata checks; thirteen control mutants were caught, and four non-empty kernel paths recorded zero ambient or caller-input mutation attempts. The delta interface applies a stepwise base ledger, but M2 deliberately rebuilds the complete derived projection on every accepted invocation; persistent incremental maintenance is not claimed.

The bounded M3 Python reference slice passed its supplied-value scalar-frontier gate: three frozen success sequences with seven transitions, two full-object rejections, one epoch-atomic publication, 32 seeded order trials, 64 independent-oracle comparisons, 16 slow-consumer trials, and four randomized capacity rejections. Two clean replay, two clean ambient, and two clean semantic-mutation processes reproduced exact canonical output. Thirteen guarded real paths recorded zero ambient or caller-input mutation attempts; fourteen ambient/control mutants and all ten source-level semantic mutants were detected. M3 transports explicit caller-supplied eligibility verdicts; it does not validate them or establish direct M2 integration, persistence, distributed progress truth, H authority, or effect safety.

A separate direct L-to-R projection candidate now binds explicit proposal preconditions to exact four-valued M2 materialization states and constructs M3 proposal/verdict insertion deltas. It remains `PROPOSED_PENDING_MEASUREMENT`: local candidate evidence is not yet a durable CI/receipt-backed conformance claim, and the slice does not establish domain eligibility correctness or an integrated runtime.

Run it with:

```bash
python3 -m pip install -r requirements-m0.txt
python3 scripts/validate_m0.py
python3 scripts/validate_m1.py
python3 scripts/validate_m2.py
python3 scripts/validate_m3.py
python3 scripts/validate_lr_seam.py --allow-proposed
python3 -m unittest discover -s tests -v
```

The next mechanics gates must prove:

1. a future persistent incremental L evaluator reuses prior closure while remaining equal to clean full recomputation;
2. the proposed direct L-to-R candidate is independently measured and promoted without weakening the separately measured M2 and M3 contracts;
3. crash/restart never turns one logical effect into duplicate real-world mutations;
4. trace-only, harness-only, or model-self-reported success cannot satisfy `DONE`;
5. production and harness use the same resolved composition graph modulo enumerated test adapters.

The repository contains separate measured F, L, and R reference mechanisms plus one proposed stateless direct L-to-R projection candidate. The repository still does not contain an integrated F/L/R/H runtime.

## Non-claims

This repository does **not** currently claim that FLR-H:

- is a new universal programming paradigm;
- outperforms existing agent runtimes;
- reduces cost, latency, defects, or maintenance effort;
- is an industry graph or loop standard;
- provides exactly-once external effects;
- is production-ready.

Those claims require executable mechanics first, then held-out equal-budget comparative trials.

## Research basis

The proposal composes constituent mechanisms rather than pretending one source already defines FLR-H. Primary anchors include [Reactive Streams](https://www.reactive-streams.org/), [CloudEvents](https://github.com/cloudevents/spec), [W3C SHACL](https://www.w3.org/TR/shacl/), [W3C PROV-O](https://www.w3.org/TR/prov-o/), [Differential Dataflow](https://www.cidrdb.org/cidr2013/Papers/CIDR13_Paper111.pdf), and durable agent/workflow contracts summarized in the [research baseline](research/BASELINE_2026-08-08.md).

No license has been selected yet. Do not infer permission beyond GitHub's default repository terms.
