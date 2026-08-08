# FLRH Graph Interoperability Profile v0

> Status: PROPOSED / NOT AN INDUSTRY STANDARD / NOT CANON

## Typed federation

| Graph | Responsibility | Identity basis | Failure if confused |
|---|---|---|---|
| `G_sem` | facts, goals, rules, constraints, authority, conflict | canonical dataset plus entailment regime | observed trace becomes truth or approval |
| `G_dep` | derivation, dependency, invalidation, recomputation | dependency keys plus rule/dataflow version | semantic relation is mistaken for build dependency |
| `G_comp` | resolved component, port, handler, adapter, schema | normalized graph including resolver/profile | source equality hides runtime wiring drift |
| `G_action` | command, declared inputs, platform, attempts, outputs | action/CAS digest | identical command text is mistaken for identical action |
| `G_trace` | observed event/span/attempt flow | run IDs and links; non-authoritative | sampled trace becomes terminal receipt |
| `G_prov` | entity, activity, agent, responsibility, revision | source digest plus qualified provenance | provenance becomes truth or causality proof |
| `G_schema` | vocabulary, shapes, rule bundle, migration | schema/rule bundle digest | unlike schemas are compared directly |

`GraphDelta` is a change protocol between immutable graph revisions, not an eighth universal graph.

## Identity ladder

These relations are deliberately distinct:

```text
canonical_bytes_equal
  != graph_isomorphic
  != semantically_equivalent
  != resolved_composition_equivalent
  != behaviorally_equivalent
```

A comparison must name the rung it proves and pin the canonicalizer, schema, rule bundle, entailment regime, resolver, and environment profile relevant to that rung.

## Common envelopes

```text
GraphEnvelope
  profile_version
  graph_kind
  graph_id
  revision_id
  base_revision_id?
  schema_ref + schema_digest
  rule_bundle_digest?
  resolver_ref + resolver_digest?
  environment_profile_digest?
  canonicalization_algorithm + version + media_type
  content_digest_algorithm + content_digest
  source_snapshot_digest
  provenance_refs[]

GraphDelta
  delta_id
  graph_id
  base_revision_id
  new_revision_id
  additions_digest
  deletions_digest
  causal_parent_delta_ids[]
  producer_id
  idempotency_key
  sequence_or_frontier

ResolvedCompositionReceipt
  source_spec_digest
  resolver_digest
  schema_digest
  rule_bundle_digest
  production_profile_digest
  harness_profile_digest
  normalized_prod_graph_digest
  normalized_harness_graph_digest
  substitution_manifest_digest
  forbidden_delta_count
  production_root_reachability_result

ActionReceipt
  action_digest
  command_digest
  input_root_digest
  platform_digest
  attempt_id
  idempotency_key
  output_digests[]
  terminal_status
  trace_ref
```

## Invariants

1. Every graph and edge has a `graph_kind` and namespaced type.
2. Revisions are immutable; change creates a new revision plus `GraphDelta`.
3. Digest comparison requires matching canonicalizer, schema, resolver, and profile versions.
4. Every derived fact has dependency and qualified provenance records.
5. Source or rule retraction invalidates the affected reverse closure before publication.
6. Action identity includes command, declared inputs, relevant platform/environment, and timeout.
7. Trace is never the sole authority for fact, authorization, or completion.
8. Production/harness equivalence compares resolved `G_comp`, not source text.
9. Only enumerated port-compatible adapter substitutions are permitted.
10. Delta replay and duplicate-idempotency application converge to the same final digest.
11. Migration declares `lossless` or enumerated `lossy` semantics and preserves revision lineage.
12. Canonicalization, fixpoint, causal depth, and queues have explicit budgets and no-progress behavior.

## Baseline standards profile

- RDF 1.1-compatible core representation; RDF 1.2 features remain optional until the selected processor matrix is stable.
- SHACL 1.0 Recommendation with pinned processor and version for mandatory structural gates.
- PROV-O vocabulary for provenance, without treating derivation as physical causality or correctness.
- RDFC-1.0 or another explicitly pinned algorithm for canonical dataset bytes.
- Property-graph/GQL support only as an adapter with enumerated round-trip loss.
- OpenTelemetry only as trace projection; durable receipts live outside sampled traces.
