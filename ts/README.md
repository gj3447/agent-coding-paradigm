# flrh-ts — TypeScript second implementation (M6 track)

> Status: **CANDIDATE / LOCAL VERIFY GREEN AGAINST FROZEN M0-CANONICAL + M1 CORPUS / NOT A MEASURED MILESTONE**
>
> The Python reference under `../src` plus `../fixtures` and `../spec` are the
> conformance oracle. Judgement is byte identity of `flrh-cjson/1` canonical
> output. The local suite covers: M0 canonical equal/different/reject cases and
> the frozen golden bytes; M0 protocol valid(10)/invalid(13) verdicts plus the
> EffectIntent→ActionReceipt identity preservation; M1 success(7, all frozen
> `transition_digest` values), rejection(19, code+path+context), both exact
> byte goldens, the equivalence pair, sensitivity(7), and the replay sequence.
> Clean-process replay profiles, ambient guards, and the Python checker's count
> gates are NOT reproduced here yet — claims stay checker-relative and local.

## Layout (flrh-ts discipline)

- `src/domain/` — the pure F kernel (`stepF`). Pure TypeScript only: no
  `effect`, no Promise/async/throw, no clock/random/env/IO, no ambient module
  imports. Enforced by eslint syntax rules and dependency-cruiser
  (negative-control verified: a deliberate `node:fs` import in domain fails
  both gates).
- `src/contracts/` — the wire layer: lexical JSON parser (bigint integers,
  float lexemes preserved), `flrh-cjson/1` canonicalizer, pure sha256.
- `tests/conformance|examples|properties|integration` — fixture-driven parity,
  unit, fast-check property, and replay suites.

## Commands

```bash
pnpm check    # TS7 typecheck + eslint + dependency-cruiser  (fast, run often)
pnpm verify   # check + unit + property + conformance + integration (before DONE)
```

## Toolchain notes

- `typescript@6.0.3` is the root `typescript` so eslint's TS parser and
  dependency-cruiser get the JS compiler API they support; the native
  TypeScript 7 compiler is installed side-by-side as the `typescript7` alias
  and drives `pnpm typecheck` (Microsoft's documented side-by-side pattern).
- Imports are extensionless with `moduleResolution: "bundler"` — this
  workspace is executed only through vitest/esbuild, never as raw node ESM.
- Known checker-relative boundaries: Ajv words schema errors differently from
  Python jsonschema 4.25.1, so the invalid-fixture `expected_keyword` prose is
  not string-matched here (verdicts and single-branch validation are); the M0
  reject-case prose fragments are mapped to the canonicalizer's error codes.

Per repository AGENTS.md: claim labels apply, milestones close on receipts
only, and a producer is not the sole verifier of its own success.
