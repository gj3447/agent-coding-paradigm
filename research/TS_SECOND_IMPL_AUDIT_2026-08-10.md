# TS second-implementation divergence audit — 2026-08-10

Scope: the new `ts/` workspace (M0 canonicalization + M1 kernel port, local
`pnpm verify` green against the frozen corpus) was adversarially audited by
three independent lenses hunting for inputs OUTSIDE the frozen fixtures where
the TS port and the Python reference disagree. Findings below carry claim
labels per AGENTS.md. Executed repros ran on this host (CPython 3.13 /
unicodedata 15.1 vs Node v24.18.0 / ICU with Unicode 17.0).

## Upstream findings (Python reference / spec — NOT repaired here)

These touch the sealed corpus, receipts, or the normative spec; per the change
protocol they need a failing fixture + revalidation, not a silent patch.

1. `MEASURED` **NFC verdicts are Unicode-version-bound and the spec pins no
   version.** 41 codepoints newly assigned after Unicode 15.1 (e.g. U+0897,
   U+1ACF–U+1AEB, U+113CE–U+113D0, U+10D69–U+10D6D, U+1E5EE, U+1E6E3…) have
   ccc=0 for CPython-15.1 but nonzero ccc under ICU/Unicode 17. A pure-ASCII
   wire document containing such a string (e.g. observation `{"note":"̖ࢗ"}`)
   yields FTransition + digest in Python but FRejection
   (`NON_NFC_STRING`) in TS. `spec/canonicalization.v1.json` says only
   "Unicode NFC" with no version pin, and all fixtures' non-ASCII strings
   (3 occurrences: `é`, `é` NFD, lone surrogate) predate Unicode 2.0, so the
   frozen corpus cannot detect this class. Proposed repair: pin the Unicode
   version in the canonicalization profile and add fixture strings from the
   15.1→17 delta.

2. `MEASURED` **Python kernel crashes (uncaught `TypeError: unhashable type`)
   when root `kind` — or `phase` / `declared_risk_hint` — is a JSON container.**
   `canonical.py` line 88 `SET_LIKE_PATHS_BY_KIND.get(root_kind, …)` hashes the
   value; `kernel.py` catches only `CanonicalizationError`, so
   `{"kind": ["FStateSnapshot"], …}` kills `step_f` outright. The TS port
   guards with `typeof === "string"` and returns a typed
   `MALFORMED_SNAPSHOT` rejection. Reachable from arbitrary parsed input, so
   the Python side is an unauthenticated crash path. Proposed repair
   (fixture-first): guard non-string `kind` in the canonical profile, then add
   rejection fixtures; note this changes the sealed rejection count gates.

3. `MEASURED` **Deep-nesting behavior differs by construction.** Python
   `canonical_bytes` hits an uncaught `RecursionError` from depth ≈999;
   Node handles the same documents to depth ≈4000 (returning transitions
   Python can never produce), then overflows too. No fixture pins any
   recursion budget. Proposed repair: specify an explicit depth limit in the
   canonicalization profile and enforce it in both implementations.

## TS-side findings (repaired in this change)

4. `MEASURED→fixed` NaN/Infinity/-Infinity: Python `json.loads` always accepts
   these constants and the canonicalizer rejects them in-band as
   `FLOAT_FORBIDDEN` with a JSON Pointer; the TS lexical parser previously
   threw at parse time. The parser now produces float lexemes for the three
   constants, restoring verdict parity (`tests/examples/json-text.test.ts`).

5. `MEASURED→fixed` The TS kernel's canonicalization probe previously swallowed
   every exception and synthesized `UNSUPPORTED_JSON_TYPE` — laundering V8
   stack overflow into a typed rejection the oracle can never emit. It now
   rethrows non-`CanonicalizationError` exceptions (crash-propagation parity).

6. `fixed` Gate hardening from the audit: `no-eval`/`no-new-func`/
   `no-implied-eval` in domain+contracts; the canonicalizer constants and
   set-like table are now pinned to `spec/canonicalization.v1.json`
   (`tests/conformance/spec-pin.test.ts`); frozen-corpus count gates
   (7/19/7/1/1, base 3, replay 2) added; every `stepF` result is additionally
   validated against `spec/schema/m1-kernel.v1.schema.json` (skipped only for
   canonical texts carrying >15-digit integers, where JSON.parse rounding
   would produce false schema verdicts).

## Known open gaps on the TS side (documented, not yet built)

- No clean-process / environment-poisoning replay (Python: 54 spawned runs,
  two poisoned profiles, `--reverse-objects`); no ambient-guard categories; no
  implementation-file manifest; no mutant suite proving the eslint/depcruise
  gates kill real violations beyond the one manual negative control run.
- Unconsumed corpora: `fixtures/m0/logic`, run-FSM + traces, loop contract,
  manifests. The M0 invalid-protocol port asserts verdicts only — Ajv wording
  differs from Python jsonschema 4.25.1, so `expected_keyword` prose and the
  exactly-one-error rule remain checker-relative to the Python oracle.
- Rejection envelope fields `event_id`/`snapshot_revision` are pinned exactly
  by only one byte golden; other rejection cases pin code/path/context plus
  schema shape.
- Correction (same day): the reviewer's `identity_paths` claim was initially
  rejected after inspecting only `sensitivity_mutations[0]`; four of the seven
  cases do carry `identity_paths` (consumed by tests/test_m1_kernel.py). The
  TS suite now consumes them too.

## Non-claims

This audit does not upgrade the TS port beyond CANDIDATE. Local verify green
plus this audit is checker-relative, single-host evidence — not a clean-process
receipt, not an M-milestone, not efficacy evidence.
