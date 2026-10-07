# Agent Coding Paradigm

함수형·논리형·반응형 프로그래밍을 durable Harness와 typed graph engineering으로 결합하는 agent runtime 연구 저장소.

> Status: **RESEARCH INCUBATOR / M1–M3 + DIRECT L-R MEASURED / TYPESCRIPT EFFECT INTEGRATIONS PROPOSED / ENGINE DEFERRED / EFFICACY UNSUPPORTED**
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
                     (direct L-R projection measured; no persistent or general runtime)
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

This remains the target general runtime shape. The repository contains bounded
reference mechanisms and synthetic integrations, not a production or general
runtime. An empty queue is not success, a model final answer is not success,
and a trace span marked `OK` is not success.

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
- [Direct L-to-R projection seam](docs/LR_SEAM.md) — measured bounded stateless binding from exact M2 materialization state to M3 proposal/verdict deltas
- [LangGraph.js synthetic consumer](integrations/langgraphjs-synthetic/README.md) — proposed strict TypeScript integration with an Effect v3 shell and explicit approval/reconciliation boundaries
- [Engine decision ADR](docs/adr/0001-defer-engine-verdict.md) — why this is not yet called an engine
- [Research baseline](research/BASELINE_2026-08-08.md) — primary-source synthesis
- [External durable runtime comparison](research/EXTERNAL_DURABLE_RUNTIME_COMPARISON_2026-08-11.md) — official-source review and bounded TypeScript/Effect direction
- [M1 validation receipt](research/M1_VALIDATION_2026-08-08.md) — frozen commit, environment, corpus digests, local gate, and CI readback
- [M2 validation receipt](research/M2_VALIDATION_2026-08-09.md) — frozen subject tree, full-recompute digests, adversarial gates, and exact CI readback
- [M3 validation receipt](research/M3_VALIDATION_2026-08-09.md) — frozen subject tree, scalar-frontier digests, clean-process and semantic-mutation gates, and exact CI readback
- [Direct L-to-R seam validation receipt](research/LR_SEAM_VALIDATION_2026-08-09.md) — frozen measured subject, local evidence, and exact CI readback
- [Machine-readable engine decision](spec/engine-decision.v1.json) — validated defer decision
- [M0 manifest](spec/m0-manifest.v1.json) — normative contract set and non-claim boundary
- [M1 manifest](spec/m1-manifest.v1.json) — bounded pure-F implementation and conformance boundary
- [M2 manifest](spec/m2-manifest.v1.json) — bounded ground stratified-L implementation and conformance boundary
- [M3 manifest](spec/m3-manifest.v1.json) — measured bounded scalar-frontier R conformance boundary
- [Direct L-to-R seam manifest](spec/lr-seam-manifest.v1.json) — measured projection contract and exact admission closure

## TypeScript Effect experiments

The repository-local, unpublished
[LangGraph.js synthetic consumer](integrations/langgraphjs-synthetic/README.md)
is a `PROPOSED` integration over exact dependency pins. It exercises bounded
approval, dispatch, reconciliation, and independent-verification paths with
simulated or mocked adapters. It is not the repository engine, a production
adapter, or a real model-call receipt.

Its internal `run-fsm` experiment decodes a structural projection of the
repository-owned profile with Effect Schema and applies a pure decision
kernel against the existing trace corpus. It does not add another store,
dispatcher, reconciler, runtime composition root, or public API.

```bash
cd integrations/langgraphjs-synthetic
pnpm install --frozen-lockfile --ignore-scripts
pnpm verify
```

A separate narrow live Neo4j observation is `MEASURED` in
[`research/PUBLIC_RESEARCH_LIVE_ACTIVATION_2026-08-12.json`](research/PUBLIC_RESEARCH_LIVE_ACTIVATION_2026-08-12.json).
It is historical external-effect evidence, not an ordered executor receipt,
rollback authority, durable completion proof, or promotion of the synthetic
integration. Its detailed scope and nonclaims live in that artifact rather
than being copied here. It can be verified offline:

```bash
uv run --with-requirements requirements-m0.txt python scripts/validate_public_research_live_evidence.py
```

## Current admission gate

M0, M1, M2, M3, and the direct L-to-R seam have bounded `MEASURED`
receipts linked above. The receipts own their exact fixture, command,
environment, digest, and count details; this README does not duplicate those
derived values. Each result remains scoped to its named reference mechanism
and does not establish an integrated runtime or comparative efficacy.

Run it with:

```bash
python3 -m pip install -r requirements-m0.txt
python3 scripts/validate_m0.py
python3 scripts/validate_m1.py
python3 scripts/validate_m2.py
python3 scripts/validate_m3.py
python3 scripts/validate_lr_seam.py
python3 -m unittest discover -s tests -v
```

The next mechanics gates must prove:

1. a future persistent incremental L evaluator reuses prior closure while remaining equal to clean full recomputation;
2. a named immutable receipt shows that the proposed executable TypeScript synthetic consumer preserves the declared admission, effect, reconciliation, and verifier boundaries without widening them;
3. crash/restart never turns one logical effect into duplicate mutations at a real queryable destination;
4. trace-only, harness-only, or model-self-reported success cannot satisfy `DONE`;
5. production and harness use the same resolved composition graph modulo enumerated test adapters.

The repository contains measured F, L, R, and direct L-to-R reference
mechanisms plus proposed TypeScript integrations. It still does not contain a
general or production F/L/R/H engine.

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

MetaHumotonic License 1.2 has been adopted by explicit owner direction; see [LICENSE-NOTICE.md](LICENSE-NOTICE.md).

## License

**MetaHumotonic License 1.2** — [LICENSE](LICENSE); [scope, prior grants and third-party notices](LICENSE-NOTICE.md).

지정한 하드웨어의 접근권한과 전체 관리 권한을 합의한 명세서에 따라 공유하고, **CHU의 일부가 된다**는 참여 원칙을 적용합니다. 실제 접근에는 별도 승인이 필요합니다.

Source-available; not OSI-approved. Existing grants and separately licensed material remain valid.
