"""End-to-end program-selected composition on independent miniature subjects."""
import copy
import shutil
import subprocess

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.corpus import build_corpus
from generic_composition.emitter import emit
from experimental.semantic_transport import oracle
from experimental.semantic_transport.proposals import Budget, _expected, generate, materialize


def corpus_for(tmp_path, code, language='python'):
    name = {'python': 'test_toy.py', 'go': 'toy_test.go', 'typescript': 'toy.test.ts'}[language]
    (tmp_path / name).write_text(code)
    return build_corpus(tmp_path, language)


def complete(candidate, expression):
    result = oracle.validate_completions({'completions': [{
        'candidate_id': candidate['id'], 'observe': 0, 'expected': expression, 'guard': None,
    }]}, [candidate])
    assert not result['rejected'], result
    return result['accepted'][0]


def emitted(corpus, candidate, expression):
    proposal = materialize(corpus, candidate, complete(candidate, expression))
    result = emit(corpus, [proposal])
    assert not result['unsupported'], result
    return result


WRAPPER = '''def make(value):
    return value
def wrap(value):
    return '<' + value + '>'
def test_plain():
    assert make('a') == 'a'
def test_wrapped():
    assert wrap(make('b')) == '<b>'
'''


STATE = '''class Tape:
    def __init__(self): self.data = []
    def put(self, value): self.data.append(value)
    def snapshot(self): return self.data[:]
def test_a():
    tape = Tape()
    alias = tape
    alias.put('a')
    assert tape.snapshot() == ['a']
def test_b():
    tape = Tape()
    tape.put('b')
    assert tape.snapshot() == ['b']
'''


def test_program_selects_wrapper_and_literal_hole_without_unknown_argument(tmp_path):
    corpus = corpus_for(tmp_path, WRAPPER)
    before = copy.deepcopy(corpus)
    candidates = generate(corpus)['candidates']
    candidate = next(c for c in candidates if "wrap(make('a'))" in c['preview_body'])
    assert candidate['pre'] == ['a']
    assert candidate['arg'] == []
    result = emitted(corpus, candidate, "'<' + pre[0] + '>'")
    namespace = {}
    exec(result['files']['test_toy.py'], namespace)
    for row in result['controls'] + result['obligations']:
        namespace[row['test_name']]()
    assert corpus == before


def test_program_selects_state_insertion_and_preserves_aliases_and_controls(tmp_path):
    corpus = corpus_for(tmp_path, STATE)
    generated = generate(corpus)
    candidate = next(c for c in generated['candidates'] if c['pre'] == [['a']] and c['context']['kind'] == 'state_context')
    assert candidate['arg'] == ['b']
    result = emitted(corpus, candidate, 'pre[0] + [arg[0]]')
    assert "alias = tape" in result['files']['test_toy.py']
    namespace = {}
    exec(result['files']['test_toy.py'], namespace)
    for row in result['controls'] + result['obligations']:
        namespace[row['test_name']]()
    # Keep original controls passing while exposing an operation interaction.
    namespace['Tape'].put = lambda self, value: self.data.__setitem__(slice(None), [value])
    for row in result['controls']:
        namespace[row['test_name']]()
    with pytest.raises(AssertionError):
        namespace[result['obligations'][0]['test_name']]()


def test_model_cannot_modify_selected_body_or_inject_cached_literal(tmp_path):
    corpus = corpus_for(tmp_path, WRAPPER)
    candidate = generate(corpus)['candidates'][0]
    completion = complete(candidate, "'<' + pre[0] + '>'")
    forged = dict(completion, literal="'a'\n    raise RuntimeError('injected')")
    with pytest.raises(ValueError, match='completion_literal_mismatch'):
        materialize(corpus, candidate, forged)
    with pytest.raises(ValueError, match='completion_candidate_mismatch'):
        materialize(corpus, candidate, dict(completion, candidate_id='forged'))
    result = oracle.validate_completions({'completions': [{
        'candidate_id': candidate['id'], 'observe': 0, 'expected': 'pre[0]',
        'guard': None, 'body': 'forged',
    }]}, [candidate])
    assert result['protocol_error']['code'] == 'completion_schema'


def test_atomic_prefix_preserves_both_assertion_operand_effects_and_control_region(tmp_path):
    code = '''events = []
def make(value): return value
def wrap(value): return value
def actual(value):
    events.append('actual')
    return value
def expected():
    events.append('expected')
    return 'a'
def test_target():
    if True:
        value = make('a')
        assert actual(value) == expected()
        assert value == 'a'
        events.append('tail')
def test_donor():
    assert wrap(make('b')) == 'b'
'''
    corpus = corpus_for(tmp_path, code)
    candidates = generate(corpus)['candidates']
    candidate = next(c for c in candidates if "wrap(make('a'))" in c['preview_body']
                     and c['observations'][0]['text'] == 'value')
    assert '(actual(value) == expected())' in candidate['preview_body']
    assert "events.append('tail')" in candidate['preview_body']
    result = emitted(corpus, candidate, 'pre[0]')
    namespace = {}
    exec(result['files']['test_toy.py'], namespace)
    namespace[result['obligations'][0]['test_name']]()
    assert namespace['events'] == ['actual', 'expected', 'tail']


def test_expected_identifier_resolves_same_scope_and_rejects_conditional_or_mutated_sources(tmp_path):
    base = '''def make(value): return value
def test_target():
    wanted = 'a'
    def nested():
        wanted = 'wrong scope'
    assert make('a') == wanted
'''
    corpus = corpus_for(tmp_path, base)
    cap = corpus['capsules'][0]
    source = Source('test_toy.py', base, 'python')
    _, value, provenance = _expected(corpus, cap, source, {})
    assert value == 'a'
    assert provenance['kind'] == 'preceding_literal_definition'
    for replacement in ["if False:\n        wanted = 'wrong branch'", "wanted += 'changed'",
                        "wanted, other = ('b', 1)", "for wanted in ['changed']:\n        pass"]:
        code = base.replace("def nested():\n        wanted = 'wrong scope'", replacement)
        corpus = corpus_for(tmp_path, code)
        with pytest.raises(ValueError):
            _expected(corpus, corpus['capsules'][0], Source('test_toy.py', code, 'python'), {})


@pytest.mark.parametrize('language,code', [
    ('go', '''package toy
import "testing"
func TestToy(t *testing.T) {
    wanted := 1
    wanted += 2
    actual := 3
    if actual != wanted { t.Fatal(actual) }
}
'''),
    ('typescript', '''import assert from 'node:assert/strict';
test('toy', () => {
    let wanted = 1;
    wanted += 2;
    const actual = 3;
    assert.strictEqual(actual, wanted);
});
'''),
])
def test_augmented_expected_bindings_are_not_misread_as_rhs_literals(tmp_path, language, code):
    corpus = corpus_for(tmp_path, code, language)
    cap = corpus['capsules'][0]
    source = Source(cap['test_span']['path'], code, language)
    with pytest.raises(ValueError, match='expected_definition_not_literal'):
        _expected(corpus, cap, source, {})


def test_rebound_mutable_expected_cannot_be_reused_as_initial_literal(tmp_path):
    code = '''def test_target():
    wanted = ['a']
    alias = wanted
    alias.append('b')
    assert actual() == wanted
'''
    corpus = corpus_for(tmp_path, code)
    with pytest.raises(ValueError, match='expected_binding_used_after_literal_definition'):
        _expected(corpus, corpus['capsules'][0], Source('test_toy.py', code, 'python'), {})


def test_parameter_cells_are_instantiated_and_unchanged_control_rows_remain(tmp_path):
    code = '''import pytest
def make(value): return value
@pytest.mark.parametrize('item, wanted', [('v:1', 'v:1'), ('v:2', 'v:2'), ('v:3', 'v:3')])
def test_rows(item, wanted):
    assert make(item) == wanted
'''
    corpus = corpus_for(tmp_path, code)
    candidates = generate(corpus)['candidates']
    assert candidates
    candidate = candidates[0]
    assert candidate['parameter_bindings']
    result = emitted(corpus, candidate, 'arg[0]')
    namespace = {}
    exec(result['files']['test_toy.py'], namespace)
    control = namespace[result['controls'][0]['test_name']]
    combined = namespace[result['obligations'][0]['test_name']]
    for item, wanted in [('v:1', 'v:1'), ('v:2', 'v:2'), ('v:3', 'v:3')]:
        control(item, wanted)
        combined(item, wanted)
    assert result['files']['test_toy.py'].count('@pytest.mark.parametrize') == 3


def test_source_local_wrapper_cannot_become_an_unbound_name(tmp_path):
    code = '''def make(value): return value
def test_target():
    assert make('a') == 'a'
def test_donor():
    local_wrap = lambda value: value
    assert local_wrap(make('b')) == 'b'
'''
    corpus = corpus_for(tmp_path, code)
    candidates = generate(corpus)['candidates']
    assert all('local_wrap' not in c['preview_body'] for c in candidates
               if corpus['tests'][c['base_test_id']]['name'] == 'test_target')


@pytest.mark.skipif(shutil.which('node') is None, reason='Node is unavailable')
def test_typescript_prefix_retains_actual_expected_and_message_effects(tmp_path):
    code = '''import assert from 'node:assert/strict';
const events = [];
function test(name, callback) { callback(); }
function make(value) { return value; }
function wrap(value) { return value; }
function actual(value) { events.push('actual'); return value; }
function expected() { events.push('expected'); return 'a'; }
function message() { events.push('message'); return 'message'; }
test('target', () => {
    const value = make('a');
    assert.strictEqual(actual(value), expected(), message());
    assert.strictEqual(value, 'a');
});
test('donor', () => { assert.strictEqual(wrap(make('b')), 'b'); });
'''
    corpus = corpus_for(tmp_path, code, 'typescript')
    candidate = next(c for c in generate(corpus)['candidates']
                     if "wrap(make('a'))" in c['preview_body'] and c['observations'][0]['text'] == 'value')
    assert 'void ([actual(value), expected(), message()])' in candidate['preview_body']
    result = emitted(corpus, candidate, 'pre[0]')
    path = tmp_path / 'effects.mjs'
    path.write_text(result['files']['toy.test.ts'] + '''
assert.equal(events.length % 3, 0);
for (let i = 0; i < events.length; i += 3) {
    assert.deepEqual(events.slice(i, i + 3), ['actual', 'expected', 'message']);
}
''')
    run = subprocess.run(['node', str(path)], text=True, capture_output=True, timeout=20)
    assert run.returncode == 0, run.stdout + run.stderr


GO_STATE = '''package toy
import "testing"
type Tape struct { text string }
func NewTape() *Tape { return &Tape{} }
func (q *Tape) Put(x string) { q.text += x }
func (q *Tape) Text() string { return q.text }
func TestA(t *testing.T) {
 q := NewTape()
 q.Put("猫")
 if got := q.Text(); got != "猫" { t.Fatal(got) }
}
func TestB(t *testing.T) {
 q := NewTape()
 q.Put("b")
 if got := q.Text(); got != "b" { t.Fatal(got) }
}
'''


TS_STATE = '''import assert from 'node:assert/strict';
import {test} from 'node:test';
class Tape {
 constructor() { this.data = []; }
 put(x) { this.data.push(x); }
 snapshot() { return this.data.slice(); }
}
test('a', () => {
 const q = new Tape();
 q.put('猫');
 assert.deepEqual(q.snapshot(), ['猫']);
});
test('b', () => {
 const q = new Tape();
 q.put('b');
 assert.deepEqual(q.snapshot(), ['b']);
});
'''


@pytest.mark.skipif(shutil.which('go') is None, reason='Go is unavailable')
def test_go_state_endbyte_and_unicode_survive_complete_emit_and_execution(tmp_path):
    corpus = corpus_for(tmp_path, GO_STATE, 'go')
    candidates = generate(corpus)['candidates']
    candidate = next(c for c in candidates if c['context']['kind'] == 'state_context')
    result = emitted(corpus, candidate, 'pre[0] + arg[0]')
    path = tmp_path / 'toy_test.go'
    path.write_text(result['files']['toy_test.go'])
    run = subprocess.run(['go', 'test', str(path)], text=True, capture_output=True, timeout=45)
    assert run.returncode == 0, run.stdout + run.stderr


@pytest.mark.skipif(shutil.which('node') is None, reason='Node is unavailable')
def test_typescript_state_endbyte_and_array_literal_survive_complete_execution(tmp_path):
    corpus = corpus_for(tmp_path, TS_STATE, 'typescript')
    candidates = generate(corpus)['candidates']
    candidate = next(c for c in candidates if c['context']['kind'] == 'state_context')
    result = emitted(corpus, candidate, 'pre[0] + [arg[0]]')
    path = tmp_path / 'toy.test.mjs'
    path.write_text(result['files']['toy.test.ts'])
    run = subprocess.run(['node', '--test', str(path)], text=True, capture_output=True, timeout=20)
    assert run.returncode == 0, run.stdout + run.stderr


def test_parent_round_robin_keeps_large_tests_from_consuming_shown_budget(tmp_path):
    code = 'def make(value): return value\n'
    for index in range(10):
        code += f'def test_{index:02d}():\n'
        count = 12 if index == 0 else 2
        for offset in range(count):
            code += f'    assert make("v:{index * 20 + offset}") == "v:{index * 20 + offset}"\n'
    corpus = corpus_for(tmp_path, code)
    for index, test in enumerate(corpus['tests'].values()):
        test['retrieval_rank'] = index + 1
    for donor in corpus['donors']:
        donor['retrieval_rank'] = corpus['tests'][donor['test_id']]['retrieval_rank']
    result = generate(corpus, Budget(max_candidates=128, shown_candidates=24))
    all_parents = {c['base_test_id'] for c in result['candidates']}
    assert len(all_parents) == 10
    assert len({c['base_test_id'] for c in result['candidates'][:10]}) == 10


def parameter_expected(tmp_path, body, initial=1):
    code = ('import pytest\n'
            'def actual(value): return value\n'
            '@pytest.mark.parametrize("value, expected", [(1, 1)])\n'
            'def test_row(value, expected):\n' + body)
    corpus = corpus_for(tmp_path, code)
    capsule = corpus['capsules'][0]
    return _expected(corpus, capsule, Source('test_toy.py', code, 'python'),
                     {'value': 1, 'expected': initial})


@pytest.mark.parametrize('prefix', [
    '    expected += 10\n',
    '    expected = actual(expected)\n',
    '    expected, other = (11, 2)\n',
    '    if value:\n        expected = 11\n',
    '    (expected := 11)\n',
    '    del expected\n',
    '    def mutate():\n        nonlocal expected\n        expected = 11\n    mutate()\n',
    '    with actual(value) as expected:\n        pass\n',
])
def test_parameter_expected_rebindings_never_export_entry_value(tmp_path, prefix):
    with pytest.raises(ValueError):
        parameter_expected(tmp_path, prefix + '    assert actual(value) == expected\n')


@pytest.mark.parametrize('prefix', [
    '    expected.append(10)\n',
    '    alias = expected\n    alias.append(10)\n',
    '    actual(expected)\n',
    '    expected[0] = 10\n',
    '    def mutate():\n        expected.append(10)\n    mutate()\n',
])
def test_mutable_parameter_expected_unknown_effects_never_export_entry_value(tmp_path, prefix):
    with pytest.raises(ValueError, match='expected_'):
        parameter_expected(tmp_path, prefix + '    assert actual(value) == expected\n', [1])


@pytest.mark.parametrize('initial,post', [
    (1, 'expected += 10'),
    (1, 'expected = 11'),
    ([1], 'expected.append(10)'),
    ([1], 'alias = expected; alias.append(10)'),
])
def test_parameter_expected_checks_loop_backedge_writes(tmp_path, initial, post):
    body = '    for iteration in range(2):\n        assert actual(value) == expected\n        ' + post + '\n'
    with pytest.raises(ValueError, match='expected_'):
        parameter_expected(tmp_path, body, initial)


def test_parameter_expected_retains_readonly_scalar_and_fresh_literal_definition(tmp_path):
    _, value, origin = parameter_expected(tmp_path, '    actual(expected)\n    assert actual(value) == expected\n')
    assert value == 1 and origin['kind'] == 'parameter_row'
    _, value, origin = parameter_expected(tmp_path, '    expected = 11\n    assert actual(value) == expected\n')
    assert value == 11 and origin['kind'] == 'preceding_literal_definition'
    _, value, origin = parameter_expected(tmp_path, '    assert actual(value) == expected\n', [1])
    assert value == [1] and origin['kind'] == 'parameter_row'
    _, value, _ = parameter_expected(tmp_path, '    def nested():\n        expected = 100\n    assert actual(value) == expected\n')
    assert value == 1
    _, value, origin = parameter_expected(tmp_path, '    expected = [11]\n    assert actual(value) == expected\n')
    assert value == [11] and origin['kind'] == 'preceding_literal_definition'


def test_redefined_mutable_parameter_still_checks_backedge_and_earlier_capture(tmp_path):
    for body in [
        '    expected = []\n    for iteration in range(2):\n        assert actual(value) == expected\n        expected.append(1)\n',
        '    def mutate():\n        expected.append(10)\n    expected = []\n    mutate()\n    assert actual(value) == expected\n',
    ]:
        with pytest.raises(ValueError, match='expected_'):
            parameter_expected(tmp_path, body)
