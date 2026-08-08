# M0 Validation Receipt

Date: 2026-08-08
Scope: repository-local, pinned-checker contract conformance only

## Frozen subject

- Subject commit: `1f0bfd158036a5662eea03dafc424bf67e247ba2`
- Subject tree: `addabd16ba61820b5a71aa40f6e29c38f65495df`
- Python: `3.9.6`
- `jsonschema`: `4.25.1` (pinned by `requirements-m0.txt`)

The receipt is intentionally a follow-up artifact: its subject is the preceding
contract commit, so it does not claim to hash itself.

## Commands

```bash
python3 scripts/validate_m0.py
python3 -m unittest discover -s tests -v
find spec fixtures research -type f -name '*.json' -print0 \
  | xargs -0 -n1 python3 -m json.tool >/dev/null
git show --check --oneline 1f0bfd158036a5662eea03dafc424bf67e247ba2
```

## Exact result summary

```text
M0 PASS {"canonical_different":2,"canonical_equal":1,"canonical_reject":4,"default_negation":4,"derivation_identity":3,"effect_critical_states":5,"effect_identity":3,"frontier":3,"fsm_interrupts":3,"fsm_terminals":9,"fsm_traces":18,"fsm_transitions":25,"invalid_protocol":13,"loop_bound_states":20,"loop_bound_transitions":25,"manifest_contracts":8,"manifest_fixtures":5,"manifest_schemas":9,"manifest_tools":2,"retraction":3,"retraction_conflicts":3,"schemas":9,"stratification":2,"truth":4,"valid_protocol":10}
BOUNDARY pinned-checker conformance only; global consistency, runtime, recovery, efficacy, originality, and Lakatos progress remain unjudged

Ran 6 tests in 0.177s
OK
```

All repository JSON files parsed successfully. The subject commit passed Git's
whitespace/error check.

## Normative artifact hashes

These hashes cover the de-duplicated union of the manifest's normative
contracts, self-validating schemas, and conformance fixtures.

| SHA-256 | Path |
|---|---|
| `a81a44d3d572cc43bc459adc62374ee261549758e0687263a887a3774a863da2` | `spec/schema/protocol.v1.schema.json` |
| `c8095c12528826de34f2ee94b8c7eb38303733faf14c26ed32aac90e41e5e77a` | `spec/engine-decision.v1.json` |
| `e16f792a4f2bba03fe8b7f796ac65fed0f62fa23196a55ef4aad0a68bd2e7683` | `spec/claims.v1.json` |
| `87b14b371d8572125164326b74d0574a11b00e4f11ba0c117dfe84644d1a7ccc` | `spec/canonicalization.v1.json` |
| `b727ae4d112b9df93d58d30daa6e4efcade122ec3bc3d84f6ec5b6ba502e2a74` | `spec/logic-semantics.v0.json` |
| `043d8038f8bf91d7f60c2b57f7fcf788e25684eed6409f184b607fae227537ea` | `spec/run-fsm.v1.json` |
| `223369c96d50db122f5d23133b8d2dce36768bd3b31adbca1626c86c3bcc5afa` | `spec/loop-contract.v1.json` |
| `9911270fad99a0bcac2faf6fd24fcab359be3849178be73304c31822b3594241` | `spec/m0-manifest.v1.json` |
| `6daf0e0f835f562c835092c94a714937823bde247e6ab609093df99c9a81f3f6` | `spec/schema/engine-decision.v1.schema.json` |
| `f2920e14f382c444d703b98a1d956de9e44e31d15a1fe3d6ea1d997b7ed4309c` | `spec/schema/claim-ledger.v1.schema.json` |
| `4e5721c87f47dccc52c1df5c8b2f783037c8da90b0a970d8b09c82875c92f949` | `spec/schema/canonicalization.v1.schema.json` |
| `fc84ed3fc7a96764565cdcd1856c4e704e3de9c75c9f1c757d32bce9f09d0d0b` | `spec/schema/logic-semantics.v0.schema.json` |
| `0f8eafa147b69f9d20b45260749f62d131ca8f12668088ad853dfec627f06b48` | `spec/schema/run-fsm.v1.schema.json` |
| `7880b45c94d96d04bfbc82b985dd07dad6dd7db4901b83baf9e57d8a02fd2e0a` | `spec/schema/run-fsm-traces.v1.schema.json` |
| `5faf124ff85a52cba71cdc91b1d5556a8c82aad1f12a0a822facc240746696c7` | `spec/schema/loop-contract.v1.schema.json` |
| `bec1bf6c0cd210ee5f072eae6a781a4cf943d871511af848473b8093343b9b3c` | `spec/schema/m0-manifest.v1.schema.json` |
| `34f66498e3e1d662535cb76e28fbf21c1ed435de60f6df1351d22046571dc8ba` | `fixtures/m0/valid/protocol-objects.json` |
| `58b266c6b4bd3b1fe93fc6a7ffae36901ed8acd6623cf265fd7747748dae09ff` | `fixtures/m0/invalid/protocol-mutations.json` |
| `99967b9ab8b095140274337c968e305672c0ca5f163dc47f6f21ae97b324106c` | `fixtures/m0/logic/cases.json` |
| `1984f7c617b336342f4166d19aa09d12a38264ce207cbcde1ccd3a7db0a00eac` | `fixtures/m0/canonical/cases.json` |
| `0e94cc59990c696a803eda27f0ccde139fedd4b6d1cfca3efd0f65705b1b1c76` | `spec/run-fsm-traces.v1.json` |

## Validator-profile disclosure

The bundled SYMPOSIUM FSM validator reported 72 dialect-shape errors and its
trace runner returned `FAIL`; the bundled loop validator reported 32 profile
errors. The exact reasons are recorded in
`FSM_VALIDATOR_COMPATIBILITY_2026-08-08.md` and
`LOOP_VALIDATOR_COMPATIBILITY_2026-08-08.md`. None is represented as a pass or
used as an M0 gate. M6 remains open specifically because a second independent
implementation or conformance runner does not yet exist.

## Non-claims

This receipt does not demonstrate an F/L/R/H runtime, global logical
consistency, incremental equivalence, crash recovery, graph round-trip,
comparative benefit, originality, production readiness, or Lakatos progress.
Those require M1-M7 evidence and, for scientific progress, prospective
registration plus an independent deterministic judge.
