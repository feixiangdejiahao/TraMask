"""Generic authored source fixtures; no provider, execution, labels or oracles."""
import copy
import json

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search.call_default_evidence import analyze, render


def inputs(code, before, after, extra=None):
    path = 'tests/defaults.test.ts'
    sources = [Source(path, code, 'typescript')]
    sources.extend(Source(p, text, 'typescript') for p, text in (extra or {}).items())
    frontend = extract_frontend(sources)
    corpus = copy.deepcopy(to_emitter_corpus(frontend))
    test_id = next(iter(corpus['tests']))
    start = code.encode().index(before.encode(), corpus['tests'][test_id]['span']['start_byte'])
    candidate = dict(id='authored', base_test_id=test_id, imports=[], edits=[dict(
        span=dict(path=path, start_byte=start, end_byte=start + len(before.encode())),
        before=before, after=after, role='input')])
    return corpus, frontend, candidate


def project(*args, **kwargs):
    data = inputs(*args, **kwargs)
    original = copy.deepcopy(data)
    result = analyze(*data)
    assert data == original
    json.dumps(result)
    return result


def fact(result, path):
    return next(item for item in result['facts'] if item['field_path'] == path)


def test_renamed_local_default_is_exact_source_not_input_mutation():
    result = project('''
function choose(settings: Settings) {
  const {flavor = "淡"} = settings;
  return flavor;
}
test("source facts", () => { expect(choose({flavor: "浓"})).toBe("浓"); });
''', '{flavor: "浓"}', '{}')
    assert result['status'] == 'source_facts', result['unknowns']
    row = fact(result, ['flavor'])
    assert row['declaration']['text'] == 'const {flavor = "淡"} = settings;'
    assert row['default']['text'] == '"淡"'
    assert row['source_expression']['text'] == 'settings'
    assert row['modified_actual']['text'] == '{}'
    assert row['field_presence'] == {'status': 'syntax_missing', 'missing_at': ['flavor']}
    assert row['input_object_mutation'] == 'not_inferred'
    assert row['default_execution'] == 'not_proved'
    assert row['applicability'] == 'source_default_not_proved_on_all_paths'
    assert row['evidence_role'] == 'currentcandidatefact_notnormativeoracle'
    assert result['semantic_validity'] == 'unconfirmed' and not result['alarm_eligible']
    assert 'return flavor' not in render(result)


def test_nested_option_preserves_formals_and_forwarding_guards():
    result = project('''
function leaf({range: {floor = 7}}: Options) { return floor; }
function relay(payload: Options) {
  if (ready) return leaf(payload);
  return -1;
}
test("nested", () => { expect(relay({range: {floor: 2}})).toBe(2); });
''', '{range: {floor: 2}}', '{range: {}}')
    row = fact(result, ['range', 'floor'])
    assert row['field_presence']['missing_at'] == ['range', 'floor']
    assert row['declaration']['text'] == '{range: {floor = 7}}: Options'
    assert [edge['actual']['text'] for edge in row['forwarding_path']] == ['{range: {floor: 2}}', 'payload']
    assert row['forwarding_path'][0]['formal']['text'] == 'payload: Options'
    guard = row['forwarding_path'][1]['guards'][0]
    assert guard['condition']['text'] == '(ready)'
    assert guard['branch'] == 'consequence' and guard['reachability'] == 'not_proved'
    assert guard['ref']['version'] == 'original'


def test_default_inside_guard_preserves_condition_and_nullish_mechanism():
    result = project('''
function read(options: Options) {
  if (options.active) {
    const {label = "fallback"} = options;
    const cap = options.cap ?? 12;
    return [label, cap];
  }
}
test("guard", () => { expect(read({label: "x", cap: 3})).toBeDefined(); });
''', '{label: "x", cap: 3}', '{label: null, cap: null}')
    first, second = fact(result, ['label']), fact(result, ['cap'])
    assert first['mechanism'] == 'destructuring_default'
    assert second['mechanism'] == 'nullish_coalescing'
    assert second['declaration']['text'] == 'const cap = options.cap ?? 12;'
    assert all(row['guards'][0]['condition']['text'] == '(options.active)' for row in (first, second))
    assert all(row['field_presence']['status'] == 'syntax_present' for row in (first, second))
    assert all(row['field_presence']['value']['text'] == 'null' for row in (first, second))
    # Different default triggers are not collapsed into an inferred result.
    assert all(row['default_execution'] == 'not_proved' for row in (first, second))


METHOD_CODE = '''
class Vessel {
  read(options: Options) { const {shade = "gray"} = options; return shade; }
}
test("receiver", () => {
  const vessel = new Vessel();
  expect(vessel.read({shade: "red"})).toBe("red");
});
'''


def test_resolved_receiver_argument_edit_projects_existing_resolution():
    result = project(METHOD_CODE, '{shade: "red"}', '{}')
    row = fact(result, ['shade'])
    assert row['forwarding_path'][0]['resolution'] == 'source_constructor_receiver'
    assert row['runtime_receiver_identity'] == 'not_proved'


def test_receiver_edit_invalidates_mapping_even_when_a_default_is_known():
    result = project(METHOD_CODE, 'vessel.read({shade: "red"})', 'other.read({})')
    assert not result['facts']
    assert result['unknowns'][0]['reason'] == 'edits_not_within_one_call_arguments'


@pytest.mark.parametrize('after, reason', [
    ('{}, 4', 'callee_receiver_or_argument_slots_changed'),
    ('settings', 'modified_actual_not_object_literal'),
    ('{', 'modified_source_parse_error'),
])
def test_structural_argument_changes_are_explicit_unknown(after, reason):
    result = project('''
function read(options: Options) { const {tone = "soft"} = options; return tone; }
test("edits", () => { expect(read({tone: "loud"})).toBe("loud"); });
''', '{tone: "loud"}', after)
    assert not result['facts']
    assert any(row['reason'] == reason for row in result['unknowns'])


def test_unresolved_path_is_skipped_without_inventing_api_matches():
    data = inputs('''
function read(options: Options) { const {limit = 5} = options; return limit; }
test("metadata", () => { expect(read({limit: 2})).toBe(2); });
''', '{limit: 2}', '{}')
    data[1]['field_defaults'][0]['caller_bindings'][0]['resolution'] = 'unknown'
    result = analyze(*data)
    assert not result['facts']
    assert result['unknowns'][0]['reason'] == 'unresolved_actual_formal_path'


def test_missing_path_or_wrong_test_never_selects_a_similar_name():
    data = inputs('''
function read(options: Options) { const {limit = 5} = options; return limit; }
test("metadata", () => { expect(read({limit: 2})).toBe(2); });
''', '{limit: 2}', '{}')
    data[1]['field_defaults'][0]['caller_bindings'][0]['test_id'] = 'different-test'
    result = analyze(*data)
    assert not result['facts']
    assert result['unknowns'][0]['reason'] == 'no_applicable_resolved_field_default_path'


@pytest.mark.parametrize('after', ['{...other}', '{[name]: 1}', '{limit: 1, limit: 2}'])
def test_dynamic_or_duplicate_keys_do_not_prove_presence_or_absence(after):
    result = project('''
function read(options: Options) { const {limit = 5} = options; return limit; }
test("keys", () => { expect(read({limit: 2})).toBe(2); });
''', '{limit: 2}', after)
    assert fact(result, ['limit'])['field_presence']['status'] == 'unknown'


@pytest.mark.parametrize('change, expected', [
    ('imports', 'added_imports_mapping_not_revalidated'),
    ('before', 'frontend_expression_source_mismatch'),
    ('source', 'frontend_source_mismatch'),
])
def test_stale_sources_or_added_imports_are_not_projected(change, expected):
    data = inputs('''
function read(options: Options) { const {limit = 5} = options; return limit; }
test("stale", () => { expect(read({limit: 2})).toBe(2); });
''', '{limit: 2}', '{}')
    if change == 'imports':
        data[2]['imports'] = [dict(name='other', module='new-module')]
    elif change == 'before':
        data[2]['edits'][0]['before'] = '{limit: 3}'
    else:
        data[1]['sources']['tests/defaults.test.ts']['code'] += '\n// changed'
    result = analyze(*data)
    assert result['status'] == 'unknown' and not result['facts']
    assert result['unknowns'][0]['reason'] == expected


def test_import_forwarding_retains_exact_source_references_and_hashes():
    result = project('''
import { forward as invoke } from "../lib/forward";
test("import", () => { expect(invoke({limit: 2})).toBe(2); });
''', '{limit: 2}', '{}', extra={
        'lib/forward.ts': 'import { leaf } from "./leaf"; export function forward(config: Options) { if (enabled) return leaf(config); }',
        'lib/leaf.ts': 'export function leaf(config: Options) { const {limit = 5} = config; return limit; }',
    })
    row = fact(result, ['limit'])
    assert len(row['forwarding_path']) == 2
    assert row['declaration']['ref']['path'] == 'lib/leaf.ts'
    assert row['forwarding_path'][1]['call']['text'] == 'leaf(config)'
    assert row['forwarding_path'][1]['guards'][0]['condition']['text'] == '(enabled)'
    assert set(result['source_hashes']) == {'tests/defaults.test.ts', 'lib/forward.ts', 'lib/leaf.ts'}
    assert 'modified_sha256' not in result['source_hashes']['lib/leaf.ts']
    output = render(result)
    assert 'leaf(config)' in output and 'source_default_not_proved_on_all_paths' in output
    assert 'export function leaf' not in output


def test_two_distinct_call_edits_do_not_reuse_single_call_mapping():
    code = '''
function read(options: Options) { const {limit = 5} = options; return limit; }
test("two calls", () => { read({limit: 2}); read({limit: 3}); });
'''
    data = inputs(code, '{limit: 2}', '{}')
    start = code.index('{limit: 3}')
    data[2]['edits'].append(dict(span=dict(path='tests/defaults.test.ts', start_byte=start,
        end_byte=start + len('{limit: 3}')), before='{limit: 3}', after='{}', role='input'))
    result = analyze(*data)
    assert not result['facts']
    assert all(row['reason'] == 'edits_not_within_one_call_arguments' for row in result['unknowns'])


def test_multiple_argument_edits_preserve_exact_utf8_old_and_new_refs():
    code = '''
function read(options: Options, title: string) {
  const {label = "猫"} = options; return label;
}
test("bytes", () => { expect(read({label: "犬"}, "bird")).toBe("犬"); });
'''
    corpus, frontend, candidate = inputs(code, '{label: "犬"}', '{}')
    start = code.encode().index(b'"bird"')
    candidate['edits'].append(dict(span=dict(path='tests/defaults.test.ts', start_byte=start,
        end_byte=start + len(b'"bird"')), before='"bird"', after='"鳥鳥"', role='input'))
    result = analyze(corpus, frontend, candidate)
    assert result['status'] == 'source_facts', result['unknowns']
    current = code.encode()
    for edit in reversed(candidate['edits']):
        extent = edit['span']
        current = current[:extent['start_byte']] + edit['after'].encode() + current[extent['end_byte']:]

    def check(value):
        if isinstance(value, dict):
            if {'ref', 'text', 'omitted_chars'} <= value.keys():
                ref = value['ref']
                data = current if ref['version'] == 'modified' else corpus['sources'][ref['path']]['code'].encode()
                exact = data[ref['start_byte']:ref['end_byte']].decode()
                assert exact.startswith(value['text'])
                assert len(exact) - len(value['text']) == value['omitted_chars']
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    check(result)
    assert result['edits'][1]['modified']['text'] == '"鳥鳥"'


def test_long_default_is_marked_as_exact_prefix_with_full_source_ref():
    default = 'x' * 900
    code = (f'function read(options: Options) {{ const {{label = "{default}"}} = options; return label; }}\n'
            'test("long", () => { expect(read({label: "short"})).toBe("short"); });')
    result = project(code, '{label: "short"}', '{}')
    row = fact(result, ['label'])
    assert row['declaration']['omitted_chars'] > 0
    assert len(row['declaration']['text']) == 512
    ref = row['declaration']['ref']
    assert ref['end_byte'] - ref['start_byte'] > 900
    assert '[excerpt;' in render(result)
    assert len(render(result)) < 4000


def test_tampered_forwarding_argument_span_never_claims_a_path():
    data = inputs('''
function leaf(options: Options) { const {label = "x"} = options; return label; }
function relay(options: Options) { return leaf(options); }
test("path", () => { expect(relay({label: "y"})).toBe("y"); });
''', '{label: "y"}', '{}')
    data[1]['field_defaults'][0]['caller_bindings'][0]['path'][1]['argument_span']['start_byte'] += 1
    result = analyze(*data)
    assert not result['facts']
    assert result['unknowns'][0]['reason'] in {'actual_formal_metadata_mismatch', 'forwarding_call_source_mismatch'}
