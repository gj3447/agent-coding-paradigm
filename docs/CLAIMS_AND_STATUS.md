# Claims and Status

Updated: 2026-08-08

## Current claims

| Claim | Status | Evidence boundary |
|---|---|---|
| the pinned checker returns PASS for the declared M0 schemas and fixtures | MEASURED | checker-relative local conformance; no global consistency proof or runtime |
| the bounded Python M1 reference implements a deterministic pure-F transition with typed rejection and inert proposals for the frozen event profile | MEASURED | six success cases, nineteen full-rejection fixture oracles, seven sensitivity mutations, two exact goldens, one two-step replay, 52 clean replay runs plus two guarded-import runs, eight explicit categories plus three audit-only probes, ten import-metadata checks, and eight detected control mutants; no universal purity or integrated-runtime claim |
| F/L/R/H responsibilities can be specified without collapsing into one LLM loop | PROPOSED | architecture plus machine contracts; no runtime |
| signed deltas and scalar logical frontiers provide a plausible L-to-R narrow waist | HYPOTHESIS | executable fixture semantics; no incremental implementation |
| typed graph federation avoids several category errors of a soup graph | HYPOTHESIS | machine-validated graph-kind/envelope shapes; no graph implementation |
| H should own continuation and effect/evidence closure | PROPOSED | validated abstract FSM/loop; no crash/recovery evidence |
| the repository is ready to be called a reusable engine | DEFERRED | no executable consumer, durability proof, or recovery evidence |
| FLR-H improves agent outcomes | UNSUPPORTED | no held-out equal-budget comparison |
| FLR-H is original or an industry standard | UNSUPPORTED | no prior-art exhaustion or standards process |
| FLR-H is production-ready | UNSUPPORTED | only one bounded pure-F reference slice exists; L/R/H, durability, graphs, and operational trials remain open |

## Falsifiers

The proposal must be downgraded if any of these persist after reasonable repair:

- real coding tasks repeatedly require hidden ambient effects inside F;
- incremental L/R results disagree with clean recomputation;
- separating semantic, dependency, composition, trace, provenance, and schema graphs loses required information or makes round-trip impossible;
- independent implementations cannot agree on the same conformance corpus;
- H cannot prevent duplicate mutation or false terminal state across crash/resume;
- the boundary adds complexity without serving at least two real consumers;
- equal-budget held-out trials show no improvement or material regression on the selected outcomes.

If mechanics fail, rename the work from “Agent Coding Paradigm” to an internal experimental architecture profile. If comparative efficacy fails, preserve useful mechanisms without claiming a superior paradigm.

## Residual risks

- stratified negation may be too weak; stronger semantics may be too expensive or hard to explain;
- provenance completeness depends on declaring all dependencies and hidden inputs;
- graph digests can miss resolver, plugin, flag, schema, or environment drift unless the composition profile is complete;
- fake adapters may not reproduce real destination failure modes;
- some external systems cannot provide stable idempotency or queryable receipts;
- independent verifiers may share assumptions, libraries, or training-data blind spots;
- durable bookkeeping may cost more than it saves for short, low-risk tasks.

## Exclusion

Jaebaeman is not a dependency, module, layer, protocol, or explanatory frame in this repository. Planning and dispatch can be studied elsewhere without changing the FLR-H runtime question.
