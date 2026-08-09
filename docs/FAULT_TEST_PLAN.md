# Mechanics Admission and Fault Test Plan

> Status: F TESTS 1–3 AND L TESTS 4–9 MEASURED BY M1/M2; R, H, GRAPH, AND EFFICACY TESTS PROPOSED. These tests admit mechanics only; they do not prove comparative efficacy.

## F — purity and replay ✅ M1 MEASURED 2026-08-08

1. The same snapshot, accepted event, and versions produce the same transition digest.
2. Reducer access to clock, RNG, filesystem, network, credentials, and model/tool calls is blocked.
3. Malformed and incompatible inputs yield typed rejection with no mutation.

## L — fixpoint, contradiction, provenance, retraction ✅ M2 MEASURED 2026-08-09

4. Shuffled rule/worklist order produces the same fixpoint digest.
5. The selected semantics handles `p :- not q; q :- not p` exactly as specified or rejects it as outside v0.
6. `NEITHER` and `BOTH` evidence states remain distinct.
7. With `a -> c` and `b -> c`, retracting `a` retains `c` through `b`.
8. Removing the last support retracts the fact and leaves no stale provenance.
9. Recursive-edge deletion yields the same closure as clean full recomputation.

## R — delta, frontier, ordering, backpressure

10. Insert, delete, duplicate, and out-of-order deltas converge to the clean recompute digest.
11. No irreversible effect fires before the epoch frontier passes.
12. A late event follows the declared correction/retraction/rejection/compensation policy.
13. Dependencies and reactions for one epoch publish as one stable batch.
14. Slow consumers preserve queue bounds and the declared overflow policy.
15. Equal-priority ready items use deterministic tie-breaking.

## H — approval, durability, effects, interrupts

16. Crash before intent commit causes no external effect.
17. Crash after intent commit but before dispatch resumes to one logical effect.
18. Crash after external success but before receipt recording reconciles by destination evidence and never blind-retries.
19. Duplicate effect delivery and duplicate result events converge to one mutation/result.
20. Expired, revoked, replayed, wrong-nonce, wrong-action, wrong-destination, wrong-visibility, and wrong-version approvals fail closed.
21. A stale runner fencing token cannot commit after split brain.
22. Corrupt or incompatible checkpoints quarantine or explicitly migrate; they never silently resume.
23. Cancel, timeout, and budget exhaustion during an effect are persisted, the effect is reconciled, then the interrupt is honored.
24. Transient, permanent, and unknown outcomes route to retry, no-retry, and reconcile paths respectively.
25. No-progress windows and meaningful-gain reset reproduce from checkpointed evidence.

## Graph and harness closure

26. Invalid graph kind, cardinality, edge domain/range, or schema fixtures fail structural validation.
27. Triple order and blank-node renaming preserve canonical digest; non-isomorphic data changes it.
28. Adversarial canonicalization exceeding its budget fails closed.
29. Delta replay is idempotent and reaches the declared new revision digest.
30. Orphan handler, feature-flag inversion, plugin omission, schema drift, or platform adapter drift fails resolved composition equivalence.
31. A changed component must be reachable from the resolved production root and to a terminal receipt path.
32. Trace-only evidence cannot satisfy `DONE`.
33. A deterministic oracle failure overrides a model judge's pass.
34. Two independent implementations agree on the conformance corpus's canonical digests, structural verdicts, and delta replay results.

## Comparative experiment gate

All mechanics tests above must pass before M7. Comparative evaluation then requires a held-out sealed task corpus, equal budgets, fixed environments, blinded or independent outcome scoring, long-horizon maintenance outcomes, uncertainty intervals, and published failures—not just successful demos.
