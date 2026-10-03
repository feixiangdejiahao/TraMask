import copy

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search.transitive_contract_call_priority import Analyzer, issue_names, select
from tests.test_edited_contract_call_priority import fixture


def check(code, actual, before='1', after='2', issue='Change `parse()`.', **kwargs):
    corpus, frontend, candidate = fixture(code, actual, before, after, **kwargs)
    return Analyzer(corpus, frontend, issue).evidence(candidate)


def test_transitive_argument_reach_crosses_multiple_local_assignments():
    code = '''from toolkit import parse
def test_x():
    initial = 1
    intermediate = initial
    final = intermediate
    result = parse(final)
    assert result == 4
'''
    result = check(code, 'result')
    assert result['feature'], result
    assert result['witnesses'][0]['input_basis'] == 'transitive_local_argument_may_reach'


@pytest.mark.parametrize('setup', [
    '    if condition:\n        value = initial\n',
    '    value = initial\n    value = 7\n',
])
def test_conditional_or_overwritten_chain_does_not_borrow_an_old_input(setup):
    code = ('from toolkit import parse\ndef test_x():\n    initial = 1\n' + setup
            + '    result = parse(value)\n    assert result == 4\n')
    assert not check(code, 'result')['feature']


def test_local_generator_body_reaches_argument():
    code = '''from toolkit import parse
def test_x():
    def chunks():
        yield 1
    result = parse(chunks())
    assert result == 4
'''
    assert check(code, 'result')['feature']
    shadowed = code.replace('    result =', '    chunks = other\n    result =')
    assert not check(shadowed, 'result')['feature']


def class_fixture(argument='1', constructor='Box', helper=''):
    library = '''class Box:
    def __init__(self, value):
        self.value = value
    def consume(self):
        return self.value
'''
    code = '''from boxlib import Box
def test_x():
''' + helper + f'''    box = {constructor}({argument})
    result = box.consume()
    assert result == 4
'''
    frontend = extract_frontend([Source('boxlib.py', library, 'python'),
                                 Source('test_sample.py', code, 'python')])
    corpus = to_emitter_corpus(frontend)
    base = next(iter(corpus['tests']))
    begin = code.index('1', code.index('def test_x'))
    candidate = dict(id='edit', base_test_id=base, imports=[], kind='input', edits=[dict(
        before='1', after='2', span=dict(path='test_sample.py', start_byte=begin, end_byte=begin+1))])
    return corpus, frontend, candidate


def test_constructor_argument_edit_keeps_resolved_receiver_class():
    corpus, frontend, candidate = class_fixture()
    result = Analyzer(corpus, frontend, 'Change `Box.consume`.').evidence(candidate)
    assert result['feature'], result
    assert result['witnesses'][0]['input_basis'] == 'receiver_value_may_reach'
    assert result['witnesses'][0]['resolution'] == 'unchanged_class_constructor_with_argument_only_edits'


def test_generator_edit_reaches_receiver_then_observed_call():
    corpus, frontend, candidate = class_fixture('chunks()', helper='    def chunks():\n        yield 1\n')
    result = Analyzer(corpus, frontend, 'Change `Box.consume`.').evidence(candidate)
    assert result['feature'], result


def test_constructor_replacement_cannot_reuse_receiver_resolution():
    corpus, frontend, candidate = class_fixture()
    code = corpus['sources']['test_sample.py']['code']
    at = code.index('Box(1)', code.index('def test_x'))
    candidate['edits'] = [dict(before='Box(1)', after='other(1)',
        span=dict(path='test_sample.py', start_byte=at, end_byte=at+6))]
    assert not Analyzer(corpus, frontend, 'Change `Box.consume`.').evidence(candidate)['feature']


def test_prose_api_names_require_exact_existing_distinctive_identifiers():
    functions = [dict(name=name, production=True) for name in ['WaitForWrite', 'try_parse', 'read', 'NeverCalled']]
    assert issue_names('WaitForWrite and try_parse wait. read can read data.', functions) == ['WaitForWrite', 'try_parse']
    assert issue_names('waitforwrite and try_parser', functions) == []


def test_reach_budget_is_explicit_and_never_becomes_priority():
    lines = ['    a0 = 1'] + [f'    a{i} = a{i-1}' for i in range(1, 18)]
    code = 'from toolkit import parse\ndef test_x():\n' + '\n'.join(lines) + '\n    result = parse(a17)\n    assert result == 4\n'
    result = check(code, 'result')
    assert not result['feature'] and 'local_reach_budget' in result['unknowns']


def test_candidate_truth_fields_do_not_affect_frozen_ranking():
    corpus, frontend, candidate = class_fixture()
    original = copy.deepcopy((corpus, frontend, candidate))
    result = select(corpus, frontend, [candidate], 'Change `Box.consume`.', budget=1)
    annotated = dict(candidate, evaluation={'valid': False}, native_failure='anything')
    assert result == select(corpus, frontend, [annotated], 'Change `Box.consume`.', budget=1) | {'selected': [candidate]}
    assert (corpus, frontend, candidate) == original
