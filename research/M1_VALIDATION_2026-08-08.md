# M1 Validation Receipt

Date: 2026-08-08
Scope: bounded Python pure-F reference mechanics and frozen corpus only

## Frozen subject

- Subject commit: `166fd41cc2b31bd1f5371fdf8c9ac5ca2d157c94`
- Subject tree: `d9d4a5679253c8dd25ccb2576cfff9d59499bf09`
- Local runtime: CPython `3.9.6`, macOS `27.0` build `26A5378n`, arm64
- CI runtime: CPython `3.12.13`, GitHub-hosted `ubuntu-latest`, x64
- `jsonschema`: `4.25.1`
- Dependency-file SHA-256: `44ff0dc2f1e40311b8239e83146749ab9d9cee2a650e699f5464755d552ee20d`

The receipt is intentionally a follow-up artifact: its subject is the preceding
implementation-and-repair commit, so it does not claim to hash itself.

## Commands

```bash
python3 scripts/validate_m0.py
python3 scripts/validate_m1.py
python3 -m unittest discover -s tests -v
find spec fixtures research -type f -name '*.json' -print0 \
  | xargs -0 -n1 python3 -m json.tool >/dev/null
git show --check --oneline 166fd41cc2b31bd1f5371fdf8c9ac5ca2d157c94
```

Remote readback:

```bash
gh run view 31252244371 --repo gj3447/agent-coding-paradigm
```

## Exact result summary

```text
M1 PASS {"m1_alias_boundary_cases":2,"m1_ambient_guard_categories":8,"m1_ambient_guard_processes":2,"m1_audit_guard_self_tests":3,"m1_base_inputs":3,"m1_bindings":3,"m1_byte_mismatches":0,"m1_canonical_different":2,"m1_canonical_equal":1,"m1_canonical_reject":4,"m1_clean_process_comparisons":27,"m1_clean_process_runs":54,"m1_control_mutants_detected":8,"m1_equivalence_pairs":1,"m1_exact_result_goldens":2,"m1_explicit_guard_self_tests":8,"m1_forbidden_static_surfaces":0,"m1_guard_self_tests":11,"m1_import_metadata_checks":10,"m1_inherited_dependencies":2,"m1_input_mutation_attempts":0,"m1_kernel_ambient_attempts":0,"m1_manifested_implementation_files":3,"m1_non_json_array_reject":1,"m1_non_json_boundary_rejections":1,"m1_rejection_cases":19,"m1_replay_sequences":1,"m1_replay_steps":2,"m1_schemas":4,"m1_sensitivity_mutations":7,"m1_static_import_roots":7,"m1_success_cases":7,"m1_success_input_schema_checks":7}
BOUNDARY measured Python reference-F mechanics and frozen corpus only; universal purity, L/R/H integration, production readiness, comparative efficacy, and Lakatos progress remain unjudged

Ran 17 tests
OK
```

The local M0 prerequisite also returned `M0 PASS`. All repository JSON files
parsed successfully, `git diff --check` passed, and the subject commit passed
Git's whitespace/error check.

GitHub Actions run
[`31252244371`](https://github.com/gj3447/agent-coding-paradigm/actions/runs/31252244371)
checked out the exact subject commit and passed M0, M1, and all 17 tests on
Python 3.12.13. The conformance job completed successfully in 20 seconds.

## Process and guard evidence

- Seven materialized success inputs validated against the normative `M1Input`
  schema before execution; these include independent `T...z` and `t...Z`
  RFC 3339 marker combinations.
- Nineteen rejection fixtures matched complete independently constructed
  `FRejection` values, not only codes or paths.
- Twenty-six cases plus one two-step sequence ran in two independently spawned
  processes: 54 child executions, 27 exact byte comparisons, zero mismatches.
- Two further guarded-import processes agreed on one canonical report.
- Eight explicit category probes plus three audit-only probes made 11 positive
  guard self-tests; ten import-metadata checks passed.
- Eight deliberate ambient or mutation control mutants were detected.
- Kernel ambient-attempt count, caller-input mutation-attempt count, and
  byte-mismatch count were all zero; recursive output checks found no H-owned
  intent, authority, approval, adapter, idempotency, or receipt field.

The local child profiles used fresh randomized directories. The table hashes a
normalized compact sorted-JSON descriptor in which those paths are replaced by
stable placeholders; it does not pretend that the temporary path strings were
identical.

| Profile | Hash seed | Timezone | Poison marker | Descriptor SHA-256 |
|---|---:|---|---|---|
| replay-a | 11 | UTC | `profile-a` | `f62a922719cbb9f5da60c4c0cb5a2ec29698d2cd6b9cc3ee96d58eec87a95e81` |
| replay-b | 97 | Pacific/Honolulu | `profile-b` | `3127262dc6d5789bd3893145718d7b11f298322f7ab2afd9667ec86dac212c85` |
| guard-a | 23 | UTC | `guard-a` | `736ccd2b7f274eb532467a66030b70827c3daf88aa703d73fad26f3dae302ca5` |
| guard-b | 71 | Asia/Seoul | `guard-b` | `872ca102855ba6ed4c54fdc5ac72beb6f9ddbbf8e4cd1728b754b804d702c50f` |

Every profile also fixed `LANG=C`, `LC_ALL=C`, `PATH=/bin:/usr/bin`, and
`PYTHONDONTWRITEBYTECODE=1`; each `HOME` pointed inside its fresh process root.
The descriptor digest is SHA-256 over the corresponding UTF-8 line below,
without a trailing newline. Object keys are already in lexical order.

```jsonl
{"cwd":"<fresh-process-root>","env":{"FLRH_AMBIENT_POISON":"profile-a","HOME":"<fresh-process-root>/home","LANG":"C","LC_ALL":"C","PATH":"/bin:/usr/bin","PYTHONDONTWRITEBYTECODE":"1","PYTHONHASHSEED":"11","TZ":"UTC"}}
{"cwd":"<fresh-process-root>","env":{"FLRH_AMBIENT_POISON":"profile-b","HOME":"<fresh-process-root>/home","LANG":"C","LC_ALL":"C","PATH":"/bin:/usr/bin","PYTHONDONTWRITEBYTECODE":"1","PYTHONHASHSEED":"97","TZ":"Pacific/Honolulu"}}
{"cwd":"<fresh-process-root>","env":{"FLRH_AMBIENT_POISON":"guard-a","HOME":"<fresh-process-root>/home","LANG":"C","LC_ALL":"C","PATH":"/bin:/usr/bin","PYTHONDONTWRITEBYTECODE":"1","PYTHONHASHSEED":"23","TZ":"UTC"}}
{"cwd":"<fresh-process-root>","env":{"FLRH_AMBIENT_POISON":"guard-b","HOME":"<fresh-process-root>/home","LANG":"C","LC_ALL":"C","PATH":"/bin:/usr/bin","PYTHONDONTWRITEBYTECODE":"1","PYTHONHASHSEED":"71","TZ":"Asia/Seoul"}}
```

For example, copy one line exactly and run
`printf '%s' "$descriptor" | shasum -a 256`; the placeholder records only the
deliberately variable temporary directory, not an omitted environment input.

## Artifact hashes

| SHA-256 | Path |
|---|---|
| `a81a44d3d572cc43bc459adc62374ee261549758e0687263a887a3774a863da2` | `spec/schema/protocol.v1.schema.json` |
| `87b14b371d8572125164326b74d0574a11b00e4f11ba0c117dfe84644d1a7ccc` | `spec/canonicalization.v1.json` |
| `593bd94c634dc826d000764fa384507b82c371e776ef36677d131894973bf772` | `spec/m1-kernel-contract.v1.json` |
| `07064055e63b7e6de37060672a82bfd7d2aa2f5045596189dd6454552e409cbd` | `spec/m1-manifest.v1.json` |
| `3f914944c9a7f0084fa0f725923489d8cd6feb5e70d510ffa5d54b5c20395c4d` | `spec/schema/m1-kernel.v1.schema.json` |
| `a2557ebb5c389c58223f9293c865ff1c12e9230e6db2fabb3f19ca52f4806712` | `spec/schema/m1-kernel-contract.v1.schema.json` |
| `2ed21adaf11dae5162dd2728b915baedda84b2db88f48c62aefaacc96e234059` | `spec/schema/m1-fixtures.v1.schema.json` |
| `658ec2a0c48ef557c1e1c01a3e8d2661bdbac35cda69982bb521cdb328cf360d` | `spec/schema/m1-manifest.v1.schema.json` |
| `456f9a07de72a3800866c56a18be9450e6865b1bfcef33f58b0e0fbef06ec57b` | `fixtures/m1/cases.json` |
| `cd1360e0db9024cc6b03abde4a4d28e56aea82f901577bd2c4eae0cbdb5700b8` | `fixtures/m1/golden/observe-with-effect.transition.json` |
| `5eded19f77f758d8ae10deeb19a4325de5f0b12ddebcb5611be3e374d5bef4fe` | `fixtures/m1/golden/invalid-calendar-timestamp.rejection.json` |
| `f79da3595f0ee92e6b2c8133bd909d853efa1e3eb649b17468c87ae307a78cbf` | `src/flrh_kernel/__init__.py` |
| `24f42e4d0d7355ed027fa4b684ca2c7e0a283c98ff51d3669be3f771c77ca602` | `src/flrh_kernel/canonical.py` |
| `2a24131c23756b11842ab6e05f37fc0e441887cdba0483f5e3e32495da534938` | `src/flrh_kernel/kernel.py` |
| `7547fc4ddd10ff82b9f9471bb8f0c4e8b95167b25afca3039e5c375e9169bb6e` | `scripts/m1_fixtures.py` |
| `76350084b1e85303793b4f2c576c87d761b21a1945c657b13d4af0d7517d8ea8` | `scripts/m1_guard.py` |
| `be37713b1d03e8588144d4b0721b7ff7c239eb8467594a803684147a2e1c0a6a` | `scripts/check_m1_ambient.py` |
| `b8c93bb28fc829ecce217cb0c3c202bfb1d131fc5e620c9364d532a656cc820c` | `scripts/run_m1_replay.py` |
| `4a6c68b3f69e8d3ea36a0ed74aa3e53743827f14b5a52e3bd07349b9b7fb3c38` | `scripts/validate_m1.py` |
| `8bf1ac864341a8705a62a062146e13d1bed02d9c214bf3d031bd14214a771682` | `tests/test_m1_kernel.py` |

## Frozen result digests

Result digests below are SHA-256 over independent `flrh-cjson/1` bytes. A
transition row also records the transition's own explicitly projected digest.

| Case | Result kind | Result digest | Transition digest |
|---|---|---|---|
| `observe-no-effect` | FTransition | `2d67c8debaf0c4b11e238fcb3a673b055db41f7b5843fbf599623b68072fa624` | `81623155177c6ce653aea5eb72493adaffcd734a874cda4e10f4f47269d73ae3` |
| `observe-rfc3339-case-variants` | FTransition | `2d67c8debaf0c4b11e238fcb3a673b055db41f7b5843fbf599623b68072fa624` | `81623155177c6ce653aea5eb72493adaffcd734a874cda4e10f4f47269d73ae3` |
| `observe-with-effect` | FTransition | `1c520e585b87162163c53be3dcb3b01f212831da71dd4a265468fe4b9f973941` | `58aebb4a6256a7dc2d5cde67eb2f303c1902afc9687c2854e5e292ee2c0b3f3f` |
| `observe-with-effect-reordered-preconditions` | FTransition | `1c520e585b87162163c53be3dcb3b01f212831da71dd4a265468fe4b9f973941` | `58aebb4a6256a7dc2d5cde67eb2f303c1902afc9687c2854e5e292ee2c0b3f3f` |
| `reserved-kind-action-order-a` | FTransition | `3be6b8cd317f28e010e29cbeb2c99fb1b2bfe1e40d6c504e1df46eaec595f4dd` | `dd25fe85422335c74d91b2416809c870cc4b7b63a8b1a189fdcf8c2f88482193` |
| `reserved-kind-action-order-b` | FTransition | `6c268d191ec7a8c8186754bfcadc20642b5d04a0749b17c32f574da33ae598b5` | `864cd854013aa09338e498e301b5680f2f3ed6b4e6517b4c717e912b27efe863` |
| `observe-and-close` | FTransition | `eb5aa3c5e037f1c37d1f06de2749677e265b6d9ee1fdf57f3a1364668c210f79` | `98b7a3b922e209dc10747706a345cc06f7b62f5cbfb04963d4c254036471ad37` |
| `snapshot-extra-field` | FRejection | `8cdbbc4b4fbf89d74ddca655a42bfcca9e2237a68ef47a3e570de41b992b473f` | — |
| `event-missing-id` | FRejection | `1a59a77b742a77be9f2668dfecf4fafef78cf09ee1f3bc754129c3c400342742` | — |
| `non-nfc-observation` | FRejection | `384b2acf1b02e7f5942ad480a1caa9e873f93c00fa5f621022e01a33dd7c9521` | — |
| `workflow-version-mismatch` | FRejection | `577631768f5ba8c0a0cfe2eaa1c29f6e20d62e408a681a5de6371081435c9eb3` | — |
| `unsupported-state-schema` | FRejection | `181828af62682ef79bec1e9ceb122e316db32100621ee25aad577469e719c841` | — |
| `unsupported-event-schema` | FRejection | `0906268e231a7c42ed9f91d540760abf663282c15efee1d2ca82fb2545c102c8` | — |
| `unsupported-canonicalization` | FRejection | `e318253b38614adede5def9a8d01899afe059f7308e2e1f504a100526dfba186` | — |
| `aggregate-mismatch` | FRejection | `40a52954149b59999c77a6633c657665b737a90167575fdfb1b29a38a58ce61e` | — |
| `stale-revision` | FRejection | `292bd5d5c65155ad327667bdb0da60144c0dea3d263d71c46e6e22ddbad2ca3a` | — |
| `logical-time-regression` | FRejection | `ee9253b5798778614ad9f0c091c8360f8fcc200cb683bd5a91488cb4b94405f7` | — |
| `unsupported-event-payload` | FRejection | `cb76ad600e31ee78b46d942e7adda48bbc87423e59b1c76d1682d87d42d1b14c` | — |
| `closed-snapshot` | FRejection | `2bb7e7667271f10e56ca575d6513e05f3bb2ea637da8043d2bd9fada994516fd` | — |
| `duplicate-precondition` | FRejection | `facdea4073dace51666b5af24842f0646376be16612a93c44fa849bcc4d148b1` | — |
| `snapshot-int64-overflow` | FRejection | `92b17af3376b2217fd7ef764ecd43529f2a91b82140ccf0366de2c5223d88de7` | — |
| `event-float-logical-time` | FRejection | `5d8c7b442bb2bef9e5c5075548505ebfeb4145467c6a31712fcc1b4e1c8e7d9a` | — |
| `snapshot-revision-exhausted` | FRejection | `a624bbdf261660c7418637ebe8db4135fea432f0bcde126ad27d535e8ec1a41f` | — |
| `unicode-surrogate-observation` | FRejection | `fea62820bc82f3d9461883edb43c5aea59bd3a41dd81723daa962ec3c7f42fa2` | — |
| `invalid-calendar-timestamp` | FRejection | `f44eed7c51546efbff35a9388e444a9897bdd64317af41c3cf0922435fa444ca` | — |
| `invalid-offset-timestamp` | FRejection | `c5b1ece4523c5f4f7d169ee9cb44ffb3078585f1e9affb5f651a76e6ad15fc47` | — |

The `two-observations` replay result digest is
`6e3ecdbf8d99a2c57942faffeae3cdd7c191ddcd3020ce3934e73cc5f55e9034`.
Its transition digests, in order, are
`81623155177c6ce653aea5eb72493adaffcd734a874cda4e10f4f47269d73ae3`
and `dcd3efad1305caaa24a4bada6cbe801731b1b0c35a8ecaa49227381523bd7b9d`.

The equal timestamp-variant result is intentional: timestamps are validated
accepted-event metadata but are not causal fields in the frozen transition
projection. Likewise, the reordered proposal preconditions are a declared set.

## Non-claims

This receipt does not prove universal Python purity or sandboxing. The guarded
memory loader is observably distinct from a production `SourceFileLoader`, and
native extensions plus uninstrumented Python or OS surfaces are outside the
claim. It measures the current source and named guard surfaces in two process
profiles, not every possible evasive future implementation.

The transition digest does not bind the complete accepted-event wire:
`occurred_at`, `received_at`, accepted-event `causation_id`, and ingress
`idempotency_key` remain ingress/H conflict concerns. Only workflow,
state-schema, event-schema, and canonicalization versions are checked against
M1 constants; the remaining version fields are equality-, preservation-, and
digest-bound rather than registry-validated.

No L fixpoint, R scheduling/frontier, H durability or effect closure, graph
runtime, crash recovery, real consumer, comparative benefit, originality,
production readiness, or Lakatos progress is established. The reusable-engine
verdict remains deferred.
