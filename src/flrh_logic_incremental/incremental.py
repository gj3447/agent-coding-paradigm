"""Pure persistent checkpoint adjunct for the exact M2 stratified-L profile.

This candidate intentionally remains an adjunct: it pins and reuses M2 private
construction helpers, independently constructs an exact fixpoint, and only
then calls the public M2 boundary as an equivalence oracle.  It performs no I/O.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from flrh_logic import solve_l
from flrh_logic import logic as _m2

from .canonical import canonical_bytes, canonical_digest, closed_copy


CONTRACT_VERSION = "flrh-l-persistent-incremental/1"
CHECKPOINT_SCHEMA_VERSION = "flrh-l-persistent-checkpoint/1"
RESULT_SCHEMA_VERSION = "flrh-l-persistent-result/1"
CANONICALIZATION_VERSION = "flrh-cjson/1"
MAX_ACTIVE_BASE_SUPPORTS = 10_000
MAX_CACHE_ENTRIES = 65_536
MAX_BODY_EVALUATIONS = 65_536
MAX_CHECKPOINT_BYTES = 67_108_864
INT64_MAX = 2**63 - 1

LPersistentLStep = Dict[str, Any]
LPersistentLRejection = Dict[str, Any]


def _persistent_rejection(code: str, path: str, logical_time: Any, bundle_digest: Any, context: Optional[Mapping[str, Any]] = None) -> LPersistentLRejection:
    return closed_copy({
        "kind": "LPersistentLRejection",
        "schema_version": RESULT_SCHEMA_VERSION,
        "contract_version": CONTRACT_VERSION,
        "code": code,
        "path": path,
        "logical_time": logical_time if isinstance(logical_time, int) and not isinstance(logical_time, bool) else None,
        "rule_bundle_digest": bundle_digest if isinstance(bundle_digest, str) else None,
        "context": dict(context or {}),
    })


def _checkpoint_without_digest(checkpoint: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: checkpoint[key] for key in checkpoint if key != "checkpoint_digest"}


def _is_uint64(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= INT64_MAX


def _cache_wire_error(entry: Mapping[str, Any], index: int, bundle: Any) -> Optional[str]:
    """Return the first malformed cache wire path; perform no rule evaluation."""
    root = f"/prior_checkpoint/evaluation_cache/{index}"
    if entry.get("kind") != "M2ILEvaluationCacheEntry":
        return root + "/kind"
    context = entry.get("context")
    context_keys = {"kind", "rule_id", "rule_digest", "rule_bundle_digest", "stratum", "trigger", "existing_support", "required_literals", "default_positive_presence"}
    if not isinstance(context, dict) or set(context) != context_keys:
        return root + "/context"
    if context.get("kind") != "M2ILCacheContext":
        return root + "/context/kind"
    rules = {rule.rule_id: rule for rule in bundle.rules}
    rule = rules.get(context.get("rule_id"))
    if rule is None:
        return root + "/context/rule_id"
    if context.get("rule_digest") != rule.rule_digest:
        return root + "/context/rule_digest"
    if context.get("rule_bundle_digest") != bundle.digest:
        return root + "/context/rule_bundle_digest"
    if context.get("stratum") != rule.stratum:
        return root + "/context/stratum"
    if not isinstance(context.get("existing_support"), bool):
        return root + "/context/existing_support"
    required = context.get("required_literals")
    expected_required = [_m2._literal_key(literal) for literal in rule.required_body]
    if not isinstance(required, list) or len(required) != len(expected_required):
        return root + "/context/required_literals"
    for offset, (item, expected_key) in enumerate(zip(required, expected_required)):
        path = root + f"/context/required_literals/{offset}"
        if not isinstance(item, dict) or set(item) != {"literal_key", "present", "depth"}:
            return path
        if item.get("literal_key") != expected_key:
            return path + "/literal_key"
        if not isinstance(item.get("present"), bool):
            return path + "/present"
        depth = item.get("depth")
        if item["present"]:
            if not _is_uint64(depth):
                return path + "/depth"
        elif depth is not None:
            return path + "/depth"
    trigger = context.get("trigger")
    allowed_triggers = set(expected_required) if expected_required else {"default-only"}
    if not isinstance(trigger, str) or trigger not in allowed_triggers:
        return root + "/context/trigger"
    defaults = context.get("default_positive_presence")
    if not isinstance(defaults, list) or len(defaults) != len(rule.default_not_positive_body):
        return root + "/context/default_positive_presence"
    witnesses = []
    for offset, (item, default) in enumerate(zip(defaults, rule.default_not_positive_body)):
        path = root + f"/context/default_positive_presence/{offset}"
        expected_key = _m2._literal_key(_m2._Literal("positive", default.atom_bytes))
        if not isinstance(item, dict) or set(item) != {"positive_literal_key", "positive_present", "referenced_stratum", "completed_lower_stratum_digest"}:
            return path
        if item.get("positive_literal_key") != expected_key:
            return path + "/positive_literal_key"
        if not isinstance(item.get("positive_present"), bool):
            return path + "/positive_present"
        if item.get("referenced_stratum") != default.referenced_stratum:
            return path + "/referenced_stratum"
        completed_digest = item.get("completed_lower_stratum_digest")
        if not _m2._valid_digest(completed_digest):
            return path + "/completed_lower_stratum_digest"
        witnesses.append(_m2._absence_witness(default.atom_bytes, default.referenced_stratum, completed_digest))
    outcome = entry.get("outcome")
    if not isinstance(outcome, dict):
        return root + "/outcome"
    if set(outcome) != {"status", "depth", "support"}:
        missing = next((field for field in ("status", "depth", "support") if field not in outcome), None)
        return root + "/outcome" + (("/" + missing) if missing else "")
    status = outcome.get("status")
    if status not in {"satisfied", "unsatisfied"}:
        return root + "/outcome/status"
    if status == "unsatisfied":
        if outcome.get("depth") is not None:
            return root + "/outcome/depth"
        if outcome.get("support") is not None:
            return root + "/outcome/support"
        return None
    depth = outcome.get("depth")
    if not _is_uint64(depth) or depth < 1:
        return root + "/outcome/depth"
    if not all(item["present"] for item in required) or any(item["positive_present"] for item in defaults):
        return root + "/outcome/status"
    support = outcome.get("support")
    if not isinstance(support, dict) or set(support) != set(_m2.DERIVED_SUPPORT_KEYS):
        return root + "/outcome/support"
    expected_support = _m2._derived_support_wire(_m2._derived_support_for_rule(rule, witnesses, bundle))
    if support != expected_support:
        return root + "/outcome/support"
    expected_depth = 1 + max((item["depth"] for item in required), default=0)
    if depth != expected_depth:
        return root + "/outcome/depth"
    return None


def _validate_checkpoint(checkpoint: Any, bundle: Mapping[str, Any], logical_time: Any) -> Union[Tuple[dict[str, Any], list[dict[str, Any]]], LPersistentLRejection]:
    digest = bundle.get("rule_bundle_digest") if isinstance(bundle, Mapping) else None
    required = {
        "kind", "schema_version", "contract_version", "profile_id",
        "m2_contract_version", "m2_profile_id", "canonicalization_version",
        "rule_bundle_digest", "through_logical_time", "materialization",
        "materialization_digest", "evaluation_cache", "checkpoint_digest",
    }
    if not isinstance(checkpoint, dict) or set(checkpoint) != required:
        return _persistent_rejection("MALFORMED_CHECKPOINT", "/prior_checkpoint", logical_time, digest)
    version_fields = (
        ("schema_version", CHECKPOINT_SCHEMA_VERSION),
        ("contract_version", CONTRACT_VERSION),
        ("profile_id", CONTRACT_VERSION),
        ("m2_contract_version", _m2.CONTRACT_VERSION),
        ("m2_profile_id", _m2.PROFILE_ID),
        ("canonicalization_version", CANONICALIZATION_VERSION),
    )
    for field, expected in version_fields:
        if checkpoint.get(field) != expected:
            return _persistent_rejection("UNSUPPORTED_PERSISTENT_SCHEMA", f"/prior_checkpoint/{field}", logical_time, digest)
    try:
        observed = canonical_digest({
            "kind": "M2ILCheckpointPreimage",
            "contract_version": CONTRACT_VERSION,
            "checkpoint_without_checkpoint_digest": _checkpoint_without_digest(checkpoint),
        })
    except ValueError:
        return _persistent_rejection("MALFORMED_CHECKPOINT", "/prior_checkpoint", logical_time, digest)
    if observed != checkpoint["checkpoint_digest"]:
        return _persistent_rejection("CHECKPOINT_DIGEST_MISMATCH", "/prior_checkpoint/checkpoint_digest", logical_time, digest)
    materialization = checkpoint["materialization"]
    if not isinstance(materialization, dict) or checkpoint["materialization_digest"] != materialization.get("materialization_digest"):
        return _persistent_rejection("CHECKPOINT_BINDING_MISMATCH", "/prior_checkpoint/materialization_digest", logical_time, digest)
    if checkpoint["rule_bundle_digest"] != digest:
        return _persistent_rejection("CHECKPOINT_BINDING_MISMATCH", "/prior_checkpoint/rule_bundle_digest", logical_time, digest)
    if checkpoint["through_logical_time"] != materialization.get("through_logical_time"):
        return _persistent_rejection("CHECKPOINT_BINDING_MISMATCH", "/prior_checkpoint/through_logical_time", logical_time, digest)
    cache = checkpoint["evaluation_cache"]
    if not isinstance(cache, list):
        return _persistent_rejection("MALFORMED_CHECKPOINT", "/prior_checkpoint/evaluation_cache", logical_time, digest)
    if cache != sorted(cache, key=canonical_bytes):
        return _persistent_rejection("CHECKPOINT_BINDING_MISMATCH", "/prior_checkpoint/evaluation_cache", logical_time, digest)
    parsed_bundle = _m2._parse_bundle(bundle)
    seen_contexts = set()
    for index, entry in enumerate(cache):
        if not isinstance(entry, dict) or set(entry) != {"kind", "context", "context_digest", "outcome", "entry_digest"}:
            return _persistent_rejection("MALFORMED_CHECKPOINT", f"/prior_checkpoint/evaluation_cache/{index}", logical_time, digest)
        if entry["context_digest"] != canonical_digest(entry["context"]):
            return _persistent_rejection("CHECKPOINT_BINDING_MISMATCH", f"/prior_checkpoint/evaluation_cache/{index}/context_digest", logical_time, digest)
        if entry["context_digest"] in seen_contexts:
            return _persistent_rejection("MALFORMED_CHECKPOINT", f"/prior_checkpoint/evaluation_cache/{index}/context_digest", logical_time, digest)
        seen_contexts.add(entry["context_digest"])
        without = {key: entry[key] for key in entry if key != "entry_digest"}
        expected_entry = canonical_digest({"kind": "M2ILCacheEntryPreimage", "contract_version": CONTRACT_VERSION, "entry_without_entry_digest": without})
        if entry["entry_digest"] != expected_entry:
            return _persistent_rejection("CHECKPOINT_BINDING_MISMATCH", f"/prior_checkpoint/evaluation_cache/{index}/entry_digest", logical_time, digest)
        malformed_path = _cache_wire_error(entry, index, parsed_bundle)
        if malformed_path is not None:
            return _persistent_rejection("MALFORMED_CHECKPOINT", malformed_path, logical_time, digest)
    if len(cache) > MAX_CACHE_ENTRIES or len(materialization.get("base_supports", [])) > MAX_ACTIVE_BASE_SUPPORTS or len(canonical_bytes(checkpoint)) > MAX_CHECKPOINT_BYTES:
        return _persistent_rejection("PERSISTENT_BOUNDS_EXCEEDED", "/prior_checkpoint", logical_time, digest)
    return materialization, cache


def _support_from_wire(value: Mapping[str, Any]) -> Any:
    literal = _m2._Literal(value["literal"]["polarity"], _m2.canonical_bytes(value["literal"]["atom"]))
    witnesses = tuple(_m2._AbsenceWitness(item["fact_key"], _m2.canonical_bytes(item["atom"]), item["referenced_stratum"], item["completed_stratum_digest"], item["witness_digest"]) for item in value["default_absence_witnesses"])
    return _m2._DerivedSupport(value["derivation_id"], value["support_content_digest"], literal, value["rule_id"], value["rule_digest"], tuple(value["premise_literal_keys"]), witnesses, value["rule_set_version"], value["dataflow_version"])


def _evaluation_context(rule: Any, bundle: Any, present: Mapping[str, Any], depths: Mapping[str, int], completed_presence: Mapping[int, frozenset], completed_digests: Mapping[int, str], trigger: str, existing: bool) -> dict[str, Any]:
    required = []
    for literal in rule.required_body:
        key = _m2._literal_key(literal)
        required.append({"literal_key": key, "present": key in present, "depth": depths.get(key)})
    defaults = []
    for default in rule.default_not_positive_body:
        key = _m2._literal_key(_m2._Literal("positive", default.atom_bytes))
        defaults.append({"positive_literal_key": key, "positive_present": key in completed_presence.get(default.referenced_stratum, frozenset()), "referenced_stratum": default.referenced_stratum, "completed_lower_stratum_digest": completed_digests.get(default.referenced_stratum)})
    return {"kind": "M2ILCacheContext", "rule_id": rule.rule_id, "rule_digest": rule.rule_digest, "rule_bundle_digest": bundle.digest, "stratum": rule.stratum, "trigger": trigger, "existing_support": existing, "required_literals": required, "default_positive_presence": defaults}


def _evaluate_rule_body(rule: Any, bundle: Any, present: Mapping[str, Any], depths: Mapping[str, int], completed_presence: Mapping[int, frozenset], completed_digests: Mapping[int, str]) -> dict[str, Any]:
    premise_keys = [_m2._literal_key(item) for item in rule.required_body]
    if any(key not in present for key in premise_keys):
        return {"status": "unsatisfied", "depth": None, "support": None}
    witnesses = []
    for default in rule.default_not_positive_body:
        positive_key = _m2._literal_key(_m2._Literal("positive", default.atom_bytes))
        if positive_key in completed_presence[default.referenced_stratum]:
            return {"status": "unsatisfied", "depth": None, "support": None}
        witnesses.append(_m2._absence_witness(default.atom_bytes, default.referenced_stratum, completed_digests[default.referenced_stratum]))
    depth = 1 + max((depths[key] for key in premise_keys), default=0)
    support = _construct_derived_support(rule, witnesses, bundle)
    return {"status": "satisfied", "depth": depth, "support": _m2._derived_support_wire(support)}


def _construct_derived_support(rule: Any, witnesses: Sequence[Any], bundle: Any) -> Any:
    """Candidate-owned provenance evaluator, bypassed on exact cache hits."""
    return _m2._derived_support_for_rule(rule, witnesses, bundle)


def _derive_incremental(bundle: Any, base_supports: Sequence[Any], prior_cache: Sequence[Mapping[str, Any]]) -> Tuple[Any, List[dict[str, Any]], dict[str, Any]]:
    ordered_base = tuple(sorted(base_supports, key=lambda item: _m2.canonical_bytes(_m2._base_support_wire(item))))
    base_ids = {item.derivation_id for item in ordered_base}
    present: Dict[str, Any] = {}; depths: Dict[str, int] = {}
    for support in ordered_base:
        key = _m2._literal_key(support.literal); present[key] = support.literal; depths[key] = 0
    strata_values = {rule.stratum for rule in bundle.rules}
    for rule in bundle.rules: strata_values.update(item.referenced_stratum for item in rule.default_not_positive_body)
    rules_by_stratum: Dict[int, List[Any]] = {}
    for rule in bundle.rules: rules_by_stratum.setdefault(rule.stratum, []).append(rule)
    for rules in rules_by_stratum.values(): rules.sort(key=lambda item: _m2.canonical_bytes(_m2._rule_wire(item)))
    prior_by_context = {item["context_digest"]: item for item in prior_cache}
    next_cache: List[dict[str, Any]] = []; reused_digests: List[str] = []
    derived_by_rule: Dict[str, Any] = {}; derived_depths: Dict[str, int] = {}
    completed_digests: Dict[int, str] = {}; completed_presence: Dict[int, frozenset] = {}; stratum_wires = []
    evaluations = firings = pops = hits = misses = executed = 0
    for stratum in sorted(strata_values):
        current_rules = rules_by_stratum.get(stratum, []); required_index: Dict[str, List[Any]] = {}; default_only = []
        for rule in current_rules:
            if rule.required_body:
                for literal in rule.required_body: required_index.setdefault(_m2._literal_key(literal), []).append(rule)
            else: default_only.append(rule)
        for rules in required_index.values(): rules.sort(key=lambda item: _m2.canonical_bytes(_m2._rule_wire(item)))
        queue = _m2._sort_strings(list(present)); queued = set(queue)
        def enqueue(key: str) -> None:
            if key not in queued: queue.append(key); queue.sort(key=_m2.canonical_bytes); queued.add(key)
        def evaluate(rule: Any, trigger: str) -> None:
            nonlocal evaluations, firings, hits, misses, executed
            evaluations += 1
            context = _evaluation_context(rule, bundle, present, depths, completed_presence, completed_digests, trigger, rule.rule_id in derived_by_rule)
            context_digest = canonical_digest(context); cached = prior_by_context.get(context_digest)
            if cached is not None:
                outcome = cached["outcome"]; hits += 1; reused_digests.append(cached["entry_digest"])
            else:
                outcome = _evaluate_rule_body(rule, bundle, present, depths, completed_presence, completed_digests); misses += 1; executed += 1
            entry_without = {"kind": "M2ILEvaluationCacheEntry", "context": context, "context_digest": context_digest, "outcome": outcome}
            entry = dict(entry_without); entry["entry_digest"] = canonical_digest({"kind": "M2ILCacheEntryPreimage", "contract_version": CONTRACT_VERSION, "entry_without_entry_digest": entry_without}); next_cache.append(entry)
            if outcome["status"] == "unsatisfied": return
            support = _support_from_wire(outcome["support"]); depth = outcome["depth"]
            existing = derived_by_rule.get(rule.rule_id)
            if existing is None:
                if support.derivation_id in base_ids: raise _m2._KernelReject("DERIVED_SUPPORT_TARGET", "/fact_delta_inputs", {"derivation_id": support.derivation_id})
                derived_by_rule[rule.rule_id] = support; derived_depths[rule.rule_id] = depth; firings += 1
                if firings > bundle.max_rule_firings: raise _m2._KernelReject("RULE_BUDGET_EXHAUSTED", "/rule_bundle/limits/max_rule_firings", {"limit": bundle.max_rule_firings, "observed": firings})
                head_key = _m2._literal_key(rule.head); old = depths.get(head_key); present[head_key] = rule.head
                if old is None or depth < old: depths[head_key] = depth; enqueue(head_key)
            elif depth < derived_depths[rule.rule_id]:
                derived_depths[rule.rule_id] = depth; head_key = _m2._literal_key(rule.head); old = depths.get(head_key)
                if old is None or depth < old: depths[head_key] = depth; enqueue(head_key)
        for rule in default_only: evaluate(rule, "default-only")
        while queue:
            key = queue.pop(0); queued.remove(key); pops += 1
            for rule in required_index.get(key, []): evaluate(rule, key)
        current = tuple(sorted(derived_by_rule.values(), key=lambda item: _m2.canonical_bytes(_m2._derived_support_wire(item))))
        digest = _m2._completed_stratum_digest(stratum, bundle, ordered_base, current); completed_digests[stratum] = digest; completed_presence[stratum] = frozenset(present); stratum_wires.append({"kind": "LStratumDigest", "stratum": stratum, "digest": digest})
    derived = tuple(sorted(derived_by_rule.values(), key=lambda item: _m2.canonical_bytes(_m2._derived_support_wire(item))))
    maximum_depth = max(derived_depths.values(), default=0)
    if maximum_depth > bundle.max_derivation_depth: raise _m2._KernelReject("DERIVATION_DEPTH_EXCEEDED", "/rule_bundle/limits/max_derivation_depth", {"limit": bundle.max_derivation_depth, "observed": maximum_depth})
    states, conflicts = _m2._project_facts(bundle, ordered_base, derived)
    result = _m2._Derivation(derived, states, conflicts, tuple(_m2._sort_wires(stratum_wires)), evaluations, firings, pops, maximum_depth)
    next_cache.sort(key=canonical_bytes)
    counts = {"candidate_cache_lookups": evaluations, "candidate_cache_hits": hits, "candidate_cache_misses": misses, "reused_candidate_body_evaluations": hits, "executed_candidate_body_evaluations": executed, "accounted_candidate_body_evaluations": hits + executed, "reused_entry_digests": sorted(reused_digests, key=canonical_bytes)}
    return result, next_cache, counts


def _restore_validated_prior(value: Any, bundle: Any) -> Any:
    """Restore a public-preflight-validated checkpoint without re-derivation."""
    if value is None: return None
    base = tuple(sorted((_m2._parse_base_support(raw, index, bundle) for index, raw in enumerate(sorted(value["base_supports"], key=_m2.diagnostic_order_key))), key=lambda item: _m2.canonical_bytes(_m2._base_support_wire(item))))
    derived = tuple(sorted((_support_from_wire(raw) for raw in value["derived_supports"]), key=lambda item: _m2.canonical_bytes(_m2._derived_support_wire(item))))
    return _m2._Prior(value["through_logical_time"], value["materialization_digest"], base, derived)


def _candidate_fixpoint(prior: Any, rule_bundle: Any, fact_delta_inputs: Any, logical_time: Any, prior_cache: Sequence[Mapping[str, Any]]) -> Tuple[dict[str, Any], List[dict[str, Any]], dict[str, Any]]:
    """Construct the accepted M2 result without consulting public ``solve_l``."""
    bundle = _m2._parse_bundle(rule_bundle)
    if not isinstance(fact_delta_inputs, list) or len(fact_delta_inputs) > _m2.MAX_FACT_DELTA_INPUTS:
        raise ValueError("M2 input boundary")
    parsed_prior = _restore_validated_prior(prior, bundle)
    normalized = sorted(fact_delta_inputs, key=_m2.canonical_bytes)
    parsed_inputs = tuple(_m2._parse_fact_delta_input(raw, index, logical_time, bundle) for index, raw in enumerate(normalized))
    next_base, input_digests, _ = _m2._apply_inputs(parsed_inputs, parsed_prior)
    derivation, next_cache, counts = _derive_incremental(bundle, next_base, prior_cache)
    materialization = _m2._materialization_wire(bundle, logical_time, next_base, derivation)
    prior_digest = parsed_prior.materialization_digest if parsed_prior else None
    causation_id = _m2._invocation_causation_id(logical_time, bundle.digest, prior_digest, input_digests)
    derived = _m2._derived_delta_projection(parsed_prior.derived if parsed_prior else (), derivation.derived, logical_time, causation_id)
    without = {
        "kind": "LFixpointResult", "schema_version": _m2.RESULT_SCHEMA_VERSION,
        "contract_version": _m2.CONTRACT_VERSION, "logical_time": logical_time,
        "rule_bundle_digest": bundle.digest, "prior_materialization_digest": prior_digest,
        "input_delta_digests": list(input_digests), "next_materialization": materialization,
        "derived_fact_deltas": list(derived),
        "stats": {"evaluation_mode": "full_recompute", "rule_evaluation_count": derivation.rule_evaluation_count, "rule_firing_count": derivation.rule_firing_count, "worklist_pop_count": derivation.worklist_pop_count, "max_derivation_depth": derivation.max_derivation_depth},
    }
    result = dict(without)
    result["fixpoint_digest"] = _m2.canonical_digest({"kind": "M2FixpointPreimage", "contract_version": _m2.CONTRACT_VERSION, "fixpoint_result_without_fixpoint_digest": without})
    return closed_copy(result), next_cache, counts


def step_incremental_l(prior_checkpoint: Any, rule_bundle: Any, fact_delta_inputs: Any, logical_time: Any) -> Union[LPersistentLStep, LPersistentLRejection, Dict[str, Any]]:
    """Advance one explicit pure checkpoint, or return a closed rejection."""
    prior_materialization = prior_checkpoint.get("materialization") if isinstance(prior_checkpoint, dict) else None
    inherited = solve_l(prior_materialization, rule_bundle, fact_delta_inputs, logical_time)
    if inherited.get("kind") == "LRejection": return inherited
    prior_cache: Sequence[Mapping[str, Any]] = ()
    if prior_checkpoint is not None:
        validated = _validate_checkpoint(prior_checkpoint, rule_bundle, logical_time)
        if isinstance(validated, dict):
            return validated
        prior_materialization, prior_cache = validated
    candidate, cache, counts = _candidate_fixpoint(prior_materialization, rule_bundle, fact_delta_inputs, logical_time, prior_cache)
    oracle = solve_l(prior_materialization, rule_bundle, fact_delta_inputs, logical_time)
    if canonical_bytes(candidate) != canonical_bytes(oracle):
        return _persistent_rejection("EQUIVALENCE_VIOLATION", "/fixpoint_result", logical_time, oracle.get("rule_bundle_digest"))
    materialization = candidate["next_materialization"]
    if len(materialization["base_supports"]) > MAX_ACTIVE_BASE_SUPPORTS:
        return _persistent_rejection("PERSISTENT_BOUNDS_EXCEEDED", "/next_checkpoint/materialization/base_supports", logical_time, candidate["rule_bundle_digest"])
    if len(cache) > MAX_CACHE_ENTRIES or counts["executed_candidate_body_evaluations"] > MAX_BODY_EVALUATIONS:
        return _persistent_rejection("PERSISTENT_BOUNDS_EXCEEDED", "/next_checkpoint/evaluation_cache", logical_time, candidate["rule_bundle_digest"])
    checkpoint_without = {"kind": "LPersistentLCheckpoint", "schema_version": CHECKPOINT_SCHEMA_VERSION, "contract_version": CONTRACT_VERSION, "profile_id": CONTRACT_VERSION, "m2_contract_version": _m2.CONTRACT_VERSION, "m2_profile_id": _m2.PROFILE_ID, "canonicalization_version": CANONICALIZATION_VERSION, "rule_bundle_digest": candidate["rule_bundle_digest"], "through_logical_time": logical_time, "materialization": materialization, "materialization_digest": materialization["materialization_digest"], "evaluation_cache": cache}
    checkpoint = dict(checkpoint_without)
    checkpoint["checkpoint_digest"] = canonical_digest({"kind": "M2ILCheckpointPreimage", "contract_version": CONTRACT_VERSION, "checkpoint_without_checkpoint_digest": checkpoint_without})
    if len(canonical_bytes(checkpoint)) > MAX_CHECKPOINT_BYTES:
        return _persistent_rejection("PERSISTENT_BOUNDS_EXCEEDED", "/next_checkpoint", logical_time, candidate["rule_bundle_digest"])
    prior_digest = prior_checkpoint.get("checkpoint_digest") if isinstance(prior_checkpoint, dict) else None
    receipt_without = {"kind": "M2ILReuseReceipt", "prior_checkpoint_digest": prior_digest, "next_checkpoint_digest": checkpoint["checkpoint_digest"], "oracle_fixpoint_digest": oracle["fixpoint_digest"], "candidate_fixpoint_digest": candidate["fixpoint_digest"], "public_m2_solve_calls": 2, **counts}
    receipt = dict(receipt_without); receipt["receipt_digest"] = canonical_digest({"kind": "M2ILReuseReceiptPreimage", "contract_version": CONTRACT_VERSION, "receipt_without_receipt_digest": receipt_without})
    step_without = {"kind": "LPersistentLStep", "schema_version": RESULT_SCHEMA_VERSION, "contract_version": CONTRACT_VERSION, "fixpoint_result": candidate, "next_checkpoint": checkpoint, "reuse_receipt": receipt}
    step = dict(step_without); step["step_digest"] = canonical_digest({"kind": "M2ILStepPreimage", "contract_version": CONTRACT_VERSION, "step_without_step_digest": step_without})
    return closed_copy(step)
