# M4B durable harness reference

> Status: `PROPOSED_PENDING_MEASUREMENT`

M4B is a bounded Python `sqlite3` L_RT reference. It accepts an exact M0
`EffectIntent`, stores intent/checkpoint/outbox in one `BEGIN IMMEDIATE`
transaction, records an attempt before adapter I/O, and requires destination
reconciliation after a started or unknown attempt. It deliberately claims
at-least-once-capable delivery, not exactly-once external effects.

The database uses `STRICT` tables, foreign keys, WAL, `synchronous=FULL`, and
`trusted_schema=OFF`. Lease generations fence stale runners. Approval evidence
is accepted only after recomputing the exact current M4A request and approval
preimages. A separate ledger bit consumes it once in the same transaction as
the exact `EffectIntent`, immutable receipt binding, checkpoint, and outbox.
The request/approval pair binds proposal, action, artifact, destination,
capability, authority, adapter, nonce, actor, scope, visibility, source run,
workflow version, policy/context, rationale, and time/revocation state.
The current M4A approval request's `run_id` must equal the intent's
`correlation_id`; the mutator and independent verifier both enforce that
cross-milestone boundary.
Receipt plus checkpoint persistence is atomic. Cancel, timeout, and budget
interrupts remain pending until effects are reconciled. Checkpoint hash or
version mismatch or canonicalization failure (including float, signed-int64,
or NFC violations) durably quarantines the run. Three checkpointed
no-progress rounds produce `budget_exhausted` only when no outbox item remains
pending; meaningful gain resets the counter.

The runner rechecks its fence inside the receipt/checkpoint transaction after
external I/O. If takeover occurred while the adapter call was in flight, the
old runner cannot publish a receipt; the new generation must query destination
evidence and reconcile the already-observed mutation.

`commit_intent` also requires an immutable receipt-binding sidecar containing
`command_digest`, `input_root_digest`, and `platform_digest`. The injected
receipt-evidence port supplies the actual attempt's `output_digests`,
`trace_ref`, and terminal `outcome`, which must equal the adapter or reconcile
observation. The harness converts its injected epoch clock to the RFC 3339
`recorded_at`; M4B validates and
persists the exact frozen M0 `ActionReceipt`. Both intent and receipt use the
shared frozen `flrh-cjson/1` canonicalizer, including NFC, signed-int64, and
`ActionReceipt.output_digests` set semantics. The returned receipt object is
the same canonical object reconstructed from persisted bytes.

Each run explicitly bounds pending effects and attempts. This profile caps
`max_pending` at 1024 and `max_attempts` at 16; defaults are 64 and 3. Terminal
runs reject new intent commits, dispatches, rounds, and interrupt requests. A
pending interrupt is idempotent only for the same interrupt kind; a different
kind conflicts. It rejects new intent commits and rounds, but already-committed
effects remain recoverable: the runner must reconcile or dispatch them to a
terminal observation before honoring the interrupt. This prevents cancellation
or a no-progress threshold from stranding durable work.

`FakeAdapter` is only a deterministic simulated destination. It enforces fence
and idempotency identities and exposes apply, query, and mutation counts.
`verify_run` independently opens SQLite read-only and checks canonical bytes,
protocol schemas and digests, receipt binding and intent linkage, attempt /
outbox / receipt coherence, approval preimages/consumption/workflow binding,
generation and per-intent attempt bounds, every attempt's identity/status/
transition, profile ceilings, run/interrupt vocabularies, orphan approvals,
checkpoint integrity, foreign keys, and terminal/pending counts. Approval rows
also carry a deferred SQLite foreign key to the intent created in their atomic
transaction.
The package's intentional public surface is exactly `DurableHarness`,
`FakeAdapter`, and the read-only `verify_run` function.

The manifest includes itself in an exact ordered closure, lists every owned
M4B artifact, and pins inherited M0 protocol/canonicalization plus semantic M4A
contract, schema, source, fixture, and golden dependencies by SHA-256. The
ordinary nonrecursive candidate-gate test invokes the aggregate proposed gate.
The behavioral report is explicitly an adversarial-sensitivity suite; it does
not claim to execute source mutants.

Validation:

```bash
python3 -m py_compile src/flrh_harness/*.py scripts/m4b_*.py scripts/check_m4b_*.py scripts/run_m4b_replay.py scripts/validate_m4b.py tests/test_m4b_durable.py tests/test_m4b_candidate_gate.py
python3 -m unittest tests.test_m4b_durable tests.test_m4b_candidate_gate
python3 scripts/validate_m4b.py --allow-proposed
```

Passing those commands is local proposed evidence only. It does not validate
M4A policy decisions, integrated F/L/R/H operation, a real destination,
production safety, comparative efficacy, or engine promotion.

## Approval validity at the writer boundary

`FALSIFIED` for the pre-repair implementation at commit `3c381ad`: approval
validity was checked before `BEGIN IMMEDIATE`, but not again inside the writer
transaction. A frozen fault clock could therefore move from epoch 100 to the
exclusive expiry boundary 200 between those checks and still persist the
approval, intent, checkpoint, and outbox row.

`PROPOSED` repair: `commit_intent` now captures one precheck epoch and one
transaction epoch. Inside the writer transaction it uses the latter for both
the fence check and complete approval revalidation, including exact preimages,
bindings, state, issue time, and the exclusive expiry boundary. The
`expires_during_commit` fault fixture fixes this boundary.

`MEASURED` only for the named local commands and environment recorded in
[`H_DURABILITY_GAP_AUDIT_2026-08-11.md`](../research/H_DURABILITY_GAP_AUDIT_2026-08-11.md):
the repaired candidate rejected the boundary case, the M4B aggregate passed,
and selected M4C/M4C-IL happy and crash paths did not regress. The M4B claim
remains `PROPOSED` and its manifest status remains
`PROPOSED_PENDING_MEASUREMENT`; this repair is not a durability promotion or
outer-completion result.
