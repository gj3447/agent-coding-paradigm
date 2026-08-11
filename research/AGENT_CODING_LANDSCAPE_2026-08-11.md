# Agent-coding landscape and bounded absorption plan — 2026-08-11

> GitHub metadata is `MEASURED` only at the instant recorded in
> `AGENT_CODING_SOURCE_SNAPSHOT_2026-08-11.md`. The reuse plan below is
> `PROPOSED`. Popularity is not correctness or suitability evidence.

## What was gathered

The machine-readable ledger pins exact revisions and licenses for 17 sources.
The larger coding-agent signals include [OpenCode](https://github.com/anomalyco/opencode),
[Gemini CLI](https://github.com/google-gemini/gemini-cli),
[OpenAI Codex](https://github.com/openai/codex),
[OpenHands](https://github.com/OpenHands/OpenHands),
[Cline](https://github.com/cline/cline), [Goose](https://github.com/aaif-goose/goose),
and [Aider](https://github.com/Aider-AI/aider). Smaller or broader projects are
retained when they expose a useful seam: [mini-SWE-agent](https://github.com/SWE-agent/mini-swe-agent)
as a compact comparator, [LangGraph](https://github.com/langchain-ai/langgraph)
and [Microsoft Agent Framework](https://github.com/microsoft/agent-framework)
for checkpoint/orchestration comparison, and the
[Agent Client Protocol](https://github.com/agentclientprotocol/agent-client-protocol)
for versioned editor-agent interoperability vocabulary.

No project is vendored. A source is not adopted merely because it is popular,
open source, importable, or similar to FLR-H.

## Mechanisms worth testing locally

`PROPOSED` bounded absorption candidates:

1. Permission and approval policy as versioned data, with deny taking
   precedence and approvals bound to exact lifecycle/effect identities.
2. Typed action, observation, and error events, while keeping observations and
   trajectories outside accepted-state and completion authority.
3. Checkpoint/resume fixtures that explicitly exercise code re-execution,
   unknown effects, cancellation, and bounded waits.
4. Path- and task-routed context with on-demand rule bodies, no hard
   prompt-token limit, and quality-first A/B evaluation.
5. Task packages that bind instruction, environment, base revision, allowed
   effects, fault schedule, hidden verifier, and run receipt.

These are mechanism inputs, not permission to build a broad plugin framework or
replace the current contracts. Each candidate needs a failing fixture,
independent verifier, and claim boundary before implementation evidence can
change.

## Evaluation data lanes

The ledger includes [SWE-bench](https://github.com/SWE-bench/SWE-bench) for
issue/base-commit/test binding, [SWE-smith](https://github.com/SWE-bench/SWE-smith)
for mutation-generated fault tasks, [Harbor](https://github.com/harbor-framework/harbor)
and [Terminal-Bench 2](https://github.com/harbor-framework/terminal-bench-2)
for instruction/environment/verifier packages,
[OpenAI Frontier Evals](https://github.com/openai/frontier-evals) for
offline-verified software-work tasks, and
[OpenHands benchmarks](https://github.com/OpenHands/benchmarks) as a moving
adapter/harness comparison surface.

External benchmark outcomes belong only to a separately preregistered efficacy
lane. They cannot close FLR-H conformance, durability, real-consumer, or engine
gates. Dataset and repository revisions must be pinned, and licensing must be
checked again for any assets actually used.

## Private operational sample

The first private-work-derived sample follows the Harbor/SWE-bench package
shape but contains synthetic values only. It binds six lanes—task, repository,
tests, resources, effects, and independent verification—and freezes failure
shapes instead of copying private code, tickets, captures, logs, topology, or
commands. See `docs/CONSUMER_SAMPLE_PROTOCOL.md`.

The exact source ledger is
[`agent-coding-source-registry.v1.json`](agent-coding-source-registry.v1.json).
