"""Recover complete modified test occurrences after decorator byte edits."""
import copy

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search.compact_test_obligations import analyze, source_text


def fixture(code, replacements, *, owner=0):
    path = 'tests/test_decorators.py'
    frontend = extract_frontend([Source(path, code, 'python')])
    corpus = to_emitter_corpus(frontend)
    identifier = list(corpus['tests'])[owner]
    test = corpus['tests'][identifier]
    edits = []
    for before, after in replacements:
        start = code.encode().index(before.encode(), test['span']['start_byte'])
        edits.append(dict(span=dict(path=path, start_byte=start,
            end_byte=start+len(before.encode())), before=before, after=after, role='input'))
    candidate = dict(id='authored_decorator', base_test_id=identifier,
        edits=edits, imports=[], source_test_ids=[identifier])
    return corpus, frontend, candidate


def test_multiple_utf8_decorator_edits_and_body_edit_keep_every_assertion():
    code = '''import pytest
# A UTF-8 prefix: 猫
@pytest.mark.parametrize("first", ["猫猫"])
@pytest.mark.parametrize("second", ["a"])
def test_fields(first, second):
    observed = "old"
    assert first is not None
    assert second != "final"
    assert observed == "原值"
'''
    corpus, frontend, candidate = fixture(code,
        [('"猫猫"', 'None'), ('"a"', '"长字符串"'), ('"old"', '"new-long-value"')])
    before = copy.deepcopy((corpus, frontend, candidate))
    result = analyze(corpus, frontend, candidate)
    assert (corpus, frontend, candidate) == before
    assert 'root' in result
    checks = [source_text(result, row['at']) for row in result['obligations'].values()]
    assert checks == ['assert first is not None', 'assert second != "final"', 'assert observed == "原值"']
    complete = source_text(result, result['units'][result['root']]['at'])
    assert complete.startswith('@pytest.mark.parametrize("first", [None])')
    assert '@pytest.mark.parametrize("second", ["长字符串"])' in complete
    assert 'observed = "new-long-value"' in complete
    assert complete.endswith('assert observed == "原值"')
    assert not result['alarm_eligible']


@pytest.mark.parametrize('owner,expected,excluded', [
    (0, 'assert value == "module"', 'assert value == "method"'),
    (1, 'assert value == "method"', 'assert value == "module"'),
])
def test_identical_names_in_distinct_scopes_select_only_the_exact_occurrence(owner, expected, excluded):
    code = '''import pytest
@pytest.mark.parametrize("value", ["long"])
def test_same(value):
    assert value == "module"
class TestOther:
    @pytest.mark.parametrize("value", ["long"])
    def test_same(self, value):
        assert value == "method"
'''
    corpus, frontend, candidate = fixture(code, [('"long"', 'None')], owner=owner)
    result = analyze(corpus, frontend, candidate)
    assert 'root' in result
    assert len(result['units']) == 1
    checks = [source_text(result, row['at']) for row in result['obligations'].values()]
    assert checks == [expected]
    assert excluded not in source_text(result, result['units'][result['root']]['at'])


def test_truncated_definition_span_is_not_silently_recovered_by_name():
    code = '''import pytest
@pytest.mark.parametrize("value", ["long"])
def test_same(value):
    assert value
    assert value != "final"
'''
    corpus, frontend, candidate = fixture(code, [('"long"', 'None')])
    corpus['tests'][candidate['base_test_id']]['definition_span']['end_byte'] -= 1
    result = analyze(corpus, frontend, candidate)
    assert 'root' not in result
    assert result['unknowns'][0]['detail'] == 'modified root test not recovered'


def test_edit_crossing_the_definition_boundary_abstains_even_if_code_parses():
    code = '''import pytest
@pytest.mark.parametrize("value", ["long"])
def test_same(value):
    assert value
'''
    corpus, frontend, candidate = fixture(code, [('"long"])\ndef', 'None])\ndef')])
    result = analyze(corpus, frontend, candidate)
    assert 'root' not in result
    assert result['unknowns'][0]['detail'] == 'candidate edit crosses selected definition boundary'
