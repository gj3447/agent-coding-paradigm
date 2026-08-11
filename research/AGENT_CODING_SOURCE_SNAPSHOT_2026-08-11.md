# Agent-coding GitHub source snapshot — 2026-08-11

> `MEASURED` only for the GitHub REST metadata observation described here.
> Stars and forks are discovery signals, not quality, adoption, efficacy, or
> engine-promotion evidence. GitHub's detected SPDX value is not legal advice
> or a complete license review.

## Subject and environment

- Observation time: `2026-08-11T09:48:34Z`
- Host: Linux `7.0.14-5-pve`, x86_64
- GitHub CLI: `gh 2.97.0`
- Fixture: `research/agent-coding-source-registry.v1.json`
- Schema: `spec/schema/agent-source-registry.v1.schema.json`
- Scope: 17 non-exhaustively selected coding agents, comparators, protocol, and
  evaluation repositories

The exact repository set is frozen in the fixture. For each repository the
observation executed these two authenticated read-only requests, with the first
response's exact `default_branch` supplied to the second:

```bash
gh api repos/{owner}/{repo} \
  --jq '{full_name,html_url,stargazers_count,forks_count,archived,default_branch,license:(.license.spdx_id // "NOASSERTION"),pushed_at}'
gh api repos/{owner}/{repo}/commits/{default_branch} \
  --jq '{sha:.sha,committed_at:.commit.committer.date}'
```

`MEASURED`: the snapshot contains 17 unique repositories and exact 40-hex HEAD
SHAs: eight coding agents, two runtime comparators, one protocol, and six
evaluation sources. GitHub reported nine MIT and eight Apache-2.0 repositories.
No source tree, package, model, task payload, or benchmark asset was copied.

The offline checker command was:

```bash
uv run --with-requirements requirements-m0.txt \
  python scripts/validate_agent_source_registry.py
```

Its expected report status is `MEASURED_METADATA_SNAPSHOT_VALIDATED` with 17
sources and zero vendored sources. This validation proves only frozen metadata
shape and local boundary checks; it does not re-query GitHub or establish that
the snapshot remains current.
