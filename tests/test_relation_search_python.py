"""Independent source-only checks for Python relation-shape constructors."""
import ast
import copy
import json

import pytest

from anchor_retrieval.syntax import Source
from prototypes.relation_search_python import Budget, analyze, generate
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus


def prepare(code):
    frontend = extract_frontend([Source('test_shapes.py', code, 'python')])
    return to_emitter_corpus(frontend), frontend


def execute(corpus, candidate):
    output = emit(corpus, [candidate])
    assert not output['unsupported']
    namespace = {}
    exec(compile(output['files']['test_shapes.py'], '<shape-test>', 'exec'), namespace)
    return namespace, output['obligations'][0]['test_name']


EXCEPTION_SOURCE = '''import pytest
class Reader:
    def __init__(self, data, kind='raw'):
        self.data = data
        self.kind = kind
        self.closed = False
    def read(self):
        try:
            chunks = [self.data] if isinstance(self.data, bytes) else self.data
            for chunk in chunks:
                if self.kind == 'structured' and chunk == b'bad':
                    raise ValueError('invalid record')
                yield chunk
        finally:
            self.closed = True

def test_bad():
    source = Reader(b'bad', kind='structured')
    with pytest.raises(ValueError, match='invalid record'):
        list(source.read())

def test_live():
    def feed():
        yield b'good'
    receiver = Reader(feed(), kind='raw')
    assert list(receiver.read()) == [b'good']
    assert receiver.closed is True
'''


def test_constructor_product_preserves_source_assert_and_exception_matcher():
    corpus, frontend = prepare(EXCEPTION_SOURCE)
    frozen = copy.deepcopy((corpus, frontend))
    report = analyze(corpus, frontend)
    products = [row for row in report['candidates'] if row['kind'] == 'constructor_coordinate_product']
    assert products
    selected = products[0]
    assert selected['provenance']['inline_source_assertion_retained']
    assert {edit['after'] for edit in selected['edits']} >= {"b'bad'", "'structured'"}
    context = next(edit for edit in selected['edits'] if edit.get('role') == 'source_exception_context')
    assert 'assert list(receiver.read()) == [b\'good\']' in context['after']
    assert "pytest.raises(ValueError, match='invalid record')" in context['after']
    namespace, name = execute(corpus, selected)
    namespace[name]()
    assert (corpus, frontend) == frozen
    json.dumps(report)


def test_constructor_product_never_imports_unclosed_sibling_local():
    corpus, frontend = prepare(EXCEPTION_SOURCE.replace("source = Reader(b'bad', kind='structured')",
        "mode = unknown_factory()\n    source = Reader(b'bad', kind=mode)"))
    report = analyze(corpus, frontend)
    assert not [row for row in report['candidates'] if row['kind'] == 'constructor_coordinate_product']


ALIAS_SOURCE = '''def label(value): return value
def collect(first, second, cap):
    rows = {'left': ['a', 'b'], 'right': ['c', 'd']}
    return list(dict.fromkeys((rows[first] + rows[second])[:cap]))

def test_bounded():
    left = label('left')
    right = label('right')
    result = collect(left, right, 2)
    assert len(result) == 2
'''


def test_same_constructor_argument_merge_preserves_quota_and_assertion():
    corpus, frontend = prepare(ALIAS_SOURCE)
    rows = [row for row in generate(corpus, frontend) if row['kind'] == 'argument_binding_merge']
    assert len(rows) == 2
    for row in rows:
        assert len(row['edits']) == 1
        assert row['edits'][0]['before'] in {'left', 'right'}
        namespace, name = execute(corpus, row)
        namespace[name]()  # This implementation's contiguous groups mask aliasing.
        assert row['relation']['expected_binding_partition'] == [0, 0]


def test_merge_does_not_pair_unrelated_constructor_families():
    corpus, frontend = prepare(ALIAS_SOURCE.replace("right = label('right')", "right = other('right')"))
    assert not [row for row in generate(corpus, frontend) if row['kind'] == 'argument_binding_merge']


def test_literal_option_markers_keep_input_group_separate_from_other_roles():
    corpus, frontend = prepare('''def test_options():
    a = label('a')
    b = label('b')
    destination = label('destination')
    run('--inputs', a, b, '--output', destination)
    assert done()
''')
    rows = [row for row in generate(corpus, frontend) if row['kind'] == 'argument_binding_merge']
    assert len(rows) == 2
    assert {row['edits'][0]['before'] for row in rows} == {'a', 'b'}
    assert all(row['relation']['source_marker_group'] == '--inputs' for row in rows)


SQL_SOURCE = '''def test_database():
    resource = 'memory'
    runner.invoke(['constraint', resource, 'widgets', 'COUNT(*) = 1'])
    result = runner.invoke(['insert', resource, 'widgets'], input='[{"id": 1, "title": "old"}]')
    assert result.exit_code == 0
    result = runner.invoke(['bulk', resource, 'UPDATE widgets SET title = :title WHERE id = :id'],
                           input='{"id": 1, "title": "new"}')
    assert result.exit_code == 0
'''


def test_sql_overlap_uses_same_resource_fixture_and_changed_written_field():
    corpus, frontend = prepare(SQL_SOURCE)
    rows = [row for row in generate(corpus, frontend) if row['kind'] == 'sql_predicate_write_overlap']
    assert len(rows) == 1
    row = rows[0]
    refined = ast.literal_eval(row['edits'][0]['after'])
    assert refined == '(COUNT(*) = 1) AND MIN("title") = \'old\''
    assert row['relation']['source_initial_value'] == 'old'
    assert row['relation']['source_update_values'] == ['new']
    output = emit(corpus, [row])
    assert not output['unsupported']
    assert output['files']['test_shapes.py'].count('assert result.exit_code == 0') >= 6
    # The same deterministic SQL probe crosses true -> false on real SQLite,
    # independent of any candidate implementation or invented expected result.
    import sqlite3
    db = sqlite3.connect(':memory:')
    db.execute('CREATE TABLE widgets (id INT, title TEXT)')
    db.execute('INSERT INTO widgets VALUES (1, ?)', ('old',))
    assert db.execute('SELECT ' + refined + ' FROM widgets').fetchone() == (1,)
    db.execute('UPDATE widgets SET title = :title WHERE id = :id', {'title': 'new', 'id': 1})
    assert db.execute('SELECT ' + refined + ' FROM widgets').fetchone() == (0,)


@pytest.mark.parametrize('code', [
    SQL_SOURCE.replace("['insert', resource", "['insert', unrelated"),
    SQL_SOURCE.replace('"title": "new"', '"title": "old"'),
    SQL_SOURCE.replace("resource, 'widgets', 'COUNT", "resource, 'other', 'COUNT"),
    SQL_SOURCE.replace('COUNT(*) = 1', 'MIN(title) = 1'),
])
def test_sql_overlap_rejects_wrong_resource_no_change_wrong_table_and_already_read_field(code):
    corpus, frontend = prepare(code)
    assert not [row for row in generate(corpus, frontend) if row['kind'] == 'sql_predicate_write_overlap']


def test_bounded_deterministic_and_non_python_noop():
    corpus, frontend = prepare(EXCEPTION_SOURCE + ALIAS_SOURCE + SQL_SOURCE)
    budget = Budget(max_candidates=3)
    first = generate(corpus, frontend, budget)
    assert first == generate(corpus, frontend, budget)
    assert len(first) == 3
    assert generate({'language': 'go'}, {}) == []


def test_exception_probe_runs_after_the_caught_exception_before_state_assertion(tmp_path, monkeypatch):
    import sys
    import types
    from relation_search.runtime import HELPER_SOURCE, prepare_python_probes
    corpus, frontend = prepare(EXCEPTION_SOURCE)
    row = next(row for row in generate(corpus, frontend) if row['kind'] == 'constructor_coordinate_product')
    assert row['runtime_probes'][0]['phase'] == 'after_expected_exception'
    instrumented = prepare_python_probes(EXCEPTION_SOURCE, 'test_shapes.py', row['id'],
                                         row['source_window'], row['runtime_probes'])
    row = {**row, 'edits': [*row['edits'], *instrumented['edits']]}
    helper = types.ModuleType('__relation_runtime')
    exec(HELPER_SOURCE, helper.__dict__)
    monkeypatch.setitem(sys.modules, '__relation_runtime', helper)
    monkeypatch.setenv('COMBINATION_REPORT_DIR', str(tmp_path))
    namespace, name = execute(corpus, row)
    namespace[name]()
    events = [json.loads(line) for line in (tmp_path/'relation_trace.jsonl').read_text().splitlines()]
    assert len(events) == 1
    assert events[0]['phase'] == 'after_expected_exception'
    observation = next(role for role in events[0]['roles'] if role['name'] == 'observation:0')
    assert observation['value'] == {'type': 'bool', 'value': True}


def test_binding_probe_reads_changed_actuals_but_controls_keep_two_source_bindings():
    corpus, frontend = prepare(ALIAS_SOURCE)
    row = next(row for row in generate(corpus, frontend) if row['kind'] == 'argument_binding_merge')
    mutated = row['runtime_probes'][0]['roles']
    original = row['control_runtime_probes'][0]['roles']
    assert mutated[0]['expression'] == mutated[1]['expression']
    assert original[0]['expression'] != original[1]['expression']
    assert [r['origin_span'] for r in mutated] == [r['origin_span'] for r in original]
