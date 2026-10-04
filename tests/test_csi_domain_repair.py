import ast
import copy
import json
from pathlib import Path

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search import csi_domain_repair as repair
from relation_search import csi_domain_repair_review as review
from relation_search.csi_repair_transport import verify as verify_emission


def bound(code, value, *, helper=False):
    tree = ast.parse(code)
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call) and
                ((isinstance(n.func, ast.Name) and n.func.id == 'keys') if helper else
                 (isinstance(n.func, ast.Attribute) and n.func.attr == 'feed')))
    def receipt(node):
        a, b = repair._span(code, node)
        return dict(path='<modified_test>', source_sha256=repair.sha(code), start_byte=a, end_byte=b,
                    text=code.encode()[a:b].decode())
    check = dict(value=value, call_receipt=receipt(call), binding_chain=[])
    if helper:
        check['call_receipt'] = dict(path='helpers.py', source_sha256='helper_hash', start_byte=0, end_byte=1, text='x')
        check['binding_chain'] = [dict(arguments=[dict(formal='data', actual=receipt(call.args[-1]))])]
    return dict(modified_test_sha256=repair.sha(code), checks=[check])


def proposal(code, value, *, helper=False):
    payload = dict(language='python', modified_test=code)
    return repair.opportunities(payload, bound(code, value, helper=helper))


@pytest.mark.parametrize('value,expected', [('\x1b[65;4u', '\x1b[97;4u'), ('\x1b[90;2;90u', '\x1b[122;2;90u'),
                                           ('\x1b[65:65:97;4:3;97u', '\x1b[97:65:97;4:3;97u')])
def test_only_uppercase_primary_changes_and_all_other_fields_remain(value, expected):
    code = f'def test(parser):\n    [event] = parser.feed({value!r})\n    assert event.key == "same oracle"\n'
    output = proposal(code, value)['opportunities'][0]
    assert output['value_after'] == expected
    assert output['repaired_test'].endswith('assert event.key == "same oracle"\n')
    assert output['repaired_test'].replace(output['literal_after'], output['literal_before']) == code


@pytest.mark.parametrize('value', ['\x1b[65;1u', '\x1b[65;3u', '\x1b[65;0u', '\x1b[65;258u',
                                 '\x1b[97:65;2u', '\x1b[65;2~', '\x1b[913;2u'])
def test_no_inferred_shift_no_alternate_repair_no_suffix_or_unicode_expansion(value):
    code = f'def test(parser):\n    [event] = parser.feed({value!r})\n'
    assert proposal(code, value)['opportunities'] == []


def test_equal_expected_string_is_not_an_input_binding():
    value = '\x1b[65;4u'
    code = f'def test(parser):\n    [event] = parser.feed({value!r})\n    assert event.key == {value!r}\n'
    output = proposal(code, value)['opportunities'][0]
    assert output['repaired_test'].count('65;4u') == 1
    assert output['repaired_test'].count('97;4u') == 1


def test_exact_helper_argument_binding_is_supported_without_protocol_claim():
    value = '\x1b[65;4;97u'
    code = f'def test(parser):\n    [event] = keys(parser, {value!r})\n    assert event.character is None\n'
    gate = bound(code, value, helper=True)
    gate.update(decision='unknown', status='input_domain_or_binding_unproved')
    result = repair.opportunities(dict(language='python', modified_test=code), gate)
    assert len(result['opportunities']) == 1
    assert result['opportunities'][0]['semantic_status'].startswith('hypothesis')


def test_stale_or_forged_source_receipt_fails_closed():
    value = '\x1b[65;4u'
    code = f'def test(parser):\n    parser.feed({value!r})\n'
    gate = bound(code, value)
    gate['checks'][0]['call_receipt']['text'] = 'different input'
    with pytest.raises(ValueError, match='receipt differs'):
        repair.opportunities(dict(language='python', modified_test=code), gate)


def test_nonliteral_input_keeps_unknown_instead_of_editing_an_unbound_example():
    value = '\x1b[65;4u'
    code = f'def test(parser):\n    sample = {value!r}\n    parser.feed(sample)\n'
    result = proposal(code, value)
    assert not result['opportunities'] and result['unknowns']


def construction():
    source = 'def test_key(parser):\n    [event] = parser.feed("\\x1b[97;4u")\n    assert event.key == "alt+shift+a"\n    assert event.character is None\n'
    frontend = extract_frontend([Source('test_api.py', source, 'python', 'repository')])
    corpus = to_emitter_corpus(frontend)
    identifier = next(iter(corpus['tests']))
    before, after = '"\\x1b[97;4u"', '"\\x1b[65;4;97u"'
    a = source.index(before)
    candidate = dict(id='historical', language='python', kind='input_edit', base_test_id=identifier,
                     imports=[], source_test_ids=[identifier], edits=[dict(span=dict(path='test_api.py', start_byte=a,
                     end_byte=a+len(before)), before=before, after=after)])
    modified = repair.preview(corpus, candidate)
    payload = dict(language='python', original_test=source.rstrip('\n'), modified_test=modified)
    opportunity = proposal(modified, '\x1b[65;4;97u')['opportunities'][0]
    return corpus, candidate, payload, opportunity


def test_composition_preserves_all_prior_fields_full_oracle_and_original_controls():
    corpus, prior, payload, opportunity = construction()
    before = copy.deepcopy(prior)
    candidate = repair.construct(corpus, prior, payload, opportunity)
    assert repair.preview(corpus, candidate) == opportunity['repaired_test']
    assert candidate['source_test_ids'] == prior['source_test_ids']
    assert candidate['edits'][0]['before'] == prior['edits'][0]['before']
    assert ';4;97u' in candidate['edits'][0]['after']
    assert prior == before
    assert 'runtime_probes' not in candidate and 'program_edits' not in candidate


def transport(tmp_path, corpus, candidate, code):
    group = tmp_path/'emitted/group_000'
    group.mkdir(parents=True)
    source = tmp_path/'emitted_test.py'
    source.write_text(code)
    def put(path, value):
        path.write_text(json.dumps(value))
    put(group.parent/'accepted.json', [candidate])
    put(group/'manifest.json', dict(obligations=[dict(candidate_id=candidate['id'], path='test_api.py', test_name='test_generated')],
        mounts=[dict(target='stage.py', source=str(source), sha256=repair.sha(code))]))
    put(group/'phase_plan.json', dict(phases=[dict(role='generated', files=[dict(target='test_api.py', staged='stage.py')])]))
    return verify_emission(corpus, candidate, group)


def test_complete_transport_accepts_only_name_change_and_rejects_lost_later_assertion(tmp_path):
    corpus, prior, payload, opportunity = construction()
    candidate = repair.construct(corpus, prior, payload, opportunity)
    code = opportunity['repaired_test'].replace('def test_key(', 'def test_generated(')
    assert transport(tmp_path/'good', corpus, candidate, code)['status'] == 'matched'
    shortened = '\n'.join(code.splitlines()[:-1])
    assert transport(tmp_path/'short', corpus, candidate, shortened)['reason'] == 'complete_test_ast_changed'
    changed = code.replace('97;4;97u', '65;4;97u')
    assert transport(tmp_path/'wrong', corpus, candidate, changed)['reason'] == 'complete_python_values_or_test_changed'


def review_request(state='unknown', outside=False):
    payload = dict(original_test='old complete test', modified_test='repaired complete test')
    guard = dict(decision=state, status='bounded_input_domain_checked' if state == 'allow' else 'input_domain_or_binding_unproved',
                 allow_prior_gate=state == 'allow', checks=[dict(value='packet', positive_key_result=True,
                     decision='allow', domain_binding=dict(source='public doc'))],
                 **{key+'_sha256': repair.sha(value) for key, value in payload.items()})
    if outside:
        guard.update(status='outside_registered_scope', checks=[])
    metadata = dict(guard=guard, repaired_value='packet')
    return dict(prompt=json.dumps(payload), csi_repair_domain=metadata,
                csi_repair_domain_sha256=repair.canonical_sha(metadata))


@pytest.mark.parametrize('state,outside,allowed', [('unknown', False, False), ('allow', True, False), ('allow', False, True)])
def test_fresh_model_support_cannot_override_unproved_source_domain(monkeypatch, state, outside, allowed):
    monkeypatch.setattr(review.whole_test, 'decide', lambda *a, **k: dict(status='semantic_supported', alarm_eligible=True))
    result = review.decide(review_request(state, outside), '{}')
    assert result['full_test_review']['status'] == 'semantic_supported'
    assert result['source_domain_allowed'] is allowed
    assert result['alarm_eligible'] is allowed
    assert result['status'] == ('semantic_supported' if allowed else 'unknown')
