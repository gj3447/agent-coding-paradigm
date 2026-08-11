# Public consumer sample protocol

> Status: `PROPOSED`. This protocol defines a corpus shape; it is not runtime,
> production, or comparative-efficacy evidence.

## Why the first sample is synthetic

The motivating workflow runs bounded analysis work on a shared,
production-adjacent accelerator and must yield to higher-priority workloads.
The private source material is useful for identifying the control problem, but
it is not a public dataset. It may contain operational identifiers, topology,
commands, paths, logs, captures, or product context that cannot be made safe by
renaming a few fields.

The public sample therefore preserves only the workflow structure:

```text
task + repository + tests + resource observation
  -> pure decision
  -> explicit eligibility
  -> stable publication
  -> durable intent and bounded dispatch
  -> reconciliation when outcome is unknown
  -> independent read-only verification
  -> H-owned terminal state
```

No private payload is copied, hashed into the fixture, excerpted, or required
to run the validator. The values are synthetic from the start. This is
structural synthesis, not a claim that the fixture represents the distribution
or performance of the private workload.

## Six data lanes

Each sample joins six graph-kind-aware lanes instead of flattening everything
into one trace:

- `task_spec`: declared goal, inputs, constraints, and authority boundary;
- `repository_state`: exact code/configuration subject or synthetic stand-in;
- `test_evidence`: producer-independent executable checks;
- `resource_observation`: bounded capacity and priority evidence;
- `effect_observation`: dispatch, unknown outcome, and reconciliation facts;
- `verification_receipt`: read-only evidence consumed by H before completion.

The first corpus freezes six variants: happy path, insufficient headroom,
unknown after dispatch, duplicate-identity conflict, producer self-report
without independent evidence, and cancellation while an effect is unresolved.
The one-mutation expectations are synthetic oracle values and do not establish
exactly-once delivery.

## Admission and future measurement

Run the offline admission gate with:

```bash
python3 scripts/validate_consumer_samples.py
python3 -m unittest tests.test_consumer_samples -v
```

The checker validates the closed JSON Schema, FLR-H ownership, bounded waits
and attempts, conflict routing, reconciliation-before-retry, independent
verification, and generic leak patterns. A future real-consumer receipt must be
kept private unless separately cleared, name the exact environment and command,
and must not upgrade this `PROPOSED` corpus based on a model verdict or producer
self-report.

The machine-readable boundaries are
[`consumer-sample-contract.v1.json`](../spec/consumer-sample-contract.v1.json),
[`consumer-sample.v1.schema.json`](../spec/schema/consumer-sample.v1.schema.json),
and [`cases.json`](../fixtures/consumer-samples/cases.json).
