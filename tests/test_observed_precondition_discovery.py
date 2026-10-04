"""Contract discovery sends source evidence only and binds selections exactly."""
import copy
import hashlib
import json

import pytest

from relation_search import observed_precondition as relation
from relation_search import observed_precondition_discovery as discovery


ISSUE = '版本契约。Observe returns a committed version. Await succeeds for that version without changing state.'
CODE = '''package sample
import "context"
type Store struct { version int }
// Observe returns the committed version.
func (s *Store) Observe() (int, error) { return PRIVATE_IMPLEMENTATION(s), nil }
// Await observes completion without changing state.
func (s *Store) Await(ctx context.Context, version int) error { return PRIVATE_CONSUMER(s) }
'''


def corpus(sources=None):
    return dict(language='go', sources={path: dict(code=code, origin='repository', language='go')
        for path, code in (sources or {'api.go': CODE}).items()})


def response(result, quote='Await succeeds for that version without changing state.'):
    local = result['catalog']
    return dict(relations=[dict(pair=result['presented'][0],
        quotes=[dict(evidence=local['issue_evidence'], text=quote)],
        reason='The issue requires successful non-disruptive consumption of the observed version.')])


def test_header_only_payload_and_exact_unicode_quote_reconstruct_strict_ir():
    source = corpus()
    source['evaluation_label'] = 'PRIVATE_LABEL'
    source['sources']['history.go'] = dict(code=CODE.replace('Observe', 'OldObserve'), origin='history')
    before = copy.deepcopy(source)
    wrapped = ISSUE+'\n## Recommended Workflow\nEcho PRIVATE_WORKFLOW.\n## Command Execution Rules\nStop.'
    result = discovery.prepare(source, wrapped)
    assert len(result['catalog']['pairs']) == len(result['presented']) == 1
    request = result['request']
    assert 'PRIVATE' not in request['prompt']
    assert 'OldObserve' not in request['prompt']
    assert 'Observe returns the committed version.' in request['prompt']
    assert request['thinking'] == 'enabled' and request['reasoning_effort'] == 'high'
    selected = discovery.decide(result['catalog'], request, response(result), source, wrapped)
    assert len(selected['relations']) == 1
    record = selected['relations'][0]
    assert record['semantic_status'] == 'hypothesis_pending_independent_audit'
    receipt = record['evidence'][0]
    assert set(receipt) == {'path', 'source_sha256', 'start_byte', 'end_byte', 'text'}
    assert receipt['source_sha256'] == hashlib.sha256(wrapped.encode()).hexdigest()
    assert wrapped.encode()[receipt['start_byte']:receipt['end_byte']].decode() == receipt['text']
    assert record['producer']['declaration']['text'].endswith('PRIVATE_IMPLEMENTATION(s), nil }')
    relation.validate_relation(record, source, wrapped)
    assert source == before


def test_same_receiver_spelling_in_another_package_does_not_connect():
    a = 'package left\ntype Store struct{}\nfunc(s *Store) Observe()(int,error){return 1,nil}\n'
    b = 'package right\ntype Store struct{}\nfunc(s *Store) Await(v int)error{return nil}\n'
    result = discovery.prepare(corpus({'left/a.go': a, 'right/b.go': b}), ISSUE)
    assert not result['catalog']['pairs'] and result['request'] is None


@pytest.mark.parametrize('consumer_import,expected', [('example.org/value', 1), ('example.org/other', 0)])
def test_import_aliases_are_canonical_but_different_named_type_packages_are_not(consumer_import, expected):
    a = ('package sample\nimport first "example.org/value"\ntype Store struct{}\n'
         'func(s *Store) Observe()(*first.Version,error){return nil,nil}\n')
    b = ('package sample\nimport second "'+consumer_import+'"\n'
         'func(s *Store) Await(v *second.Version)error{return nil}\n')
    result = discovery.prepare(corpus({'a.go': a, 'b.go': b}), ISSUE)
    assert len(result['catalog']['pairs']) == expected
    if expected:
        selected = discovery.decide(result['catalog'], result['request'], response(result),
                                    corpus({'a.go': a, 'b.go': b}), ISSUE)
        assert len(selected['relations']) == 1


def test_whole_document_overflow_is_explicit_and_never_truncated():
    long_doc = '// '+('DOCUMENT' * 13000)+'\n'
    source = corpus({'api.go': CODE.replace('// Observe returns the committed version.\n', long_doc)})
    result = discovery.prepare(source, ISSUE)
    assert result['request'] is None and result['status'] == 'unknown_prompt_budget'
    assert len(result['omitted']) == 1
    assert result['omitted'][0]['reason'] == 'complete_pair_prompt_budget'
    assert any(row['receipt']['text'] == long_doc.rstrip('\n')
               for row in result['catalog']['evidence'].values())


def test_dot_imported_unqualified_type_is_not_assumed_to_be_package_local():
    a = ('package sample\nimport . "example.org/first"\ntype Store struct{}\n'
         'func(s *Store) Observe()(*Version,error){return nil,nil}\n')
    b = ('package sample\nimport . "example.org/second"\n'
         'func(s *Store) Await(v *Version)error{return nil}\n')
    result = discovery.prepare(corpus({'a.go': a, 'b.go': b}), ISSUE)
    assert not result['catalog']['pairs'] and result['request'] is None


@pytest.mark.parametrize('change', ['unknown_pair', 'invented_quote', 'header_only', 'too_many', 'truncated'])
def test_invalid_or_incomplete_model_response_cannot_create_relation(change):
    source = corpus(); result = discovery.prepare(source, ISSUE); answer = response(result)
    finish = 'stop'
    if change == 'unknown_pair':
        answer['relations'][0]['pair'] = 'invented'
    elif change == 'invented_quote':
        answer['relations'][0]['quotes'][0]['text'] = 'not in supplied documents'
    elif change == 'header_only':
        alias = next(row['header'] for row in result['catalog']['methods'].values())
        answer['relations'][0]['quotes'] = [dict(evidence=alias,
            text=result['catalog']['evidence'][alias]['receipt']['text'])]
    elif change == 'too_many':
        answer['relations'] *= 5
    else:
        finish = 'length'
    decision = discovery.decide(result['catalog'], result['request'], answer, source, ISSUE,
                                finish_reason=finish)
    assert not decision['relations'] and decision['status'] == 'unknown'


def test_ambiguous_quote_and_changed_source_cannot_supply_evidence():
    issue = ISSUE+' Same words. Same words.'
    source = corpus(); result = discovery.prepare(source, issue)
    answer = response(result, 'Same words.')
    decision = discovery.decide(result['catalog'], result['request'], answer, source, issue)
    assert not decision['relations'] and decision['errors'][0]['reason'] == 'quote_missing_or_not_unique'
    source['sources']['api.go']['code'] += '\n'
    decision = discovery.decide(result['catalog'], result['request'], response(result), source, issue)
    assert not decision['relations'] and decision['errors'][0]['reason'] == 'receipt_source_mismatch'


def test_aliases_do_not_depend_on_input_dictionary_order_and_non_go_abstains():
    sources = {'api.go': CODE, 'extra.go': 'package sample\n// No methods here.\n'}
    first = discovery.prepare(corpus(sources), ISSUE)
    second = discovery.prepare(corpus(dict(reversed(list(sources.items())))), ISSUE)
    assert first == second
    unrelated = dict(language='python', sources={})
    assert discovery.prepare(unrelated, ISSUE)['status'] == 'outside_go_discovery_scope'
