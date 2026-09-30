"""Cache equivalence and counted work; all miniature subjects remain source data."""
import copy
import difflib
import json
from dataclasses import replace

import pytest

from anchor_retrieval.syntax import Source
from experimental.patch_observation_priority_cached import Analyzer, _AssertionLookup, select
from experimental.patch_observation_priority_v2 import Analyzer as OriginalAnalyzer, select as original_select
from relational_gap.frontend import extract_frontend, to_emitter_corpus


def fixture(body='value=11\nresult=compute(value)\nassert result==22', *,
            language='python', old=None, imports='compute'):
    if language == 'python':
        production = old or 'def compute(value):\n    return value * 2\n'
        path = 'library.py'; test_path = 'test_source.py'
        test = 'from library import '+imports+'\ndef test_case():\n'+''.join(
            '    '+line+'\n' for line in body.splitlines())
    elif language == 'go':
        production = old or 'package sample\nfunc compute(value int) int {return value * 2}\n'
        path = 'library.go'; test_path = 'source_test.go'; test = body
    else:
        production = old or 'export function compute(value:number):number{return value * 2;}\n'
        path = 'library.ts'; test_path = 'source.test.ts'; test = body
    changed = production.replace('* 2', '* 3')
    patch = ''.join(difflib.unified_diff(production.splitlines(True), changed.splitlines(True),
                                        fromfile='a/'+path, tofile='b/'+path, n=0))
    front = extract_frontend([Source(path, changed, language), Source(test_path, test, language)], patch=patch)
    return to_emitter_corpus(front), front, patch


def candidate(corpus, before='11', after='19', name='input'):
    base = next(iter(corpus['tests'])); where = corpus['tests'][base]['span']
    raw = corpus['sources'][where['path']]['code'].encode()
    start = raw.index(before.encode(), where['start_byte'])
    return dict(id=name, base_test_id=base, operator='input', imports=[], edits=[dict(
        span=dict(path=where['path'], start_byte=start, end_byte=start+len(before.encode())),
        before=before, after=after, role='input')])


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode()


@pytest.mark.parametrize('mode', ['strict', 'may'])
@pytest.mark.parametrize('body,old,imports', [
    ('value=11\nresult=compute(value)\nassert result==22', None, 'compute'),
    ('value=11\nresult=compute(value)\nassert 22==result\nassert (result)==22', None, 'compute'),
    ('value=11\nresult=compute(value)\nassert result>0 and result<100\nassert result', None, 'compute'),
    ('value=11\nresult=compute(value)\nassert result==22; assert result==22', None, 'compute'),
    ('value=11\nresult=compute(value)\nself.assertEqual(result,22)\nself.assertTrue(result)', None, 'compute'),
    ('value=11\nfor unused in [0]:\n    pass\nresult=compute(value)\nassert result==22', None, 'compute'),
    ('value=11\nif value:\n    unused=0\nresult=compute(value)\nassert result==22', None, 'compute'),
    ('value=11\nresult=compute(value)\nprint(result)\nassert result==22', None, 'compute'),
    ('value=11\nresult=compute(value)\nassert result==22', 'def compute(value):\n    return opaque(value) * 2\n', 'compute'),
    ('box=Box()\nvalue=11\nresult=box.compute(value)\nassert result==22',
     'class Box:\n    def compute(self,value):\n        return value * 2\n', 'Box'),
])
def test_cache_only_preserves_entire_selection_bytes(mode, body, old, imports):
    c, f, p = fixture(body, old=old, imports=imports)
    rows = [candidate(c, after=after, name='c'+str(i)) for i, after in enumerate(['19', '300', '3'])]
    untouched = copy.deepcopy((c, f, rows))
    expected = original_select(c, f, rows, p, budget=2, mode=mode, disable_receiver_fix=True)
    actual = select(c, f, rows, p, budget=2, mode=mode)
    assert encoded(actual) == encoded(expected)
    assert (c, f, rows) == untouched


@pytest.mark.parametrize('language,body', [
    ('go', 'package sample\nimport "testing"\nfunc TestCase(t *testing.T){value:=11;result:=compute(value);if result!=22{t.Error(result)};if result<=0{t.Fatal(result)}}\n'),
    ('go', 'package sample\nimport("testing";"github.com/stretchr/testify/require")\nfunc TestCase(t *testing.T){value:=11;result:=compute(value);require.Equal(t,22,result);require.True(t,result>0)}\n'),
    ('go', 'package sample\nimport "testing"\nfunc TestCase(t *testing.T){value:=11;t.Run("nested",func(t *testing.T){result:=compute(value);if result!=22{t.Error(result)}})}\n'),
    ('typescript', 'import {compute} from "./library";test("case",()=>{let value=11;let result=compute(value);expect(result).toBe(22);expect(result).toBeTruthy();});\n'),
    ('typescript', 'import {compute} from "./library";import assert from "node:assert/strict";test("case",()=>{let value=11;let result=compute(value);assert.equal(result,22);assert.ok(result);});\n'),
    ('typescript', 'import {compute} from "./library";test("case",()=>{let value=11;run(()=>{expect(compute(value)).toBe(22);});});\n'),
])
def test_other_language_frameworks_and_nested_callbacks_keep_exact_evidence(language, body):
    c, f, p = fixture(body, language=language)
    row = candidate(c)
    expected = OriginalAnalyzer(c, f, p, disable_receiver_fix=True).evidence(row)
    actual = Analyzer(c, f, p).evidence(row)
    assert encoded(actual) == encoded(expected)


def test_observation_reordering_and_repeats_do_not_change_first_match():
    c, f, p = fixture('value=11\nresult=compute(value)\n'+'\n'.join(['assert result==22']*4))
    f = copy.deepcopy(f)
    f['observations'] = list(reversed(f['observations'])) + f['observations'][:2]
    row = candidate(c)
    original = OriginalAnalyzer(c, f, p, disable_receiver_fix=True)
    cached = Analyzer(c, f, p)
    assert encoded(cached.evidence(row)) == encoded(original.evidence(row))
    assert cached.work_counts['assertion_adapter_computations'] == 4
    assert cached.work_counts['assertion_lookup_queries'] == 6
    assert cached.work_counts['assertion_index_hits'] == 5


def test_duplicate_statement_span_keeps_original_earliest_assertion_object():
    c, f, p = fixture()
    analyzer = OriginalAnalyzer(c, f, p, disable_receiver_fix=True)
    unit = next(unit for unit in analyzer.index.units.values() if unit.test)
    flow = analyzer.index.flow(unit.id)
    first = flow.assertions[0]
    second = replace(first, predicate='different_adapter_metadata')
    duplicate = copy.copy(flow)
    duplicate.assertions = [first, second]
    counts = dict(assertion_lookup_builds=0, assertion_lookup_queries=0,
                  assertion_adapter_computations=0, assertion_index_hits=0)
    lookup = _AssertionLookup(unit.source, unit, duplicate, counts)
    q = f['observations'][0]['span']
    assert lookup.find(q)[0] is first
    assert lookup.find(q)[0] is first
    assert counts['assertion_adapter_computations'] == 1


def test_unused_late_assertion_is_not_eagerly_parsed(monkeypatch):
    import experimental.patch_observation_priority as old_module
    import experimental.patch_observation_priority_cached as new_module
    c, f, p = fixture('value=11\nresult=compute(value)\nassert result==22\nassert result>0')
    f = copy.deepcopy(f); f['observations'] = f['observations'][:1]
    original_adapter = old_module._assertion_nodes
    def guarded(source, assertion, unit):
        if assertion.text.endswith('>0'):
            raise ValueError('late_adapter_error')
        return original_adapter(source, assertion, unit)
    monkeypatch.setattr(old_module, '_assertion_nodes', guarded)
    monkeypatch.setattr(new_module, '_assertion_nodes', guarded)
    row = candidate(c)
    old = OriginalAnalyzer(c, f, p, disable_receiver_fix=True).evidence(row)
    new = Analyzer(c, f, p).evidence(row)
    assert encoded(new) == encoded(old)
    assert 'late_adapter_error' not in new['unknowns']


def test_reached_adapter_exception_keeps_original_unknown_and_no_witnesses(monkeypatch):
    import experimental.patch_observation_priority as old_module
    import experimental.patch_observation_priority_cached as new_module
    c, f, p = fixture('value=11\nresult=compute(value)\nassert result==22\nassert result>0')
    original_adapter = old_module._assertion_nodes
    def guarded(source, assertion, unit):
        if assertion.text.endswith('>0'):
            raise ValueError('reached_adapter_error')
        return original_adapter(source, assertion, unit)
    monkeypatch.setattr(old_module, '_assertion_nodes', guarded)
    monkeypatch.setattr(new_module, '_assertion_nodes', guarded)
    row = candidate(c)
    old = OriginalAnalyzer(c, f, p, disable_receiver_fix=True).evidence(row)
    new = Analyzer(c, f, p).evidence(row)
    assert encoded(new) == encoded(old)
    assert 'reached_adapter_error' in new['unknowns']
    assert not new['strong_priority'] and not new['may_priority']


def test_edited_owner_invalidation_covers_lengths_unicode_callee_and_repeated_ids():
    old = 'def compute(value):\n    return value * 2\ndef neutral(value):\n    return value\n'
    c, f, p = fixture(old=old, imports='compute,neutral')
    ordinary = candidate(c)
    longer = candidate(c, after='123456')
    changed_callee = candidate(c, 'compute(value)', 'neutral(value)')
    unicode = candidate(c)
    insertion = candidate(c, 'value=11', 'value=11')['edits'][0]
    insertion.update(before='', after='label="雪"\n    ')
    insertion['span']['end_byte'] = insertion['span']['start_byte']
    unicode['edits'].insert(0, insertion)
    changed_assertion = candidate(c, '22', '19')
    reused = Analyzer(c, f, p)
    for row in [ordinary, longer, changed_callee, unicode, changed_assertion, ordinary]:
        expected = OriginalAnalyzer(c, f, p, disable_receiver_fix=True).evidence(row)
        fresh = Analyzer(c, f, p).evidence(row)
        actual = reused.evidence(row)
        assert encoded(actual) == encoded(expected) == encoded(fresh)
    assert reused.work_counts['assertion_lookup_builds'] == 5


@pytest.mark.parametrize('n', [1, 8, 32])
def test_work_count_replaces_quadratic_body_scans_with_at_most_one_per_assertion(monkeypatch, n):
    import experimental.patch_observation_priority as old_module
    import experimental.patch_observation_priority_cached as new_module
    c, f, p = fixture('value=11\nresult=compute(value)\n'+'\n'.join(['assert result==22']*n))
    original_adapter = old_module._assertion_nodes
    old_calls = []; new_calls = []
    def count_old(*args):
        old_calls.append(1)
        return original_adapter(*args)
    def count_new(*args):
        new_calls.append(1)
        return original_adapter(*args)
    monkeypatch.setattr(old_module, '_assertion_nodes', count_old)
    monkeypatch.setattr(new_module, '_assertion_nodes', count_new)
    row = candidate(c)
    old = OriginalAnalyzer(c, f, p, disable_receiver_fix=True).evidence(row)
    cached = Analyzer(c, f, p)
    new = cached.evidence(row)
    assert encoded(new) == encoded(old)
    assert len(old_calls) == n*(n+3)//2
    assert len(new_calls) == n
    assert cached.work_counts['assertion_adapter_computations'] == n
    assert cached.work_counts['assertion_lookup_queries'] == n
    assert 'work_counts' not in new


def test_optional_receiver_repair_is_inherited_without_any_new_semantics():
    old = 'class Box:\n    def compute(owner,value):\n        return value * 2\n'
    c, f, p = fixture('box=Box()\nvalue=11\nresult=box.compute(value)\nassert result==22', old=old, imports='Box')
    rows = [candidate(c)]
    expected = original_select(c, f, rows, p, disable_receiver_fix=False)
    actual = select(c, f, rows, p, disable_receiver_fix=False)
    assert encoded(actual) == encoded(expected)


def test_default_preserving_observation_hooks_are_called_without_changing_evidence():
    class Tracked(Analyzer):
        def _observation_span(self, old, changes):
            self.mapped.append(copy.deepcopy(old))
            return super()._observation_span(old, changes)
        def _observation_source_matches(self, owner, current, old):
            self.checked.append((copy.deepcopy(current), copy.deepcopy(old)))
            return super()._observation_source_matches(owner, current, old)
    c, f, p = fixture('value=11\nresult=compute(value)\nassert result==22\nassert result>0')
    row = candidate(c, after='123456')
    tracked = Tracked(c, f, p); tracked.mapped = []; tracked.checked = []
    expected = OriginalAnalyzer(c, f, p, disable_receiver_fix=True).evidence(row)
    assert encoded(tracked.evidence(row)) == encoded(expected)
    assert len(tracked.mapped) == len(tracked.checked) == 2
    assert all(current['start_byte'] == old['start_byte']+4 for current, old in tracked.checked)
