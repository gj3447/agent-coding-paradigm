#!/usr/bin/env python3
"""Nonrecursive validator for the proposed M2-IL candidate closure."""

from __future__ import annotations
import hashlib, json, subprocess, sys
from pathlib import Path
from jsonschema import Draft202012Validator
ROOT=Path(__file__).resolve().parents[1]
def load(p): return json.loads((ROOT/p).read_text(encoding='utf-8'))
manifest=load('spec/m2il-manifest.v1.json')
assert len(manifest['owned_closure'])==22 and len(set(manifest['owned_closure']))==22
assert len(manifest['inherited_sha256_pins'])==19
for path in manifest['owned_closure']: assert (ROOT/path).is_file(), path
for pin in manifest['inherited_sha256_pins']:
    observed='sha256:'+hashlib.sha256((ROOT/pin['artifact']).read_bytes()).hexdigest(); assert observed==pin['sha256'], pin['artifact']
owned=set(manifest['owned_closure'])
def classify_closure(entries, head_paths):
    entries=list(entries); paths={path for _,path in entries}; statuses={status for status,_ in entries}
    if not entries and owned <= set(head_paths): return 'committed-clean'
    if len(entries)==22 and paths==owned and (statuses=={'??'} or statuses=={'A '}): return 'precommit-added-only'
    raise AssertionError({'git_entries':sorted(entries),'head_owned':sorted(owned & set(head_paths))})
assert classify_closure([('??',path) for path in owned],set())=='precommit-added-only'
assert classify_closure([],owned)=='committed-clean'
try: classify_closure([(' M',next(iter(owned)))],owned)
except AssertionError: pass
else: raise AssertionError('mixed git state accepted')
raw=subprocess.check_output(['git','status','--porcelain=v1','-z','--untracked-files=all'],cwd=ROOT).decode().split('\0')
entries=[(item[:2],item[3:]) for item in raw if item]
head_paths=set(filter(None,subprocess.check_output(['git','ls-tree','-r','--name-only','-z','HEAD'],cwd=ROOT).decode().split('\0')))
closure_mode=classify_closure(entries,head_paths)
schemas=('spec/schema/m2il-incremental.v1.schema.json','spec/schema/m2il-contract.v1.schema.json','spec/schema/m2il-fixtures.v1.schema.json','spec/schema/m2il-manifest.v1.schema.json')
for schema in schemas: Draft202012Validator.check_schema(load(schema))
bindings=[('spec/m2il-incremental-contract.v1.json','spec/schema/m2il-contract.v1.schema.json'),('spec/m2il-manifest.v1.json','spec/schema/m2il-manifest.v1.schema.json'),('fixtures/m2il/cases.json','spec/schema/m2il-fixtures.v1.schema.json')]
for instance,schema in bindings: Draft202012Validator(load(schema)).validate(load(instance))
wire_schema=load('spec/schema/m2il-incremental.v1.schema.json'); wire_validator=Draft202012Validator(wire_schema)
assert not wire_validator.is_valid({'kind':'LPersistentLStep','evil':None})
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from flrh_logic_incremental import step_incremental_l
from flrh_logic_incremental.canonical import canonical_bytes
from m2il_fixtures import materialize_step
checkpoint=None
for sequence in load('fixtures/m2il/cases.json')['sequences']:
    checkpoint=None
    for index in range(len(sequence['steps'])):
        bundle,deltas=materialize_step(load('fixtures/m2il/cases.json'),sequence['id'],index,index+1)
        emitted=step_incremental_l(checkpoint,bundle,deltas,index+1)
        wire_validator.validate(emitted)
        canonical_bytes(emitted)
        if emitted['kind']=='LPersistentLStep':
            wire_validator.evolve(schema=wire_schema['$defs']['Checkpoint']).validate(emitted['next_checkpoint'])
            wire_validator.evolve(schema=wire_schema['$defs']['Receipt']).validate(emitted['reuse_receipt'])
            checkpoint=emitted['next_checkpoint']
        else: checkpoint=None
bundle,deltas=materialize_step(load('fixtures/m2il/cases.json'),'disjoint-chain-bootstrap-noop-unrelated-retract',0,1)
accepted=step_incremental_l(None,bundle,deltas,1)
forged=json.loads(json.dumps(accepted['next_checkpoint'])); forged['m2_contract_version']='wrong/1'
without={key:forged[key] for key in forged if key!='checkpoint_digest'}
from flrh_logic_incremental.canonical import canonical_digest
forged['checkpoint_digest']=canonical_digest({'kind':'M2ILCheckpointPreimage','contract_version':'flrh-l-persistent-incremental/1','checkpoint_without_checkpoint_digest':without})
wire_validator.validate(step_incremental_l(forged,bundle,[],2))
from m2_fixtures import load_cases as load_m2_cases, materialize_case
m2_cases=load_m2_cases(); rejection_case=next(item for item in m2_cases['rejection_cases'] if item['id']=='identity-conflict-atomic')
rejection_bundle,rejection_deltas=materialize_case(m2_cases,rejection_case)
inherited_rejection=step_incremental_l(None,rejection_bundle,rejection_deltas,1)
assert inherited_rejection['kind']=='LRejection' and 'rejection_digest' not in inherited_rejection
wire_validator.validate(inherited_rejection); canonical_bytes(inherited_rejection)
for golden in ('fixtures/m2il/golden/insertion-reuse.fixpoint.json','fixtures/m2il/golden/retraction-reuse.fixpoint.json'):
    value=load(golden); assert json.loads(canonical_bytes(value))==value
corpus=load('fixtures/m2il/cases.json'); inherited=load('fixtures/m2/cases.json')
known={item['id'] for key in ('success_cases','rejection_cases','sequences','equivalence_pairs') for item in inherited.get(key,[])}
assert set(corpus['inherited_cases']) <= known
commands=[[sys.executable,'-m','unittest','tests.test_m2il_incremental'],[sys.executable,'scripts/check_m2il_ambient.py'],[sys.executable,'scripts/check_m2il_semantic_mutants.py'],[sys.executable,'scripts/run_m2il_replay.py']]
for command in commands: subprocess.run(command,cwd=ROOT,check=True)
if '--inherited' in sys.argv:
    for script in ('validate_m0.py','validate_m1.py','validate_m2.py','validate_m3.py'):
        subprocess.run([sys.executable,'scripts/'+script],cwd=ROOT,check=True)
    def lr_action(mode): return 'defer' if mode=='precommit-added-only' else 'require-pass'
    assert lr_action('precommit-added-only')=='defer' and lr_action('committed-clean')=='require-pass'
    if lr_action(closure_mode)=='defer':
        print('M2IL inherited LR gate: DEFERRED_UNTIL_COMMITTED_CLEAN (exact 22 added-only closure)')
    else:
        subprocess.run([sys.executable,'scripts/validate_lr_seam.py'],cwd=ROOT,check=True)
        print('M2IL inherited LR gate: PASS')
print('M2IL PROPOSED_PENDING_MEASUREMENT validator PASS (nonrecursive; inherited gates independently runnable)')
