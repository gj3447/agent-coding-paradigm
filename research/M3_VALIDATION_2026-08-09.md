# M3 Validation Receipt

Date: 2026-08-09
Scope: bounded Python in-memory scalar-frontier R reference mechanics and frozen supplied-value corpus only

## Frozen subject

- Subject commit: `12f04162c142027285c6bef12f592f6b0a05cbdf`
- Subject tree: `d7d4ca1f73ace13bb7e73ea381ffd4f9255a2b4f`
- Local runtime: CPython `3.9.6`, macOS `27.0` build `26A5378n`, arm64
- CI runtime: CPython `3.12.13`, GitHub-hosted Ubuntu `24.04`, x64
- `jsonschema`: `4.25.1`
- Dependency-file SHA-256: `44ff0dc2f1e40311b8239e83146749ab9d9cee2a650e699f5464755d552ee20d`

This receipt is intentionally a follow-up artifact. Its subject is the preceding
implementation-and-engine-decision repair commit, so it does not claim to hash
itself.

## Commands

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_m0.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_m1.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_m2.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_m3.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/check_m3_ambient.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/check_m3_semantic_mutants.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
find spec fixtures research -type f -name '*.json' -print0 \
  | xargs -0 -n1 python3 -m json.tool >/dev/null
git show --check --oneline 12f04162c142027285c6bef12f592f6b0a05cbdf
```

M3 has no `--show-digests` mode. Frozen result digests are read from the
independent evaluator outputs and exact golden files below.

Remote readback:

```bash
gh run view 31293631531 --repo gj3447/agent-coding-paradigm
gh run view 31293631531 --repo gj3447/agent-coding-paradigm --log
```

## Exact result summary

```json
{"ambient_kernel_paths": 13, "ambient_mutants_detected": 14, "clean_ambient_processes": 2, "clean_process_dimensions": "cwd+HOME+PYTHONHASHSEED+TZ+poison", "clean_replay_processes": 2, "clean_semantic_processes": 2, "mechanics_tests": 6, "publications": 1, "randomized_capacity_rejections": 4, "randomized_oracle_comparisons": 64, "randomized_order_trials": 32, "rejections": 2, "semantic_mutants_detected": 10, "slow_consumer_trials": 16, "status": "MEASURED_REFERENCE_CONFORMANCE", "success_sequences": 3, "transitions": 7}
```

```text
BOUNDARY measured: 3 success sequences/7 transitions, 1 publication,
2 complete typed rejections, 32 order trials/64 independent-oracle
comparisons, 16 slow-consumer trials, 4 capacity rejections,
6 clean child processes, 13 guarded kernel paths, 14 ambient/control
mutants, and 10/10 semantic source mutants killed

BOUNDARY not established: eligibility correctness, direct M2 integration,
persistent or distributed streaming, irreversible-effect safety, H authority
or effects, durability, production readiness, comparative efficacy,
engine promotion, or Lakatos progress

Ran 59 tests
OK
```

The local M0, M1, and M2 prerequisite validators also returned `PASS`. All
repository JSON files parsed successfully, `git diff --check` passed, and the
subject commit passed Git's whitespace/error check.

GitHub Actions run
[`31293631531`](https://github.com/gj3447/agent-coding-paradigm/actions/runs/31293631531)
checked out the exact subject SHA and passed M0, M1, M2, M3, and all 59 tests on
CPython 3.12.13. The x64 Ubuntu 24.04 conformance job ran from
`2026-08-09T04:00:38Z` through `2026-08-09T04:01:55Z` and completed
successfully. Its reported `headSha` exactly equals the subject commit. The CI
test log reported `Ran 59 tests in 19.840s` followed by `OK`.

## Semantic, process, and guard evidence

- Three frozen success sequences produced seven accepted transitions. The main
  frontier sequence contains five transitions, and the two input-order
  permutations contain one transition each.
- The gate observed one whole-epoch publication and two complete typed
  rejections. Thirty-two seeded order trials yielded 64 production/oracle
  comparisons, 16 slow-consumer trials, and four fail-closed capacity
  rejections.
- Replay, ambient checking, and semantic mutation checking each ran in two
  independently spawned clean profiles: six child executions total, with
  byte-identical canonical stdout within each pair.
- Thirteen non-empty real-kernel paths ran under the locked guard: ten successes
  and three rejections, with zero ambient or caller-input mutation attempts.
  Eleven positive guard self-tests and ten import-metadata checks passed;
  fourteen ambient, adapter, and mutation control mutants were detected.
- The independent semantic baseline called the uninstrumented public package
  waist and covered ten probes, 34 steps, and 112 schema documents. Ten exact
  source mutants were killed with zero escapes and zero invalid mutants.
- The all-status probes transported `eligible`, `ineligible`, and `conflicted`
  supplied verdicts without interpreting their status. Conditional
  `ineligible` filtering and conditional authority-shaped output were both
  detected at the publication step.
- M1 proposal and M2 support artifacts are pinned seam provenance only. They do
  not establish direct M2-to-M3 inference or eligibility correctness.
- No output authorized, dispatched, retried, reconciled, or performed an
  external effect. The reusable-engine verdict remains `defer`; all promotion
  gates remain `OPEN` or `BLOCKED` with no M3-only shortcut.

The standalone semantic report had SHA-256
`179391d3e03bada534e9f72114441abb3bf67e570f4b3f530a2794417507830a`;
the standalone ambient report had SHA-256
`3aaf1dcab0ac4ef7f66fcde705d1a3a41412117e71aa8addd6a7248f37d972e7`.
Those hashes cover the captured canonical stdout including its terminating
newline.

## Clean-process descriptors

The table hashes a normalized compact key-sorted UTF-8 JSON descriptor without
a trailing newline. Only fresh temporary-root paths are replaced by the stable
placeholder. The semantic profiles retain the explicit local `PYTHONPATH` that
made the pinned `jsonschema` installation visible.

| Process | Profile | Hash seed | Timezone | Descriptor SHA-256 |
|---|---|---:|---|---|
| replay | clean-a | 37 | UTC | `fda90c2c4fd2f4175b5c5c24ee3e9601327352a2407247834334906bd73467c3` |
| replay | clean-b | 83 | Asia/Seoul | `4fb181f8494006efc52a108f88995273a19e682095914dbab1918b56c6abf38f` |
| ambient | clean-a | 37 | UTC | `00f62f72f7a863362f70f01c87ff5cb7286d5a5878cf2b939f15d0c5559d3fba` |
| ambient | clean-b | 83 | Asia/Seoul | `e90fc6556a6fe1ab203b8d32b09e4e75cb0685dc8f8aac215ad0eb533a586612` |
| semantic-mutants | clean-a | 37 | UTC | `655a41f094ca375ef74fe97d66a75a89a6e188fd033b8494bbdbd3c8bc02d8de` |
| semantic-mutants | clean-b | 83 | Asia/Seoul | `4f24aa2e0fbe30854c8633740ea27a39efee4b22ac3877784ca7bca399e79e61` |

```jsonl
{"cwd":"<fresh-process-root>/cwd","env":{"FLRH_M3_PROCESS_POISON":"replay:clean-a","HOME":"<fresh-process-root>/home","LANG":"C","LC_ALL":"C","PATH":"/bin:/usr/bin","PYTHONDONTWRITEBYTECODE":"1","PYTHONHASHSEED":"37","TMPDIR":"<fresh-process-root>/tmp","TZ":"UTC"}}
{"cwd":"<fresh-process-root>/cwd","env":{"FLRH_M3_PROCESS_POISON":"replay:clean-b","HOME":"<fresh-process-root>/home","LANG":"C","LC_ALL":"C","PATH":"/bin:/usr/bin","PYTHONDONTWRITEBYTECODE":"1","PYTHONHASHSEED":"83","TMPDIR":"<fresh-process-root>/tmp","TZ":"Asia/Seoul"}}
{"cwd":"<fresh-process-root>/cwd","env":{"FLRH_M3_PROCESS_POISON":"ambient:clean-a","HOME":"<fresh-process-root>/home","LANG":"C","LC_ALL":"C","PATH":"/bin:/usr/bin","PYTHONDONTWRITEBYTECODE":"1","PYTHONHASHSEED":"37","TMPDIR":"<fresh-process-root>/tmp","TZ":"UTC"}}
{"cwd":"<fresh-process-root>/cwd","env":{"FLRH_M3_PROCESS_POISON":"ambient:clean-b","HOME":"<fresh-process-root>/home","LANG":"C","LC_ALL":"C","PATH":"/bin:/usr/bin","PYTHONDONTWRITEBYTECODE":"1","PYTHONHASHSEED":"83","TMPDIR":"<fresh-process-root>/tmp","TZ":"Asia/Seoul"}}
{"cwd":"<fresh-process-root>/cwd","env":{"FLRH_M3_PROCESS_POISON":"semantic-mutants:clean-a","HOME":"<fresh-process-root>/home","LANG":"C","LC_ALL":"C","PATH":"/bin:/usr/bin","PYTHONDONTWRITEBYTECODE":"1","PYTHONHASHSEED":"37","PYTHONPATH":"/Users/lagyeongjun/Library/Python/3.9/lib/python/site-packages","TMPDIR":"<fresh-process-root>/tmp","TZ":"UTC"}}
{"cwd":"<fresh-process-root>/cwd","env":{"FLRH_M3_PROCESS_POISON":"semantic-mutants:clean-b","HOME":"<fresh-process-root>/home","LANG":"C","LC_ALL":"C","PATH":"/bin:/usr/bin","PYTHONDONTWRITEBYTECODE":"1","PYTHONHASHSEED":"83","PYTHONPATH":"/Users/lagyeongjun/Library/Python/3.9/lib/python/site-packages","TMPDIR":"<fresh-process-root>/tmp","TZ":"Asia/Seoul"}}
```

For example, copy one line exactly and run
`printf '%s' "$descriptor" | shasum -a 256`.

## Semantic mutant receipt

- Status: `PASS`
- Completion-gate axes: `10`
- Mutants: `10`
- Killed: `10`
- Escaped: `0`
- Invalid: `0`
- Per-mutant timeout: `10` seconds
- Source stable: `true`
- Oracle independent: `true`
- Baseline: 10 probes, 34 steps, 112 schema documents

| Mutant | Completion-gate axis | Probe | Divergence step | Expected to actual | Schema valid |
|---|---|---|---:|---|---|
| `frontier_non_strict` | `non_strict_frontier_publication` | `frontier_equal` | 2 | transition to transition | yes |
| `frontier_global_max` | `max_instead_of_min_frontier` | `frontier_skew` | 2 | transition to transition | yes |
| `partial_epoch_publication` | `partial_epoch_publication` | `two_pair_epoch` | 3 | transition to transition | yes |
| `item_level_demand` | `item_rather_than_batch_demand` | `whole_batch_demand` | 3 | transition to transition | yes |
| `overflow_accept_drop_max_open` | `accept_or_drop_overflow_including_max_open` | `max_open_overflow` | 0 | rejection to transition | yes |
| `late_delta_acceptance` | `late_acceptance` | `per_source_late` | 2 | rejection to transition | yes |
| `eligibility_status_interpretation` | `eligibility_status_interpretation` | `all_status_transport` | 3 | transition to transition | yes |
| `nested_value_rewrite` | `nested_value_rewriting` | `nested_value_preservation` | 3 | transition to transition | yes |
| `nested_dataflow_version_drift` | `version_binding` | `nested_version_preservation` | 3 | transition to transition | yes |
| `authority_shaped_output` | `authority_shaped_output` | `all_status_authority_absence` | 3 | transition to transition | no, deliberately forbidden field |

Every row has `anchor_matches=1`, `outcome=KILLED`, and
`invalid_reason=null`. A missing or multiply matched anchor, compile/import
failure, or unexpected exception is an invalid mutant and cannot count as a
kill.

Bound source hashes:

- Production source: `419df40cbefe9b878f91297ed00cf79434e8e443323ef31f340c86f1d65b8c34`
- Independent oracle: `ad2341cc55e1bb201a4aa8c90bc157c4e1ef6f731c740d082dd9f5b0c75385f6`
- Contract: `c4bd93be23eccaa232c4f8b0e1f6e4047f9ed572625238fe3f4ee601b74fa297`
- Wire schema: `58621bf3ab2b3f850b502cbfa22c87bc976c1baf915301586d9db0769a96632e`

## Artifact hashes

The table covers every unique M3 manifest closure path plus the pinned
dependency file. Hashes were recomputed from the frozen subject commit, not the
follow-up receipt worktree.

| SHA-256 | Path |
|---|---|
| `c4bd93be23eccaa232c4f8b0e1f6e4047f9ed572625238fe3f4ee601b74fa297` | `spec/m3-reactive-contract.v1.json` |
| `58621bf3ab2b3f850b502cbfa22c87bc976c1baf915301586d9db0769a96632e` | `spec/schema/m3-reactive.v1.schema.json` |
| `c316151d051b1b1c4d547e32678f494c2473c1d6d50f96fad9c878ec3be337cf` | `spec/m3-manifest.v1.json` |
| `a81a44d3d572cc43bc459adc62374ee261549758e0687263a887a3774a863da2` | `spec/schema/protocol.v1.schema.json` |
| `87b14b371d8572125164326b74d0574a11b00e4f11ba0c117dfe84644d1a7ccc` | `spec/canonicalization.v1.json` |
| `b727ae4d112b9df93d58d30daa6e4efcade122ec3bc3d84f6ec5b6ba502e2a74` | `spec/logic-semantics.v0.json` |
| `593bd94c634dc826d000764fa384507b82c371e776ef36677d131894973bf772` | `spec/m1-kernel-contract.v1.json` |
| `3f914944c9a7f0084fa0f725923489d8cd6feb5e70d510ffa5d54b5c20395c4d` | `spec/schema/m1-kernel.v1.schema.json` |
| `07064055e63b7e6de37060672a82bfd7d2aa2f5045596189dd6454552e409cbd` | `spec/m1-manifest.v1.json` |
| `65f8ae41c4c5c6c11f8298b77b477d19a31f2b0dc9ede058639183960cf4cd9e` | `spec/m2-logic-contract.v1.json` |
| `a39e152397693b3e1a026c1e561a1c955ba77f753f695f231d8768d80a7c4fa0` | `spec/schema/m2-logic.v1.schema.json` |
| `c792eb1fbea2e8e430cd7d0452b8e3ed290f2488dd297b107d3cd5a92f139200` | `spec/m2-manifest.v1.json` |
| `cd1360e0db9024cc6b03abde4a4d28e56aea82f901577bd2c4eae0cbdb5700b8` | `fixtures/m1/golden/observe-with-effect.transition.json` |
| `5a03b388701f65bb2d179b4388a2f2f5159e3bb8c5fb1b4457f79617d5e372bb` | `fixtures/m2/golden/two-support-retraction.fixpoint.json` |
| `ddc9eb812a946e07addc9f0e99e5a00d1f15963704a838383d64395a66a78044` | `spec/schema/m3-reactive-contract.v1.schema.json` |
| `78935a74e28d7845d1c199407d60ae7e3f0573ed79f866e990ed1ecb50a86cdf` | `spec/schema/m3-fixtures.v1.schema.json` |
| `acf07ee387b169861c1e9e8badecce20bd5d3ec54bcb48d81fe3fd71d8381fd0` | `spec/schema/m3-manifest.v1.schema.json` |
| `3e80671d1e707d9c3d7ac7313713eb4dccea8b0e175f62546ceb9a62e9d777c3` | `fixtures/m3/cases.json` |
| `e8ced5cb51dfc0b58ca99b30eb043be520fbd33431200f2a9d98f9dcfd1a781a` | `fixtures/m3/golden/frontier-stable.transition.json` |
| `7f511fb4af38fc66c7a589edb403ac2ccc9b26d9c6365e9e91a2b2678f0659c5` | `fixtures/m3/golden/late-delta.rejection.json` |
| `07a097b270f43bfce54a5df7605ae875b6741179beeba434a034d6400b67d46f` | `src/flrh_reactive/__init__.py` |
| `c39440238884bd96ca2131481549cc73c9de51a6a4ba242330ef325aa8c59f96` | `src/flrh_reactive/canonical.py` |
| `419df40cbefe9b878f91297ed00cf79434e8e443323ef31f340c86f1d65b8c34` | `src/flrh_reactive/reactive.py` |
| `76350084b1e85303793b4f2c576c87d761b21a1945c657b13d4af0d7517d8ea8` | `scripts/m1_guard.py` |
| `eb098c4e762f9f527ba1dea10b293b5500874d7a1e9b1d6ba0b42fb93631a49d` | `scripts/validate_m0.py` |
| `4a6c68b3f69e8d3ea36a0ed74aa3e53743827f14b5a52e3bd07349b9b7fb3c38` | `scripts/validate_m1.py` |
| `371c36d1071b61d25eb644e7ea073fc47e4683fdd04cc82dadabe1ba5e347f27` | `scripts/validate_m2.py` |
| `b72ba41bccdce98ed85ebc063abeead968caf9a1ce8658bbd2d7a42b5ff5d800` | `scripts/m3_fixtures.py` |
| `ad2341cc55e1bb201a4aa8c90bc157c4e1ef6f731c740d082dd9f5b0c75385f6` | `scripts/m3_oracle.py` |
| `f7563cdd240aba835d0e58528089a67f9b226be8d4d20b2f2de4001250c1eb04` | `scripts/m3_guard.py` |
| `f2e32eb0b0d9ba3951d312001a3eb6127ddf7af5d6723a2f6146330df1e2e377` | `scripts/check_m3_ambient.py` |
| `0f07bee0fbddac7936d0ca8767318f77de1245d88ac95d094208b51c34efdd5e` | `scripts/check_m3_semantic_mutants.py` |
| `797c48b49a912118c5ed9c69fcc5a164fc18e20199a0e61b1dae52aad8db6f1f` | `scripts/run_m3_replay.py` |
| `2224504133f36cf0495f9640b79f0e2a6b37c8c1fd4155475f73b67d404efcc7` | `scripts/validate_m3.py` |
| `9615646f39a3fc15fb4d7957cd9ebcdf96a4266b0390c2548fd68c43c3341dc8` | `tests/test_m3_reactive.py` |
| `44ff0dc2f1e40311b8239e83146749ab9d9cee2a650e699f5464755d552ee20d` | `requirements-m0.txt` |

## Frozen results

| Sequence | Ordered transition digests |
|---|---|
| `sequence:frontier-stable` | `sha256:9d633ca2b2646465a1b16098adc2de46c03d2c02c165f23814fbf838d11e0529`, `sha256:3ca898aca6ea0b5396312d4afef000c85c6779e9b97a1e512232cf9899b8f9da`, `sha256:c47706edbd7a3b10abd015173d213a1b146b84829aebc56c9766a3de642c3ced`, `sha256:8369e329308cdbc6345954fb11a44c7815e33d761838b2fe72d39fd701a4b974`, `sha256:55bebf44352c0d67cfc0629b7e53bf42afb13404493ea3bba50fb21de946edb2` |
| `sequence:apply-left` | `sha256:9d633ca2b2646465a1b16098adc2de46c03d2c02c165f23814fbf838d11e0529` |
| `sequence:apply-right` | `sha256:9d633ca2b2646465a1b16098adc2de46c03d2c02c165f23814fbf838d11e0529` |

The exact stable-publication golden closes epoch `7` at low watermark `8`.
Its batch ID is
`batch:307f1d9fa3279d3bae9e3b4b728c4ee05c0f36733164f3ebb888322ed43b033e`,
its batch digest uses the same hex payload, and its next-state digest is
`sha256:4cd3165965e34278b901a0ee53d2d755ec8671a7c0c3906b22dc856b0b28e6af`.

Typed rejections:

- `rejection:late-delta`: `LATE_DELTA`, path
  `/command/deltas/0/logical_time`, logical time `6`, source
  `source:m3:a`.
- `rejection:demand-command-limit`: `DEMAND_LIMIT_EXCEEDED`, path
  `/command/batches`, observed `3`, limit `2`.

## Governance readback

These subject-commit governance rows are outside the M3 manifest closure. The
README and claim ledger are intentionally changed only in the follow-up receipt
commit to add this receipt link.

| SHA-256 | Path |
|---|---|
| `38d8149732d9f9258c89e1c141c926bbbc9f543835250b8a1eeafc4b7f792edb` | `spec/engine-decision.v1.json` |
| `19b0b1227323d8b7e6ddf008b53e9b21ffa0345255d4a79c293da01a2d3a5d7d` | `docs/adr/0001-defer-engine-verdict.md` |
| `149eaeb11874a06940390f106c504de71d98bf5d0039016d0c1b6064a53e4d26` | `spec/claims.v1.json` |
| `5073ccb312479ed4944efe565d8837d71619fb2e50d3086693da1ae664ef2fad` | `.github/workflows/ci.yml` |
| `d8ac3bf11acadeeb7512c8e51330ccf86617c8ff420f8f556983997696eded0e` | `README.md` |

The machine decision still says `defer`. Its deterministic-incremental gate is
still `OPEN`; the prerequisite now uses the measured M3 corpus only as an input
to future direct L-to-R binding and persistent-reuse evidence. M3 does not close
that engine gate.

## Non-claims

This receipt measures one finite in-memory Python scalar-frontier R profile,
the frozen supplied-value corpus, deterministic canonical identities, bounded
queues and whole-batch demand, the independent evaluator oracle, and the named
local and CI environments. It does not establish eligibility correctness,
direct inference or integration from M2, general antichain time, distributed
watermark truth or coordination, persistent incremental streaming,
native-extension behavior, universal purity or sandboxing, or portability to
another implementation language.

No H authority, approval, capability, effect-intent creation, dispatch, retry,
compensation, reconciliation, persistence, crash recovery, irreversible-effect
safety, exactly-once external behavior, integrated F/L/R/H runtime, real
consumer, production readiness, comparative benefit, originality, engine
promotion, or Lakatos progress is established. The reusable-engine verdict
remains deferred.
