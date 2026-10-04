import copy
import json

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search import contract_scalar_observer as core
from relation_search import contract_scalar_observer_review as gate
from relation_search import oracle

ISSUE = ('Queued changes must preserve each owned object presence observation across commit. '
         'The token constructor and presence observer are pure and return stable values. '
         'Presence accepts a token pair and returns boolean, including after destruction.')
CODE = '''import { expect, it } from 'vitest';
import { createOwner, token } from './api';
const Linked = token({ cascade: true });
it('cross object effect ✓', () => {
    const owner = createOwner();
    const parent = owner.spawn();
    const item = owner.spawn(Linked(parent));
    owner.queue.remove(parent);
    owner.queue.commit();
    expect(owner.contains(item)).toBe(false);
    expect(owner.contains(parent)).toBe(false);
});
'''


def fixture(code=CODE, origin='repository'):
    source = Source('example.test.ts', code, 'typescript', origin)
    frontend = extract_frontend([source]); corpus = to_emitter_corpus(frontend)
    return source, corpus, frontend


def prepared(code=CODE):
    source, corpus, frontend = fixture(code)
    result = core.prepare(corpus, frontend, ISSUE)
    assert result['request'], result
    host = json.loads(result['request']['prompt'])['hosts'][0]
    receiver = next(r for r in host['receivers'] if r['name']=='item')
    donor = next(d for d in host['argument_donors'] if d['expression']['text']=='Linked(parent)')
    proposal = dict(host_alias=host['host_alias'], receiver_alias=receiver['alias'], method='present',
        argument_aliases=[donor['alias']], scalar_kind='boolean', issue_quote=ISSUE.split('. ')[0]+'.')
    return source, corpus, frontend, result, proposal


def decoded(code=CODE):
    source, corpus, frontend, result, proposal = prepared(code)
    response=json.dumps({'observations':[proposal]})
    result=core.decide(corpus,frontend,result,response)
    assert len(result['candidates'])==1, result
    return source, corpus, frontend, result['candidates'][0]


def test_new_observer_on_existing_object_and_pair_keeps_complete_original_program():
    source, corpus, frontend, candidate = decoded()
    modified=oracle.preview(corpus,candidate)
    assert modified.count('Linked(parent)')==2  # old action plus one extra capture
    assert modified.count('item.present(')==2
    assert modified.count('owner.queue.remove(parent);')==1
    assert modified.count('owner.queue.commit();')==1
    assert modified.count('expect(owner.contains(item)).toBe(false);')==1
    assert modified.count('expect(owner.contains(parent)).toBe(false);')==1
    assert modified.index('const _contractObservation_')>modified.index('owner.queue.remove(parent)')
    assert modified.index('_before = item.present')<modified.index('owner.queue.commit()')
    assert modified.index('_after = item.present')>modified.index('owner.queue.commit()')
    assert '✓' in modified
    assert candidate['source_provenance']['modified_test_utf8_sha256']==core._hash(modified)
    artifact=emit(corpus,[candidate]);assert not artifact['unsupported'],artifact
    assert not Source(source.path,artifact['files'][source.path],'typescript').root.has_error


def test_static_relation_does_not_claim_purity_or_admission():
    _,corpus,frontend,prep,proposal=prepared()
    assert all(d['purity'].startswith('unknown') for h in prep['catalog']['hosts'] for d in h['argument_donors'])
    result=core.decide(corpus,frontend,prep,json.dumps({'observations':[proposal]}))
    assert result['alarm_eligible'] is False
    assert result['candidates'][0]['observation_hypothesis']['semantic_conditions_proved'] is False


def test_fresh_review_has_actual_whole_test_and_four_independent_premises():
    _,corpus,frontend,candidate=decoded()
    result=gate.prepare(corpus,frontend,candidate,ISSUE)
    assert result['request'],result
    request=result['request'];payload=json.loads(request['prompt'])
    assert payload['modified_test']==oracle.preview(corpus,candidate)
    assert set(gate.EXTRA_CHECKS)<=set(request['check_ids'])
    assert 'one plain identifier' not in request['system']  # not the generation prompt
    changed=copy.deepcopy(request);p=json.loads(changed['prompt']);p['checks'].pop('OBSERVER_READS');changed['prompt']=json.dumps(p)
    assert gate.decide(changed, {})['status']=='unknown'


@pytest.mark.parametrize('bad', ['present(); owner.destroy(); //','a.b','x[0]','constructor','__proto__'])
def test_model_cannot_supply_code_or_special_property(bad):
    _,c,f,p,row=prepared();row['method']=bad
    result=core.decide(c,f,p,json.dumps({'observations':[row]}))
    assert not result['candidates']


@pytest.mark.parametrize('field,value', [('host_alias','H999'),('receiver_alias','R999'),('argument_aliases',['A999']),('scalar_kind','object'),('issue_quote','invented public contract')])
def test_response_must_bind_shown_objects_arguments_and_exact_public_quote(field,value):
    _,c,f,p,row=prepared();row[field]=value
    assert not core.decide(c,f,p,json.dumps({'observations':[row]}))['candidates']


def test_incomplete_duplicate_or_free_code_responses_abstain():
    _,c,f,p,row=prepared()
    assert core.decide(c,f,p,json.dumps({'observations':[row]}),finish_reason='length')['status']=='unknown'
    assert core.decide(c,f,p,'{"observations":[],"observations":[]}')['status']=='unknown'
    row['code']='injected()'
    assert not core.decide(c,f,p,json.dumps({'observations':[row]}))['candidates']


def test_duplicate_executable_observation_does_not_gain_a_rank_by_changing_quote():
    _,c,f,p,row=prepared();second=dict(row,issue_quote=ISSUE.split('. ')[1]+'.')
    result=core.decide(c,f,p,json.dumps({'observations':[row,second]}))
    assert len(result['candidates'])==1
    assert result['rejected'][0]['response_index']==2


@pytest.mark.parametrize('extra', ['const alias = item;', 'item.present = other;', 'item = parent;',
    'unknown(item);','const later = () => item.present();','await unrelated();'])
def test_unknown_receiver_alias_rebinding_capture_and_async_are_excluded(extra):
    _,c,f=fixture(CODE.replace('    owner.queue.commit();','    '+extra+'\n    owner.queue.commit();'))
    hosts=core.catalog(c,f)['hosts']
    assert not any(any(r['name']=='item' for r in h['receivers']) for h in hosts)


def test_assertion_values_and_future_bindings_are_not_argument_donors():
    code=CODE.replace('    owner.queue.commit();', '    expect(item.present("oracle-only")).toBe(true);\n    owner.queue.commit();\n    const later = Linked(parent);')
    _,c,f=fixture(code);host=core.catalog(c,f)['hosts'][0]
    assert all(d['expression']['text'] not in {'"oracle-only"','later'} for d in host['argument_donors'])


def test_nested_calls_and_effectful_expression_shapes_are_not_donors():
    code=CODE.replace('Linked(parent)', 'Linked(transform(parent))')
    _,c,f=fixture(code);host=core.catalog(c,f)['hosts'][0]
    assert not any(d['expression']['text']=='Linked(transform(parent))' for d in host['argument_donors'])
    code=CODE.replace('Linked(parent)', 'Linked(++parent)')
    _,c,f=fixture(code);hosts=core.catalog(c,f)['hosts']
    assert not any(d['expression']['text']=='Linked(++parent)' for h in hosts for d in h['argument_donors'])


def test_source_and_frontend_receipts_cannot_drift():
    _,c,f,p,row=prepared();c=copy.deepcopy(c);path=next(iter(c['sources']));c['sources'][path]['code']+='\n'
    with pytest.raises(ValueError,match='source_snapshot_changed'):
        core.decide(c,f,p,json.dumps({'observations':[row]}))
    with pytest.raises(ValueError,match='frontend_source_mismatch'):
        core.catalog(c,f)


def test_budget_omits_complete_context_without_truncation_and_cannot_select_omitted_host():
    _,c,f=fixture();p=core.prepare(c,f,ISSUE,max_prompt_bytes=100)
    assert p['request'] is None and p['omitted'] and p['truncated'] is False


def test_repository_origin_and_language_limits():
    _,c,f=fixture(origin='history');assert not core.catalog(c,f)['hosts']
    c['language']='python';assert core.catalog(c,f)['status']=='language_unsupported'


def test_names_are_not_api_or_case_whitelists_and_expect_alias_is_resolved():
    code=CODE.replace('expect, it','expect as verify, it').replace('expect(', 'verify(')
    code=code.replace('Linked','Ticket').replace('parent','rootObject').replace('item','leaf').replace('commit','publish')
    _,c,f=fixture(code);p=core.prepare(c,f,ISSUE);assert p['request']
    host=json.loads(p['request']['prompt'])['hosts'][0]
    assert host['expect_callee']=='verify'
    row=dict(host_alias=host['host_alias'],receiver_alias=next(r['alias'] for r in host['receivers'] if r['name']=='leaf'),
        method='checkMembership',argument_aliases=[next(d['alias'] for d in host['argument_donors'] if d['expression']['text']=='Ticket(rootObject)')],
        scalar_kind='boolean',issue_quote=ISSUE.split('. ')[0]+'.')
    candidate=core.decide(c,f,p,json.dumps({'observations':[row]}))['candidates'][0]
    assert 'verify(_contractObservation_' in oracle.preview(c,candidate)
