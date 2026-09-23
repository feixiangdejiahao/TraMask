"""Behavioral regression checks for the analysis, using independent small programs."""
from pathlib import Path

from anchor_retrieval.graph import Flow
from anchor_retrieval.index import Index
from anchor_retrieval.retrieve import make_anchors, annotate_gaps, rank
from anchor_retrieval.syntax import Source, diff_lines, trajectory_sources, units


def index_for(code, tests, language='python', production='lib.py', testpath='test_lib.py'):
    patch = f'+++ b/{production}\n@@ -0,0 +1,{len(code.splitlines())} @@\n' + '\n'.join('+' + s for s in code.splitlines())
    return Index([Source(production, code, language), Source(testpath, tests, language)], patch)


def test_backward_slice_excludes_unrelated_call_and_follows_reassignment():
    index = index_for('''def first(x): return x
def second(x): return x
def unrelated(x): return x
''', '''from lib import first, second, unrelated
def test_value():
    noise = unrelated(99)
    value = first(1)
    value = second(2)
    assert value == 2
''')
    records, _ = make_anchors(index)
    assert records[0]['calls'] == ['second']
    assert all('unrelated' not in s and 'first' not in s for s in records[0]['impact_symbols'])


def test_field_projection_reaches_optional_regex_group_and_donor():
    index = index_for(r'''import re
PAT = re.compile(r"(\d+)(?:;([a-z]+))?")
class Packet:
    def __init__(self, number, payload):
        self.number = number
        self.payload = payload
def decode(raw):
    if match := PAT.fullmatch(raw):
        number, payload = match.groups()
        return Packet(number, payload)
''', '''from lib import decode
def test_empty():
    event = decode("12")
    assert event.payload is None
def test_text():
    event = decode("3;abc")
    assert event.payload == "abc"
''')
    rows, _ = make_anchors(index)
    assert len(rows) == 2
    assert rows[0]['field_witnesses'][0]['field'] == 'payload'
    assert any('#group:2' in s for s in rows[0]['bindings'])
    assert not any('#group:1' in s for s in rows[0]['bindings'])
    annotate_gaps(rows)
    assert rows[0]['input_gap_candidates'][0]['donors'][0]['value'] == '"abc"'


def test_receiver_type_disambiguates_same_method_name():
    index = index_for('''class Left:
    def get(self): return 1
class Right:
    def get(self): return 2
''', '''from lib import Left, Right
def test_left():
    obj = Left()
    assert obj.get() == 1
''')
    rows, _ = make_anchors(index)
    assert any('Left.get' in s for s in rows[0]['impact_symbols'])
    assert not any('Right.get' in s for s in rows[0]['impact_symbols'])


def test_go_assertion_helper_and_state_sequence():
    index = index_for('''package box
type Box struct { Value int }
func New() *Box { return &Box{} }
func (b *Box) Add(x int) { b.Value += x }
func (b *Box) Read() int { return b.Value }
''', '''package box
import "github.com/stretchr/testify/require"
func TestState(t *testing.T) {
    b := New()
    b.Add(7)
    require.Equal(t, 7, b.Read())
}
''', 'go', 'box.go', 'box_test.go')
    rows, _ = make_anchors(index)
    assert len(rows) == 1
    assert {'New', 'b.Add', 'b.Read'} <= set(rows[0]['calls'])
    assert any('Box.Read' in s for s in rows[0]['impact_symbols'])


def test_typescript_runtime_assertion_and_barrel_import():
    code = 'export function wrap(x: unknown) { return { value: x }; }'
    test = '''import { wrap } from './index.ts';
test('wrapped', () => { const x = wrap(7); expect(x.value).toBe(7); });'''
    patch = '+++ b/wrap.ts\n@@ -0,0 +1 @@\n+' + code
    index = Index([Source('wrap.ts', code, 'typescript'),
                   Source('index.ts', "export * from './wrap.ts';", 'typescript'),
                   Source('wrap.test.ts', test, 'typescript'),
                   Source('wrap.test-d.ts', test, 'typescript')], patch)
    rows, counts = make_anchors(index)
    assert len(rows) == 1
    assert rows[0]['name'] == 'wrapped'
    assert rows[0]['impact_symbols']
    assert counts['type_only_units_excluded'] == 1


def test_historical_heredocs_and_editor_guards():
    trajectory = {'steps': [{'step_id': 4, 'tool_calls': [{'arguments': {'command':
        "python - <<'PY'\ncontent = open('lib.py').read()\nassert 'old' in content\nPY\n"}}]},
        {'step_id': 5, 'tool_calls': [{'arguments': {'command':
        "cat > check.go <<'EOF'\npackage box\nfunc TestX(t *testing.T) { require.Equal(t, 1, Run()) }\nEOF\n"}}]}]}
    sources = trajectory_sources(trajectory, 'python')
    assert [s.language for s in sources] == ['python', 'go']
    index = Index(sources, '')
    rows, counts = make_anchors(index)
    assert counts['editor_assertions_excluded'] == 1
    assert all('assert \'old\'' not in r['assertion'] for r in rows)


def test_different_parameter_rows_are_not_deduplicated():
    base = '''import pytest
@pytest.mark.parametrize('x', VALUES)
def test_x(x):
    assert run(x) == 1
'''
    a = units(Source('test_a.py', base.replace('VALUES', '[1]'), 'python'))[0][0]
    b = units(Source('test_b.py', base.replace('VALUES', '[2]'), 'python'))[0][0]
    assert a.fingerprint != b.fingerprint
    assert a.parameter_values == {'x': [1]}


def test_deletion_only_diff_keeps_change_boundary():
    assert diff_lines('+++ b/lib.py\n@@ -4 +4,0 @@\n-old\n') == {'lib.py': {4}}


def test_comparison_operator_is_part_of_fingerprint():
    a = units(Source('test_a.py', 'def test_x():\n    assert x == y', 'python'))[0][0]
    b = units(Source('test_b.py', 'def test_x():\n    assert x != y', 'python'))[0][0]
    assert a.fingerprint != b.fingerprint


def test_equal_test_text_in_different_files_is_not_deduplicated():
    body = 'def test_value():\n    assert run(1) == 1\n'
    index = Index([Source('test_one.py', body, 'python'), Source('test_two.py', body, 'python')], '')
    rows, counts = make_anchors(index)
    assert len(rows) == 2
    assert counts['unique_test_units'] == 2


def test_filtered_helper_return_retains_element_type():
    index = index_for('''class Record:
    def __init__(self, data): self.data = data
''', '''from lib import Record
def select(records):
    return [record for record in records if isinstance(record, Record)]
def test_selected():
    (record,) = select([Record(7)])
    assert record.data == 7
''')
    helper = next(u for u in index.units.values() if u.name == 'select')
    assert index.return_types(helper) == {'Record'}
    rows, _ = make_anchors(index)
    assert rows[0]['field_witnesses'][0]['field'] == 'data'


def test_base_method_dispatch_includes_override_but_super_calls_base():
    index = index_for('''class Base:
    def run(self): return self.parse()
    def parse(self): return 0
class Derived(Base):
    def parse(self): return 1
''', '''from lib import Derived
def test_derived():
    item = Derived()
    assert item.run() == 1
''')
    rows, _ = make_anchors(index)
    assert any('Derived.parse' in s for s in rows[0]['impact_symbols'])


def test_builtin_list_append_does_not_reach_unrelated_repository_append():
    index = index_for('''class Log:
    def append(self, value): return value
''', '''def test_list():
    items = []
    items.append(3)
    assert items == [3]
''')
    rows, _ = make_anchors(index)
    assert not rows[0]['impact_symbols']


def test_literal_parameter_sets_export_as_stable_json():
    import json
    from anchor_retrieval.syntax import json_safe
    assert json.dumps(json_safe({'a': {3, 1}})) == '{"a": {"$set": [1, 3]}}'


def test_match_provenance_crosses_helper_parameter():
    index = index_for(r'''import re
PAT = re.compile(r"(\d+)(?:;([a-z]+))?")
class Packet:
    def __init__(self, payload): self.payload = payload
def finish(match):
    number, payload = match.groups()
    return Packet(payload)
def decode(raw):
    if match := PAT.fullmatch(raw):
        return finish(match)
''', '''from lib import decode
def test_empty():
    assert decode('12').payload is None
def test_text():
    print(decode('12;hello'))
''')
    rows, _ = make_anchors(index)
    annotate_gaps(rows, index.input_donors)
    assert len(rows) == 1
    assert any('#group:2' in g['slot'] for g in rows[0]['input_gap_candidates'])
    assert rows[0]['input_gap_candidates'][0]['donors'][0]['value'] == '"hello"'


def test_historical_production_snapshot_is_not_a_final_candidate_callee():
    code = 'class Service:\n    def read(self): return 1\n'
    tests = 'from lib import Service\ndef test_read():\n    assert Service().read() == 1\n'
    historical = Source('trajectory/old.py', code.replace('return 1', 'return 9'), 'python',
                        'trajectory', 1, 'lib.py')
    patch = '+++ b/lib.py\n@@ -0,0 +1,2 @@\n+class Service:\n+    def read(self): return 1\n'
    index = Index([Source('lib.py', code, 'python'), Source('test_lib.py', tests, 'python'), historical], patch)
    rows, _ = make_anchors(index)
    chains = [e for w in rows[0]['impact_witnesses'] for e in w['chain']]
    assert chains
    assert not any('trajectory/old.py' in e['callee'] for e in chains)


def test_imported_typescript_assertion_helper_is_a_runtime_oracle():
    index = Index([
        Source('lib.ts', 'export function run(x: number) { return x; }', 'typescript'),
        Source('expectValue.ts', '''import { expect } from 'vitest';
export function expectValue(x: number) { expect(x).toBe(1); }''', 'typescript'),
        Source('lib.test.ts', '''import { run } from './lib.ts';
import { expectValue } from './expectValue.ts';
test('value', () => { expectValue(run(1)); });''', 'typescript')],
        '+++ b/lib.ts\n@@ -0,0 +1 @@\n+export function run(x: number) { return x; }')
    rows, _ = make_anchors(index)
    assert len(rows) == 1
    assert rows[0]['predicate'] == 'assertion_helper'
    assert rows[0]['impact_symbols']


def test_python_builtin_does_not_bind_to_same_named_repository_method():
    index = index_for('''class Example:
    def super(self): return True
    def len(self): return 3
''', '''def test_builtin():
    assert len([1, 2]) == 2
''')
    rows, _ = make_anchors(index)
    assert rows[0]['impact_symbols'] == []


def test_unrelated_constructor_field_change_is_not_parameter_change():
    source = '''class Pair:
    def __init__(self, left, right):
        self.left = left
        self.right = right + 1
'''
    tests = '''from lib import Pair
def test_left():
    assert Pair(1, 2).left == 1
'''
    patch = '+++ b/lib.py\n@@ -4 +4 @@\n-        self.right = right\n+        self.right = right + 1\n'
    index = Index([Source('lib.py', source, 'python'), Source('test_lib.py', tests, 'python')], patch)
    rows, _ = make_anchors(index)
    assert rows[0]['impact_symbols']  # Coarse function impact remains possible.
    assert rows[0]['field_witnesses'] == []  # But it is not evidence that left changed.


def test_javascript_isolated_surrogate_literal_survives_utf8_export():
    import json
    from anchor_retrieval.syntax import canonical
    encoded = canonical('\ud83d')
    assert encoded.encode('utf-8') == b'"\\ud83d"'
    assert json.loads(encoded) == '\ud83d'
