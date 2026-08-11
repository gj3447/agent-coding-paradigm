# Agent instruction routing without prompt-token limits

> Status: `PROPOSED`. The routing mechanism is locally specified and checked;
> no token, cost, latency, or task-success improvement is claimed yet.

## Decision

The repository uses one root `AGENTS.md` as a compact constitution and router.
It does not add nested auto-loaded instruction files. Detailed FLR-H semantic
invariants live in `agent-rules/semantic-invariants.md` and are loaded only for
semantic, runtime, conformance, fault, evidence, or consumer-sample work.
Claim, engine, publication, and mechanical edits have separate routes in
`agent-rules/routes.v1.json`.

There is no hard prompt-token ceiling. Routing may record bytes, words, and—if
an exact tokenizer and version are named—tokens as observations. It may not
truncate required instructions, omit a required rule, or reject work because
the prompt is large. If two routes plausibly apply, the resolver loads their
union in canonical order and deduplicates by stable rule ID.

This does not relax runtime safety. Bounded queues, attempts, rule firing,
deadlines, waits, cancellation, and effect budgets protect execution and remain
hard invariants. They are not prompt-context limits.

## Why routing is the chosen control

The local audit found one automatic instruction file, not a hierarchy of
competing files. The larger cost risk is repeatedly preloading architecture,
semantics, harness, graph, claim, ADR, and manifest closures for unrelated
work. Manifest `owned_closure` and inherited digests prove an evidence subject;
they do not instruct an agent to read every artifact before every task.

Official OpenAI guidance recommends removing repeated instructions, exposing
only task-relevant tools, and validating leaner prompts on representative tasks
instead of assuming lower token use means better performance. The local route
keeps this as a mechanism source, not as evidence that this repository already
improved. See [OpenAI model guidance](https://developers.openai.com/api/docs/guides/latest-model#favor-leaner-prompts).

## Admission checker

```bash
python3 scripts/check_agent_rule_routes.py
python3 -m unittest tests.test_agent_rule_routes -v
```

The checker fails on schema drift, missing or duplicate rule IDs, a wrong route
union, irrelevant preloading in a frozen fixture, instruction truncation, or a
hard prompt-token limit. A deliberately large but relevant rule source must be
accepted and merely observed.

## Quality-first A/B protocol

Before claiming an improvement, run the old and routed instruction structures
against the same frozen tasks, commit, Codex/model version, tools, and
environment. Include at least a documentation edit, F purity change, L
retraction fault, R frontier fault, H unknown-outcome fault, claim update, and
public-source ingestion task.

Primary outcomes are conformance, invariant preservation, correct claim labels,
zero forbidden actions, and independent review. Secondary observations are
context bytes/tokens, repeated-rule count, latency, and cost. Adopt the routed
variant only if primary quality is not degraded. Do not set a token target,
truncate either arm, or count fewer tokens as success by itself.
