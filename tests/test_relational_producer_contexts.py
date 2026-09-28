"""Executable source-producing slices, without subject-specific adapters."""
import json
import os
import shutil
import subprocess

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relational_gap.producer_contexts import ProducerBudget, generate_producer_contexts


SETUP = '''events = []
class Child:
    def __init__(self): self.value = 0
    def add(self, value): self.value += value; events.append(('add', value))
    def position(self): events.append(('position', self.value)); return self.value
class Device:
    def __init__(self): self.current = 0; events.append(('create', 0))
    def begin(self): events.append(('begin', 0)); return Child()
    def apply(self, child): self.current = child.value; events.append(('apply', child.value))
    def wait(self, position): events.append(('wait', position)); return position > self.current
def not_ready(value): return not value
'''


def prepare(code, language='python', budget=None):
    path = 'test_producers.py' if language == 'python' else 'producers_test.go'
    frontend = extract_frontend([Source(path, code, language)])
    corpus = to_emitter_corpus(frontend)
    result = generate_producer_contexts(corpus, frontend, budget=budget)
    return result, corpus, frontend


def source(donor_prefix='', recipient_prefix='', donor_suffix=''):
    return SETUP + f'''
def test_donor():
    amount = 2
    obj = Device()
{donor_prefix}    child = obj.begin()
    child.add(amount)
    obj.apply(child)
    x = child.position()
{donor_suffix}    assert not obj.wait(x)

def test_recipient():
    receiver = Device()
{recipient_prefix}    handle = receiver.wait(1000)
    assert not_ready(handle)
'''


def for_recipient(result):
    return [c for c in result['candidates'] if c['base_test_id'].endswith(':test_recipient')]


def execute(corpus, candidate):
    output = emit(corpus, [candidate])
    assert not output['unsupported']
    namespace = {}
    for code in output['files'].values():
        exec(compile(code, '<producer-witness>', 'exec'), namespace)
    namespace[output['obligations'][0]['test_name']]()
    return namespace, output


def test_produced_value_preserves_source_actions_once_and_recipient_q():
    result, corpus, _ = prepare(source())
    candidates = for_recipient(result)
    assert candidates, result
    candidate = candidates[0]
    assert candidate['provenance']['receiver_mapping'] == {'obj': 'receiver'}
    assert len(candidate['provenance']['source_spans']) == 5
    assert candidate['oracle']['assertion_ids'] == [candidate['source_observation_id']]
    namespace, emitted = execute(corpus, candidate)
    assert namespace['events'] == [('create', 0), ('begin', 0), ('add', 2), ('apply', 2), ('position', 2), ('wait', 2)]
    assert 'assert not_ready(handle)' in emitted['files']['test_producers.py']
    assert not any('Device()' in edit['after'] for edit in candidate['edits'])
    json.dumps(result)


def test_local_names_are_hygienic_and_unrelated_recipient_bindings_survive():
    result, corpus, _ = prepare(source(recipient_prefix="    child = 'keep'\n    amount = 91\n    x = 17\n"))
    candidate = for_recipient(result)[0]
    _, emitted = execute(corpus, candidate)
    body = emitted['files']['test_producers.py']
    assert "child = 'keep'" in body and 'amount = 91' in body and 'x = 17' in body
    assert all(value.startswith('rg_producer_') for key, value in candidate['provenance']['local_binding_renames'].items()
               if not key.startswith('obj:'))


def test_intervening_state_action_after_value_production_is_retained():
    result, corpus, _ = prepare(source(donor_suffix='    child.add(1)\n    obj.apply(child)\n'))
    candidate = for_recipient(result)[0]
    namespace, _ = execute(corpus, candidate)
    assert namespace['events'][-3:] == [('add', 1), ('apply', 3), ('wait', 2)]
    assert len(candidate['provenance']['source_spans']) == 7


def test_pure_donor_check_is_omitted_but_effectful_check_is_explicit_unknown():
    result, corpus, _ = prepare(source(donor_suffix='    assert amount >= 0\n'))
    candidate = for_recipient(result)[0]
    assert len(candidate['provenance']['omitted_pure_assertion_spans']) == 1
    execute(corpus, candidate)
    result, _, _ = prepare(source(donor_suffix='    assert child.position() >= 0\n'))
    assert not for_recipient(result)
    assert result['skipped']['producer_ordinary_assertion_effect_unknown']


@pytest.mark.parametrize('prefix', [
    '    if flag:\n        obj.apply(unknown)\n',
    '    for value in values:\n        obj.apply(value)\n',
    '    def callback():\n        obj.apply(unknown)\n',
])
def test_branch_loop_and_nested_scope_prefixes_remain_unknown(prefix):
    result, _, _ = prepare(source(donor_prefix=prefix))
    assert not for_recipient(result)
    assert result['skipped']['producer_control_or_nested_scope_unknown']


def test_independent_resource_dependency_is_not_silently_transplanted():
    code = source().replace('child.add(amount)', 'other = Device()\n    child.add(other.current)')
    result, _, _ = prepare(code)
    assert not for_recipient(result)
    assert result['skipped']['producer_dependency_has_independent_resource_root']


def test_effectful_recipient_actual_is_not_dropped():
    code = source().replace('receiver.wait(1000)', 'receiver.wait(fetch_position())')
    result, _, _ = prepare(code)
    assert not for_recipient(result)


def test_snapshot_q_predating_recipient_call_is_not_pinned():
    code = source().replace('    handle = receiver.wait(1000)\n    assert not_ready(handle)',
                            '    early = receiver.current\n    handle = receiver.wait(1000)\n    assert early == 0')
    result, _, _ = prepare(code)
    assert not for_recipient(result)


def test_different_creator_and_receiver_member_do_not_align():
    code = source().replace('    receiver = Device()', '    receiver = Different()')
    result, _, _ = prepare(code)
    assert not for_recipient(result)
    code = source().replace('receiver.wait(1000)', 'receiver.other(1000)')
    result, _, _ = prepare(code)
    assert not for_recipient(result)


def test_same_source_globals_cannot_capture_recipient_local_shadow():
    code = source().replace('child.add(amount)', 'child.add(transform(amount))')
    code = 'def transform(value): return value\n' + code
    code = code.replace('    receiver = Device()', '    transform = lambda x: 100\n    receiver = Device()')
    result, _, _ = prepare(code)
    assert not for_recipient(result)
    assert any(reason.startswith('producer_external_binding_unknown:') for reason in result['skipped'])


GO = '''package sample
import "testing"
type Child struct { value int }
func (c *Child) Add(n int) { c.value += n }
func (c *Child) Position() int { return c.value }
type Device struct { current int }
func Make() *Device { return &Device{} }
func (d *Device) Begin() *Child { return &Child{} }
func (d *Device) Apply(c *Child) { d.current = c.value }
func (d *Device) Wait(n int) bool { return n > d.current }
func TestDonor(t *testing.T) {
 amount := 2
 obj := Make()
 child := obj.Begin()
 child.Add(amount)
 obj.Apply(child)
 x := child.Position()
 result := obj.Wait(x)
 if result { t.Fatal("unexpected") }
}
func TestRecipient(t *testing.T) {
 receiver := Make()
 handle := receiver.Wait(1000)
 if handle { t.Fatal("not ready") }
}
'''


def test_go_single_result_producer_slice_compiles_and_keeps_source_q(tmp_path):
    result, corpus, _ = prepare(GO, 'go')
    candidates = [c for c in result['candidates'] if c['base_test_id'].endswith(':TestRecipient')]
    assert candidates, result
    output = emit(corpus, candidates[:1])
    assert not output['unsupported']
    if shutil.which('go'):
        for path, code in output['files'].items():
            (tmp_path / path).write_text(code)
        name = output['obligations'][0]['test_name']
        completed = subprocess.run(['go', 'test', '-run', '^' + name + '$', './...'], cwd=tmp_path,
                                   env=dict(os.environ, GO111MODULE='off'), capture_output=True, text=True, timeout=60)
        assert completed.returncode == 0, completed.stdout + completed.stderr


def test_go_normal_fatal_check_prefix_is_not_copied_as_setup():
    code = GO.replace(' child := obj.Begin()', ' if obj.current != 0 { t.Fatal("normal state") }\n child := obj.Begin()')
    result, _, _ = prepare(code, 'go')
    assert not [c for c in result['candidates'] if c['base_test_id'].endswith(':TestRecipient')]
    assert result['skipped']['producer_control_or_nested_scope_unknown']


def test_go_setup_noerror_guard_keeps_source_check_and_typed_parameter_mapping(tmp_path):
    code = GO.replace('import "testing"', 'import "testing"\nimport "github.com/stretchr/testify/require"')
    code = code.replace('func Make()', 'func (d *Device) Prepare() error { return nil }\nfunc Make()')
    code = code.replace(' child := obj.Begin()', ' err := obj.Prepare()\n require.NoError(t, err)\n child := obj.Begin()')
    code = code.replace('func TestRecipient(t *testing.T)', 'func TestRecipient(check *testing.T)')
    code = code.replace('if handle { t.Fatal("not ready") }', 'if handle { check.Fatal("not ready") }')
    result, corpus, _ = prepare(code, 'go')
    candidate = next(c for c in result['candidates'] if c['base_test_id'].endswith(':TestRecipient'))
    assert candidate['provenance']['source_setup_guard_count'] == 1
    assert candidate['provenance']['setup_parameter_mapping'] == {'t': 'check'}
    assert 'require.NoError(check,' in candidate['edits'][0]['after']
    assert len(candidate['oracle']['assertion_ids']) == 1
    output = emit(corpus, [candidate])
    assert not output['unsupported']
    if shutil.which('go'):
        (tmp_path / 'go.mod').write_text('module example.invalid/producer\n\ngo 1.18\nrequire github.com/stretchr/testify/require v0.0.0\nreplace github.com/stretchr/testify/require => ./guard\n')
        guard = tmp_path / 'guard'
        guard.mkdir()
        (guard / 'go.mod').write_text('module github.com/stretchr/testify/require\n\ngo 1.18\n')
        (guard / 'guard.go').write_text('package require\nimport "testing"\nfunc NoError(t *testing.T, err error) { if err != nil { t.Fatal(err) } }\n')
        for path, content in output['files'].items():
            (tmp_path / path).write_text(content)
        name = output['obligations'][0]['test_name']
        process = subprocess.run(['go', 'test', '-run', '^' + name + '$', './...'], cwd=tmp_path,
                                 env=dict(os.environ, GO111MODULE='on', GOPROXY='off'), capture_output=True, text=True, timeout=60)
        assert process.returncode == 0, process.stdout + process.stderr


def test_go_reassignment_preserves_declaration_and_one_hygienic_variable(tmp_path):
    code = GO.replace(' x := child.Position()', ' x := 0\n x = child.Position()')
    result, corpus, _ = prepare(code, 'go')
    candidate = next(c for c in result['candidates'] if c['base_test_id'].endswith(':TestRecipient'))
    names = [name for key, name in candidate['provenance']['local_binding_renames'].items() if key.startswith('x:')]
    assert len(names) == 2 and len(set(names)) == 1
    output = emit(corpus, [candidate])
    assert not output['unsupported']
    if shutil.which('go'):
        for path, content in output['files'].items():
            (tmp_path / path).write_text(content)
        process = subprocess.run(['go', 'test', '-run', '^' + output['obligations'][0]['test_name'] + '$', './...'], cwd=tmp_path,
                                 env=dict(os.environ, GO111MODULE='off'), capture_output=True, text=True, timeout=60)
        assert process.returncode == 0, process.stdout + process.stderr


def test_budgets_and_output_are_deterministic():
    result, corpus, frontend = prepare(source(), budget=ProducerBudget(max_candidates=1))
    assert len(result['candidates']) == 1 and result['budget_exhausted']
    assert result == generate_producer_contexts(corpus, frontend, budget=ProducerBudget(max_candidates=1))
    limited = generate_producer_contexts(corpus, frontend, budget=ProducerBudget(max_statements=2))
    assert not limited['candidates'] and limited['skipped']['producer_slice_budget']
    with pytest.raises(ValueError, match='Producer budgets'):
        generate_producer_contexts(corpus, frontend, budget=ProducerBudget(max_attempts=0))
