# FSM Validator Compatibility Readback

Date: 2026-08-08
Target: `spec/run-fsm.v1.json`

The project contract declares the project-specific dialect `flrh-run-fsm/v1`. It uses one Draft 2020-12 schema for complete typed events, an actor-role/capability authority matrix, global interrupt semantics, and a separate closed trace-fixture schema.

The bundled SYMPOSIUM FSM validator and trace runner were run read-only. They target a different repository-native shape: `fsm-spec/v1` with per-event schemas, a custom context field map, effect payload bindings, prose verification fields, and string event names in trace steps. The static validator returned 72 dialect-shape errors; the trace runner could not interpret the typed event objects and returned `FAIL`.

The project does not label its contract `fsm-spec/v1` and does not count either bundled invocation as a passing M0 check. The pinned project checker instead validates the closed JSON schemas, actor/capability authority, reachability, success isolation, interrupt deferral, all 25 declared transitions, every guard-false outcome, all nine terminal categories, and all three interrupt types over 18 typed traces.

This is a disclosed dialect incompatibility. It is also why M6 still requires a second independent implementation or conformance runner; the M0 PASS is checker-relative and cannot establish global consistency by itself.
