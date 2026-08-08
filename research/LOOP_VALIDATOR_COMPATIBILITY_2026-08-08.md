# Loop Validator Compatibility Readback

Date: 2026-08-08
Target: `spec/loop-contract.v1.json`

The target contract follows the generic bounded-loop mechanics from the SYMPOSIUM `loop-engineering` reference: hard aggregate budgets, no-progress cutoff, durable checkpoints, intent-before-effect, exact approval, unknown-outcome reconciliation, deferred interrupts, independent verification, replay, and trace fields. Its lifecycle is deliberately referenced rather than duplicated: `control_fsm_binding` pins `spec/run-fsm.v1.json` by SHA-256.

The bundled validator was run read-only on 2026-08-08. It returned 32 errors: 27 assume that `states`, `transitions`, terminal maps, and interrupts are embedded again inside the loop document, and five require the SYMPOSIUM seven-commander canon, including `JaebaeMan`. The validator has no mode for a digest-bound external FSM.

This repository intentionally excludes planning/dispatch doctrine and Jaebaeman, and it rejects two normative lifecycle copies that can drift. It therefore does not add a dormant commander object or duplicate the FSM merely to turn that project-specific validator green. `scripts/validate_m0.py` checks the applicable loop invariants, verifies the exact FSM digest and cross-contract state bindings, and asserts that `commander_dispatch` is absent.

The bundled result is an expected validator-profile incompatibility, not a passing check, runtime evidence, or scientific verdict.
