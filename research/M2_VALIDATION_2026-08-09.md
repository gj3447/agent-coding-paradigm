# M2 Validation Receipt

Date: 2026-08-09
Scope: bounded Python ground/propositional stratified-L reference mechanics and frozen corpus only

## Frozen subject

- Subject commit: `bd4c5a9f5ac3ce73b03eead9468b5ce0e66c9499`
- Subject tree: `bf3ba50e1e105b6ad3534cbef1d4cc2f8cfd4c58`
- Local runtime: CPython `3.9.6`, macOS `27.0` build `26A5378n`, arm64
- CI runtime: CPython `3.12.13`, GitHub-hosted Ubuntu `24.04`, x64
- `jsonschema`: `4.25.1`
- Dependency-file SHA-256: `44ff0dc2f1e40311b8239e83146749ab9d9cee2a650e699f5464755d552ee20d`

This receipt is intentionally a follow-up artifact. Its subject is the preceding
implementation-and-repair commit, so it does not claim to hash itself.

## Commands

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_m0.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_m1.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_m2.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_m2.py --show-digests
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
find spec fixtures research -type f -name '*.json' -print0 \
  | xargs -0 -n1 python3 -m json.tool >/dev/null
git show --check --oneline bd4c5a9f5ac3ce73b03eead9468b5ce0e66c9499
```

Remote readback:

```bash
gh run view 31289146287 --repo gj3447/agent-coding-paradigm
```

## Exact result summary

```text
M2 PASS {"m2_ambient_guard_categories":8,"m2_ambient_guard_processes":2,"m2_bindings":3,"m2_byte_mismatches":0,"m2_canonical_equal":3,"m2_canonical_reject":6,"m2_canonical_typed_rejection_checks":1,"m2_clean_process_comparisons":33,"m2_clean_process_runs":66,"m2_control_mutants_detected":13,"m2_dynamic_authority_calls":0,"m2_equivalence_pairs":2,"m2_exact_result_goldens":2,"m2_guard_self_tests":11,"m2_implementation_files":3,"m2_import_metadata_checks":10,"m2_inherited_dependencies":5,"m2_input_ceiling_boundary_checks":3,"m2_kernel_ambient_attempts":0,"m2_kernel_path_ambient_attempts":0,"m2_kernel_path_executions":4,"m2_kernel_path_input_mutation_attempts":0,"m2_kernel_path_rejections":1,"m2_kernel_path_successes":3,"m2_nested_fact_delta_checks":8,"m2_public_root_exports":1,"m2_rejection_cases":14,"m2_rejection_order_pairs":8,"m2_schemas":4,"m2_sequence_derived_delta_checks":12,"m2_sequence_steps":9,"m2_sequences":3,"m2_static_imports":7,"m2_success_cases":10,"m2_unicode_application_key_cases":1}
BOUNDARY measured: 10 success, 14 rejection, 3 sequences/9 steps, 66 clean runs/33 comparisons, 11 guard self-tests, 13 mutants
BOUNDARY not established: general Datalog/negation, R/H, durability, engine, efficacy

Ran 37 tests
OK
```

The local M0 and M1 prerequisite validators also returned `PASS`. All repository
JSON files parsed successfully, `git diff --check` passed, and the subject
commit passed Git's whitespace/error check.

GitHub Actions run
[`31289146287`](https://github.com/gj3447/agent-coding-paradigm/actions/runs/31289146287)
checked out the exact subject SHA and passed M0, M1, M2, and all 37 tests on
CPython 3.12.13. The x64 Ubuntu 24.04 conformance job completed successfully in
46 seconds. Its reported `headSha` exactly equals the subject commit.

## Semantic, process, and guard evidence

- Ten successful cases and fourteen complete typed-rejection cases matched the
  frozen schemas and independent oracle expectations.
- Three stateful sequences covered nine steps, including two-support retention,
  complete reverse-closure removal, positive-cycle deletion, duplicate delivery,
  and a final double-retraction rejection.
- Three input-ceiling checks admitted 10,000 duplicate inputs, rejected 10,001
  before prior evaluation, and bound the exact typed rejection. Eight malformed
  ordering pairs produced byte-identical rejections, including nested and
  cross-level permutations. A non-NFC object key also returned a canonical typed
  rejection without copying the invalid key into the rejection path.
- Every accepted step matched an independent naive full recomputation after
  excluding only numeric evaluation counters. `evaluation_mode` remained bound
  to `full_recompute`.
- Thirty-three cases or sequence comparisons ran in two independently spawned
  profiles: 66 child executions, 33 exact byte comparisons, zero mismatches.
- Two further guarded-import processes agreed on one canonical report. Eleven
  positive guard self-tests and ten import-metadata checks passed.
- Thirteen deliberate ambient, mutation, adapter, and conditional-path mutants
  were detected. Four non-empty real-kernel paths ran under the locked guard:
  three successes and one late rejection, with zero ambient or caller-input
  mutation attempts.
- The package root exports only `solve_l`; M1 remains `step_f`-only. Opaque
  caller atom/provenance fields remain inert, and no R- or H-owned value is
  emitted.

The local child profiles used fresh randomized directories. The table hashes a
normalized compact sorted-JSON descriptor in which those paths are replaced by
stable placeholders; it does not pretend that temporary path strings matched.

| Profile | Hash seed | Timezone | Poison marker | Descriptor SHA-256 |
|---|---:|---|---|---|
| replay-a | 13 | UTC | `m2-a` | `987bffe4857ab18c5be8fc2fa815d40ec3922e6babbe2db134e47f03664b1856` |
| replay-b | 89 | Pacific/Honolulu | `m2-b` | `d2ed925a26d251fc3cbd9884f72c4c34f77bae9664e53ea49f15399866cc2a93` |
| guard-a | 29 | UTC | `m2-guard-a` | `3d926c8c846ce3a2eddff560e09784bea78676001377888eb641f65887ee4752` |
| guard-b | 73 | Asia/Seoul | `m2-guard-b` | `6a11f4d22c462614a5d36c3ff7a15efbd20ec65fa5866c72bc18826b9acda8b3` |

Every profile also fixed `LANG=C`, `LC_ALL=C`, `PATH=/bin:/usr/bin`, and
`PYTHONDONTWRITEBYTECODE=1`; each `HOME` pointed inside its fresh process root.
The descriptor digest is SHA-256 over the corresponding UTF-8 line below,
without a trailing newline. Object keys are already in lexical order.

```jsonl
{"cwd":"<fresh-process-root>","env":{"FLRH_AMBIENT_POISON":"m2-a","HOME":"<fresh-process-root>/home","LANG":"C","LC_ALL":"C","PATH":"/bin:/usr/bin","PYTHONDONTWRITEBYTECODE":"1","PYTHONHASHSEED":"13","TZ":"UTC"}}
{"cwd":"<fresh-process-root>","env":{"FLRH_AMBIENT_POISON":"m2-b","HOME":"<fresh-process-root>/home","LANG":"C","LC_ALL":"C","PATH":"/bin:/usr/bin","PYTHONDONTWRITEBYTECODE":"1","PYTHONHASHSEED":"89","TZ":"Pacific/Honolulu"}}
{"cwd":"<fresh-process-root>","env":{"FLRH_AMBIENT_POISON":"m2-guard-a","HOME":"<fresh-process-root>/home","LANG":"C","LC_ALL":"C","PATH":"/bin:/usr/bin","PYTHONDONTWRITEBYTECODE":"1","PYTHONHASHSEED":"29","TZ":"UTC"}}
{"cwd":"<fresh-process-root>","env":{"FLRH_AMBIENT_POISON":"m2-guard-b","HOME":"<fresh-process-root>/home","LANG":"C","LC_ALL":"C","PATH":"/bin:/usr/bin","PYTHONDONTWRITEBYTECODE":"1","PYTHONHASHSEED":"73","TZ":"Asia/Seoul"}}
```

For example, copy one line exactly and run
`printf '%s' "$descriptor" | shasum -a 256`. The placeholder records only the
deliberately variable temporary directory, not an omitted environment input.

## Artifact hashes

The table covers every unique M2 manifest closure path plus the pinned
dependency file.

| SHA-256 | Path |
|---|---|
| `65f8ae41c4c5c6c11f8298b77b477d19a31f2b0dc9ede058639183960cf4cd9e` | `spec/m2-logic-contract.v1.json` |
| `a39e152397693b3e1a026c1e561a1c955ba77f753f695f231d8768d80a7c4fa0` | `spec/schema/m2-logic.v1.schema.json` |
| `c792eb1fbea2e8e430cd7d0452b8e3ed290f2488dd297b107d3cd5a92f139200` | `spec/m2-manifest.v1.json` |
| `a81a44d3d572cc43bc459adc62374ee261549758e0687263a887a3774a863da2` | `spec/schema/protocol.v1.schema.json` |
| `87b14b371d8572125164326b74d0574a11b00e4f11ba0c117dfe84644d1a7ccc` | `spec/canonicalization.v1.json` |
| `b727ae4d112b9df93d58d30daa6e4efcade122ec3bc3d84f6ec5b6ba502e2a74` | `spec/logic-semantics.v0.json` |
| `3f914944c9a7f0084fa0f725923489d8cd6feb5e70d510ffa5d54b5c20395c4d` | `spec/schema/m1-kernel.v1.schema.json` |
| `cd1360e0db9024cc6b03abde4a4d28e56aea82f901577bd2c4eae0cbdb5700b8` | `fixtures/m1/golden/observe-with-effect.transition.json` |
| `14d7962411d3127bf07ac03a893042b5c0f47cddb693b63ff54d96601c104b3a` | `spec/schema/m2-logic-contract.v1.schema.json` |
| `a63f6cd24e935112f07df25da0002e7d012f1f944bc5a93e287a0a887f36cc92` | `spec/schema/m2-fixtures.v1.schema.json` |
| `86cd43ee18f7499b4061fcd3a042dde12eb2de71936235020fff204cfcc52f8a` | `spec/schema/m2-manifest.v1.schema.json` |
| `e05c59628de8e7c4c6f30613d97fba6a06fb5fb5012b87eae7f0189f2e6e8dcf` | `fixtures/m2/cases.json` |
| `5a03b388701f65bb2d179b4388a2f2f5159e3bb8c5fb1b4457f79617d5e372bb` | `fixtures/m2/golden/two-support-retraction.fixpoint.json` |
| `bfb97b8356a2477e7b0764c083f464a1d276d97aa7c8866aa8a7bb1ebc7abfae` | `fixtures/m2/golden/negative-cycle.rejection.json` |
| `94fcebb1aeb5f6fb88819369796114e1970cd395574a34a66bc09eacb715cf37` | `src/flrh_logic/__init__.py` |
| `ace2c768436035396c94d0c2690bd0692380a19e20ae8e9336aa325ee4fad112` | `src/flrh_logic/canonical.py` |
| `461f92aa04939690123cd5ff124e05f19abcb51cc9fc332118e6e91e2648da58` | `src/flrh_logic/logic.py` |
| `76350084b1e85303793b4f2c576c87d761b21a1945c657b13d4af0d7517d8ea8` | `scripts/m1_guard.py` |
| `eb098c4e762f9f527ba1dea10b293b5500874d7a1e9b1d6ba0b42fb93631a49d` | `scripts/validate_m0.py` |
| `2aed96890d99b66c3c60e16a13b94aa94b87d45eb21abe3f6ffa45f7a7ac168b` | `scripts/m2_fixtures.py` |
| `bc0dfabace9d9dd0d29ce8ea88020b65c649868c188d54261fd339f79fae4acc` | `scripts/m2_oracle.py` |
| `e94638cc2cf25e7808f8d5b36df12271868ecd5d8319b48bafd43ecc11ccd11e` | `scripts/m2_guard.py` |
| `b7da8a353e2f45437ef6505d6829b97e7d05c9c4fa2cd61d2b503972624f0027` | `scripts/check_m2_ambient.py` |
| `e32bd2c4da374672d833b07e6818c0878bc580cf966c3402cac62dbb853ce24f` | `scripts/run_m2_replay.py` |
| `371c36d1071b61d25eb644e7ea073fc47e4683fdd04cc82dadabe1ba5e347f27` | `scripts/validate_m2.py` |
| `33484d1a1aa3919d473e7ae1a1e85b334c90f85454e84373fa736f559f357dea` | `tests/test_m2_logic.py` |
| `44ff0dc2f1e40311b8239e83146749ab9d9cee2a650e699f5464755d552ee20d` | `requirements-m0.txt` |

## Frozen result digests

Success and sequence entries below are the exact `fixpoint_digest` values
reported by the subject validator.

| Success case | Fixpoint digest |
|---|---|
| `default-negation-accepts-false-only` | `sha256:0f47bb5ff09027c82cb17575820340a45ce00095de88cae66452f712c4aa05fe` |
| `default-negation-after-empty-lower-stratum` | `sha256:d092d99b8f415d5f9eb7c8c3dab221ef048e50fc28c82a9e566f8be2a4e56553` |
| `default-negation-rejects-both` | `sha256:c431a5f2864f624c188f1f4f779e3f2a7129cce7a6e7cc26b5059d3077a06154` |
| `exact-budget-boundary` | `sha256:bbdc0540457f1c3e0db48f3f8c656cd90e17b72d79a4c3bb4bc96be3650788ab` |
| `exact-duplicate-batch-idempotent` | `sha256:eca4a6c0ddc603539fbce4b94993f4687a82b83d9f4fd17eb942cc6bfc62447d` |
| `four-truth-states` | `sha256:36c63895b5211b9b6a12b285b0f99281493cd9290b3b77fa953145ef35fd20f6` |
| `lower-stratum-completes-before-default-negation` | `sha256:1c335af9a9e8f9d49d9c2ff9bdae0142812513e9b2109403849e29dc6bcad884` |
| `m1-positive-seam` | `sha256:d75363b94e618b152fbedb3056832317e530916c8efad074f1ed92db458cebbe` |
| `opaque-authority-shaped-data-is-inert` | `sha256:4c6826923ab59177a9adb00cb99d7e1f5ee9f22bd9cd0d3eac04e7833dd3b32b` |
| `two-supports-and-downstream` | `sha256:496fa81379e0d39a69a5bd44c92e3c6b0e1411e11cc5d1d41aa9333eaaec98e7` |

| Sequence | Ordered step digests |
|---|---|
| `duplicate-then-double-retract` | `sha256:eca4a6c0ddc603539fbce4b94993f4687a82b83d9f4fd17eb942cc6bfc62447d`, `sha256:6295ede5bc6be710921eb9bbf9454fb69043d01ae409bd3a50a75c253d4708b9`, `sha256:a04e8235086303197e3bc3aaa0a3b9b016149de6cff1bc30af3af69458ffc75c`, typed rejection (no fixpoint digest) |
| `positive-cycle-delete` | `sha256:98831715c34bf82e9c0302abd66510917af59174169758f270c22923bc0a438a`, `sha256:8eef6fdb9cfee90ed935e07f77a174a9f80b3fc22ec7ee0eb16b43b28d0cdb58` |
| `two-support-retain-then-remove` | `sha256:496fa81379e0d39a69a5bd44c92e3c6b0e1411e11cc5d1d41aa9333eaaec98e7`, `sha256:9ddc7e9346e37270f12a6468f3bd456b45dc708c9f4ae2dfca4ea826c0e77b4d`, `sha256:a49218a84c464b9c8d10a0a441a17f92d2fe5ce99125910081e696416566711a` |

The exact golden-file byte hashes are included in the artifact table:
`5a03b388...72bb` for the two-support retraction fixpoint and
`bfb97b83...abfae` for the negative-cycle rejection.

## Non-claims

This receipt measures one finite ground/propositional stratified rule profile,
one Python implementation, the frozen corpus, the named CPython guard surfaces,
and the two local plus one CI environments above. It does not establish general
Datalog, arbitrary negation, universal purity or sandboxing, native-extension
behavior, persistent incremental maintenance, incremental performance, or
portability to another implementation language.

No R frontier/scheduling/backpressure kernel, H authority/effect closure,
integrated F/L/R/H runtime, persistence, crash recovery, real consumer,
production readiness, comparative benefit, originality, or Lakatos progress is
established. The reusable-engine verdict remains deferred.
