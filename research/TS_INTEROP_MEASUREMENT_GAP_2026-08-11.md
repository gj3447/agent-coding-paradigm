# TypeScript interoperability measurement gap — 2026-08-11

> Status: `MEASURED` read-only audit of branch, corpus, tests, and two named CI
> runs. The TypeScript implementation and the proposed next gate remain
> `PROPOSED`. This audit does not close fault test 34, M6, or the repository's
> independent-implementation falsifier.

## Frozen audit subject

- Local branch: `ts-second-impl`
- Local and remote head: `e5c3f2de394e6081fabee7b8de9dd301e12fc288`
- Topology at audit: `main...ts-second-impl = 0 behind / 9 ahead`
- Implemented scope: M0 canonicalization, M0 protocol verdicts, and M1 F kernel
- Explicitly absent scope: L, R, H, graph delta, outer FSM execution, and a
  fresh Python-versus-TypeScript differential verifier

Named audit commands:

```text
git rev-list --left-right --count main...ts-second-impl
git rev-parse ts-second-impl origin/ts-second-impl
git ls-tree -r --name-only ts-second-impl:ts
git show ts-second-impl:fixtures/m1/cases.json
git show ts-second-impl:fixtures/m0/canonical/cases.json
gh run view 31349786750 --repo gj3447/agent-coding-paradigm --json ...
gh run view 31357600353 --repo gj3447/agent-coding-paradigm --json ...
gh api repos/gj3447/agent-coding-paradigm/actions/runs/<run-id>/artifacts
```

`MEASURED`: the branch contains a real second-language implementation with its
own JSON value model, canonicalizer, pure SHA-256, and F kernel. It consumes the
repository's shared fixtures directly. It is therefore more than prose or a
stub, but its current tests are still candidate conformance tests rather than a
paired interoperability receipt.

## Corpus actually consumed

Read-only counts at the audited branch head:

| Corpus | Count |
|---|---:|
| M0 canonical equal pairs | 2 |
| M0 canonical different pairs | 2 |
| M0 canonical rejection cases | 5 |
| M0 valid protocol objects | 10 |
| M0 invalid protocol mutations | 13 |
| M1 success cases | 7 |
| M1 rejection cases | 22 |
| M1 sensitivity mutations | 7 |
| M1 equivalence pairs | 1 |
| M1 replay sequences | 1 |

`MEASURED`: existing TS tests do not compare the full result bytes for every M1
case against a freshly executed Python child. Success tests primarily pin
transition digests and selected fields; rejection tests primarily pin
code/path/context; only two result goldens are full-byte checks. The replay test
pins transition-digest sequence and final revision rather than a paired raw
result envelope.

`MEASURED`: the only replay-named TS path is
`ts/tests/integration/m1-replay.test.ts`. There is no TS stdout exporter with
the contract of `scripts/run_m1_replay.py`, no independent subprocess comparer,
and no interoperability receipt artifact.

## Remote CI readback

The last two path-triggered `ts-conformance` runs were read with `gh run view`
and their artifact endpoints were read with `gh api`.

| Run | Subject | Install | `pnpm verify` | Artifacts |
|---|---|---|---|---:|
| [31349786750](https://github.com/gj3447/agent-coding-paradigm/actions/runs/31349786750) | `d6b9bbc776fd793ddd706dae328c2f3b84a47e9a` | failure | skipped | 0 |
| [31357600353](https://github.com/gj3447/agent-coding-paradigm/actions/runs/31357600353) | `83f581cd733d19f8a603e525a2be003e263dfb94` | failure | skipped | 0 |

Exact second-run boundary:

```text
Node v24.18.0
pnpm install --frozen-lockfile
[ERR_PNPM_IGNORED_BUILDS] Ignored build scripts: esbuild@0.28.2
pnpm verify: skipped
```

`MEASURED`: later branch commits `267e2b3` and `e5c3f2d` were documentation-only
and did not trigger the path-filtered workflow. Consequently the recorded local
`pnpm verify` success remains useful candidate evidence, but there is no exact
remote TS-green readback at the audited head.

## Smallest honest next gate

`PROPOSED`: first repair the declared pnpm build policy so the clean CI install
can execute without weakening supply-chain checks. Then add:

1. a TS CLI that accepts `--case`, `--sequence`, and `--reverse-objects` and
   emits exactly one canonical result line;
2. an independent Python verifier that spawns the existing Python runner and
   the TS runner under two clean environment profiles;
3. raw-byte and SHA-256 comparison for all 29 M1 cases plus the full replay;
4. a one-byte negative control that must be detected;
5. a receipt binding commit/tree, Python/Node/ICU/Unicode/pnpm versions, input
   artifact hashes, per-case output hashes and lengths, and exact CI readback.

The first narrow target report should contain at least:

```json
{"byte_mismatches":0,"m1_case_byte_comparisons":29,"m1_replay_byte_comparisons":1,"negative_controls_detected":1}
```

Only after that report passes in the named clean environments may the following
narrow statement become `MEASURED`: the two implementations agree byte-for-byte
on the frozen M1 corpus and replay. M0 normalized verdicts, sensitivity cases,
ambient guards, logic/FSM/loop corpora, L/R/H deltas, and two real consumers
remain later gates; the broad falsifier stays open.
