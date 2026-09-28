"""Record and sequence coordinates preserve source field identity."""
import ast
import json

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.cells import generate_cells, recover_rows
from relational_gap.frontend import extract_frontend, to_emitter_corpus


def fixture(code, language='python'):
    path = 'test_fields.py' if language == 'python' else 'fields_test.go'
    frontend = extract_frontend([Source(path, code, language)])
    corpus = to_emitter_corpus(frontend)
    return corpus, frontend


def test_distinct_go_record_fields_never_share_literal_axis():
    corpus, frontend = fixture('''package toy
import "testing"
type Options struct { Label string; Flag bool }
func inspect(n int, o Options) bool { return n > 0 }
func TestA(t *testing.T) { got := inspect(1, Options{Label:"first"}); if !got { t.Fatal("bad") } }
func TestB(t *testing.T) { got := inspect(2, Options{Flag:true}); if !got { t.Fatal("bad") } }
func TestC(t *testing.T) { got := inspect(3, Options{Label:"third"}); if !got { t.Fatal("bad") } }
''', 'go')
    rows, details, _ = recover_rows(corpus, frontend)
    fields = [(axis, value) for row in rows for axis, value in row['coordinates'].items() if '[' in axis]
    assert any('Label' in axis and value == 'first' for axis, value in fields)
    assert any('Flag' in axis and value is True for axis, value in fields)
    result = generate_cells(corpus, frontend)
    edits = [edit for c in result['candidates'] for edit in c['edits']]
    assert any(e['before'] == '"first"' and e['after'] == '"third"' or e['before'] == '"third"' and e['after'] == '"first"' for e in edits)
    assert not any((e['before'] == 'true') != (e['after'] == 'true') for e in edits)
    json.dumps(result)


def test_matching_nested_python_field_still_combines_and_executes():
    corpus, frontend = fixture('''
def inspect(n, opts): return n > 0 and isinstance(opts['meta']['label'], str)
def test_first():
    result = inspect(1, {'meta': {'label': 'red'}, 'flag': True})
    assert result
def test_second():
    result = inspect(2, {'flag': False, 'meta': {'label': 'blue'}})
    assert result
''')
    rows, _, _ = recover_rows(corpus, frontend)
    assert any('meta' in axis and 'label' in axis for row in rows for axis in row['coordinates'])
    assert all(not isinstance(value, dict) for row in rows for value in row['coordinates'].values())
    result = generate_cells(corpus, frontend)
    assert result['candidates']
    assert any(e['before'] in {"'red'", "'blue'"} and e['after'] in {"'red'", "'blue'"}
               for c in result['candidates'] for e in c['edits'])
    emitted = emit(corpus, result['candidates'])
    assert not emitted['unsupported']
    scope = {}
    exec(emitted['files']['test_fields.py'], scope)
    for row in emitted['obligations']:
        scope[row['test_name']]()


def test_sequence_positions_are_separate_axes():
    corpus, frontend = fixture('''
def inspect(values): return True
def test_first():
    result = inspect(['red', True])
    assert result
def test_second():
    result = inspect(['blue', False])
    assert result
''')
    result = generate_cells(corpus, frontend)
    assert result['candidates']
    for candidate in result['candidates']:
        for edit in candidate['edits']:
            assert type(ast.literal_eval(edit['before'])) is type(ast.literal_eval(edit['after']))


def test_whole_scalar_argument_axes_remain_compatible():
    corpus, frontend = fixture('''
def inspect(a,b): return True
def test_first():
    result = inspect(1, 10)
    assert result
def test_second():
    result = inspect(2, 20)
    assert result
''')
    rows, _, _ = recover_rows(corpus, frontend)
    assert all(set(row['coordinates']) == {'0:0', '0:1'} for row in rows)
    assert len(generate_cells(corpus, frontend)['candidates']) == 2


def test_source_bound_whole_scalar_retains_whole_argument_axis():
    corpus, frontend = fixture('''
def inspect(a,b): return True
def test_first():
    a = 1
    result = inspect(a, 10)
    assert result
def test_second():
    a = 2
    result = inspect(a, 20)
    assert result
''')
    rows, _, _ = recover_rows(corpus, frontend)
    assert all(set(row['coordinates']) == {'0:0', '0:1'} for row in rows)
    assert len(generate_cells(corpus, frontend)['candidates']) == 2


def test_scalar_may_flow_into_record_does_not_become_whole_record_axis():
    corpus, frontend = fixture('''
def inspect(n, opts): return True
def test_first():
    flag = True
    result = inspect(1, {'flag': flag})
    assert result
def test_second():
    result = inspect(2, {'label': 'blue'})
    assert result
''')
    rows, _, _ = recover_rows(corpus, frontend)
    assert all('0:1' not in row['coordinates'] for row in rows)
    assert all(value is not True for row in rows for value in row['coordinates'].values())


def test_source_bound_literal_container_keeps_field_path():
    corpus, frontend = fixture('''
def inspect(n, opts): return True
def test_first():
    opts = {'label': 'red'}
    result = inspect(1, opts)
    assert result
def test_second():
    opts = {'label': 'blue'}
    result = inspect(2, opts)
    assert result
''')
    rows, _, _ = recover_rows(corpus, frontend)
    assert all(any('label' in axis for axis in row['coordinates']) for row in rows)
    assert generate_cells(corpus, frontend)['candidates']
