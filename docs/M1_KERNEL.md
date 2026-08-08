# M1 Pure-F Kernel

> Status: **MEASURED REFERENCE CONFORMANCE / ONE EVENT PROFILE / NO INTEGRATED RUNTIME**
>
> Measurement date: 2026-08-08

## Implemented boundary

M1 implements one public waist:

```text
step_f(snapshot, accepted_event) -> FTransition | FRejection
```

The package root exports only `step_f`. Canonical byte helpers remain module-local conformance utilities, not a second public kernel API. Accepted timestamps use the JSON Schema `date-time` RFC 3339 profile, including lowercase `t` and `z`; validation is purely lexical and calendrical and never reads a clock.

The accepted profile is version-pinned to `flrh.m1.observation-recorded/1`. A successful step returns a fresh `FStateSnapshot`, one signed `FactDelta`, and zero or one inert `EffectProposal`. It never returns `EffectIntent`, capability, approval, adapter binding, dispatch, or receipt data.

The reference package is deliberately small:

- [`kernel.py`](../src/flrh_kernel/kernel.py) validates, decides, evolves, and returns a closed wire result;
- [`canonical.py`](../src/flrh_kernel/canonical.py) implements `flrh-cjson/1` independently from the M0 checker;
- [`m1-kernel.v1.schema.json`](../spec/schema/m1-kernel.v1.schema.json) closes snapshot, input, transition, and rejection shapes;
- [`m1-kernel-contract.v1.json`](../spec/m1-kernel-contract.v1.json) states the supported versions, invariants, exclusions, and completion boundary;
- [`cases.json`](../fixtures/m1/cases.json) freezes success, rejection, equivalence, sensitivity, and multi-step replay cases.

There is no kernel class, handler registry, plugin SDK, port, adapter, persistence layer, scheduler, async API, or generic rule/dataflow abstraction in M1.

## Determinism and transition identity

All causal data is explicit. IDs and digests use versioned canonical preimages; the kernel reads no clock, randomness, UUID source, environment, filesystem, network, subprocess, model, or tool adapter.

`derivation_id`, `proposal_id`, and `proposal_dedup_key` bind the complete emitted value, excluding only their own self-referential identity fields. Changes to logical time, correlation, declared risk, preconditions, or versioned content therefore cannot silently reuse an identity for different bytes.

`transition_digest` covers:

1. contract version and accepted event ID;
2. the prior snapshot digest;
3. the next snapshot digest;
4. ordered root-canonical `FactDelta` digests;
5. ordered root-canonical `EffectProposal` digests.

Nested proposal preconditions are therefore canonicalized under the proposal's own set rule. Arbitrary arrays inside the accepted event payload remain ordered application data.

The projection deliberately does not include the complete accepted-event wire. `occurred_at`, `received_at`, accepted-event `causation_id`, and ingress `idempotency_key` can change without changing the transition. Detecting one reused event identity with different ingress bytes is therefore an ingress/H responsibility, not an M1 result. Only workflow, state-schema, event-schema, and canonicalization versions are checked against M1's supported constants; the remaining version fields are equality-, preservation-, and digest-bound, not registry-validated.

## Typed rejection

Malformed, noncanonical, incompatible, stale, regressing, closed, or invariant-breaking input returns a closed `FRejection`. A rejection contains no next snapshot, delta, or proposal, and does not expose Python exception text or a traceback. Exact version mismatch fails closed; M1 has no migration or upcaster chain.

## Measured gate

Run:

```bash
python3 scripts/validate_m1.py
python3 -m unittest discover -s tests -v
```

The frozen gate covers seven schema-checked successful transitions, including mixed uppercase/lowercase RFC 3339 markers, nineteen typed rejections, seven causal/identity-sensitivity mutations, one proposal-set equivalence pair, two exact canonical output goldens, one two-step replay, and 54 clean spawned replay runs across two environment profiles. A separate admission check starts two fresh processes, preloads and compiles the trusted implementation source, locks filesystem reads, and then uses a memory-backed finder/loader to perform `importlib` metadata-bearing Python imports behind an audit hook and explicit Python surface traps. Eight explicit category checks plus three audit-hook-only probes provide 11 positive self-tests, and ten checks bind `__spec__`, `__loader__`, origin, and package search metadata; the kernel records zero attempts and eight deliberate ambient or mutation mutants are caught, including direct OS-backend read/stat bypasses and a metadata-conditional import-body probe. Recursively write-detecting inputs cover ordinary success, late rejection, and nested aliases.

The semantic oracle reconstructs the entire successful transition and every frozen rejection from fixture input and expectations, then canonicalizes them with the independent M0 checker. Child stdout is parsed and independently re-canonicalized, and representative transition and rejection bytes are frozen as exact goldens. Passing evidence is checker- and surface-relative: the memory loader is observably distinct from a production `SourceFileLoader`, and native extensions, uninstrumented Python or OS surfaces, other languages, and arbitrary future event profiles are outside this result.

## What M1 does not establish

M1 does not implement or validate L fixpoint semantics, R scheduling/frontiers, H durability/effect closure, graph mechanics, crash recovery, real consumers, comparative efficacy, production readiness, originality, or Lakatos progress. The engine verdict remains deferred.
