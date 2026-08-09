# M2-IL Persistent Incremental L Candidate Receipt

> Status: **PROPOSED_PENDING_MEASUREMENT**. This is a self-excluded follow-up receipt for one bounded M2-IL candidate profile. It is not a repository-wide milestone promotion, a performance result, an engine verdict, a production claim, an efficacy result, or a Lakatos progress verdict.

## Frozen subject

- Repository: `gj3447/agent-coding-paradigm`
- Commit: `62622b3ddccb02970ede9d336a9eec31957adeda`
- Tree: `4eb3c2de377e61c1149178c36dce86130308a333`
- Parent: `864c40bd0a095854f01d8936db6ecf8767830e36`
- Subject: `feat: add proposed M2-IL incremental logic profile`
- Subject delta: exactly 22 added M2-IL-owned paths
- Manifest status: `PROPOSED_PENDING_MEASUREMENT`
- Public profile: `flrh-l-persistent-incremental/1`
- Public API: `step_incremental_l`

This receipt follows the frozen subject and is not included in its 22-path manifest closure.

## What the subject demonstrates

The candidate accepts an explicit prior checkpoint, an unchanged bounded M2 rule bundle, a fact-delta prefix, and an explicit logical time. It constructs a candidate `LFixpointResult`, emits the next explicit checkpoint and a reuse receipt, and accepts a success only when the candidate fixpoint is canonical-byte equal to the pinned public M2 result.

The candidate path does not invoke the inherited M2 full derivation or prior-materialization derivation. Its hot no-op probe fatal-patches `_derive`, `_parse_prior`, body evaluation, and provenance construction while producing four cache hits and zero candidate body or provenance evaluations. The frozen disjoint-chain sequence reports candidate cache hits `0, 4, 4, 2`; the final hot-root retraction preserves the two cold-chain entries while executing the two invalidated hot evaluations.

Two public M2 calls remain deliberately outside the candidate counters: one establishes exact inherited rejection precedence, and one performs the differential conformance comparison. The receipt therefore demonstrates actual reuse inside the candidate construction path, not lower total wall time or performance superiority for the complete public call.

The independent stdlib-only oracle runs with both production logic packages import-blocked. It covers signed heads and bodies, signed derived deltas, two-support retraction, rootless positive-cycle deletion, conflict projection, and lower-stratum default behavior through `NEITHER`, `TRUE_ONLY`, `BOTH`, and `FALSE_ONLY` states.

The checkpoint and result schemas are closed. Exact inherited M2 `LRejection` values pass through unchanged and validate as the eight-key M2 wire without an invented rejection digest.

## Local evidence

Environment:

- macOS `27.0`, Darwin `27.0.0 arm64`
- CPython `3.9.6`

Committed-clean aggregate command:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:scripts python3 scripts/validate_m2il.py --inherited
```

The aggregate passed the M2-IL candidate validator, M0, M1, M2, M3, and the measured direct LR validator on the exact committed subject. The LR readback was:

```text
OK {"ambient_paths":10,"clean_process_descriptors":["replay:clean-a","replay:clean-b","ambient:clean-a","ambient:clean-b","semantic:clean-a","semantic:clean-b"],"clean_processes":6,"inherited_nonregression_gates":4,"lr_conformance_test_gate":1,"manifest_artifacts":34,"oracle_comparisons":8,"public_step_r_publication_chains":8,"rejection_paths":24,"semantic_axes":14,"status":"MEASURED_REFERENCE_CONFORMANCE","success_paths":8}
M2IL inherited LR gate: PASS
M2IL PROPOSED_PENDING_MEASUREMENT validator PASS (nonrecursive; inherited gates independently runnable)
```

Focused evidence:

- M2-IL tests: 17/17 PASS
- Candidate-path semantic mutants: 13/13 killed, 0 escaped
- Candidate clean-process replays: 2/2 exact
- Independent stdlib oracle clean process: 1/1, with production imports denied
- Frozen replay prefixes: 11/11 accepted with exact step digests
- Manifest-owned closure: 22/22 exact
- Inherited dependency digests: 19/19 exact
- Public package surface: exactly `step_incremental_l`
- Nonrecursive candidate discovery gate: 1/1 PASS
- Full local discovery: 167 tests, `381.101s`, OK

The 13 frozen sensitivity cases are:

```text
candidate-path-full-recompute
fake-hit-cached-body-still-executes
support-as-boolean
no-reverse-closure
rootless-scc
wrong-default-false-both
identity-last-write
ignore-forged-checkpoint
trust-forged-cache
order-dependence
caller-mutation
ambient-access
oracle-calls-sut
```

## Exact CI readback

- Workflow run: `31314426520`
- Job: `93247262811` (`conformance`)
- Event: `push`
- Head SHA: `62622b3ddccb02970ede9d336a9eec31957adeda` (exact subject)
- Conclusion: `success`
- Runner: Ubuntu 24.04 x64
- Python: CPython 3.12.13
- Job interval: `2026-08-09T12:53:54Z` to `2026-08-09T12:58:06Z`
- Full CI discovery: 167 tests, `142.508s`, OK
- Run URL: https://github.com/gj3447/agent-coding-paradigm/actions/runs/31314426520
- Job URL: https://github.com/gj3447/agent-coding-paradigm/actions/runs/31314426520/job/93247262811

The CI workflow directly passed M0, M1, M2, M3, and the measured LR validator. Full test discovery then passed the proposed M4A, M4B, M4C, and M2-IL candidate gates. The M2-IL candidate gate invokes its aggregate validator without recursively invoking itself.

## Frozen subject artifacts

| Path | SHA-256 |
|---|---|
| `docs/M2IL_INCREMENTAL_L.md` | `b49361183eda89f311831cef3b8d4b0baec0ea45ee1c9a0e7c4ed522775369bb` |
| `fixtures/m2il/cases.json` | `fdff3d607ae349f474d24a1886c41a6e8e306c4c69699a33d5d764256c3d0a07` |
| `fixtures/m2il/golden/insertion-reuse.fixpoint.json` | `7ac74957efac1db408b1f3d6d7e9818e92431838705026c0de5701f7d0378ae9` |
| `fixtures/m2il/golden/retraction-reuse.fixpoint.json` | `5f6da1c91f8f5656fbfc0c626fc5cc9f537c2e68445918c68eb2e3ec66951123` |
| `scripts/check_m2il_ambient.py` | `f900d922b8ae0b73dad8e1e8fc5b67404353a1c61042fb1195fd357e424808ea` |
| `scripts/check_m2il_semantic_mutants.py` | `35401049f0f5cad854ae695c6c5c88204879226fb0173d65e7fc187cadc03b24` |
| `scripts/m2il_fixtures.py` | `560a6deafa4139808390cff8db808871ef62bf16482e58d3d70489bd01b0fb9a` |
| `scripts/m2il_guard.py` | `41fd212776db1a11bd9174c7877065688cc1a4503b85f735b883c5a175070f9d` |
| `scripts/m2il_oracle.py` | `75c3e947c71d9a5d19d6b822251244b41dfd6096db99d63d58a5c164d10f8c9d` |
| `scripts/run_m2il_replay.py` | `eb5c93feec4f73dc5f6dfcd8539c93e79e96f64d2fd1052f1b9bdc1f44d4a0ca` |
| `scripts/validate_m2il.py` | `477cd0c3dae6d195e9a71bc143dd1fb8d03a9aa6a2ba3f9f364a2f2b1e440bad` |
| `spec/m2il-incremental-contract.v1.json` | `d29b026322b49ee406837ebf9dbf64b350fcfe1e88da530f842abbff4c51aaa0` |
| `spec/m2il-manifest.v1.json` | `44c32802c0a7e3e5c3e81570f9cf62a6fa85f40965391d8a80bb976f8af16456` |
| `spec/schema/m2il-contract.v1.schema.json` | `ee67ede19e541934b9117b95cdd4ad939fe46b99e012fcb81c3b34a9175c81d5` |
| `spec/schema/m2il-fixtures.v1.schema.json` | `0db63fb5ed5f280e473bc292c5812cfbe87ab5875157e989e787565223cc8e45` |
| `spec/schema/m2il-incremental.v1.schema.json` | `7b8be90186b2bed9716dafbf2fe6f640c87f98cd6cdd31c7086e93ec53f8be81` |
| `spec/schema/m2il-manifest.v1.schema.json` | `d1f7eaf66265370d1147bbf0b347e4badb48c82beb8f5c1d5aa8aae57ea8c24e` |
| `src/flrh_logic_incremental/__init__.py` | `97a6171a183ca429f894fc68ff084fd141f7f2fae3fe25cb8c2c8a0b06ee4161` |
| `src/flrh_logic_incremental/canonical.py` | `d01c7c5abe65d8551f887f44e4815bbc5b60fcbe7b8d6b67e3869323f9d0fb39` |
| `src/flrh_logic_incremental/incremental.py` | `996760a92e6860055d3fc81114f9428d5ca235c19d327931b685acbf305161c4` |
| `tests/test_m2il_candidate_gate.py` | `ee0bc187daee86c4fdce0a477dc115366a4671b6f348eb486eb39e74ef9b3e8c` |
| `tests/test_m2il_incremental.py` | `e46f3234060f0b18762588ae53334b6256dce13efff6ee12801ea643f1894841` |

## Explicit nonclaims

This receipt does not establish any of the following:

- lower total runtime, lower latency, lower memory use, or performance superiority
- persistent filesystem or database storage; persistence here means explicit cross-invocation checkpoint reuse
- general Datalog, variables, rule migration, unbounded evaluation, or unsupported M2 semantics
- integrated LR, R, H, M4C, or outer-FSM execution using this incremental profile
- a real destination, effect execution, exactly-once behavior, production readiness, deployment, or security
- two independent real consumers, interoperability, or engine promotion
- comparative efficacy, originality, scientific confirmation, or Lakatos progress

The repository-wide engine verdict remains `defer`. M2-IL remains proposed candidate evidence pending a separate frozen measurement and truthful top-level claim update.
