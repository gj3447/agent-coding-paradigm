# M4C Integrated Verification Profile Candidate Receipt

> Status: **PROPOSED_PENDING_MEASUREMENT**. This is a self-excluded follow-up receipt for a bounded candidate profile. It is not a milestone promotion, engine verdict, production claim, efficacy result, or Lakatos progress verdict.

## Frozen subject

- Repository: `gj3447/agent-coding-paradigm`
- Commit: `b387a0cb8ffe9acde58abcd295e7692f1d17ad54`
- Tree: `d2841c5d546945737422a9e447218b06a118a0b7`
- Parent: `cb1f01685b724b3cd0ff0da184cffa1f3d3e657f`
- Subject: `feat: add bounded M4C integrated verification profile`
- Subject delta: exactly 14 added M4C-owned paths
- Manifest status: `PROPOSED_PENDING_MEASUREMENT`

This receipt follows the frozen subject and is not included in its 14-path manifest closure.

## What the subject demonstrates

The candidate executes one bounded public reference chain:

`step_f -> solve_l -> project_lr -> step_r -> project_h_intent -> DurableHarness -> verify_run`

The candidate also executes a real child-process crash at `after_external_success` using `os._exit(86)`, reopens the SQLite harness and durable fake adapter in a fresh process context, queries before retry, and reconciles to one confirmed effect without a second destination mutation.

The independent M4C verifier rebuilds frozen inputs and reexecutes every public F/L/LR/R/H stage instead of trusting stored adjacent outputs. It binds the exact M0 `ActionReceipt`, detached M4B consistency report, source-derived `run-fsm.v1` transition/authority/evidence/guard projection, and the crash worker envelope.

The projected outer trace stops at `HONOR_PENDING_INTERRUPT`, records `SLICE_CONFORMED`, and explicitly records `outer_reducer_executed=false` and `FSM_CONFORMANCE_PROJECTION_ONLY`.

## Local evidence

Environment:

- macOS `27.0`, Darwin `27.0.0 arm64`
- CPython `3.9.6`

Aggregate command:

```text
python3 scripts/validate_m4c.py --allow-proposed
```

Exact report:

```json
{"clean_process_descriptors":["happy:clean-a","crash_after_external_success:clean-a","happy:clean-b","crash_after_external_success:clean-b"],"clean_processes":4,"crash_recovery_paths":1,"fsm_transitions":7,"inherited_dependencies":18,"inherited_nonregression_gates":7,"kind":"M4CValidationReport","manifest_owned_paths":14,"public_pipeline_stages":6,"sensitivity_cases":16,"status":"PROPOSED_PENDING_MEASUREMENT","success_paths":2,"unit_test_gate":1,"verification_checks":9}
```

The aggregate passed all inherited M0, M1, M2, M3, measured direct LR, proposed M4A, and proposed M4B non-regression gates.

Focused evidence:

- M4C integration tests: 9/9 PASS
- Cross-consistent and redigested forgery sensitivity cases: 16/16 detected, 0 escaped
- JSON Schema metaschemas: 3/3 PASS
- Contract/manifest/fixture schema bindings: 3/3 PASS
- Inherited dependency digests: 18/18 exact
- Clean process replays: 4/4 exact, covering happy and crash modes under two process profiles
- Full local discovery: 149 tests, `171.624s`, OK

## Exact CI readback

- Workflow run: `31309658427`
- Job: `93235372649` (`conformance`)
- Event: `push`
- Head SHA: `b387a0cb8ffe9acde58abcd295e7692f1d17ad54` (exact subject)
- Conclusion: `success`
- Runner: Ubuntu 24.04 x64
- Python: CPython 3.12.13
- Job interval: `2026-08-09T10:59:01Z` to `2026-08-09T11:02:18Z`
- Full CI discovery: 149 tests, `110.598s`, OK
- Run URL: https://github.com/gj3447/agent-coding-paradigm/actions/runs/31309658427
- Job URL: https://github.com/gj3447/agent-coding-paradigm/actions/runs/31309658427/job/93235372649

The CI workflow directly passed M0, M1, M2, M3, and LR validators. Full test discovery then passed the proposed M4A, M4B, and M4C candidate gates; the M4C candidate gate invokes the aggregate validator without recursively invoking itself.

## Frozen subject artifacts

| Path | SHA-256 |
|---|---|
| `docs/M4C_INTEGRATED_SLICE.md` | `117c2e124f72aba9b81aa628d4c9aa5afc0b043f27986ea980f0a4c1b4785b2c` |
| `fixtures/m4c/cases.json` | `bd8f12c206c2512826bb489e9b51c31a21a8939ae1d00e25798fd47437e977fd` |
| `scripts/check_m4c_sensitivity.py` | `42ec8b0c27e03e845137e5b62dc23940f0ad6d662627d4ea3ffe3f3990b968db` |
| `scripts/m4c_fixtures.py` | `dbaea9aa53dd81688c45cd6fa6d701685c925e1636698d7d284ed65fc3550eee` |
| `scripts/m4c_verifier.py` | `c3e73aab5376a684c17a1293049b8ef07ebdf7ebd9d764bcba48c87681d4dacc` |
| `scripts/run_m4c_replay.py` | `045585b7bfb49d8df68a96a4c4d88896c368b97712b758e8c47451afe283547f` |
| `scripts/validate_m4c.py` | `6c381b5540779aa80367bc9ca246f8d86d3ec0f3fed6725a087ff3ca7f746362` |
| `spec/m4c-integration-contract.v1.json` | `aeb06aa24af5b06729d8f54663b46abfb8fd68a858f5b75b695a4af561679efa` |
| `spec/m4c-manifest.v1.json` | `35a389a406e069f4e0cc6cb0b82b9a54b2cd9ab96047a608701e161ee7864898` |
| `spec/schema/m4c-fixtures.v1.schema.json` | `79a60075d291866e514a8e04846a85e65d795084fe743586ceb3e4c0c6eaa75d` |
| `spec/schema/m4c-integration-contract.v1.schema.json` | `0352bf564aa8720cf33be549b6bca65177f6a7555afd6287f7ae75737e6a013d` |
| `spec/schema/m4c-manifest.v1.schema.json` | `2ca72c28ff129b0f53e8f571d0ce33fd629cac23fa7897c848fabd66227d272d` |
| `tests/test_m4c_candidate_gate.py` | `eafd08ed998fdad4c25e94f6201cd6e1164aa6b246150d455fd06937026fdba4` |
| `tests/test_m4c_integration.py` | `2c0f20a1f00c940e1f0616cc641185f0eb6410cf9790a801fa26a945ddc19e57` |

## Explicit nonclaims

This receipt does not establish any of the following:

- outer FSM execution or `SUCCEEDED`
- persistent incremental L reuse
- general eligibility correctness or frontier truth
- a real destination, real policy authority, authenticated external evidence, or exactly-once effects
- general crash recovery beyond the frozen bounded cut
- integrated production runtime, security, deployment, or operational readiness
- two independent real consumers, interoperability, or engine promotion
- comparative efficacy, originality, scientific confirmation, or Lakatos progress

The engine verdict remains `defer`. M4A, M4B, and M4C remain proposed candidate evidence pending separate frozen measurement and broader operational closure.
