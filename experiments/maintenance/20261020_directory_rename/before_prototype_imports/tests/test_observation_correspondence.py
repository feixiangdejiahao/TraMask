"""Identity transport; no repository or model is executed."""
import copy

import pytest

from anchor_retrieval.syntax import Source
from experimental.observation_correspondence import correspond, enclosing_span
from relation_search.oracle_evidence import _modified_sources
from tests.test_patch_observation_priority import candidate, fixture


def prepare(body='assert compute(11) == 22', before='11', after='19', occurrence=0):
    corpus, front, patch = fixture(body=body)
    row = candidate(corpus, before, after, occurrence=occurrence)
    _, owner, changes, _, _ = _modified_sources(corpus, row)
    original = Source(owner.path, corpus['sources'][owner.path]['code'], 'python')
    observations = [q for q in front['observations'] if q['test_id'] == row['base_test_id']]
    return original, owner, observations, changes


def test_actual_input_change_preserves_checker_and_expectation():
    original, modified, observations, changes = prepare()
    frozen = copy.deepcopy((observations, changes))
    result = correspond(original, modified, observations[0], changes)
    assert result['status'] == 'corresponding'
    assert result['basis'] == 'actual_edit_with_unchanged_checker_bytes'
    extent = result['actual_span']
    assert modified.data[extent['start_byte']:extent['end_byte']] == b'compute(19)'
    assert (observations, changes) == frozen


@pytest.mark.parametrize('before,after', [('22', '33'), ('==', '!='),
                                        ('assert compute(11) == 22', 'pass')])
def test_checker_and_statement_replacements_are_not_transportable(before, after):
    old, new, observations, changes = prepare(before=before, after=after)
    assert correspond(old, new, observations[0], changes)['status'] == 'unknown'


def test_actual_callee_change_is_identity_only_and_requires_rebinding():
    old, new, observations, changes = prepare(before='compute(11)', after='other(19)')
    result = correspond(old, new, observations[0], changes)
    assert result['status'] == 'corresponding'
    assert result['oracle_status'] == 'original_expectation_requires_semantic_review'


def test_same_text_assertions_preserve_distinct_source_stages():
    body = 'assert compute(11) == 22\ncompute = other\nassert compute(11) == 22'
    old, new, observations, changes = prepare(body=body, occurrence=1)
    first, second = [correspond(old, new, q, changes) for q in observations]
    assert first['basis'] == 'unchanged_statement_bytes'
    assert second['basis'] == 'actual_edit_with_unchanged_checker_bytes'
    assert first['span']['start_byte'] < second['span']['start_byte']


def test_inserting_identical_assertion_before_original_does_not_take_its_identity():
    old, new, observations, changes = prepare()
    insertion = dict(changes[0]); point = observations[0]['span']['start_byte']
    insertion.update(before='', after='assert compute(11) == 22\n    ',
                     original_span=dict(path=old.path, start_byte=point, end_byte=point))
    data = old.data[:point] + insertion['after'].encode() + old.data[point:]
    offset = len(insertion['after'].encode())
    edit = changes[0]['original_span']; left, right = edit['start_byte'] + offset, edit['end_byte'] + offset
    data = data[:left] + changes[0]['after'].encode() + data[right:]
    new = Source(old.path, data.decode(), 'python')
    result = correspond(old, new, observations[0], [insertion, changes[0]])
    assert result['status'] == 'corresponding'
    assert result['span']['start_byte'] == point + offset


def test_multibyte_source_offsets_survive_actual_growth():
    old, new, observations, changes = prepare(body='label = "雪"\nassert compute(11) == 22', after='123456')
    result = correspond(old, new, observations[0], changes)
    assert result['status'] == 'corresponding'
    e = result['span']; assert new.data[e['start_byte']:e['end_byte']] == b'assert compute(123456) == 22'


@pytest.mark.parametrize('after', ['compute(19); assert False', '# erased', 'compute('])
def test_split_or_erased_expression_is_not_one_corresponding_ast(after):
    old, new, observations, changes = prepare(before='compute(11)', after=after)
    assert correspond(old, new, observations[0], changes)['status'] == 'unknown'


def test_edit_crossing_span_boundary_is_unknown():
    extent = dict(path='x.py', start_byte=5, end_byte=15)
    edits = [dict(original_span=dict(path='x.py', start_byte=4, end_byte=7), before='abc', after='d')]
    assert enclosing_span(extent, edits) is None


@pytest.mark.parametrize('language,old,new,body', [
    ('go', 'package sample\nfunc compute(value int) int {return value * 2}\n',
     'package sample\nfunc compute(value int) int {return value * 3}\n',
     'package sample\nimport "testing"\nfunc TestCase(t *testing.T){if compute(11)!=22{t.Error("wrong")}}\n'),
    ('typescript', 'export function compute(value: number): number {return value * 2;}\n',
     'export function compute(value: number): number {return value * 3;}\n',
     'import {compute} from "./library";\ntest("case",()=>{expect(compute(11)).toBe(22);});\n'),
])
def test_source_correspondence_also_preserves_go_guard_and_typescript_matcher(language, old, new, body):
    corpus, front, patch = fixture(old, new, body, language)
    row = candidate(corpus)
    _, modified, changes, _, _ = _modified_sources(corpus, row)
    original = Source(modified.path, corpus['sources'][modified.path]['code'], language)
    observation = next(q for q in front['observations'] if q['test_id'] == row['base_test_id'])
    result = correspond(original, modified, observation, changes)
    assert result['status'] == 'corresponding', result
    extent = result['actual_span']
    assert modified.data[extent['start_byte']:extent['end_byte']] == b'compute(19)'


@pytest.mark.parametrize('body', ['assert compute(11) == 22 and 1 == 1',
                                  'assert 0 < compute(11) < 22'])
def test_composite_predicate_does_not_certify_embedded_checker_preservation(body):
    old, new, observations, changes = prepare(body=body, before='22', after='33')
    result = correspond(old, new, observations[0], changes)
    assert result['status'] == 'unknown'
    assert result['reason'] == 'actual_and_checker_roles_not_separated'
