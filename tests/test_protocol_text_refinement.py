import copy
import json

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search import protocol_text_refinement as relation
from relation_search import protocol_text_refinement_review as review
from relation_search import oracle
from relation_search import csi_repair_transport


def fixture(*, doc='Decode Kitty keyboard protocol CSI into key events.', body=None, decorators='', extras=''):
    body=body or '[event] = parser.feed("\\x1b[97;2:2;65u")\nassert event.character == "A"\nassert event.phase == "repeat"\nassert event.modifiers == ("shift",)'
    code='import pytest\nfrom wire import Reader\n@pytest.fixture\ndef parser():\n    return Reader()\n'+extras+'\n'+decorators+'def test_text(parser):\n'+'\n'.join('    '+line for line in body.splitlines())+'\n'
    api='class Reader:\n    def feed(self, data):\n        """'+doc+'"""\n        return []\n'
    frontend=extract_frontend([Source('test_wire.py',code,'python','repository'),Source('wire.py',api,'python','repository')])
    corpus=to_emitter_corpus(frontend)
    return corpus,frontend,'Support the Kitty keyboard protocol. Preserve text and phase/modifier metadata.'


def choose(prepared, field='phase', slots=None):
    return json.dumps({'selections':[dict(slot=s['slot'],projection_ids=[p['id'] for p in s['host']['projections'] if p['field']==field]) for s in prepared['slots'] if slots is None or s['slot'] in slots]})


def test_three_fixed_domains_keep_raw_nontext_fields_and_original_complete_test():
    corpus,frontend,issue=fixture();prepared=relation.prepare(corpus,frontend,issue)
    assert prepared['request']['reasoning_effort']=='low' and prepared['request']['max_tokens']==8192
    assert [s['refinement']['transform'] for s in prepared['slots']]==list(relation.TRANSFORMS)
    assert [s['refinement']['packet']['text'] for s in prepared['slots']]==[['65','65'],['65','32'],['65','769']]
    decoded=relation.decide(corpus,frontend,prepared,choose(prepared))
    assert [c['order'] for c in decoded['candidates']]==[[1],[2],[3]]
    for candidate in decoded['candidates']:
        before=oracle.text(corpus,corpus['tests'][candidate['base_test_id']]['span']);after=oracle.preview(corpus,candidate)
        assert after.startswith(before+'\n')
        added=after[len(before):]
        assert '.phase == \'repeat\'' in added and '.character' not in added and '.modifiers' not in added
        assert candidate['source_provenance']['source_file']['origin']=='repository'
        assert len(candidate['protocol_text_refinement']['selected_projections'])==1
        assert candidate['protocol_text_refinement']['old_source_guard']['decision']=='allow'


def test_missing_keyword_stays_unknown_with_source_association_not_admission():
    corpus,frontend,issue=fixture(doc='Parse a complete input packet.')
    prepared=relation.prepare(corpus,frontend,issue)
    assert len(prepared['slots'])==3
    host=prepared['slots'][0]['host']
    assert host['old_source_guard']['decision']=='unknown'
    assert host['receiver_evidence']['identity']=='wire.Reader'
    assert relation.decide(corpus,frontend,prepared,choose(prepared))['alarm_eligible'] is False


def test_module_import_receipt_and_fresh_name_do_not_shadow_existing_names():
    corpus,_,issue=fixture(extras='def other(_protocol_text_observation):\n    return None\n')
    rows=corpus['sources'];code=rows['test_wire.py']['code'].replace('from wire import Reader','import wire as codec').replace('return Reader()','return codec.Reader()')
    frontend=extract_frontend([Source('test_wire.py',code,'python','repository'),Source('wire.py',rows['wire.py']['code'],'python','repository')]);corpus=to_emitter_corpus(frontend)
    prepared=relation.prepare(corpus,frontend,issue)
    assert prepared['slots'][0]['host']['receiver_evidence']['imports'][0]['text']=='import wire as codec'
    candidate=relation.decide(corpus,frontend,prepared,choose(prepared))['candidates'][0]
    assert '[_protocol_text_observation_]' in oracle.preview(corpus,candidate)


def test_overwritten_import_cannot_supply_receiver_binding():
    corpus,_,issue=fixture();rows=corpus['sources']
    code=rows['test_wire.py']['code'].replace('from wire import Reader','from wire import Reader\nReader = other')
    frontend=extract_frontend([Source('test_wire.py',code,'python','repository'),Source('wire.py',rows['wire.py']['code'],'python','repository')]);corpus=to_emitter_corpus(frontend)
    prepared=relation.prepare(corpus,frontend,issue)
    assert not prepared['slots'] and prepared['host_omissions'][0]['reason']=='fixture_constructor_binding_unresolved'


@pytest.mark.parametrize('message',['side_effect()', '(changed := 1)'])
def test_assertion_message_effect_is_preserved_but_never_transported(message):
    corpus,frontend,issue=fixture(body='[event] = parser.feed("\\x1b[97;2:2;65u")\n'
        'assert event.phase == "repeat", '+message+'\nassert event.modifiers == ("shift",)')
    prepared=relation.prepare(corpus,frontend,issue)
    assert [p['field'] for p in prepared['slots'][0]['host']['projections']]==['modifiers']
    candidate=relation.decide(corpus,frontend,prepared,choose(prepared,field='modifiers'))['candidates'][0]
    full=oracle.preview(corpus,candidate)
    assert full.count(message)==1 and full.startswith(prepared['slots'][0]['host']['original_test'])


@pytest.mark.parametrize('body,extras,reason',[
    ('[event] = parser.feed("\\x1b[65;2;65u")\nassert event.phase == "press"','', 'original_packet_domain_unproved'),
    ('[event] = parser.feed("\\x1b[97;2;10u")\nassert event.phase == "press"','', 'original_packet_domain_unproved'),
    ('[event] = other.feed("\\x1b[97;2;65u")\nassert event.phase == "press"','', 'receiver_fixture_binding_unresolved'),
    ('[event] = list(parser.feed("\\x1b[97;2;65u"))\nassert event.phase == "press"','', 'indirect_wrapped_or_multiple_consumer'),
    ('[event] = collect(parser,"\\x1b[97;2;65u")\nassert event.phase == "press"','def collect(p,s):\n    result=list(p.feed(s))\n    list(p.feed(""))\n    return result\n','helper_closes_receiver'),
    ('[event] = parser.feed("\\x1b[97;2;65u")\nparser.close()\nassert event.phase == "press"','', 'host_setup_or_receiver_state'),
    ('[event] = parser.feed("\\x1b[97;2;65u")\nassert mutate(parser)\nassert event.phase == "press"','', 'receiver_used_after_original_call'),
])
def test_bad_input_binding_wrapper_close_or_state_abstains(body,extras,reason):
    corpus,frontend,issue=fixture(body=body,extras=extras)
    prepared=relation.prepare(corpus,frontend,issue)
    assert not prepared['slots'] and any(reason in x['reason'] for x in prepared['host_omissions'])


def test_parameterized_host_is_not_silently_replaced_by_one_good_row():
    corpus,frontend,issue=fixture(decorators='@pytest.mark.parametrize("unused",[1,2])\n')
    prepared=relation.prepare(corpus,frontend,issue)
    assert not prepared['slots'] and 'parameterized_or_marked' in prepared['host_omissions'][0]['reason']


@pytest.mark.parametrize('response',[
    '{"selections":[],"code":"anything"}', '{"selections":[],"selections":[]}',
    '{"selections":[{"slot":"C9","projection_ids":["O1"]}]}',
    '{"selections":[{"slot":"C1","projection_ids":["O99"]}]}',
    '{"selections":[{"slot":"C1","projection_ids":["O1","O1"]}]}',
])
def test_selection_cannot_supply_code_unknown_ids_or_duplicate_records(response):
    corpus,frontend,issue=fixture();prepared=relation.prepare(corpus,frontend,issue)
    assert relation.decide(corpus,frontend,prepared,response)['status']=='unknown'


def test_empty_and_partial_selection_keep_frozen_rank_without_refill():
    corpus,frontend,issue=fixture();prepared=relation.prepare(corpus,frontend,issue)
    result=relation.decide(corpus,frontend,prepared,choose(prepared,slots={'C3'}))
    assert [c['order'] for c in result['candidates']]==[[3]]
    assert [r['rank'] for r in result['rejected']]==[1,2]
    assert not relation.decide(corpus,frontend,prepared,choose(prepared),finish_reason='length')['candidates']


def test_complete_context_over_budget_withholds_whole_slots(monkeypatch):
    corpus,frontend,issue=fixture();monkeypatch.setattr(relation,'MAX_PROMPT_BYTES',32)
    prepared=relation.prepare(corpus,frontend,issue)
    assert prepared['request'] is None and not prepared['slots']
    assert len(prepared['slot_ledger'])==3 and all(r['status']=='whole_context_prompt_budget' for r in prepared['slot_ledger'])


def test_full_review_requires_old_q_and_every_relation_obligation():
    corpus,frontend,issue=fixture(doc='Parse packets.')
    prepared=relation.prepare(corpus,frontend,issue)
    candidate=relation.decide(corpus,frontend,prepared,choose(prepared))['candidates'][0]
    reviewed=review.prepare(corpus,frontend,candidate,issue)
    request=reviewed['request'];payload=json.loads(request['prompt'])
    assert set(review.OBLIGATIONS).issubset(payload['checks'])
    assert '.character == "A"' in payload['modified_test']
    assert payload['protocol_text_refinement']['old_source_guard']['decision']=='unknown'
    response=dict(basis='fixture contract',judgments={k:'supported' for k in request['check_ids']})
    assert review.decide(request,json.dumps(response))['status']=='semantic_supported'
    response['judgments']['R_DOMAIN']='unknown'
    assert review.decide(request,json.dumps(response))['status']=='unknown'
    response['judgments'].pop('R_DOMAIN')
    assert review.decide(request,json.dumps(response))['status']=='unknown'
    changed=copy.deepcopy(candidate);changed['protocol_text_refinement']['original_test_sha256']='bad'
    with pytest.raises(ValueError,match='Original complete test'):
        review.prepare(corpus,frontend,changed,issue)


def test_changed_source_is_rejected_before_selection_decode():
    corpus,frontend,issue=fixture();prepared=relation.prepare(corpus,frontend,issue)
    corpus['sources']['wire.py']['code']+='\n# changed\n'
    with pytest.raises(ValueError,match='source_changed'):
        relation.decide(corpus,frontend,prepared,choose(prepared))


def test_strict_transport_preserves_original_checks_and_followup_text(tmp_path):
    corpus,frontend,issue=fixture();prepared=relation.prepare(corpus,frontend,issue)
    candidate=relation.decide(corpus,frontend,prepared,choose(prepared))['candidates'][2]
    code=oracle.preview(corpus,candidate).replace('def test_text(', 'def test_generated(')
    def emitted(label,text):
        group=tmp_path/label/'emitted/group_000';group.mkdir(parents=True)
        source=tmp_path/label/'emitted.py';source.write_text(text)
        (group.parent/'accepted.json').write_text(json.dumps([candidate]))
        (group/'manifest.json').write_text(json.dumps(dict(obligations=[dict(candidate_id=candidate['id'],path='test_wire.py',test_name='test_generated')],mounts=[dict(target='stage.py',source=str(source),sha256=relation.sha(text))])))
        (group/'phase_plan.json').write_text(json.dumps(dict(phases=[dict(role='generated',files=[dict(target='test_wire.py',staged='stage.py')])])) )
        return csi_repair_transport.verify(corpus,candidate,group)
    assert emitted('correct',code)['status']=='matched'
    assert emitted('wrong_text',code.replace(':769u',':32u'))['status']=='mismatch'
    assert emitted('dropped_original',code.replace('    assert event.character == "A"\n',''))['status']=='mismatch'
