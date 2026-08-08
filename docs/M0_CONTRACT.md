# M0 Contract and Test Boundary

> Status: **MEASURED CONTRACT CONFORMANCE / NO RUNTIME / EFFICACY UNJUDGED**
>
> Measurement date: 2026-08-08

## What kind of theory is this?

FLR-H is currently an **engineering research programme with an executable formal-design layer**. It is not yet a demonstrated programming paradigm, a production runtime, or an industry standard.

Four claim levels must remain separate:

| Level | Question | Current state |
|---|---|---|
| Formal design | Do the current F/L/R/H artifacts satisfy their closed schemas, encoded invariants, and declared fixtures? | M0 checker conformance measured |
| Mechanism | Can independent code implement those contracts deterministically, incrementally, durably, and safely? | M1–M5 not implemented |
| Comparative efficacy | Does full FLR-H improve held-out coding-agent outcomes over a simpler equal-budget control? | Unpreregistered and unjudged |
| Paradigm/standard | Is the abstraction independently adopted, stable across implementations, and worth teaching as a general paradigm? | Unsupported |

M0 therefore records **checker-relative contract conformance**. It does not prove global logical consistency, implementation feasibility, or practical usefulness.

## Lakatos framing

The dedicated LakatoTree programme currently carries this hard core:

1. execution closure, not a tool-call trace or model assertion, defines completed work;
2. Harness control is intrinsic rather than an optional wrapper;
3. functional, logic, and reactive mechanisms are materials for a machine-checkable execution graph;
4. no efficacy claim is admissible without an equal-compute comparison.

The v0 choices in this repository—four-valued support, stratified negation, scalar epochs, signed deltas, typed graph federation, and intent-before-effect—form a replaceable protective belt. A failed v0 choice may be repaired without silently changing the hard core. Repeated ad hoc repair, however, must be reported as degeneration rather than hidden.

## Normative M0 artifacts

- [`m0-manifest.v1.json`](../spec/m0-manifest.v1.json) — completion boundary, schema bindings, and file set
- [`protocol.v1.schema.json`](../spec/schema/protocol.v1.schema.json) — accepted event, fact delta, proposal/eligibility/stable-batch/intent seam, graph objects, and receipts
- [`logic-semantics.v0.json`](../spec/logic-semantics.v0.json) — truth states, default negation, retraction, strata, and frontier
- [`canonicalization.v1.json`](../spec/canonicalization.v1.json) — local deterministic JSON profile
- [`run-fsm.v1.json`](../spec/run-fsm.v1.json) — sole authoritative outer control machine
- [`run-fsm-traces.v1.json`](../spec/run-fsm-traces.v1.json) — declared-transition, guard, terminal, authority, and interrupt coverage fixture; not an exhaustive state-space proof
- [`loop-contract.v1.json`](../spec/loop-contract.v1.json) — bounded/resumable operational profile, digest-bound to the authoritative FSM
- [`claims.v1.json`](../spec/claims.v1.json) — machine-readable claims and falsifiers

Diagrams and prose are explanatory views. If they disagree with a normative machine file, the machine file wins until a versioned correction is accepted.

## M0 checks

Run:

```bash
python3 -m pip install -r requirements-m0.txt
python3 scripts/validate_m0.py
python3 -m unittest discover -s tests -v
```

The current checked bundle checks:

- nine Draft 2020-12 schemas, including closed bindings for every normative instance;
- ten valid protocol object kinds and thirteen single-invariant negative mutations, including rejection of F-owned authoritative risk/effect-idempotency fields and inconsistent approval bindings;
- all four evidence states and all four default-negation outcomes;
- multiple-support retention, last-support removal, conflict preservation, stratification rejection, and strict frontier passage;
- canonical equivalence, ordered nested-payload separation, duplicate-set rejection, mutation separation, floating-point rejection, NFC rejection, and signed-int64 bounds;
- 25 FSM transitions, four false-guard branches, schema/authority rejection, nine terminal paths, three immediate/deferred interrupt classes, and 18 traces;
- one digest-bound lifecycle authority plus bounded budgets, durable intent, approval expiry, receipt re-ingestion, unknown-outcome terminal closure, no-progress, and independent success closure.

The Python checker is non-normative and replaceable. A second implementation should be able to consume the same JSON contracts and fixtures.

## Test ladder beyond M0

| Milestone | Decisive test | What would falsify or downgrade it? |
|---|---|---|
| M1 Functional | replay/property tests in two clean processes | identical explicit inputs yield different canonical state/effect proposals |
| M2 Logic | incremental insert/delete/retract versus clean recomputation | support, conflict, or provenance diverges |
| M3 Reactive | randomized order, frontier, slow-consumer, and backpressure tests | intermediate effects leak or queues grow outside bounds |
| M4 Harness | crash injection around intent/send/receipt plus cancellation and fencing | duplicate confirmed mutation or false `SUCCEEDED` |
| M5 Graph | round-trip, migration, resolver, and composition-mutation tests | required identity is lost or forbidden wiring passes |
| M6 Interop | independent conformance runner and two real consumers | contract cannot survive independent implementation |
| M7 Efficacy | preregistered held-out equal-budget A/B with independent judge | no material gain, regression, or cost ceiling violation |

The full FLR-H comparison must be preregistered before measurement. A null or negative result is valid evidence and must downgrade the efficacy claim.

## LakatoTree exact-readback boundary

Read-only verification found the dedicated `LakatosTree_AgentParadigm_20260808` tree, incarnation `93264ef9e2734621a24b7d48d46ebfc2`, at notebook assurance with partial coverage and no scientific judgment. The narrower E1 execution-closure prediction has receipt `1d714918c729f1d7d44a89294f7345b7d0a77c27b61cab07910c2c2554fd399f`.

That receipt is **not** a full FLR-H efficacy preregistration. The standalone repository commit is also not yet bound to a LakatoTree node. [`LAKATOTREE_BINDING_2026-08-08.json`](../research/LAKATOTREE_BINDING_2026-08-08.json) preserves the exact readback without pretending that a local pointer mutates the tree.

No progress verdict is issued by M0. Only an independent registered judge may issue one after prospective evidence exists.

## Validator portability note

The bundled `fsm-design` tools target their own `fsm-spec/v1` dialect; this repository declares `flrh-run-fsm/v1` with a full Draft 2020-12 event schema and typed actor/capability authority. The bundled `loop-engineering` validator expects an embedded second FSM plus the SYMPOSIUM seven-commander canon, including Jaebaeman. Both read-only invocations therefore fail on profile shape and are **not** counted as M0 passes. Importing duplicate lifecycle authority or unrelated planning mythology would violate this repository's contract. M0 uses a repository-local replaceable checker, while M6 explicitly requires an independent conformance implementation. Exact incompatibility readbacks are recorded in [`FSM_VALIDATOR_COMPATIBILITY_2026-08-08.md`](../research/FSM_VALIDATOR_COMPATIBILITY_2026-08-08.md) and [`LOOP_VALIDATOR_COMPATIBILITY_2026-08-08.md`](../research/LOOP_VALIDATOR_COMPATIBILITY_2026-08-08.md).
