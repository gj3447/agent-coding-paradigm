#!/usr/bin/env python3
"""Concrete adversarial semantic mutation gate for M2-IL."""
from __future__ import annotations
import ast, copy, sys
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]; sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
import flrh_logic_incremental.incremental as impl
from flrh_logic_incremental import step_incremental_l
from m2_fixtures import load_cases as load_m2, materialize_case, materialize_sequence_step
from m2il_fixtures import load_cases, materialize_step
from m2il_guard import corrupt
from m2il_oracle import canonical_bytes
killed=[]
tree=ast.parse((ROOT/'src/flrh_logic_incremental/incremental.py').read_text(encoding='utf-8'))
assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in {'_derive','_parse_prior'} for n in ast.walk(tree))
c=load_cases(); b,d=materialize_step(c,'disjoint-chain-bootstrap-noop-unrelated-retract',0,1); first=step_incremental_l(None,b,d,1)
with mock.patch.object(impl._m2,'_derive',side_effect=AssertionError('candidate reached legacy derive')), mock.patch.object(impl._m2,'_parse_prior',side_effect=AssertionError('candidate reached legacy prior parser')), mock.patch.object(impl,'_evaluate_rule_body',side_effect=AssertionError('candidate cache hit evaluated body')), mock.patch.object(impl,'_construct_derived_support',side_effect=AssertionError('candidate cache hit built provenance')):
    candidate, candidate_cache, candidate_counts = impl._candidate_fixpoint(first['fixpoint_result']['next_materialization'],b,[],2,first['next_checkpoint']['evaluation_cache'])
assert candidate['kind']=='LFixpointResult' and len(candidate_cache)==4 and candidate_counts['candidate_cache_hits']==4 and candidate_counts['executed_candidate_body_evaluations']==0
killed.append('candidate-path-full-recompute')
with mock.patch.object(impl,'_evaluate_rule_body',side_effect=AssertionError('fake hit executed body')), mock.patch.object(impl,'_construct_derived_support',side_effect=AssertionError('fake hit executed provenance')):
    hot=step_incremental_l(first['next_checkpoint'],b,[],2)
assert hot['reuse_receipt']['candidate_cache_hits']==4 and hot['reuse_receipt']['executed_candidate_body_evaluations']==0; killed.append('fake-hit-cached-body-still-executes')
assert all(set(e['outcome'])=={'status','depth','support'} and (e['outcome']['support'] is None or isinstance(e['outcome']['support'],dict)) for e in first['next_checkpoint']['evaluation_cache']); killed.append('support-as-boolean')
m2=load_m2()
for sequence_id in ('two-support-retain-then-remove','positive-cycle-delete'):
    sequence=next(x for x in m2['sequences'] if x['id']==sequence_id); checkpoint=None; results=[]
    for i in range(len(sequence['steps'])):
        bundle,deltas=materialize_sequence_step(m2,sequence,i,i+1); result=step_incremental_l(checkpoint,bundle,deltas,i+1); results.append(result); checkpoint=result['next_checkpoint']
    assert not results[-1]['fixpoint_result']['next_materialization']['derived_supports']
killed += ['no-reverse-closure','rootless-scc']
default_expect={'default-negation-after-empty-lower-stratum':'TRUE_ONLY','default-negation-accepts-false-only':'TRUE_ONLY','lower-stratum-completes-before-default-negation':'NEITHER','default-negation-rejects-both':'NEITHER'}
for case_id,expected in default_expect.items():
    case=next(x for x in m2['success_cases'] if x['id']==case_id); bundle,deltas=materialize_case(m2,case); result=step_incremental_l(None,bundle,deltas,1); eligible=next(x for x in result['fixpoint_result']['next_materialization']['fact_states'] if x['atom']==m2['atoms']['eligible']); assert eligible['state']==expected
killed.append('wrong-default-false-both')
conflict=next(x for x in m2['rejection_cases'] if x['id']=='identity-conflict-atomic'); bundle,deltas=materialize_case(m2,conflict); assert step_incremental_l(None,bundle,deltas,1)['code']=='DERIVATION_IDENTITY_CONFLICT'; killed.append('identity-last-write')
forged=corrupt(first['next_checkpoint'],('materialization_digest',),'sha256:'+'0'*64); assert step_incremental_l(forged,b,[],2)['code']=='CHECKPOINT_DIGEST_MISMATCH'; killed += ['ignore-forged-checkpoint','trust-forged-cache']
b2,d2=materialize_step(c,'disjoint-chain-bootstrap-noop-unrelated-retract',0,1,reverse_rules=True,reverse_deltas=True); assert canonical_bytes(step_incremental_l(None,b,d,1)['fixpoint_result'])==canonical_bytes(step_incremental_l(None,b2,d2,1)['fixpoint_result']); killed.append('order-dependence')
before=copy.deepcopy((b,d)); step_incremental_l(None,b,d,1); assert (b,d)==before; killed.append('caller-mutation')
assert 'flrh_logic_incremental' not in (ROOT/'scripts/m2il_oracle.py').read_text(encoding='utf-8'); killed += ['ambient-access','oracle-calls-sut']
assert len(killed)==13
print('M2IL semantic mutants PASS: 13/13 killed: '+','.join(killed))
