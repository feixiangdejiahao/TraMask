import copy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from scripts import run_sealed_summary_chain as chain


def put(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    return chain.frozen(path)


@pytest.fixture
def context(tmp_path,monkeypatch):
    subprocess.run(['git','init','-q',str(tmp_path)],check=True)
    (tmp_path/'file').write_text('fixture')
    subprocess.run(['git','-C',str(tmp_path),'add','file'],check=True)
    subprocess.run(['git','-C',str(tmp_path),'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','fixture'],check=True)
    commit=subprocess.check_output(['git','-C',str(tmp_path),'rev-parse','HEAD']).decode().strip()
    monkeypatch.setattr(chain,'ROOT',tmp_path)
    inputs={case:{role:put(tmp_path/'sources'/case/role,dict(case=case,role=role)) for role in chain.INPUTS} for case in ['a','b']}
    return tmp_path,commit,inputs


def make_component(context,name='first',*,layout='object',alert_case='a',token='original'):
    root,commit,inputs=context;directory=root/name
    prepared=dict(version='fixture.v1',cases=['a','b'],
        source_inventory={case:dict(inputs=values) for case,values in inputs.items()},
        # Deliberately unavailable: the thin layer must not inspect audits or
        # pretend to validate an executed algorithm/provider/native closure.
        algorithm={'path':str(root/'never-executed.py'),'sha256':'0'*64},
        independent_audit={'path':str(root/'never-open-audit.json'),'sha256':'0'*64})
    case_selector=dict(pointer='/cases',kind='array',case_pointer='')
    source_selector=dict(pointer='/source_inventory',kind='object',case_pointer=None,
        inputs={role:'/inputs/'+role for role in chain.INPUTS})
    if layout=='array':
        prepared['cases']=[dict(case=case,inputs=values) for case,values in inputs.items()]
        case_selector['case_pointer']='/case'
        source_selector=dict(pointer='/cases',kind='array',case_pointer='/case',inputs=source_selector['inputs'])
    elif layout=='attempts':
        prepared['cases']=[dict(case=case,ranking=[]) for case in inputs]
        case_selector['case_pointer']='/case'
        prepared['attempts']=[dict(selection=dict(case=case),source_inputs=dict(corpus=values['corpus.json'],frontend=values['frontend.json']),issue=values['issue.md']) for case,values in inputs.items() for _ in range(2)]
        source_selector=dict(pointer='/attempts',kind='array',case_pointer='/selection/case',
            inputs={'corpus.json':'/source_inputs/corpus','frontend.json':'/source_inputs/frontend','issue.md':'/issue','case.json':None,'selection.json':None})
    p=put(directory/'prepared.json',prepared)
    summary=dict(version='fixture.v1',stage='complete',prepared=p,trial_denominator=2,
        results=[dict(case=case,alert=dict(token=token,complete={'inputs':[1,2],'expected':False}) if case==alert_case else None) for case in inputs])
    summary['alerts']=[r for r in summary['results'] if r['alert']]
    summary['detector_alerts']=len(summary['alerts'])
    s=put(directory/'summary.json',summary)
    ps=put(directory/'seal.json',dict(prepared=p));ss=put(directory/'summary_seal.json',s)
    return dict(name=name,commit=commit,prepared_version='fixture.v1',summary_version='fixture.v1',prepared=p,summary=s,
        prepared_seal=dict(receipt=ps,pointer='/prepared'),summary_seal=dict(receipt=ss,pointer=''),
        prepared_cases=case_selector,source_rows=source_selector,
        summary_rows=dict(pointer='/results',kind='array',case_pointer='/case',alert_pointer='/alert'),
        summary_denominator_pointer='/trial_denominator',declared_alert_count_pointer='/detector_alerts',
        alert_rows_pointer='/alerts',summary_prepared_pointer='/prepared')


def reseal(spec,prepared=None,summary=None):
    if prepared is not None:
        spec['prepared']=put(spec['prepared']['path'],prepared)
        ps=Path(spec['prepared_seal']['receipt']['path'])
        spec['prepared_seal']['receipt']=put(ps,dict(prepared=spec['prepared']))
    if summary is None:summary=chain.read(spec['summary']['path'])
    summary['prepared']=spec['prepared']
    spec['summary']=put(spec['summary']['path'],summary)
    spec['summary_seal']['receipt']=put(spec['summary_seal']['receipt']['path'],spec['summary'])


@pytest.mark.parametrize('layout',['object','array','attempts'])
def test_all_supported_source_projection_forms_are_complete(context,layout):
    spec=make_component(context,layout=layout)
    loaded,sources,report=chain.load_components([spec],2)
    assert sorted(sources)==['a','b']
    assert report['verified_data_files']>=10
    assert loaded['first']['report']['source_row_count']==(4 if layout=='attempts' else 2)
    assert not loaded['first']['report']['provider_native_receipts_revalidated']


def test_first_complete_alert_is_copied_and_shadowed_outputs_remain(context):
    first=make_component(context,'first',token='keep')
    second=make_component(context,'second',layout='attempts',token='shadowed')
    loaded,sources,_=chain.load_components([first,second],2)
    decisions=chain.compose(sorted(sources),loaded)
    assert decisions[0]['alert']==chain.read(first['summary']['path'])['results'][0]['alert']
    assert decisions[0]['canonical_complete_alert_sha256']==chain.canonical(decisions[0]['alert'])
    assert loaded['second']['rows'][0]['alert']['token']=='shadowed'
    assert decisions[1]['alert'] is None


@pytest.mark.parametrize('mutation,match',[
    ('summary_missing','cohort differs'),('summary_duplicate','Duplicate complete'),
    ('prepared_duplicate','Duplicate complete'),('source_missing','omits original'),
    ('source_extra','outside original'),('stage','not complete'),
    ('count','alert count'),('null_count','alert count'),('denominator','denominator'),
    ('alert_list','alert rows'),('empty_alert','complete nonempty'),
])
def test_resealed_but_inconsistent_components_are_rejected(context,mutation,match):
    spec=make_component(context);p=chain.read(spec['prepared']['path']);s=chain.read(spec['summary']['path'])
    if mutation=='summary_missing':s['results'].pop()
    elif mutation=='summary_duplicate':s['results'].append(s['results'][0])
    elif mutation=='prepared_duplicate':p['cases'].append('a')
    elif mutation=='source_missing':del p['source_inventory']['b']
    elif mutation=='source_extra':p['source_inventory']['c']=p['source_inventory']['b']
    elif mutation=='stage':s['stage']='running'
    elif mutation=='count':s['detector_alerts']=0
    elif mutation=='null_count':s['detector_alerts']=None
    elif mutation=='denominator':s['trial_denominator']=1
    elif mutation=='alert_list':s['alerts']=[]
    elif mutation=='empty_alert':s['results'][0]['alert']={}
    reseal(spec,p,s)
    with pytest.raises(ValueError,match=match):chain.load_components([spec],2)


def test_repeated_attempt_sources_cannot_change_under_one_case(context):
    spec=make_component(context,layout='attempts');p=chain.read(spec['prepared']['path'])
    p['attempts'][1]['source_inputs']['corpus']=p['attempts'][2]['source_inputs']['corpus']
    reseal(spec,p)
    with pytest.raises(ValueError,match='Repeated source'):chain.load_components([spec],2)


@pytest.mark.parametrize('role',sorted(chain.INPUTS))
def test_common_inputs_and_overlapping_metadata_must_match(context,role):
    left=make_component(context,'left');right=make_component(context,'right')
    p=chain.read(right['prepared']['path'])
    p['source_inventory']['a']['inputs'][role]=put(context[0]/'changed.json',dict(different=role))
    reseal(right,p)
    with pytest.raises(ValueError,match='source bytes or overlapping'):chain.load_components([left,right],2)


def test_equal_source_bytes_in_distinct_locations_are_verified(context):
    left=make_component(context,'left');right=make_component(context,'right')
    p=chain.read(right['prepared']['path']);old=p['source_inventory']['a']['inputs']['corpus.json']
    path=context[0]/'duplicate.json';path.write_bytes(Path(old['path']).read_bytes())
    p['source_inventory']['a']['inputs']['corpus.json']=chain.frozen(path);reseal(right,p)
    assert chain.load_components([left,right],2)[1]['a']['inputs']['corpus.json']==old
    path.write_text('changed')
    with pytest.raises(ValueError,match='Changed sealed data'):chain.load_components([left,right],2)


@pytest.mark.parametrize('which',['prepared_seal','summary_seal'])
def test_seal_must_identify_exact_document(context,which):
    spec=make_component(context)
    receipt=spec['prepared'] if which=='summary_seal' else spec['summary']
    content=receipt if which=='summary_seal' else dict(prepared=receipt)
    spec[which]['receipt']=put(spec[which]['receipt']['path'],content)
    with pytest.raises(ValueError,match='Seal identifies'):chain.load_components([spec],2)


def test_seal_may_be_a_receipt_inside_a_frozen_parent_document(context):
    spec=make_component(context)
    parent=put(context[0]/'parent-prepared.json',dict(components=[dict(summary=spec['summary'])]))
    spec['summary_seal']=dict(receipt=parent,pointer='/components/0/summary')
    chain.load_components([spec],2)
    # The whole parent remains sealed, including bytes outside the selected edge.
    value=chain.read(parent['path']);value['unrelated']='changed'
    put(parent['path'],value)
    with pytest.raises(ValueError,match='Changed sealed data'):chain.load_components([spec],2)


def test_full_declared_denominator_names_and_commits_are_required(context):
    spec=make_component(context)
    with pytest.raises(ValueError,match='full denominator'):chain.load_components([spec],17)
    with pytest.raises(ValueError,match='Duplicate component'):chain.load_components([spec,spec],2)
    spec['commit']='main'
    with pytest.raises(ValueError,match='full immutable'):chain.load_components([spec],2)
    spec['commit']='0'*40
    with pytest.raises(ValueError,match='unavailable'):chain.load_components([spec],2)


def test_no_audit_projection_or_external_closure_is_followed(context):
    spec=make_component(context)
    chain.load_components([spec],2) # nonexistent audit/native/algorithm paths are intentionally not edges
    spec['source_rows']['pointer']='/independent_audit'
    with pytest.raises(ValueError,match='Audit fields'):chain.load_components([spec],2)


def test_json_pointer_escapes_and_duplicate_json_keys(tmp_path):
    assert chain.pointer({'a/b':{'~name':[7]}},'/a~1b/~0name/0')==7
    for p in ['missing','/a~2','/array/-1','/array/01']:
        with pytest.raises(ValueError):chain.pointer({'array':[1]},p)
    p=tmp_path/'duplicate.json';p.write_text('{"a":1,"a":2}')
    with pytest.raises(ValueError,match='Duplicate JSON'):chain.read(p)


def test_prepare_run_resume_and_tamper_detection(context):
    root,_,_=context
    specs=[make_component(context,'first'),make_component(context,'second',alert_case='b')]
    put(root/'components.json',specs)
    output=root/'combined'
    chain.prepare(SimpleNamespace(components=root/'components.json',output=output,expected_trials=2))
    assert chain.run(SimpleNamespace(input=output))['alerts']==2
    summary=chain.read(output/'summary.json')
    assert chain.run(SimpleNamespace(input=output))==summary
    assert summary['provider_native_receipts_revalidated'] is False
    assert list(summary['component_outputs'])==['first','second']
    changed=copy.deepcopy(summary);changed['decisions'][0]['alert']['token']='tampered'
    put(output/'summary.json',changed);put(output/'summary_seal.json',chain.frozen(output/'summary.json'))
    with pytest.raises(ValueError,match='Completed composition differs'):chain.run(SimpleNamespace(input=output))


def test_invalid_inputs_do_not_create_output(context):
    root,_,_=context;spec=make_component(context)
    put(root/'components.json',[spec]);Path(spec['summary']['path']).write_text('{}')
    with pytest.raises(ValueError):chain.prepare(SimpleNamespace(components=root/'components.json',output=root/'never-created',expected_trials=2))
    assert not (root/'never-created').exists()
