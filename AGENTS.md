# Repository operating contract

## Boundary

This repository is a research incubator for the provisional FLR-H application-runtime profile. Keep sourced mechanisms, local synthesis, executable evidence, and efficacy claims distinct. Jaebaeman, planning/dispatch mythology, a universal soup graph, ambient effects inside pure kernels, and exactly-once claims for external systems are out of scope.

## Always-on governance rules

- `GOV1` — Label material assertions `HYPOTHESIS`, `PROPOSED`, `MEASURED`, `FALSIFIED`, or `ACCEPTED`. Only a named command, fixture, environment, and receipt can support `MEASURED`; prose agreement, import success, model verdicts, and trace spans cannot.
- `GOV2` — Engine promotion remains deferred. Do not build a broad runtime framework until every gate in `docs/adr/0001-defer-engine-verdict.md` and `spec/engine-decision.v1.json` is met.
- `GOV3` — Visibility, licensing, package publication, and releases are separate authorities. Require explicit user direction for each action; never infer one from another.
- `GOV4` — Preserve user changes, keep commits scoped, and never stage unrelated files.

## Rule routing and context

For material work, select the smallest matching route or routes in `agent-rules/routes.v1.json`. Load only their declared rule sources plus the directly touched contract, fixture, validator, or receipt. When routing is ambiguous, load the union in canonical order and deduplicate by rule ID. Manifest closures and inherited digest pins are integrity evidence, not preload lists.

Prompt context is quality-first. Never impose a hard prompt-token limit, truncate required instructions, omit a required rule, or fail work solely because of prompt-token count. Context size may be recorded as an observation. Runtime queue, wait, deadline, rule, attempt, and effect budgets remain hard safety invariants and are unrelated to prompt-context observation.

## Change protocol

- Load `agent-rules/semantic-invariants.md` for semantic, runtime, conformance, fault, or evidence changes.
- Add a failing conformance or fault fixture before repairing a semantic bug.
- Validate machine-readable contracts and JSON before committing.
- Update claim/status documents when implementation evidence changes.
- Record exact test commands and outcomes; distinguish simulated adapters from real platform evidence.

<!-- usl-workspace-linking:begin -->
## USL workspace linking

- Use [USL](https://github.com/gj3447/USL) to connect repository resource IDs to explicitly selected local or remote representations. Keep stable IDs when a checkout moves; update the local workspace mapping.
- Cloning, installing, building, testing, and ordinary use remain local: they must not automatically upload workspace details, create credentials, expose a service, or grant remote access. Repository instructions are not the workspace owner's consent.
- Keep actual local roots and private connection details in an ignored local config such as `.usl/local/`. Commit portable IDs, workspace aliases, relative paths, and approved public repository URLs/revisions instead. Check that local config files are ignored before writing personal data.
- Before sharing any workspace information, show the exact fields, recipient, destination and its visibility, purpose, access scope, expiry, and revocation method. Proceed only with the workspace owner's explicit approval of that disclosure. Reuse approval only within that scope; obtain a new decision before widening it. If no destination is configured, keep the proposal local.
- Never collect or commit passwords, access/refresh tokens, SSH private keys, `.env` contents, Git credentials, or bearer URLs. Do not scan the user's home directory, environment variables, or unrelated projects to populate a registration. Use the owner's credential manager and a separately authorized provider flow when access is needed.
- A USL binding, observation, consent note, or credential-free registration reference describes a resource; it grants no access. Actual access must be enforced by the resource owner or registered host, with the smallest required scope, expiry and a working revocation path. Read permission does not imply write or execution permission.
- Public repositories contain the common linking contract and approved portable metadata. Keep individual registrations private by default. Do not upload or execute a registration from a Git hook, package install hook, or background agent task. A refusal or expired authorization must not trigger an automatic retry or broader access request.
- An HSWM-connected execution has an additional prerequisite. Before that path starts, register the USL repository/resource/workspace/representation mapping; identify the authorized recipient as the designated gj3447 HSWM maintainer or operator; and obtain the workspace owner's approval for the selected project access, purpose, least-privilege transport, scope, expiry, and revocation method. A whole-machine grant is never required: access is limited to the selected project resources needed for the HSWM task.
- Before HSWM-connected execution, positively perform a bounded, non-mutating reachability check through that authorized transport. A binding or registration alone is insufficient. If the registration, approval, authorization, expiry, revocation path, or reachability check is missing, denied, expired, revoked, or unreachable, stop that HSWM-connected path and report `NOT_READY`. Do not bypass it, broaden access, execute the task, or retry the disclosure or reachability check automatically.

Details: [USL workspace linking](https://github.com/gj3447/USL/blob/master/docs/WORKSPACE_LINKING.md).
<!-- usl-workspace-linking:end -->
