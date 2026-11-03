"""Joint public matching, multi-port slicing and independent material carriers."""
from pathlib import Path
import subprocess
import shlex

from eviweave.artifacts import read_json, resolve_references, write_json
from eviweave.evidence import SourceGraph
from eviweave.history import read_context, read_source_bytes
from eviweave.material_entries import select_material_entries
from eviweave.slice_frontier import matching_statements
from eviweave.slicing import ContextProgram, slice_targets
from eviweave.source_text import decode_source
from test_eviweave_trajectory import recorded


def run_pipeline(tmp_path,sources,command,issue):
    root,out,result=recorded(tmp_path,sources,command)
    assert result['returncode']==0
    subprocess.run(['git','-C',str(root),'add','-A'],check=True,capture_output=True)
    patch=subprocess.run(['git','-C',str(root),'diff','--cached','--binary','HEAD'],check=True,capture_output=True).stdout
    subprocess.run(['git','-C',str(root),'diff','--exit-code'],check=True,capture_output=True)
    graph=read_json(out/'trajectory.json');files=graph['materials']
    write_json(out/'manifest.json',{'replay':str(out),'trajectory':str(out/'trajectory.json'),'submission_state_validated':True,
               'source_versions':[{'path':m['path'],'sha256':m['sha256']} for m in files.values() if m['kind']=='file'],
               'unobserved_source_candidates':[]})
    write_json(out/'plan.json',{'action_ids':['s1']})
    (out/'runtime').mkdir();(out/'runtime/calls').symlink_to(tmp_path/'calls')
    for name,state in [('initial',graph['initial']),('submission',graph['submitted'])]:
        write_json(out/'snapshots'/(name+'.json'),{'files':[{'kind':'file','path':files[m]['path'],'sha256':files[m]['sha256']} for m in state.values()]})
    (out/'inputs').mkdir();(out/'inputs/instruction.md').write_text(issue)
    (out/'inputs/model.patch').write_bytes(patch)
    destination=tmp_path/'slicing';summary=slice_targets(out/'manifest.json',destination)
    return out,destination,summary


def test_lowering_uses_calls_and_program_strings_without_observation_seeds():
    raw=b'''def test_code():
    value = api.execute()
    code = "target[::2]"
    field = api.enabled
    assert unrelated_value
'''
    graph=SourceGraph({'id':'source','path':'test_code.py','raw':raw})
    unit={'start':0,'end':len(raw)-1,'anchors':[[0,len(raw)-1]]}
    queries=[]
    for text in [b'api.execute()',b'"target[::2]"',b'api.enabled']:
        a=raw.index(text);queries.append((a,a+len(text)))
    ports,unmapped=matching_statements(graph,[(4,unit)],queries)
    assert not unmapped and len(ports)==2
    assert all(p['entries']==[4] for p in ports)
    retained={graph.text(graph.nodes[p['node']]['ast']) for p in ports}
    assert retained=={'value = api.execute()','code = "target[::2]"'}


def test_static_group_keeps_independent_matches_in_one_test_and_full_bindings():
    raw=b'''def helper(value):
    return value + 1
def test_pair():
    configure_mode()
    first = helper(3)
    second = helper(7)
    assert first == 4
    assert second == 8
'''
    graph=SourceGraph({'id':'source','path':'test_pair.py','raw':raw})
    seeds=[]
    for text in [b'configure_mode()',b'helper(3)',b'helper(7)']:
        a=raw.index(text);seeds.append(graph.criterion(a,a+len(text))['node'])
    rows=ContextProgram.from_source(graph).grouped_slices('source',seeds)
    assert len(rows)==1 and set(rows[0]['group']['matches'])==set(seeds)
    file,=rows[0]['view']['files'];text=''.join(raw[a:b].decode() for a,b in file['ranges'])
    assert 'configure_mode()' in text and 'assert first == 4' in text and 'assert second == 8' in text
    calls=[c for c in rows[0]['view']['calls'] if c['kind']=='direct']
    assert len(calls)==2 and all(c['arguments'][0]['parameter']=='value' for c in calls)


def test_materials_include_unmatched_validation_structured_reads_and_snapshots(tmp_path):
    actions=[
        {'id':'validate','command':'python verify.py','expected':{'output':'plain verification output'}},
        {'id':'append','command':"cat >>test_extra.py <<'PY'\ndef test_extra(): pass\nPY\n",'expected':{}},
        {'id':'read','command':'sed -n 1,20p config.rs','expected':{'output':'r#"{ "collapseGroups": true }"#'}},
        {'id':'xml','command':'cat output.svg','expected':{'output':'<svg><g id="x"/></svg>'}},
        {'id':'xml_file','command':'cat response.xml','expected':{'output':'<report>ok</report>'}},
        {'id':'json_text','command':'cat response.txt','expected':{'output':'{"condition":true}'}},
        {'id':'diff','command':'git diff test_case.py','expected':{'output':'diff of a matched source'}},
        {'id':'show','command':'git show HEAD:test_case.py','expected':{'output':'prior version of a matched source'}},
        {'id':'other','command':'cat unrelated.txt','expected':{'output':'plain unrelated text'}},
        {'id':'maintenance','command':'git status','expected':{'output':'nothing to commit'}},
    ]
    files=[{'path':p,'source':str(tmp_path/str(i))} for i,p in enumerate(
        ['/app/output.svg','/app/__snapshots__/test_case.snap','/app/other/__snapshots__/other.snap'])]
    result=select_material_entries(actions,['operation'],[],{'/app/test_case.py'},set(),files)
    assert {a['action'] for a in result['actions']}=={'validate','append','read','xml','xml_file','json_text','diff','show'}
    assert {f['path'] for f in result['files']}=={'/app/output.svg','/app/__snapshots__/test_case.snap'}
    assert next(a for a in result['actions'] if a['action']=='read')['reasons']==['structured_read']


def test_real_pipeline_groups_tests_per_execution_and_exports_readable_materials(tmp_path):
    code='''from impl import operation
def test_pair():
    first = operation(3)
    second = operation(7)
    assert first == 4
    assert second == 8
def test_other():
    assert operation(10) == 11
test_pair()
test_other()
print('{"validated":true}')
'''
    sources={'impl.py':'def operation(value):\n    return value + 1\n','test_pair.py':code,
             '__snapshots__/test_pair.snap':'expected snapshot\n'}
    out,destination,summary=run_pipeline(tmp_path,sources,'python3 -B test_pair.py; python3 -B test_pair.py','Preserve `operation()` behavior.')
    assert summary['entry_groups']>0 and summary['retained_B_records']>0
    groups=[resolve_references(read_json(p),destination) for p in (destination/'slices').glob('*.json')]
    pairs=[g for g in groups if len(g['ports'])==2]
    assert len(pairs)==2
    views=[read_json(destination/g['views'][0]) for g in pairs]
    assert len({v['execution'] for v in views})==2
    for view in views:
        calls=[c for c in view['calls'] if c['kind']=='direct' and c['parameters']==['value']]
        assert len(calls)>=2 and {c['arguments'][0]['parameter'] for c in calls}=={'value'}
        assert (destination/view['trajectory_ref']).exists()
    carriers=resolve_references(read_json(destination/'material_entries.json'),destination)
    targets=resolve_references(read_json(destination/'targets.json'),destination)
    records={r['id']:r for r in targets['records']}
    assert any('{"validated":true}' in records[i]['text'] for i in carriers['records'])
    snapshot,=carriers['files'];assert read_source_bytes(snapshot['source'])==b'expected snapshot\n'
    assert all(read_context(records[i]['source']) for i in carriers['records'])


def test_normalized_python_encoding_keeps_independent_tests_separate():
    text='# coding: latin-1\n# '+'é'*40+'''\ndef test_one():
    unrelated_long_named_value = 1000000000000000000000000000000000
    value = operation(1)
    assert value
def test_two():
    value = operation(2)
    assert value
'''
    raw=decode_source('test_encoding.py',text.encode('latin-1')).encode()
    graph=SourceGraph({'id':'source','path':'test_encoding.py','raw':raw})
    seeds=[]
    for text in [b'operation(1)',b'operation(2)']:
        a=raw.index(text);seeds.append(graph.criterion(a,a+len(text))['node'])
    rows=ContextProgram.from_source(graph).grouped_slices('source',seeds)
    assert len(rows)==2 and all(len(row['group']['matches'])==1 for row in rows)


def test_python_variadic_and_keyword_only_arguments_bind_to_their_formals():
    raw=b'''def helper(first, *rest, flag=False, **options):
    return first
def test_binding():
    result = helper(1, 2, 3, flag=True, other=4)
    assert result == 1
'''
    graph=SourceGraph({'id':'source','path':'test_binding.py','raw':raw})
    a=raw.index(b'helper(1');seed=graph.criterion(a,a+len(b'helper(1, 2, 3, flag=True, other=4)'))['node']
    row,=ContextProgram.from_source(graph).grouped_slices('source',[seed])
    call,=[c for c in row['view']['calls'] if c['kind']=='direct']
    assert [a['parameter'] for a in call['arguments']]==['first','rest','rest','flag','options']


def test_unmatched_validation_also_keeps_its_snapshot(tmp_path):
    result=select_material_entries([{'id':'run','command':'npx jest spec/other.test.ts','expected':{}}],[],[],set(),set(),
                                   [{'source':str(tmp_path/'snap'),'path':'/app/spec/__snapshots__/other.test.ts.snap'}])
    assert result['actions'] and result['files'][0]['reason']=='adjacent_snapshot'


def test_batch_exports_embedded_program_analysis(tmp_path):
    code='def operation(value): return value + 1\nexec("value = operation(3); assert value == 4")\n'
    _,destination,_=run_pipeline(tmp_path,{'test_embedded.py':code},'python3 -B test_embedded.py','Preserve `operation()`.')
    views=[read_json(p) for p in (destination/'views').glob('*.json')]
    inner=[item for view in views for item in view['embedded_inputs'] if item['text']=='value = operation(3); assert value == 4']
    assert inner and all(item['graph'] and item['slices'] for item in inner)


def test_unexecuted_source_uses_creation_snapshot_and_keeps_unresolved_import(tmp_path):
    code='from hidden_helpers import *\nfrom helper import operation\ndef test_old():\n    assert operation() == 3\n'
    command="cat >test_case.py <<'PY'\n"+code+"PY\nprintf 'def operation(): return 99\\n' >helper.py"
    sources={'helper.py':'def operation(): return 3\n',
             'conftest.py':'import pytest\n@pytest.fixture(autouse=True)\ndef ready():\n    print("setup-ready")\n'}
    out,destination,_=run_pipeline(tmp_path,sources,command,'Preserve `operation()`.')
    data=read_json(out/'trajectory.json');from eviweave.blobs import BlobStore
    store=BlobStore(out/'blobs');views=[read_json(p) for p in (destination/'views').glob('*.json')]
    static=[v for v in views if v['mode']=='static_program' and 'files' in v]
    assert static
    for view in static:
        text='\n'.join(store.read(data['materials'][f['material']]['sha256'])[a:b].decode() for f in view['files'] for a,b in f['ranges'])
        assert 'return 3' in text and 'return 99' not in text and 'setup-ready' in text
        assert view['execution'] is None and 'star_import' in view['unresolved']


def test_multiple_runtime_versions_are_candidates_not_simultaneous_direct_calls(tmp_path):
    code='''import helper, importlib
from pathlib import Path
def test_before():
    assert helper.operation() == 3
def test_after():
    assert helper.operation() == 12345
test_before()
Path('helper.py').write_text('def operation(): return 12345\\n')
importlib.invalidate_caches()
importlib.reload(helper)
test_after()
'''
    out,destination,_=run_pipeline(tmp_path,{'helper.py':'def operation(): return 3\n','test_versions.py':code},
                                      'python3 -B test_versions.py','Preserve `operation()`.')
    materials=read_json(out/'trajectory.json')['materials'];views=[read_json(p) for p in (destination/'views').glob('*.json')]
    ambiguous=[v for v in views if v['version_alternatives']]
    assert ambiguous
    for view in ambiguous:
        assert not any(materials[c['callee'][0]]['path']=='/app/helper.py' for c in view['calls'])
        assert all(len({materials[m]['sha256'] for m,s in candidate['callees']})==2 for candidate in view['version_alternatives'])


def test_bad_encoding_is_reported_without_aborting_other_slices(tmp_path):
    code='def operation(): return 3\ndef test_ok(): assert operation() == 3\ntest_ok()\n'
    command="python3 -B test_ok.py; printf '# coding: bad-encoding\\ndef operation(): return 9\\n' >broken.py"
    _,destination,summary=run_pipeline(tmp_path,{'test_ok.py':code},command,'Preserve `operation()`.')
    assert summary['entry_groups']
    targets=read_json(destination/'targets.json')
    assert any(error['kind']=='source_encoding' for entry in targets['parse_errors'] for error in entry['errors'])


def test_deleted_unexecuted_helper_recovers_latin1_test_caller(tmp_path):
    caller='# coding: latin-1\nfrom helper import café\ndef test_old():\n    assert café(3) == 4\n'
    helper='from impl import operation\ndef café(value):\n    return operation(value)\n'
    writer=('from pathlib import Path; Path("test_case.py").write_bytes('+repr(caller.encode('latin-1'))+'); '
            'Path("helper.py").write_text('+repr(helper)+')')
    command='python3 -B -c '+shlex.quote(writer)+'; rm test_case.py helper.py'
    out,destination,_=run_pipeline(tmp_path,{'impl.py':'def operation(value): return value + 1\n'},command,'Preserve `operation()`.')
    materials=read_json(out/'trajectory.json')['materials']
    static=[read_json(p) for p in (destination/'views').glob('*.json') if read_json(p)['mode']=='static_program']
    assert any(any(f['path']=='/app/test_case.py' for f in v.get('files',[])) for v in static)
    assert any(len(v['calls'])>=2 and any(materials[c['site'][0]]['path']=='/app/test_case.py' for c in v['calls']) for v in static)


def test_multiple_fixture_versions_remain_alternatives(tmp_path):
    first='import pytest\n@pytest.fixture(autouse=True)\ndef ready(): return 3\n'
    second=first.replace('return 3','return 9')
    code=('import conftest, importlib\nfrom pathlib import Path\n'
          'def operation(): return 3\ndef test_case(): assert operation() == 3\n'
          'assert conftest.ready.__wrapped__() == 3\ntest_case()\n'
          'Path("conftest.py").write_text('+repr(second)+')\n'
          'importlib.invalidate_caches()\nimportlib.reload(conftest)\n'
          'assert conftest.ready.__wrapped__() == 9\ntest_case()\n')
    out,destination,_=run_pipeline(tmp_path,{'conftest.py':first,'test_state.py':code},'python3 -B test_state.py','Preserve `operation()`.')
    materials=read_json(out/'trajectory.json')['materials'];views=[read_json(p) for p in (destination/'views').glob('*.json')]
    alternatives=[item for v in views for item in v['version_alternatives'] if item['kind']=='framework_setup']
    assert alternatives and all(len({materials[m]['sha256'] for m,s in item['callees']})==2 for item in alternatives)
    assert all(not any(c['kind']=='framework_setup' and materials[c['callee'][0]]['path']=='/app/conftest.py' for c in v['calls']) for v in views)
