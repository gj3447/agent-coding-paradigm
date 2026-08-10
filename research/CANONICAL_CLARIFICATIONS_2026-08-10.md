# Canonical clarifications repair receipt — 2026-08-10

Fixture-first repair of the three upstream findings from
`research/TS_SECOND_IMPL_AUDIT_2026-08-10.md`, executed on the audit host
(CPython 3.13 / unicodedata 15.1.0; Node v24.18.0 / Unicode 17 ICU).

## What changed

1. New normative addendum `spec/canonicalization-clarifications.v1.json`
   (+ self-validating schema), bound into the M0 manifest. It pins NFC
   verdicts to **Unicode 15.1.0** with the unassigned-codepoint barrier rule,
   bounds container nesting at **max_nesting_depth 128**, and defines
   set-like selection for **non-string root kinds** (no paths, no crash).
   The base profile `spec/canonicalization.v1.json` is byte-identical to its
   sealed state, so every frozen digest pin — including the LR promotion
   receipt's frozen evidence — remains valid. Cascade digest pins were
   recomputed only where working-tree consistency requires it
   (m4b/m4c/m4cil manifests; none are receipt-frozen).
2. Fixtures added before the repair (failing-first evidence below):
   - `fixtures/m0/canonical` equal pair `nfc-pin-unassigned-codepoint-inert`
     (U+0316 U+0897; digest `sha256:1b18c0d4…`) and reject
     `nesting-depth-limit` (depth-129 array, prose `nesting depth`).
   - `fixtures/m1` rejections `container-kind-snapshot`,
     `container-phase-snapshot`, `container-risk-hint`.
3. Repairs: `src/flrh_kernel/canonical.py` (string-kind guard for set-like
   selection; `NESTING_DEPTH_EXCEEDED` at depth ≥ 128),
   `src/flrh_kernel/kernel.py` (type guards on `phase` and
   `declared_risk_hint` membership), and the independent twin in
   `scripts/validate_m0.py` (same two rules, prose `nesting depth exceeds
   flrh-cjson/1 limit of 128`), which also now pins the clarifications and
   requires runtime `unicodedata.unidata_version` 15.x.
4. Count gates updated: m0 `canonical_reject` 4→5, manifest contracts 8→9 /
   schemas 9→10; m1 `m1_canonical_reject` 4→5, `m1_rejection_cases` 19→22,
   `m1_clean_process_comparisons` 27→30.
5. TS second implementation follows the same clarifications:
   `ts/src/contracts/unicode-15-1-assigned.ts` (707 assignment ranges
   generated from unicodedata 15.1.0) drives a segment-based pinned-NFC
   check; depth gate mirrors the kernel; the conformance suite consumes the
   new fixtures, `identity_paths`, and the clarifications pin.

## Failing-first evidence (before repair, after fixtures)

- `python3 scripts/validate_m0.py` → exit 1,
  `M0 FAIL: canonical reject fixture accepted: nesting-depth-limit`.
- `python3 scripts/validate_m1.py` → container fixtures crash the kernel with
  uncaught `TypeError: unhashable type` (audit repros), and after the spec
  edit the manifest digest gate fired
  (`M1 inherited dependency digest drift: spec/canonicalization.v1.json`) —
  which is what motivated the byte-preserving addendum design.

## Post-repair outcomes (exact commands, this host)

- `python3 scripts/validate_m0.py` → OK (canonical_equal 2, reject 5).
- `python3 scripts/validate_m1.py` → OK (rejections 22, clean-process
  comparisons 30, byte mismatches 0).
- `python3 scripts/validate_m2.py`, `validate_m3.py` → OK.
- `python3 scripts/validate_m2il.py` → PASS;
  `validate_m4a.py|m4b|m4c|m4cil --allow-proposed` → OK.
- `python3 scripts/validate_lr_seam.py` → OK — the sealed LR promotion
  receipt and its frozen evidence are untouched by this change.
- `python3 -m unittest tests.test_m0_contracts tests.test_m1_kernel` →
  17 tests OK.
- `cd ts && pnpm verify` → green (typecheck TS7, lint, arch, 10 unit /
  4 property / 56 conformance / 1 replay). Divergence controls freeze the
  audit repros to the Python verdicts: NFC repro now `FTransition`
  `sha256:51a42a18a53a6333fe54b1605af3f471716fca507ca667b04332e33b0981f54e`
  on both implementations; depth-200 repro `FRejection` /
  `NESTING_DEPTH_EXCEEDED` on both.

## Boundary

Checker-relative, single-host evidence. Open residue: CPython running
Unicode >15.1 tables would need the same barrier data the TS side carries
(guarded loudly by the new unidata_version check); the five non-kernel
Python canonical.py profiles (logic/reactive/lr-seam/authority/incremental)
retain their own sealed behaviors and were deliberately not modified — the
same clarifications would need their own fixture-first rounds if promoted.
