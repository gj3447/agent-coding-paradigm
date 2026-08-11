# Agent instruction routing observation — 2026-08-11

> The file-size observations below are `MEASURED` for the named local subjects
> and commands. The routing design and A/B protocol remain `PROPOSED`. No token,
> quality, latency, or cost improvement is claimed.

## Subjects

- Baseline: `AGENTS.md` at commit
  `7647b48cc4874a384d0d86a0e02ea355e99d11de`.
- Candidate: the 2026-08-11 worktree versions of `AGENTS.md` and
  `agent-rules/semantic-invariants.md`.
- Environment: Linux `7.0.14-5-pve` x86_64, Codex CLI `0.147.0`.

Commands:

```bash
git show 7647b48cc4874a384d0d86a0e02ea355e99d11de:AGENTS.md | wc -c -w -l
wc -c -w -l AGENTS.md agent-rules/semantic-invariants.md
codex --version
uv run --with-requirements requirements-m0.txt python scripts/check_agent_rule_routes.py
uv run --with-requirements requirements-m0.txt python -m unittest tests.test_agent_rule_routes -v
```

Observed source sizes:

| Subject | Lines | Words | UTF-8 bytes |
| --- | ---: | ---: | ---: |
| Baseline root `AGENTS.md` | 62 | 449 | 3,285 |
| Candidate root `AGENTS.md` | 26 | 317 | 2,369 |
| Routed semantic invariants | 15 | 174 | 1,169 |
| Candidate root plus semantic route | 41 | 491 | 3,538 |

The candidate makes the always-loaded repository source smaller while allowing
a relevant semantic route to be larger than the baseline. This is deliberate:
there is no hard prompt-token limit, tokenizer-derived target, truncation, or
failure threshold. Tokens remain `null` unless an exact tokenizer and version
are declared. Required instructions win over size.

The offline route checker admitted five frozen routing cases and the five unit
tests passed. Those checks establish only deterministic routing and the absence
of a configured prompt cap. The quality-first A/B protocol in
`docs/AGENT_CONTEXT_ROUTING.md` must pass representative tasks without primary
quality regression before any improvement claim is considered.
