import copy
import hashlib
import json
from pathlib import Path

import pytest

from experimental.source_declarations_context import render_declarations, sha, transform, verify_declaration_sources
from relation_search.checkpoint import digest, read, write
from scripts.prepare_source_declarations_ablation import prepare, select_request


def declaration(code, start=0, *, file_hash=None, role='callee', path='subject.py'):
    return dict(code=code, source_sha256=file_hash or sha(code), roles=[role],
                span=dict(path=path, start_byte=start, end_byte=start+len(code.encode())))


def test_containment_is_lossless_utf8_and_retains_inner_source_roles():
    code = 'def outer():\n    label = "π"\n    return label\n'
    outer = declaration(code, role='callee')
    inner_code = 'return label'
    start = code.encode().index(inner_code.encode())
    inner = declaration(inner_code, start, file_hash=outer['source_sha256'], role='source_helper')
    duplicate = {**copy.deepcopy(inner), 'roles':['source_control']}
    evidence = dict(declarations=[inner, duplicate, outer], edges=[{'GRAPH_ONLY_SENTINEL':True}])
    rendered, audit = render_declarations(evidence)
    assert audit['input_declarations'] == 3 and audit['unique_spans'] == 2
    assert audit['emitted_declarations'] == 1
    assert rendered.count(code) == 1 and 'GRAPH_ONLY_SENTINEL' not in rendered
    header = json.loads(rendered.splitlines()[0].removeprefix('SOURCE '))
    assert header['included_sources'][0]['roles'] == ['source_helper', 'source_control']
    assert header['included_sources'][0]['span'] == inner['span']
    assert len(audit['coverage']) == 2


def test_different_source_versions_and_partial_overlaps_are_not_conflated():
    first = declaration('abcd', file_hash='a'*64)
    second = declaration('cdef', 2, file_hash='a'*64)
    changed = declaration('abce', file_hash='b'*64)
    rendered, audit = render_declarations(dict(declarations=[first, second, changed]))
    assert audit['emitted_declarations'] == 3
    assert all(row['code'] in rendered for row in (first,second,changed))


def test_declaration_order_and_source_headers_match_original_renderer():
    from relation_search.oracle_evidence import render_evidence
    # Source hash ordering would reverse these distinct files; the original
    # renderer instead orders by path and byte span.
    first = declaration('first', file_hash='f'*64, path='a.py')
    second = declaration('second', file_hash='0'*64, path='z.py')
    second['roles'] = ['source_test_helper','candidate_declaration_not_oracle']
    evidence = dict(declarations=[second,first], added_import_bindings=[],changes=[],calls=[],assertions=[],
                    edges=[],controls=[],unknowns=[])
    old = render_evidence(evidence)
    new, _ = render_declarations(evidence)
    assert old.endswith(new)
    assert new.index('first') < new.index('second')


def test_conflicting_or_truncated_declared_spans_fail():
    outer = declaration('abcdef')
    inner = declaration('xyz', 2, file_hash=outer['source_sha256'])
    with pytest.raises(ValueError, match='Contained declaration disagrees'):
        render_declarations(dict(declarations=[outer,inner]))
    with pytest.raises(ValueError, match='complete UTF-8 source span'):
        render_declarations(dict(declarations=[{**outer,'code':'abc'}]))


def request_fixture():
    code = 'def helper(x):\n    return x + 1\n\ndef test_seed():\n    assert helper(1) == 2\n'
    test_start = code.index('def test_seed')
    arg_start = code.index('1', test_start)
    candidate = dict(id='source_candidate', base_test_id='seed', source_test_ids=[], imports=[], edits=[
        dict(before='1',after='2',role='input',span=dict(path='subject.py',start_byte=arg_start,end_byte=arg_start+1))])
    corpus = dict(language='python', sources={'subject.py':{'code':code}},
                  tests={'seed':{'span':dict(path='subject.py',start_byte=test_start,end_byte=len(code))}})
    evidence = dict(declarations=[declaration(code[:test_start].rstrip(),file_hash=sha(code))],
                    rendered='GRAPH_ONLY_SENTINEL\n'+('edge\n'*100), rendered_bytes=519,
                    limits={'max_bytes':100}, status='over_budget',edges=[{'graph':'unused'}])
    payload = dict(language='python',issue='Sum both operands.',candidates=[dict(candidate='C0',
        source_test=code,modified_test=code[:arg_start]+'2'+code[arg_start+1:], assertions=['helper(1) == 2'],
        input_changes=candidate['edits'], import_bindings=[],dependency_evidence=dict(
        rendered=evidence['rendered'],rendered_bytes=len(evidence['rendered'].encode()),status='over_budget',version='original'))])
    request = dict(id='original_request',system='original system',thinking='enabled',offered={'C0':{'candidate':candidate}},
                   prompt=json.dumps(payload,ensure_ascii=False),analysis_evidence={'C0':evidence})
    return request, corpus


def test_transform_only_changes_presentation_and_truthful_derived_metadata():
    request, _ = request_fixture()
    frozen = copy.deepcopy(request)
    converted, audit = transform(request)
    before, after = json.loads(request['prompt']),json.loads(converted['prompt'])
    original = before['candidates'][0]['dependency_evidence']
    changed = after['candidates'][0]['dependency_evidence']
    assert changed['rendered_bytes'] == len(changed['rendered'].encode())
    assert changed['status'] == ('over_budget' if changed['rendered_bytes']>100 else 'ready')
    assert changed['version'] == original['version']
    assert 'GRAPH_ONLY_SENTINEL' not in changed['rendered']
    after['candidates'][0]['dependency_evidence'] = original
    assert after == before
    assert converted['analysis_evidence'] == request['analysis_evidence']
    assert converted['offered'] == request['offered'] and converted['system'] == request['system']
    assert request == frozen and audit['candidates']['C0']['no_code_truncation']
    assert converted['id'] == sha(converted['prompt'])


def test_empty_and_very_long_declarations_remain_honest():
    rendered, audit = render_declarations(dict(declarations=[]))
    assert 'No source declarations' in rendered and audit['emitted_declarations'] == 0
    code = 'def large():\n'+('    data = "π"\n'*5000)
    rendered, audit = render_declarations(dict(declarations=[declaration(code)]))
    assert code in rendered and audit['emitted_code_bytes'] == len(code.encode())


def test_declarations_are_checked_against_full_frozen_sources():
    request, corpus = request_fixture()
    assert len(verify_declaration_sources(request,corpus)) == 1
    request['analysis_evidence']['C0']['declarations'][0]['code'] = 'wrong'
    with pytest.raises(ValueError,match='frozen complete source'):
        verify_declaration_sources(request,corpus)


def test_preparation_uses_only_input_wires_and_no_provider_outputs(tmp_path):
    request, corpus = request_fixture()
    source = tmp_path/'source'
    write(source/'corpus.json',corpus)
    request['source_prepared'] = str(source)
    campaign, ablation, frozen = tmp_path/'campaign',tmp_path/'ablation',tmp_path/'frozen'
    write(campaign/'configuration.json',{'cases':['toy']})
    semantic = campaign/'toy/round_000/semantic'
    write(semantic/'semantic_selection.json',{'offered_ids':['source_candidate']})
    write(semantic/'requests/request_007.json',request)
    wire = dict(model='deepseek-v4-flash',temperature=0,max_tokens=16384,stream=False,
                thinking={'type':'enabled'},messages=[{'role':'system','content':request['system']},
                                                     {'role':'user','content':request['prompt']}])
    write(semantic/'completions/request_007/request.json',wire)
    driver, provider = frozen/'scripts/relation_search_semantics.py',frozen/'relational_gap/provider.py'
    for path in (driver,provider):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('# A provider is never invoked during preparation.\n')
    write(ablation/'stage.json',dict(campaign=str(campaign),configuration_sha256=digest(campaign/'configuration.json'),
        cases=['toy'],code_sha256={str(path):digest(path) for path in (driver,provider)}))
    result = prepare(ablation,tmp_path/'prepared',frozen)
    assert result['status']=='ready' and result['prepared']==1 and result['provider_calls']==0
    converted = read(tmp_path/'prepared/toy/wire_preview.json')
    assert {k:v for k,v in converted.items() if k!='messages'} == {k:v for k,v in wire.items() if k!='messages'}
    assert converted['messages'][0] == wire['messages'][0]
    assert result == prepare(ablation,tmp_path/'prepared',frozen)
    assert not (tmp_path/'prepared/toy/completion').exists()
    # Incomplete request inventories cannot select a convenient prefix.
    write(semantic/'semantic_selection.json',{'offered_ids':['source_candidate','not_written_yet']})
    assert select_request(semantic) == (None,'source_request_inventory_incomplete')
