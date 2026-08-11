# Claims addendum — 2026-08-11

> Why an addendum: `docs/CLAIMS_AND_STATUS.md`, `README.md`, `docs/ROADMAP.md`,
> `docs/SEMANTICS.md`, `docs/LR_SEAM.md`, `docs/adr/0001-defer-engine-verdict.md`,
> `spec/claims.v1.json` and the LR contracts are **byte- or projection-sealed** by the
> measured LR promotion gate (`LR_PROMOTION_PATHS` / `LR_FROZEN_EVIDENCE_PATHS` in
> `scripts/validate_lr_seam.py`). An attempted in-place wording repair was rejected by the
> gate itself, so post-promotion status changes are recorded here — the canonical
> clarifications addendum pattern — until a receipt-superseding promotion round exists.
> On conflict about *status*, this addendum is newer than the sealed table; on conflict
> about *measured evidence*, the sealed receipts win.

## Status rows newer than the sealed table (as of 2026-08-11)

| Claim | Status | Evidence boundary |
|---|---|---|
| a persistent incremental L profile can reuse cached closure while staying byte-equal to clean full recomputation | PROPOSED_PENDING_MEASUREMENT | M2-IL candidate: 17/17 tests, 13/13 semantic mutants killed, always-on dual public `solve_l` oracle; receipt `research/M2IL_CANDIDATE_VALIDATION_2026-08-09.md`; no performance or persistence-storage claim |
| a pure H authority projection can gate proposals into intents via exact-hash approvals | PROPOSED_PENDING_MEASUREMENT | M4A candidate: 3-success/19-rejection corpus, independent fixture oracle, FSM conformance; validated only transitively inside the M4C gate; no standalone receipt |
| a durable SQLite harness can keep one logical effect from becoming duplicate mutations across crash/restart | PROPOSED_PENDING_MEASUREMENT | M4B candidate: fenced leases, atomic approval-consumption+intent+outbox, three real `os._exit(86)` cutpoints (destination counts 0/0/1 → 0/1/1, `verify_run` valid); bounded FakeAdapter evidence, not general recovery |
| the F→L→LR→R→H chain composes into one deterministic slice closing an exact ActionReceipt | PROPOSED_PENDING_MEASUREMENT | M4C / M4C-IL candidate receipts (2026-08-09/10): 16/16 sensitivity forgeries detected, real subprocess crash recovery, dual-environment CI readback; stops at HONOR_PENDING_INTERRUPT — no outer SUCCEEDED |
| a second independent implementation can reproduce M0 canonicalization + M1 kernel byte-for-byte | CANDIDATE | TypeScript workspace `ts/` (`pnpm verify` green, frozen-corpus byte parity); its adversarial audit surfaced and fixture-first-repaired 3 real reference defects (Unicode-version NFC skew, container-kind crash, unbounded nesting); clean-process replay and ambient guards not reproduced — NOT a measured milestone |
| H should own continuation and effect/evidence closure | PROPOSED (boundary updated) | the sealed row's "no crash/recovery evidence" now understates the record: bounded candidate crash/recovery evidence exists (M4B/M4C frozen cutpoints); still no MEASURED durability receipt |

## Known gaps recorded (not silently patched)

1. **M1 corpus gap** — rejection code `VERSION_ENVELOPE_MISMATCH` is reachable code with no
   direct fixture, golden, or unit test. Closing it must be fixture-first and moves the
   sealed M1 count gates (as the 2026-08-10 canonical-clarifications round did for its
   cases); never a silent patch.
2. **Sealed-prose staleness (structural, not neglect)** — README's admission-gate block and
   `docs/LR_SEAM.md:67` still quote `--allow-proposed` for the now-measured LR gate, and
   README's M1 prose counts (19 rejections) predate the clarifications corpus (22). These
   files are sealed by the promotion gate; the strict flagless
   `python3 scripts/validate_lr_seam.py` is the correct measured invocation regardless.
3. **ADR/spec vocabulary drift** — ADR 0001 says "signed-delta stabilization" where
   `spec/engine-decision.v1.json` says "unit-delta stabilization". Both are sealed; per the
   M0 rule (machine files win over prose) read the spec's wording as authoritative.
4. **Machine claim ledger lag** — `spec/claims.v1.json` (sealed) predates the five
   candidate profiles above; its update moves the sealed M0 corpus and needs its own gated
   round.

## Follow-up

A **receipt-superseding promotion protocol** (new receipt commit + validator pin rotation)
is the only path that can refresh the sealed prose set in place. Until designed and gated,
status truth = sealed table ⊕ this addendum.
