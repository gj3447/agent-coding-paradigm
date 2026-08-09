# M4A — pure singleton H authority projection

Status: **PROPOSED_PENDING_MEASUREMENT**.

M4A adds one public, deterministic function:

```python
from flrh_authority import project_h_intent
result = project_h_intent(command)
```

The command carries one exact `RPublishedBatch`, its supplied M3
`r_profile_digest`, `PLAN_EFFECTS` or
`WAIT_APPROVAL`, a supplied authority snapshot, explicit `observed_at` and
`effect_sequence`, and the approval objects needed by the selected state. The
function has no ambient authority: it does not read policy, time, credentials,
registries, adapters, files, or networks.

For eligible allowed low-risk work it emits an exact M0 `EffectIntent`
candidate with `EFFECT_AUTHORIZED -> COMMIT_INTENT`. High-risk work first emits
an exact `HApprovalRequest` with `APPROVAL_REQUIRED -> WAIT_APPROVAL`; only an
exact, live, unrevoked, unconsumed, all-field-bound grant emits the candidate
with `APPROVAL_GRANTED -> COMMIT_INTENT`.

The M3 profile digest is used to recompute the exact stable-batch preimage;
proposal, verdict, time/frontier, list uniqueness, versions, batch identity,
and outer digest are parsed fail-closed. This is self-consistency checking of
supplied evidence, not authentication, origin attestation, or provenance.
Runtime parsing also enforces the schema's object-kind constants and the
protocol `Id` pattern/128-character ceiling, including authority versions,
proposal preconditions, and verdict support identifiers.

Approval context, request, and grant bind `context_digest`, `policy_version`,
`approver_scope`, plus the loop contract's run, workflow, action, artifact,
destination, visibility, scope, actor, expiry, nonce, and rationale fields.
Projected FSM event evidence carries the exact actor-role/capability pair and
all `evidence_required` fields of the pinned transition. `APPROVAL_REQUIRED`
carries the proposal `action_digest` and snapshot `assessed_risk` as
`risk_classification`. `EFFECT_AUTHORIZED` carries two domain-separated
digests: `policy_verdict` binds the supplied R profile digest, complete
eligibility verdict, authority decision/digest, and assessed risk;
`capability_digest` binds the capability, authority, proposal/effect/action,
destination, and adapter. `APPROVAL_GRANTED` carries
`exact_hash_approval_digest` exactly equal to the validated `approval_digest`.
These event digests are supplied-evidence self-consistency bindings, not policy
authentication or provenance. Intent idempotency is derived from the frozen
tuple `run_id`, `transition_id`, `effect_sequence`, `action_digest`, and
`adapter_version`.

This slice stops before the durable boundary. It does not emit
`INTENT_COMMITTED`, dispatch anything, record an attempt or `ActionReceipt`,
reconcile an unknown outcome, or claim completion. `spec/run-fsm.v1.json`
remains the sole lifecycle authority.

Run the proposed gate explicitly:

```sh
python3 scripts/validate_m4a.py --allow-proposed
```

Passing this command is proposed reference evidence only. It is not durability,
crash-recovery, effect-safety, integrated-runtime, production, engine,
comparative-efficacy, or scientific evidence.
