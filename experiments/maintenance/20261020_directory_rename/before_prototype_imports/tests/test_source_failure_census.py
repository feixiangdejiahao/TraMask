"""The census resolver proves source identity, never semantics from API names."""
import copy
import json
import pytest
from anchor_retrieval.syntax import Source, walk
from scripts.census_source_failure_evidence import (
    attach_failure_evidence, audit_candidate_sources, import_path, resolve_imported_call,
)


def resolve(caller, package, roots=None, extras=()):
    owner = Source('tests/x_test.go', caller, 'go')
    target = Source('checks/api.go', package, 'go')
    call = next(n for n in walk(owner.root) if n.type == 'call_expression')
    return resolve_imported_call(owner, call, [owner, target, *extras],
        {'go_modules': roots or {'': 'example.org/proj'}})


def test_default_import_alias_comes_from_source_package_not_module_basename():
    caller = '''package test
import "example.org/proj/checks"
func TestX(){ proof.Moon(1, 2) }
'''
    result = resolve(caller, 'package proof\nfunc Moon(a,b int) {}')
    assert result['status'] == 'source_bound'
    assert result['package'] == 'proof'
    assert [r['formal']['name'] for r in result['actual_formal']] == ['a', 'b']
    assert [r['actuals'][0]['code'] for r in result['actual_formal']] == ['1', '2']
    # A familiar assertion spelling does not establish any failure sink.
    result = resolve(caller.replace('Moon', 'Equal'), 'package proof\nfunc Equal(a,b int) {}')
    evidence = attach_failure_evidence(result, {'functions':[{
        'id':'f', 'span':result['declaration_span'],
        'source_sha256':result['declaration_source_sha256'],
        'can_reach_failure':False}], 'conditions':[]})
    assert evidence['can_reach_failure'] is False


def test_explicit_import_alias_is_verified_and_shadowing_stays_unknown():
    package = 'package proof\nfunc Moon(a int) {}'
    caller = 'package test\nimport p "example.org/proj/checks"\nfunc TestX(){ p.Moon(1) }'
    assert resolve(caller, package)['status'] == 'source_bound'
    rebound = caller.replace('func TestX(){', 'func TestX(p Other){')
    assert resolve(rebound, package)['reason'] == 'import_receiver_shadowed_or_reassigned'


@pytest.mark.parametrize('body',[
    'if true { var a,p=1,Other{}; _=a; p.Moon(1) }',
    'for _,p:=range []Other{} { p.Moon(1) }',
    'type p Other; p.Moon(1)',
    'type p = Other; p.Moon(1)',
    'const a,p=1,2; p.Moon(1)',
])
def test_go_other_binding_forms_cannot_borrow_the_import_api(body):
    caller = ('package test\nimport p "example.org/proj/checks"\n'
        'type Other struct{}\nfunc (Other) Moon(x int){}\n'
        'func TestX(){ '+body+' }\nfunc Y(){ p.Moon(2) }')
    result = resolve(caller,'package proof\nfunc Moon(a int) {}')
    assert result['reason'] == 'import_receiver_shadowed_or_reassigned'


def test_same_package_name_or_api_name_never_overrides_module_identity():
    caller = 'package test\nimport proof "somewhere.else/checks"\nfunc TestX(){ proof.Equal(1) }'
    result = resolve(caller, 'package proof\nfunc Equal(a int) {}')
    assert result['status'] == 'unknown' and result['reason'] == 'import_source_unavailable'
    # Default imports also need available package source, not path basename.
    caller = caller.replace('proof "', '"')
    result = resolve(caller, 'package proof\nfunc Equal(a int) {}')
    assert result['status'] == 'unknown'


def test_unique_declaration_required_and_imported_test_files_cannot_prove_api():
    caller = 'package test\nimport p "example.org/proj/checks"\nfunc TestX(){ p.Moon(1) }'
    body = 'package proof\nfunc Moon(a int) {}'
    duplicate = Source('checks/other.go', body, 'go')
    assert resolve(caller, body, extras=(duplicate,))['reason'] == 'import_declaration_missing_or_ambiguous'
    test_only = Source('checks/support_test.go', 'package proof\nfunc Star(a int) {}', 'go')
    assert resolve(caller.replace('Moon','Star'), body, extras=(test_only,))['status'] == 'unknown'


def test_nested_module_root_and_written_path_control_import_identity():
    source = Source('relocated.go', 'package proof', 'go', written_path='nested/checks/api.go')
    assert import_path(source, {'':'example.org/outer', 'nested':'example.org/inner'}) == 'example.org/inner/checks'
    assert import_path(source, {}) is None


def test_variadic_bindings_preserve_actual_arguments_and_unknown_arity():
    caller = 'package test\nimport p "example.org/proj/checks"\nfunc TestX(){ p.Moon(1,2,3) }'
    body = 'package proof\nfunc Moon(a int, rest ...int) {}'
    result = resolve(caller, body)
    assert result['status'] == 'source_bound'
    assert [r['code'] for r in result['actual_formal'][1]['actuals']] == ['2','3']
    spread = resolve(caller.replace('1,2,3','1,values...'), body)
    assert spread['status'] == 'source_bound' and spread['actual_formal'][1]['actuals'][0]['spread']
    assert resolve(caller.replace('1,2,3',''), body)['reason'] == 'argument_arity_mismatch'


def test_failure_evidence_join_requires_exact_declaration_extent():
    caller = 'package test\nimport p "example.org/proj/checks"\nfunc TestX(){ p.Moon(1) }'
    binding = resolve(caller, 'package proof\nfunc Moon(a int) {}')
    assert attach_failure_evidence(binding, {'functions':[]})['status'] == 'unknown'
    wrong = dict(binding['declaration_span'],start_byte=0)
    assert attach_failure_evidence(binding, {'functions':[{'id':'f','span':wrong}]})['status'] == 'unknown'
    same_extent = {'id':'f','span':binding['declaration_span'],'source_sha256':'wrong'}
    assert attach_failure_evidence(binding, {'functions':[same_extent]})['reason'] == 'failure_analysis_source_sha_mismatch'


def test_transitive_failure_sink_and_guard_are_kept_with_source_call_graph():
    caller = 'package test\nimport p "example.org/proj/checks"\nfunc TestX(){ p.Moon(1) }'
    binding = resolve(caller, 'package proof\nfunc Moon(a int) {}')
    entry = {'id':'entry','span':binding['declaration_span'],
        'source_sha256':binding['declaration_source_sha256'],
        'can_reach_failure':True,'check_call_ids':['edge']}
    leaf = dict(entry,id='leaf',check_call_ids=['fail'],
        span=dict(entry['span'],start_byte=entry['span']['end_byte']))
    analysis = {'functions':[entry,leaf], 'calls':[{
        'id':'edge','caller_id':'entry','target_id':'leaf','actual_formal':[],
        'status':'same_package_static_call'}, {'id':'fail','caller_id':'leaf',
        'target_id':None,'status':'testing_sink'}],
        'sinks':[{'call_id':'fail','function_id':'leaf'}],
        'conditions':[{'check_call_id':'edge','expression':'a != 0'}]}
    evidence = attach_failure_evidence(binding,analysis)
    assert evidence['can_reach_failure']
    assert len(evidence['sink_evidence']) == 1 and len(evidence['conditions']) == 1
    assert len(evidence['reachable_functions']) == 2
    assert [[row['id'] for row in path] for path in evidence['shortest_failure_paths']] == [['edge','fail']]
    analysis['unknowns'] = [{'reason':'nonlocal_write_dependency_unsupported','function_id':'entry'},
        {'reason':'control_or_scheduling_unsupported','span':entry['span']},
        {'reason':'unrelated','function_id':'elsewhere'}]
    analysis['limits'] = ['memory aliases not modeled']
    evidence = attach_failure_evidence(binding,analysis)
    assert len(evidence['unknowns']) == 2 and evidence['limits'] == analysis['limits']
    analysis['calls'][0]['status'] = 'unknown'
    evidence = attach_failure_evidence(binding,analysis)
    assert evidence['sink_evidence'] == [] and len(evidence['reachable_functions']) == 1


def test_independent_span_audit_rejects_changed_declaration_or_argument_evidence():
    owner = Source('tests/x_test.go', 'package test\nimport p "example.org/proj/checks"\nfunc TestX(){ p.Moon(1) }', 'go')
    target = Source('checks/api.go', 'package proof\nfunc Moon(a int) {}', 'go')
    call = next(n for n in walk(owner.root) if n.type == 'call_expression')
    binding = resolve_imported_call(owner,call,[owner,target], {'go_modules':{'':'example.org/proj'}})
    corpus = {'language':'go', 'sources':{s.path:{'code':s.code,'language':'go'} for s in [owner,target]},
        'tests':{'t':{'span':{'path':owner.path,'start_byte':0,'end_byte':len(owner.data)}}}}
    candidate = {'id':'c','base_test_id':'t','edits':[]}
    result = {'calls':[{'span':{'path':owner.path,'start_byte':call.start_byte,'end_byte':call.end_byte},
        'code':owner.text(call),'binding':binding,'failure_evidence':{}}]}
    assert audit_candidate_sources(corpus,candidate,result)['status'] == 'exact_source_verified'
    changed = copy.deepcopy(result)
    changed['calls'][0]['binding']['declaration_sha256'] = 'incorrect'
    with pytest.raises(ValueError,match='SHA mismatch'):
        audit_candidate_sources(corpus,candidate,changed)
    changed = copy.deepcopy(result)
    changed['calls'][0]['binding']['actual_formal'][0]['actuals'][0]['code'] = '9'
    with pytest.raises(ValueError,match='exact source span'):
        audit_candidate_sources(corpus,candidate,changed)


def auditable_failure_fixture():
    from experimental.source_failure_evidence import analyze
    owner = Source('tests/x_test.go', '''package test
import "testing"
import p "example.org/proj/checks"
func TestX(t *testing.T){ p.Moon(t,1) }
''', 'go')
    target = Source('checks/api.go', '''package proof
import "testing"
func Moon(t *testing.T, x int){ if x != 0 { stop(t) } }
func stop(t *testing.T){ t.FailNow() }
''', 'go')
    call = next(n for n in walk(owner.root) if n.type == 'call_expression')
    binding = resolve_imported_call(owner,call,[owner,target],{'go_modules':{'':'example.org/proj'}})
    proof = attach_failure_evidence(binding,analyze([target]))
    assert proof['can_reach_failure'] and proof['shortest_failure_paths']
    corpus = {'language':'go', 'sources':{s.path:{'code':s.code,'language':'go'} for s in [owner,target]},
        'tests':{'t':{'span':{'path':owner.path,'start_byte':0,'end_byte':len(owner.data)}}}}
    candidate = {'id':'c','base_test_id':'t','edits':[]}
    result = {'calls':[{'span':{'path':owner.path,'start_byte':call.start_byte,'end_byte':call.end_byte},
        'code':owner.text(call),'binding':binding,'failure_evidence':proof}]}
    return corpus,candidate,result


def test_callee_full_code_and_source_path_copies_are_independently_audited():
    corpus,candidate,result = auditable_failure_fixture()
    assert audit_candidate_sources(corpus,candidate,result)['status'] == 'exact_source_verified'
    changed = copy.deepcopy(result)
    changed['calls'][0]['failure_evidence']['reachable_functions'][0]['code'] += '\n// invented'
    with pytest.raises(ValueError,match='exact source span'):
        audit_candidate_sources(corpus,candidate,changed)
    changed = json.loads(json.dumps(result))
    changed['calls'][0]['failure_evidence']['shortest_failure_paths'][0][0]['code'] = 'made_up()'
    with pytest.raises(ValueError,match='canonical source call'):
        audit_candidate_sources(corpus,candidate,changed)


def test_failure_path_must_be_contiguous_and_end_at_a_proved_sink():
    corpus,candidate,result = auditable_failure_fixture()
    changed = copy.deepcopy(result)
    proof = changed['calls'][0]['failure_evidence']
    first = proof['shortest_failure_paths'][0][0]
    first['target_id'] = 'unrelated'
    for row in proof['same_package_calls']:
        if row['id'] == first['id']:
            row['target_id'] = 'unrelated'
    with pytest.raises(ValueError,match='discontinuity'):
        audit_candidate_sources(corpus,candidate,changed)
    changed = copy.deepcopy(result)
    changed['calls'][0]['failure_evidence']['sink_evidence'] = []
    with pytest.raises(ValueError,match='confirmed testing sink'):
        audit_candidate_sources(corpus,candidate,changed)
