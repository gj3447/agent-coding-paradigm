# LakatoTree store canon declaration — 2026-08-11

Two lakatotree stores currently hold AgentParadigm trees, split by the research-environment
move:

| Store | Holds | Write auth |
|---|---|---|
| delltower `localhost:55170` (airobotics-Precision-7960) | `LakatosTree_AgentParadigm_20260810` (BOUND to this repository, branch `ts-second-impl`) | open locally |
| dev-01-side `192.168.0.26:55170` | `LakatosTree_AgentParadigm_20260808` (historical; E1 preregistration state) | token-required; token not distributed |

**Canon**: the **delltower store** is the canonical judgment surface for
`LakatosTree_AgentParadigm_*` programmes. The 2026-08-08 incarnation on the dev-01-side
store is a historical reference (its E1 prereg state also survives in
`research/LAKATOTREE_BINDING_2026-08-08.json`); do not fork new AgentParadigm nodes there.

Receipts recorded on the canonical store so far:

- `n4-4arm-round2-prereg-20260810` — 4-arm round-2 preregistration
  (pred_receipt `6df0191d415a809e54f7f88f95db4b875241431d7baa8bfb077e0eeb2bda36b1`),
  result submitted 2026-08-11 → verdict `partial@L0`, lakatos qualitative `progressive`,
  delta +0.087 (SYMPOSIUM `EXPERIMENT_4ARM_RESULTS_20260811_R2.md`).
- `n5-4arm-round3-interaction-prereg-20260811` — round-3 interaction confirmation
  preregistration (pred_receipt
  `e45bec982c1012273770299ff60d06339c8f47aa212cbaad2fd71e4ccfe8a1f8`,
  prereg sha `6952ef6d201a1867c6b453993315de22aba4fa8c5a6eeb18204da310c89d4f7a`,
  SYMPOSIUM commit `8cf2a2c`).

This note is descriptive routing, not a scientific claim; assurance stays at the tiers the
store itself reports (L0 client-asserted for the round-2 verdict).
