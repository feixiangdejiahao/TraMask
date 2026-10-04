import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_contract_scalar_observer_search as driver
from scripts import run_contract_gap_generation_search as harness
from scripts.run_contract_repair_search import frozen, write
from relation_search import contract_scalar_observer as core
from tests.test_contract_scalar_observer import fixture, CODE, ISSUE


def test_private_harness_does_not_change_sealed_modules_or_provider():
    before=dict(vars(harness));engine=driver._engine()
    assert engine['relation'] is core
    assert engine['VERSION']==driver.VERSION
    assert engine['generate'].__globals__ is engine
    assert engine['_expand'].__globals__ is engine
    assert engine['review_all'].__globals__ is engine
    assert engine['one_run'].__globals__ is engine
    assert vars(harness)==before
    assert engine['relation'] is not harness.relation


def test_host_selection_can_reach_later_original_test_without_retrieval_reordering():
    nohost="it('nothing', () => { expect(true).toBe(true); });\n"
    code=CODE[:CODE.index("it('cross")]+''.join(nohost.replace('nothing',f'old{i}') for i in range(6))+CODE[CODE.index("it('cross"):]
    _,corpus,frontend=fixture(code)
    for rank,test in enumerate(corpus['tests'].values(),1):test['retrieval_rank']=rank
    identifiers=core.seed_ids(corpus,frontend)
    assert len(identifiers)==1
    assert 'cross object' in identifiers[0]
    assert corpus['tests'][identifiers[0]]['retrieval_rank']==7


def test_source_only_prepare_retains_all_trials_and_never_dispatches(tmp_path):
    cohort=tmp_path/'cohort';cohort.mkdir();rows=[]
    for i in range(17):
        target=tmp_path/f'source{i:02}';target.mkdir()
        _,corpus,frontend=fixture(CODE if i==0 else CODE.replace('owner.queue.commit();','owner.queue.commit(1);'))
        for name,value in [('corpus.json',corpus),('frontend.json',frontend),('case.json',{}),('selection.json',{})]:write(target/name,value)
        (target/'issue.md').write_text(ISSUE)
        rows.append(dict(case=f'T{i:02}',source=str(target)))
    write(cohort/'prepared.json',dict(cases=rows));write(cohort/'seal.json',frozen(cohort/'prepared.json'))
    engine=driver._engine();real=engine['admission']
    engine['admission']=SimpleNamespace(_deadline=real._deadline,
        _preload_local_imports=lambda module:None,_loaded_sources=lambda:{},
        _enrich=lambda c,f,ids,p,out,index:(c,None))
    engine['_verify_algorithm']=lambda protocol:None
    engine['dispatch']=lambda *a,**k:pytest.fail('source prepare dispatched provider')
    engine['one_run']=lambda *a,**k:pytest.fail('source prepare executed native')
    out=tmp_path/'out'
    result=engine['prepare'](SimpleNamespace(source_cohort=cohort,output=out,deadline_utc='2030-01-01T00:00:00+00:00'))
    assert result['trials']==17 and result['requests']==1
    assert result['provider_calls']==result['native_executions']==0
    protocol=json.loads((out/'prepared.json').read_text())
    assert len(protocol['cases'])==17 and protocol['max_candidates_per_trial']==3
    assert protocol['policy']==core.POLICY
    assert all(row['candidates']==[] for row in protocol['cases'])
    engine['_verify_protocol'](protocol,'generation')
    assert json.loads((out/'seal.json').read_text())==frozen(out/'prepared.json')
    request=json.loads(Path(protocol['cases'][0]['generation_request']['path']).read_text())
    assert json.loads(request['prompt'])['hosts']
    assert request['no_execution_outcomes']
