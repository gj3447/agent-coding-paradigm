# Agent Coding Paradigm

함수형·논리형·반응형 프로그래밍을 durable Harness와 typed graph engineering으로 결합하는 agent runtime 연구 저장소.

> Status: **RESEARCH INCUBATOR / PROPOSED / NOT CANON / EFFICACY UNMEASURED**
>
> Working profile: **FLR-H** — Functional, Logic, Reactive, Harness
>
> Primary tier: **L_RT** application runtime. `L_IDE` and `L_MC` are future adapters, not the core.
>
> Jaebaeman is explicitly out of scope. This repository does not model planning or dispatch doctrine.

## Core hypothesis

An agent runtime may become substantially more reliable if it separates four responsibilities instead of asking an LLM loop to own all of them:

- **F — Functional kernel:** deterministic state transition and explicit effect intent.
- **L — Logic kernel:** facts, rules, constraints, authorization, conflict, provenance, retraction, and fixpoint.
- **R — Reactive kernel:** versioned dependencies, signed deltas, logical time/frontiers, scheduling, and backpressure.
- **H — Harness/control shell:** continuation, budgets, approvals, checkpoints, outbox, reconciliation, independent verification, and terminal receipts.

The working sentence is:

> 노드는 함수형, 제약은 논리형, 흐름은 반응형, 완료 조건은 하네스 폐쇄형.

This is a falsifiable architecture hypothesis, not evidence of originality or superiority.

## Runtime shape

```text
AcceptedEvent
    │
    ▼
pure F transition ──► base FactDelta(+/-)
    │                         │
    │                         ▼
    │                   L fixpoint + provenance
    │                         │
    │                         ▼ frontier passes epoch
    │                   R stable reaction batch
    │                         │
    ▼                         ▼
EffectIntent ──► L authorization ──► H commit/execute/reconcile
                                             │
                                             ▼
                                      durable ReceiptEvent
                                             │
                                             └──► next accepted event
```

The inner loop stabilizes facts and deltas. The outer loop closes real-world effects and evidence. An empty queue is not success, a model final answer is not success, and a trace span marked `OK` is not success.

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
- [Engine decision ADR](docs/adr/0001-defer-engine-verdict.md) — why this is not yet called an engine
- [Research baseline](research/BASELINE_2026-08-08.md) — primary-source synthesis
- [Machine-readable engine decision](spec/engine-decision.v1.json) — validated defer decision

## First admission gate

Before any efficacy comparison, a minimal vertical slice must prove:

1. replay of the same accepted events yields the same F state and L derivation digests;
2. incremental insert/delete/retract converges to the same result as clean full recomputation;
3. no irreversible effect is dispatched before the logical frontier passes;
4. crash/restart never turns one logical effect into duplicate real-world mutations;
5. trace-only, harness-only, or model-self-reported success cannot satisfy `DONE`;
6. production and harness use the same resolved composition graph modulo enumerated test adapters.

Until those gates pass, this repository contains a specification and test plan, not a working runtime.

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
