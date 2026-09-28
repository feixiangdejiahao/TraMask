"""Independent creator/action payload alignment and local source identities."""
import json
import os
import shutil
import subprocess

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relational_gap.resource_roots import ResourceRoots
from relational_gap.sequence_cells import generate_sequence_cells


BASE = 'alpha\nbeta\ngamma\ndelta\nepsilon\n'
LEFT = 'alpha\nLEFT\ngamma\ndelta\nepsilon\n'
RIGHT = 'alpha\nbeta\ngamma\nRIGHT\nepsilon\n'


def prepare(code, language='python'):
    path = {'python': 'test_resources.py', 'go': 'resources_test.go', 'typescript': 'resources.test.ts'}[language]
    source = Source(path, code, language)
    frontend = extract_frontend([source])
    corpus = to_emitter_corpus(frontend)
    return corpus, frontend, ResourceRoots(frontend, {path: source})


PYTHON_SETUP = '''events = []
class Resource:
    def __init__(self, value): self.values = [value]; events.append('create')
    def replace(self, value): self.values.append(value); events.append('action')
def factory(value): return Resource(value)
def first_update(resource, value): resource.replace(value)
def second_update(value, unused, resource): resource.replace(value)
'''


def python_source(body):
    return PYTHON_SETUP + '\ndef test_versions():\n' + ''.join('    ' + line + '\n' for line in body.splitlines())


def candidates(code, language='python'):
    corpus, frontend, roots = prepare(code, language)
    result = generate_sequence_cells(corpus, frontend)
    return result, corpus, frontend, roots


def execute(corpus, candidate):
    emitted = emit(corpus, [candidate])
    assert not emitted['unsupported']
    namespace = {}
    for code in emitted['files'].values():
        exec(compile(code, '<resource-source>', 'exec'), namespace)
    namespace[emitted['obligations'][0]['test_name']]()
    return namespace


def test_creator_and_distinct_action_ports_form_source_root_hypothesis():
    code = python_source(f'''resource = factory({{'body': {BASE!r}, 'quota': 2}})
first_update(resource, {{'body': {LEFT!r}, 'quota': 2}})
second_update({{'body': {RIGHT!r}, 'quota': 2}}, 9, resource)
assert len(resource.values) == 3''')
    result, corpus, frontend, roots = candidates(code)
    assert len(result['candidates']) == 12, result
    candidate = result['candidates'][0]
    assert candidate['relation']['carrier_kind'] == 'creator_and_actions_at_source_resource_root'
    alignment = candidate['relation']['alignment']
    assert alignment['payload_alignment'] == 'cross_callee_and_argument_position_hypothesis'
    assert alignment['resource_and_version_semantics'].startswith('unknown')
    assert [row['relation'] for row in alignment['source_links']] == ['creator_result', 'argument_reference', 'argument_reference']
    assert len({row['root_id'] for row in alignment['source_links']}) == 1
    assert [row['argument_slot'] for row in alignment['source_links']] == [None, 0, 2]
    assert all(edit['before'] not in {'2', '9'} for edit in candidate['edits'])
    assert candidate['source_observation_id'] == candidate['oracle']['assertion_ids'][0]
    namespace = execute(corpus, candidate)
    assert namespace['events'] == ['create', 'action', 'action']
    json.dumps(result)


def test_constructor_and_receiver_alias_keep_one_existing_root():
    code = python_source(f'''resource = Resource({{'body': {BASE!r}}})
alias = resource
alias.replace({{'body': {LEFT!r}}})
resource.replace({{'body': {RIGHT!r}}})
assert len(resource.values) == 3''')
    result, corpus, _, _ = candidates(code)
    assert result['candidates']
    links = result['candidates'][0]['relation']['alignment']['source_links']
    assert [row['relation'] for row in links] == ['creator_result', 'receiver_reference', 'receiver_reference']
    assert len(links[1]['alias_binding_ids']) == 2
    assert execute(corpus, result['candidates'][0])['events'] == ['create', 'action', 'action']


@pytest.mark.parametrize('body', [
    f'''one = factory({{'body': {BASE!r}}})
two = factory({{'body': {LEFT!r}}})
three = factory({{'body': {RIGHT!r}}})
assert len(one.values) == 1''',
    f'''one = factory({{'body': {BASE!r}}})
two = factory({{'other': 'unrelated'}})
first_update(one, {{'body': {LEFT!r}}})
first_update(two, {{'body': {RIGHT!r}}})
assert len(one.values) == 2''',
    f'''one = factory({{'body': {BASE!r}}})
first_update(one, {{'different': {LEFT!r}}})
first_update(one, {{'body': {RIGHT!r}}})
assert len(one.values) == 3''',
    f'''one = factory({{'body': {BASE!r}}})
first_update(one, {{'body': {LEFT!r}}})
one = factory({{'body': 'unrelated'}})
first_update(one, {{'body': {RIGHT!r}}})
assert len(one.values) == 2''',
])
def test_different_roots_keys_and_rebound_values_do_not_form_triple(body):
    result, _, _, _ = candidates(python_source(body))
    assert not result['candidates'], result


def test_stale_alias_retains_earlier_resource_after_original_name_rebind():
    code = python_source(f'''resource = factory({{'body': {BASE!r}}})
alias = resource
resource = factory({{'body': 'unrelated'}})
first_update(alias, {{'body': {LEFT!r}}})
second_update({{'body': {RIGHT!r}}}, 0, alias)
assert len(alias.values) == 3''')
    result, corpus, _, _ = candidates(code)
    assert result['candidates']
    assert execute(corpus, result['candidates'][0])['events'] == ['create', 'create', 'action', 'action']


def test_conditional_write_and_capture_do_not_prove_local_root():
    body = f'''resource = factory({{'body': {BASE!r}}})
if flag:
    resource = factory({{'body': 'unrelated'}})
first_update(resource, {{'body': {LEFT!r}}})
second_update({{'body': {RIGHT!r}}}, 0, resource)
assert len(resource.values) == 3'''
    result, _, _, _ = candidates(python_source(body))
    assert not result['candidates']
    code = python_source(f'''resource = factory({{'body': {BASE!r}}})
def run():
    first_update(resource, {{'body': {LEFT!r}}})
    first_update(resource, {{'body': {RIGHT!r}}})
run()
assert len(resource.values) == 3''')
    _, _, frontend, roots = candidates(code)
    for call in frontend['calls']:
        if call['callee'] == 'first_update':
            assert not roots.associations(call)


def test_snapshot_q_before_actions_does_not_become_post_action_observer():
    code = python_source(f'''resource = factory({{'body': {BASE!r}}})
early = len(resource.values)
first_update(resource, {{'body': {LEFT!r}}})
second_update({{'body': {RIGHT!r}}}, 0, resource)
assert early == 1''')
    result, _, _, _ = candidates(code)
    assert not result['candidates']
    assert result['skipped']['following_source_observation_not_recovered']


def go_source(actions):
    return f'''package sample
import "testing"
type Resource struct {{ values []map[string]string }}
func create(value map[string]string) (int, *Resource) {{ return 0, &Resource{{values: []map[string]string{{value}}}} }}
func update(r *Resource, value map[string]string) {{ r.values=append(r.values,value) }}
func TestVersions(t *testing.T) {{
{actions}
}}
'''


def test_go_multiple_creator_results_keep_distinct_output_roots(tmp_path):
    code = go_source(f'''_, resource := create(map[string]string{{"body":{json.dumps(BASE)}}})
alias := resource
update(alias,map[string]string{{"body":{json.dumps(LEFT)}}})
update(resource,map[string]string{{"body":{json.dumps(RIGHT)}}})
if len(resource.values)!=3 {{ t.Fatal("count") }}''')
    result, corpus, _, _ = candidates(code, 'go')
    assert result['candidates'], result
    links = result['candidates'][0]['relation']['alignment']['source_links']
    assert all(row['result_projection'] == 'distinct_source_assignment_target' for row in links)
    emitted = emit(corpus, result['candidates'][:1])
    assert not emitted['unsupported']
    if shutil.which('go'):
        for path, body in emitted['files'].items():
            (tmp_path / path).write_text(body)
        process = subprocess.run(['go', 'test', './...'], cwd=tmp_path, capture_output=True, text=True,
                                 env=dict(os.environ, GO111MODULE='off'), timeout=60)
        assert process.returncode == 0, process.stdout + process.stderr


def test_two_outputs_of_one_call_are_not_assumed_to_alias():
    code = python_source(f'''one, two = make_pair({{'body': {BASE!r}}})
first_update(one, {{'body': {LEFT!r}}})
first_update(two, {{'body': {RIGHT!r}}})
assert len(one.values) == 2''')
    result, _, frontend, roots = candidates(code)
    assert not result['candidates']
    call = next(call for call in frontend['calls'] if call['callee'] == 'make_pair')
    assert len({row['root_id'] for row in roots.associations(call)}) == 2


def test_go_block_shadow_does_not_replace_outer_resource_binding():
    code = go_source(f'''_, resource := create(map[string]string{{"body":{json.dumps(BASE)}}})
{{ _, resource := create(map[string]string{{"body":"unrelated"}}); _ = resource }}
update(resource,map[string]string{{"body":{json.dumps(LEFT)}}})
update(resource,map[string]string{{"body":{json.dumps(RIGHT)}}})
if len(resource.values)!=3 {{ t.Fatal("count") }}''')
    result, _, _, _ = candidates(code, 'go')
    assert result['candidates'], result
    links = result['candidates'][0]['relation']['alignment']['source_links']
    assert len({link['root_id'] for link in links}) == 1


def test_typescript_new_result_and_actions_are_source_aligned():
    code = f'''class Resource {{ constructor(value: any) {{}} put(value: any) {{}} count() {{return 3;}} }}
test('versions', () => {{
 const resource = new Resource({{body:{json.dumps(BASE)}}});
 const alias = resource;
 alias.put({{body:{json.dumps(LEFT)}}});
 resource.put({{body:{json.dumps(RIGHT)}}});
 expect(resource.count()).toBe(3);
}});'''
    result, corpus, _, _ = candidates(code, 'typescript')
    assert result['candidates'], result
    emitted = emit(corpus, result['candidates'][:1])
    assert not emitted['unsupported']
    assert all(not Source(path, body, 'typescript').root.has_error for path, body in emitted['files'].items())


def test_same_spelling_in_separate_tests_never_combines_resources():
    code = PYTHON_SETUP + f'''\ndef test_first():
    resource = factory({{'body': {BASE!r}}})
    first_update(resource, {{'body': {LEFT!r}}})
    assert len(resource.values) == 2
def test_second():
    resource = factory({{'body': 'unrelated'}})
    first_update(resource, {{'body': {RIGHT!r}}})
    assert len(resource.values) == 2
'''
    result, _, _, _ = candidates(code)
    assert not result['candidates']


def test_guarded_action_keeps_operation_payload_and_excludes_check_only_slots():
    code = PYTHON_SETUP + f'''
def guarded(resource, value, expected):
    assert value
    resource.values = resource.values + [value]
    events.append('action')
    assert expected

def test_versions():
    resource = factory({{'body': {BASE!r}}})
    guarded(resource, {{'body': {LEFT!r}}}, {{'body': {BASE!r}}})
    guarded(resource, {{'body': {RIGHT!r}}}, {{'body': {LEFT!r}}})
    assert len(resource.values) == 3
'''
    result, corpus, frontend, roots = candidates(code)
    assert result['candidates'], result
    guarded_calls = [c for c in frontend['calls'] if c['callee'] == 'guarded']
    assert all(c['role'] == 'assertion' and c['operation_eligible'] for c in guarded_calls)
    assert all(c['operation_argument_slots'] == [0, 1] for c in guarded_calls)
    expected_spans = [c['arguments'][2]['span'] for c in guarded_calls]
    for candidate in result['candidates']:
        for edit in candidate['edits']:
            assert not any(span['start_byte'] <= edit['span']['start_byte'] < span['end_byte'] for span in expected_spans)
    assert execute(corpus, result['candidates'][0])['events'] == ['create', 'action', 'action']


def test_guarded_go_action_resource_root_alignment_is_available():
    code = go_source(f'''_, resource := create(map[string]string{{"body":{json.dumps(BASE)}}})
guarded(t, resource,map[string]string{{"body":{json.dumps(LEFT)}}})
guarded(t, resource,map[string]string{{"body":{json.dumps(RIGHT)}}})
if len(resource.values)!=3 {{ t.Fatal("count") }}''')
    code += '\nfunc guarded(t *testing.T, r *Resource, value map[string]string) { if len(value)==0 { t.Fatal("empty") }; r.values=append(r.values,value) }\n'
    result, _, frontend, _ = candidates(code, 'go')
    assert result['candidates'], result
    assert all(c['operation_eligible'] for c in frontend['calls'] if c['callee'] == 'guarded')
