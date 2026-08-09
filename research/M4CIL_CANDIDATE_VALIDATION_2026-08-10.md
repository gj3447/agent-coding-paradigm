# M4C-IL Integrated Incremental Profile Candidate Receipt

> Status: **PROPOSED_PENDING_MEASUREMENT**. This is a self-excluded follow-up receipt for one bounded M4C-IL candidate profile. It is not a repository-wide milestone promotion, an outer-run completion claim, a performance result, an engine verdict, a production claim, an efficacy result, or a Lakatos progress verdict.

## Frozen subject

- Repository: `gj3447/agent-coding-paradigm`
- Commit: `016ecafcf9f96b074ae4019ef6bd56f4d127f827`
- Tree: `345fef72632bc452ccddff455d3dca1b757784bd`
- Parent: `496d9fd08ab5e3e70f4d05ca321dbb08329e58fd`
- Subject: `feat: add proposed M4C-IL integration profile`
- Subject delta: exactly 14 added M4C-IL-owned paths and 2,610 inserted lines
- Manifest status: `PROPOSED_PENDING_MEASUREMENT`
- Public profile: `flrh-m4cil-single-effect-incremental-reference/1`

This receipt follows the frozen subject and is not included in its 14-path manifest closure.

## What the subject demonstrates

The candidate executes one bounded public reference chain:

`step_f -> step_incremental_l (bootstrap) -> step_incremental_l (reuse) -> project_lr -> step_r -> project_h_intent -> DurableHarness`

The bootstrap incremental step consumes the frozen accepted event at logical time 1 and emits an explicit checkpoint. The reuse step consumes that exact checkpoint at logical time 2 with an empty delta batch, records at least one candidate cache hit, records zero candidate body evaluations, and passes its exact M2-compatible `LFixpointResult` to the existing LR projection. The two public M2 conformance calls performed by each incremental step are explicitly excluded from candidate reuse counters, so this is not a lower-total-runtime claim.

The happy path publishes and authorizes one low-risk effect, atomically commits it through the bounded M4B harness, records one exact M0 `ActionReceipt`, and leaves no pending intent. The recovery path kills a real child process with `os._exit(86)` after the durable fake destination mutates, reopens fresh durable objects, queries before retry, and reconciles to one confirmed effect without a second destination mutation.

The source-bound M4C-IL verifier rebuilds frozen inputs and reexecutes every public F, incremental-L, LR, R, and H stage rather than trusting stored adjacent outputs. It binds the bootstrap-to-reuse checkpoint lineage, exact M2-compatible fixpoint, durable checkpoint lineage, exact ActionReceipt, source-derived FSM evidence projection, and crash-worker envelope. Its JSON Schema is deliberately a closed structural envelope; exact inherited stage semantics come from source-bound reexecution rather than duplicated upstream schemas.

The projected outer trace stops at `HONOR_PENDING_INTERRUPT`, records `SLICE_CONFORMED`, `FSM_CONFORMANCE_PROJECTION_ONLY`, and `outer_reducer_executed=false`, while the durable run remains active.

## Local evidence

Environment:

- macOS `27.0`, Darwin `27.0.0 arm64`
- CPython `3.9.6`
- Git-history and receipt gates used APFS `TMPDIR=/tmp`; ExFAT temporary storage was excluded after a paired inherited-LR check exposed filesystem mode/history incompatibility.

Committed-clean aggregate command:

```text
TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:scripts python3 scripts/validate_m4cil.py --allow-proposed
```

Exact report:

```json
{"clean_process_descriptors":["happy:clean-a","crash_after_external_success:clean-a","happy:clean-b","crash_after_external_success:clean-b"],"clean_processes":4,"closure_mode":"committed-clean","crash_recovery_paths":1,"inherited_dependencies":36,"inherited_gate_state":"PASS","kind":"M4CILValidationReport","manifest_owned_paths":14,"public_pipeline_stages":7,"sensitivity_cases":16,"status":"PROPOSED_PENDING_MEASUREMENT","success_paths":2,"unit_test_gate":1,"verification_checks":10}
```

The aggregate passed the proposed M4C validator, the committed-clean M2-IL inherited validator, the measured direct LR validator, and their transitive M0, M1, M2, M3, M4A, and M4B non-regression gates.

Focused evidence:

- M4C-IL integration tests: 10/10 PASS
- Cross-consistent and redigested sensitivity cases: 16/16 detected, 0 escaped
- JSON Schema metaschemas: 3/3 PASS
- Contract/manifest/fixture schema bindings: 3/3 PASS
- Claim-boundary and verification-receipt schema closure attacks: rejected
- Manifest-owned closure: 14/14 exact
- Inherited dependency digests: 36/36 exact
- Clean process replays: 4/4 exact, covering happy and crash modes under two process profiles
- Nonrecursive candidate gate: 1/1 PASS in `331.250s`
- Full local discovery: 178 tests, `496.573s`, OK

The 16 frozen sensitivity cases are:

```text
bootstrap-checkpoint-digest
reuse-prior-checkpoint-digest
reuse-cache-hit-accounting
reuse-body-evaluation-accounting
final-fixpoint-digest
lr-fixpoint-binding
accepted-event-logical-time
bootstrap-delta-causation
r-frontier-logical-time
h-intent-proposal-id
durable-checkpoint-logic-lineage
receipt-input-root-binding
action-receipt-intent-id
durable-pending-count
fsm-trace-event
crash-worker-payload-digest
```

## Exact CI readback

- Workflow run: `31319921009`
- Job: `93261116393` (`conformance`)
- Event: `push`
- Head SHA: `016ecafcf9f96b074ae4019ef6bd56f4d127f827` (exact subject)
- Conclusion: `success`
- Runner: Ubuntu 24.04 x64
- Python: CPython 3.12.13
- Job interval: `2026-08-09T14:59:56Z` to `2026-08-09T15:07:35Z`
- Full CI discovery: 178 tests, `374.691s`, OK
- Run URL: https://github.com/gj3447/agent-coding-paradigm/actions/runs/31319921009
- Job URL: https://github.com/gj3447/agent-coding-paradigm/actions/runs/31319921009/job/93261116393

The CI workflow directly passed M0, M1, M2, M3, and the measured LR validators. Full test discovery then passed the proposed M4A, M4B, M4C, M2-IL, and M4C-IL candidate gates. The M4C-IL candidate gate invokes its aggregate validator without recursively invoking itself.

## Frozen subject artifacts

| Path | SHA-256 |
|---|---|
| `docs/M4CIL_INTEGRATED_INCREMENTAL_SLICE.md` | `91ded6073d0fec075bb598c2a5dbb0ffb81ef4ac11874b1200d1570d9b8b2f29` |
| `fixtures/m4cil/cases.json` | `cc189014f03fd3036fa78dbd57ff53b2636d4da22e35eaf935f3567ef25ed5c8` |
| `scripts/check_m4cil_sensitivity.py` | `cac71b553fafdf231330aa474cef842083afcd79b5accb4e2b14db9a58370332` |
| `scripts/m4cil_fixtures.py` | `787320c01aefe55b813249082f61bd4d30e7a88c71b6f747392a55330ba9eebd` |
| `scripts/m4cil_verifier.py` | `2b6ffed0bed9f1d513ea9ee8a1b2ec2e8317b9ca0bec3fb5fd8c4801d5f8dbe8` |
| `scripts/run_m4cil_replay.py` | `9aa759087aba86c2b297b96830c5caa4944839001117c09c0f2030b06fd9f56d` |
| `scripts/validate_m4cil.py` | `0f326cb0c28fea5f45ccff752805cd927a1f3cf817d7fa73d851a2f0e12ec352` |
| `spec/m4cil-integration-contract.v1.json` | `fcb7cffcdf9c8a6ffede9bb041d832e0d2ac305dbdfb73311e0ea37e0ec880cd` |
| `spec/m4cil-manifest.v1.json` | `834893f78fbb523102d5d7e229a1bae0a3acef35c87e0a13f2358d1089918c91` |
| `spec/schema/m4cil-fixtures.v1.schema.json` | `ae65d568a23413cc40214314471da6647265a6af9a0b9613d6347ac6eb50f3fd` |
| `spec/schema/m4cil-integration-contract.v1.schema.json` | `c89c5cd4a7c2af4af6b0b1658a813f733330f7cafa195e513cf935c81b7da41b` |
| `spec/schema/m4cil-manifest.v1.schema.json` | `9892dcde1cd7235440932556ec55bb4e798fc406f9d60c367cb62aaa12606483` |
| `tests/test_m4cil_candidate_gate.py` | `578667a20735ecfcf9a1eb7542cf2a4c39d7900d2b864068e9447f2fbef1a320` |
| `tests/test_m4cil_integration.py` | `c66555a74576f20b96c22f9bd64734fae54bf3f31de37bcec554d7e766cb1f50` |

## Explicit nonclaims

This receipt does not establish any of the following:

- outer FSM execution, `VERIFIED_COMPLETE`, `SUCCEEDED`, or full run completion
- a general persistent incremental runtime or persistent filesystem/database storage for L checkpoints
- lower total runtime, lower latency, lower memory use, or performance superiority
- multi-event or multi-effect scheduling, or durable R state
- a real destination, real policy authority, authenticated external evidence, or exactly-once effects
- general crash recovery beyond the frozen bounded cut
- integrated production runtime, security, deployment, or operational readiness
- two independent real consumers, interoperability, or engine promotion
- comparative efficacy, originality, scientific confirmation, or Lakatos progress

The repository-wide engine verdict remains `defer`. M4C-IL remains proposed candidate evidence pending separate frozen measurement and broader operational closure.
