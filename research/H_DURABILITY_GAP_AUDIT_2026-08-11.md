# H durability gap audit and approval-boundary repair — 2026-08-11

> Status: `MEASURED` for the exact local counterexample and commands below.
> The repaired M4B claim remains `PROPOSED`; its manifest status remains
> `PROPOSED_PENDING_MEASUREMENT`. This is not an M4 promotion receipt,
> real-destination result, outer-completion proof, production claim, efficacy
> claim, or engine verdict.

## Subject and environment

- Repository base commit: `3c381adc0f04b29a18011cafe56246327e0ebc26`
- Base tree: `d78933be716de0f141db958e042b576fff3cc18f`
- Host: Linux `7.0.14-5-pve`, x86_64, glibc 2.41
- CPython: `3.13.5`; Unicode data: `15.1.0`
- `jsonschema`: `4.25.1`; SQLite: `3.46.1`
- Dependency command: `uv run --with-requirements requirements-m0.txt ...`

The tested repair was an uncommitted four-artifact working-tree subject over
that base. Its exact post-repair SHA-256 values were:

| Artifact | SHA-256 |
|---|---|
| `fixtures/m4b/cases.json` | `77fce3a06424926e65a88d74fe1307607fd214a8fd1b43054a063a48ae840d24` |
| `spec/schema/m4b-fixtures.v1.schema.json` | `7f5bd3346696a43342d0e21022d19d9c76134f73d518a39259d955d663ddb140` |
| `src/flrh_harness/harness.py` | `65d81ebe9d96cf81f308b4c93b435a965b8cfbede2b942d2468a7cc1173017cc` |
| `tests/test_m4b_durable.py` | `3bc58e178958295432adb77d3f2fc1d09329ab77a5c8d6a9d2b145e6646504df` |

## Failing-first counterexample

`FALSIFIED` at the base implementation: the broad candidate assertion that an
expired approval always fails closed did not hold across the intent writer
boundary. The new fixture fixes these values:

```text
precheck epoch       = 100
writer transaction   = 200
approval expires_at  = 200
lease expires after  = 1100
```

The approval passed the pre-transaction check at 100. The injected clock moved
to 200 immediately before `BEGIN IMMEDIATE`. Because the implementation did
not revalidate approval state in the transaction, `commit_intent` returned
success. The fixture-first test produced:

```text
AssertionError: ApprovalRejected not raised
Ran 1 test
FAILED (failures=1)
```

This falsifies only that behavior of the pre-repair M4B candidate. It does not
falsify the architecture-wide proposal or imply a real destination failure.

## Repair boundary

`PROPOSED`: `commit_intent` now captures a single epoch for the preliminary
check and a fresh single epoch after acquiring the writer transaction. The
transaction epoch is shared by its fence check and complete approval
revalidation. That revalidation recomputes the request and approval preimages,
checks every intent/request binding, rejects revoked or consumed evidence, and
requires `issued_at <= transaction_epoch < expires_at` before any approval,
intent, receipt binding, outbox, or checkpoint write is committed.

The fixture and its closed JSON Schema add `expires_during_commit`; the unit
test advances only the injected clock at the writer boundary. No ambient clock
or real external authority is introduced.

## Post-repair measurements

Focused fault command:

```text
uv run --with-requirements requirements-m0.txt python -m unittest \
  tests.test_m4b_durable.M4BDurableTests.test_20f_approval_expiring_at_commit_transaction_fails_closed
```

Result: `1/1 OK`.

Aggregate candidate command:

```text
uv run --with-requirements requirements-m0.txt python scripts/validate_m4b.py --allow-proposed
```

Exact report:

```json
{"adversarial_sensitivity_cases":5,"ambient_violations":0,"approval_mutations":11,"fault_tests":10,"inherited_dependencies":18,"kind":"M4BValidationReport","manifest_owned_paths":22,"public_api":3,"replay_matches":true,"status":"PROPOSED_PENDING_MEASUREMENT","subprocess_cutpoints":3}
```

Durable unit plus candidate gate:

```text
uv run --with-requirements requirements-m0.txt python -m unittest \
  tests.test_m4b_durable tests.test_m4b_candidate_gate
```

Result: `36/36 OK` (`35` durable tests plus one aggregate candidate gate).

Real subprocess crash command:

```text
uv run --with-requirements requirements-m0.txt python scripts/check_m4b_crashes.py
```

`MEASURED`: all three workers exited at the injected `os._exit(86)` cutpoint.
Before intent, mutation count stayed `0 -> 0`; after intent it became `0 -> 1`
only after destination query returned `not_applied`; after external success it
stayed `1 -> 1` after reconciliation returned `confirmed_success`. Every final
SQLite run passed the read-only verifier.

Selected integration non-regression command:

```text
uv run --with-requirements requirements-m0.txt python -m unittest \
  tests.test_m4c_integration.M4CIntegrationTests.test_01_live_public_chain_closes_exactly_one_effect \
  tests.test_m4c_integration.M4CIntegrationTests.test_03_post_success_crash_reconciles_without_second_mutation \
  tests.test_m4c_integration.M4CIntegrationTests.test_08_crash_recovery_is_a_real_process_boundary \
  tests.test_m4cil_integration.M4CILIntegrationTests.test_01_happy_chain_uses_real_incremental_checkpoint_reuse \
  tests.test_m4cil_integration.M4CILIntegrationTests.test_04_actual_subprocess_crash_reopens_and_reconciles_without_resend
```

Result: `5/5 OK`. `git diff --check` also passed.

Full discovery was also run from the deliberately dirty repair tree:

```text
uv run --with-requirements requirements-m0.txt python -m unittest discover -s tests -v
```

`MEASURED`: 179 tests ran in `68.768s`; 176 passed and three admission tests
failed. The failing traces were only the gates that require committed-clean Git
closure: M2-IL rejected the listed dirty/untracked paths, M4C's inherited
measured-LR receipt rejected Git drift, and M4C-IL rejected the same dirty
closure. No M4B, M4C integration, or M4C-IL integration behavior test failed.
This is not a full-suite PASS and is not reported as one; a frozen promotion
subject would have to be committed and rerun in clean CI to close those gates.

## What remains open

`MEASURED` on this host: with `max_attempts=1`, one transient result routes to
retry, the next dispatch raises `HarnessError("max_attempts exceeded")`, and
the run remains `active` with one pending item while `verify_run` reports
`valid=true`. M4B therefore enforces the numeric bound but does not implement
the generic loop's typed `RETRY_EXHAUSTED` terminal transition.

`PROPOSED`: the next smallest H fault slice should freeze that state and require
a typed terminal or explicit human-reconciliation route without abandoning the
pending effect. Persistent unknown outcomes, full budget vocabulary, checkpoint
migration, and outer `SUCCEEDED` closure remain separate later slices.

`MEASURED` as an evidence audit: M4C and M4C-IL deliberately stop their FSM
projection at `HONOR_PENDING_INTERRUPT`, leave the durable run `active`, and do
not execute the outer reducer. They are bounded integration and crash-recovery
candidate evidence, not proof that H prevents a false terminal state.

`ACCEPTED` for repository governance: the engine verdict remains `defer`.

## Proposed retry-exhaustion follow-up

`PROPOSED`: a subsequent uncommitted M4B working-tree slice addresses the
retry-exhaustion gap above without claiming to execute the outer run reducer.
When a new attempt would exceed `max_attempts`, it persists
`status = reconcile, route = retry_exhausted` before querying the destination.
Confirmed success uses the existing success receipt path. Confirmed
non-application plus the bounded source-attempt ledger first persists
`reconciled_not_applied/retry_exhausted_not_applied`, then persists an exact
`confirmed_failure` `ActionReceipt`, retains completed route
`retry_exhausted`, and leaves the run `active` for outer receipt re-ingestion.
An unproven query persists `unknown/human_reconciliation`; later automatic
reconcile and dispatch calls do not query or retry it. A pending interrupt
cannot terminalize over that handoff. This is local fault family `m4b-rx1`, not
global graph/schema fault number 26.

The failing-first focused command was:

```text
uv run --with-requirements requirements-m0.txt python -m unittest \
  tests.test_m4b_durable.M4BDurableTests.test_26_retry_exhaustion_queries_before_confirmed_failure_receipt \
  tests.test_m4b_durable.M4BDurableTests.test_26b_retry_exhaustion_persists_bounded_human_reconciliation_handoff \
  tests.test_m4b_durable.M4BDurableTests.test_26c_verifier_rejects_exhaustion_dispatch_and_terminal_pending_mutations
```

The pre-repair result was `FAILED`: two tests errored on the untyped
`HarnessError("max_attempts exceeded")`, and one failed because no durable
exhaustion route was created. Those test bodies were later renamed into local
family `m4b-rx1a` through `m4b-rx1c` after discovering that global fault 26 is
reserved for graph/schema work. Passing current commands for the proposed
repair are recorded in `docs/M4B_DURABLE.md`. These local checks do not promote M4B:
the contract and manifest remain `PROPOSED_PENDING_MEASUREMENT`, and real
destination, production, efficacy, outer-completion, and engine claims remain
open.
