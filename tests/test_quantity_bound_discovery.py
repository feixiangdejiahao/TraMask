"""Quantity hypotheses retain exact source authority and the declared input domain."""
import copy
import hashlib
import json

import pytest

from relation_search import quantity_bound as relation
from relation_search import quantity_bound_discovery as discovery


ISSUE = '数量契约。Limit returns at most width visible cells for every string and positive width.'
CODE = '''package sample
// Limit returns no more than width visible cells.
func Limit(s string, width int) string { return PRIVATE_TRANSFORM(s, width) }
// Measure counts visible cells.
func Measure(s string) int { return PRIVATE_MEASURE(s) }
'''


def corpus(sources=None):
    return dict(language='go', tests={}, sources={path: dict(code=code, origin='repository', language='go')
        for path, code in (sources or {'api.go': CODE}).items()})


def response(result, quote='Limit returns at most width visible cells for every string and positive width.'):
    payload = json.loads(result['request']['prompt'])
    alias = next(key for key, value in payload['evidence'].items() if value['kind'] == 'issue')
    return dict(relations=[dict(pair=result['presented'][0], unit='visible cells',
        quotes=[dict(evidence=alias, text=quote)], reason='The public issue specifies this bound and input domain.')])


def test_public_headers_only_and_exact_quote_binding():
    source = corpus()
    source['evaluation_label'] = 'PRIVATE_LABEL'
    source['sources']['history.go'] = dict(code=CODE.replace('Limit', 'OldLimit'), origin='history')
    before = copy.deepcopy(source)
    result = discovery.prepare(source, ISSUE)
    assert len(result['presented']) == 1
    request = result['request']
    assert 'PRIVATE' not in request['prompt'] and 'OldLimit' not in request['prompt']
    assert 'Limit returns no more than width visible cells.' in request['prompt']
    assert 'will not constrain a string option' in request['system']
    decision = discovery.decide(result['catalog'], request, response(result), source, ISSUE)
    assert len(decision['relations']) == 1
    record = decision['relations'][0]
    assert record['unit'] == 'visible cells'
    assert record['semantic_status'] == 'hypothesis_pending_independent_audit'
    assert 'PRIVATE_TRANSFORM' in record['transform']['declaration']['text']
    receipt = record['evidence'][0]
    assert receipt['source_sha256'] == hashlib.sha256(ISSUE.encode()).hexdigest()
    assert ISSUE.encode()[receipt['start_byte']:receipt['end_byte']].decode() == receipt['text']
    relation.validate_relation(record, source, ISSUE)
    assert source == before


def test_whole_pair_overflow_does_not_truncate_contract():
    source = corpus({'api.go': CODE.replace('// Limit returns no more than width visible cells.',
                                           '// '+('LONG_DOCUMENT ' * 9000))})
    result = discovery.prepare(source, ISSUE)
    assert result['request'] is None and result['status'] == 'unknown_prompt_budget'
    assert len(result['omitted']) == 1
    assert result['omitted'][0]['reason'] == 'complete_pair_prompt_budget'


@pytest.mark.parametrize('change', ['unknown_pair', 'invented_quote', 'header_only', 'too_many',
                                    'truncated', 'empty_unit', 'extra_code'])
def test_unbound_or_incomplete_selections_remain_unknown(change):
    source = corpus(); result = discovery.prepare(source, ISSUE); answer = response(result)
    finish = 'stop'
    row = answer['relations'][0]
    if change == 'unknown_pair':
        row['pair'] = 'invented'
    elif change == 'invented_quote':
        row['quotes'][0]['text'] = 'not in supplied documents'
    elif change == 'header_only':
        payload = json.loads(result['request']['prompt'])
        alias, evidence = next((key, value) for key, value in payload['evidence'].items()
                               if value['kind'] == 'header')
        row['quotes'] = [dict(evidence=alias, text=evidence['text'])]
    elif change == 'too_many':
        answer['relations'] *= 5
    elif change == 'truncated':
        finish = 'length'
    elif change == 'empty_unit':
        row['unit'] = ' '
    else:
        row['code'] = 'untrusted generated code'
    decision = discovery.decide(result['catalog'], result['request'], answer, source, ISSUE,
                                finish_reason=finish)
    assert not decision['relations'] and decision['status'] == 'unknown'


def test_ambiguous_quote_and_changed_source_cannot_supply_authority():
    issue = ISSUE+' Same words. Same words.'
    source = corpus(); result = discovery.prepare(source, issue)
    decision = discovery.decide(result['catalog'], result['request'], response(result, 'Same words.'), source, issue)
    assert not decision['relations'] and decision['errors'][0]['reason'] == 'quote_missing_or_not_unique'
    source['sources']['api.go']['code'] += '\n'
    decision = discovery.decide(result['catalog'], result['request'], response(result), source, issue)
    assert not decision['relations']


def test_pair_and_request_identity_do_not_depend_on_dictionary_order():
    sources = {'api.go': CODE, 'other.go': 'package sample\n'}
    assert discovery.prepare(corpus(sources), ISSUE) == discovery.prepare(corpus(dict(reversed(list(sources.items())))), ISSUE)


def test_no_issue_or_no_pair_does_not_dispatch():
    assert discovery.prepare(corpus(), '')['request'] is None
    assert discovery.prepare(dict(language='python', sources={}, tests={}), ISSUE)['request'] is None
