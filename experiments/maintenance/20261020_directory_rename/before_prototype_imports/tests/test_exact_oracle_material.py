import copy
import json

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search.oracle import prepare_requests
from experimental.exact_oracle_material import MaterialIndex, request_keys, select_unique, summarize


PROGRAMS = [
    ('python', 'test_material.py', '''def helper(value): return value * 2
def test_seed():
    value = 11
    result = helper(value)
    assert result == 22
'''),
    ('go', 'material_test.go', '''package sample
import "testing"
func helper(value int) int { return value * 2 }
func TestSeed(t *testing.T) {
    value := 11
    result := helper(value)
    if result != 22 { t.Fatal(result) }
}
'''),
    ('typescript', 'material.test.ts', '''function helper(value: number) { return value * 2; }
test('seed', () => {
    const value = 11;
    const result = helper(value);
    expect(result).toBe(22);
});
'''),
]


def fixture(language='python'):
    language,path,code = next(row for row in PROGRAMS if row[0] == language)
    frontend = extract_frontend([Source(path,code,language)])
    corpus = to_emitter_corpus(frontend)
    base = next(iter(corpus['tests']))
    start = code.encode().index(b'11', corpus['tests'][base]['span']['start_byte'])
    candidate = dict(id='one',base_test_id=base,kind='family_one',imports=[],source_test_ids=[],
        edits=[dict(before='11',after='19',role='input',
                    span=dict(path=path,start_byte=start,end_byte=start+2))])
    return corpus,frontend,candidate


@pytest.mark.parametrize('language',['python','go','typescript'])
def test_ids_and_derivation_families_do_not_create_new_material(language):
    corpus,frontend,first = fixture(language)
    second = {**copy.deepcopy(first),'id':'two','kind':'family_two',
              'relation':{'provenance':'other discovery route'}}
    index = MaterialIndex('toy',corpus,frontend)
    a,b = index.record(first),index.record(second)
    assert a['status'] == b['status'] == 'materialized'
    assert a['program_key'] == b['program_key'] and a['material_key'] == b['material_key']
    assert summarize([a,b])['redundant_material_slots'] == 1


@pytest.mark.parametrize('field,value,component',[
    ('imports',[{'name':'helper','module':'.other','source_path':'different/test.py'}],'imports'),
    ('source_test_ids',['other-source-control'],'source_controls'),
    ('source_contexts',[{'span':{'path':'test_material.py','start_byte':0,'end_byte':39}}],'source_contexts'),
    ('runtime_probes',[{'expression':'counter.read()'}],'runtime_context'),
    ('control_runtime_probes',[{'expression':'counter.clear()'}],'runtime_context'),
    ('extra_setup','reset_shared_resource()','runtime_context'),
    ('future_unreviewed_premise',{'value':True},'unknown_fields'),
])
def test_identical_owner_different_real_context_never_merges(field,value,component):
    corpus,frontend,first=fixture()
    second={**copy.deepcopy(first),'id':'two',field:value}
    index=MaterialIndex('toy',corpus,frontend)
    a,b=index.record(first),index.record(second)
    assert a['program_key']==b['program_key'] and a['material_key']!=b['material_key']
    stats=summarize([a,b])
    assert stats['constraints'][component]['program_classes_split']==1
    assert stats['constraints'][component]['conservative_classes_released_if_omitted']==1


def test_same_program_different_edit_decomposition_preserves_observer_context():
    corpus,frontend,first=fixture()
    second=copy.deepcopy(first);second['id']='two'
    original=first['edits'][0]
    start=original['span']['start_byte']
    second['edits']=[dict(before='1',after='1',role='input',span={**original['span'],'end_byte':start+1}),
                     dict(before='1',after='9',role='input',span={**original['span'],'start_byte':start+1})]
    index=MaterialIndex('toy',corpus,frontend)
    a,b=index.record(first),index.record(second)
    assert a['program_key']==b['program_key']
    assert a['material_key']!=b['material_key']
    assert a['components']['edits']!=b['components']['edits']


def test_observation_location_and_base_test_are_not_text_only():
    corpus,frontend,first=fixture()
    index=MaterialIndex('toy',corpus,frontend)
    original=index.record(first)
    changed=copy.deepcopy(frontend)
    observation=next(row for row in changed['observations'] if row['kind']=='assertion')
    observation['span']['start_byte']+=1
    assert MaterialIndex('toy',corpus,changed).record(first)['material_key']!=original['material_key']
    assert MaterialIndex('other-case',corpus,frontend).record(first)['material_key']!=original['material_key']


def test_probe_edits_removed_from_owner_but_probe_premise_kept():
    corpus,frontend,first=fixture()
    instrumented=copy.deepcopy(first)
    instrumented.update(id='instrumented',program_edits=copy.deepcopy(first['edits']),
                        instrumentation={'status':'instrumented'},runtime_probes=[{'expression':'counter.read()'}])
    instrumented['edits'][0]['after']='log_probe(); 19'
    index=MaterialIndex('toy',corpus,frontend)
    a,b=index.record(first),index.record(instrumented)
    assert a['program_key']==b['program_key'] and a['material_key']!=b['material_key']


def test_invalid_edits_are_retained_as_separate_unknowns():
    corpus,frontend,candidate=fixture()
    candidate['edits'][0]['before']='wrong'
    index=MaterialIndex('toy',corpus,frontend)
    a,b=index.record(candidate),index.record({**candidate,'id':'two'})
    assert a['status']==b['status']=='unmaterializable'
    assert a['material_key']!=b['material_key']


def test_selection_refills_from_frozen_order_without_reweighting():
    corpus,frontend,first=fixture()
    index=MaterialIndex('toy',corpus,frontend)
    second={**copy.deepcopy(first),'id':'two','kind':'other'}
    third=copy.deepcopy(first);third['id']='three';third['edits'][0]['after']='29'
    records=[index.record(c) for c in [first,second,third]]
    result=select_unique(records,budget=2)
    assert [r['id'] for r in result['selected']]==['one','three']
    assert result['skipped_ids']==['two']


def test_actual_oracle_payload_confirms_toy_equivalence_and_context_difference():
    corpus,frontend,first=fixture()
    second={**copy.deepcopy(first),'id':'two','kind':'other_family'}
    requests=prepare_requests(corpus,frontend,[first,second],'Double the argument.',
                              max_requests=2,per_request=1,evidence_mode='dependency')
    assert len(requests)==2
    assert request_keys(requests[0])==request_keys(requests[1])
    changed=copy.deepcopy(requests[1]);payload=json.loads(changed['prompt'])
    payload['candidates'][0]['import_bindings'].append({'name':'context','module':'other'})
    changed['prompt']=json.dumps(payload)
    assert request_keys(changed)['wire_key']!=request_keys(requests[0])['wire_key']
    # A source spelling resembling a candidate ID remains real program data.
    changed=copy.deepcopy(requests[1]);payload=json.loads(changed['prompt'])
    payload['candidates'][0]['modified_test']+='\n# two\n'
    changed['prompt']=json.dumps(payload)
    assert request_keys(changed)['wire_key']!=request_keys(requests[0])['wire_key']
