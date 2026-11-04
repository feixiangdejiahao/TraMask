"""Real AST region selection and literal-source byte-coordinate examples."""
import json

import pytest

from eviweave.evidence import SourceGraph
from eviweave.regions import RegionIndex


def indexed(code, suffix='.py'):
    graph = SourceGraph({'id': 'example', 'path': 'example' + suffix, 'raw': code.encode()})
    assert not graph.issues
    return RegionIndex(graph)


def select(index, text):
    start = index.graph.raw.index(text.encode())
    return index.select(start, start+len(text.encode()))


def text(index, region):
    a, b = region['range']
    return index.graph.raw[a:b].decode()


def flatten(term):
    pending = [term]
    while pending:
        current = pending.pop()
        yield current
        pending.extend(child for _, child in current['children'])


def test_literal_and_field_regions_do_not_become_test_registration_calls():
    source = 'it("case", () => { const payload = {answer: [1, 2], other: 3}; expect(payload.answer).toEqual([1,2]); });'
    index = indexed(source, '.ts')
    result = select(index, '[1, 2]')
    assert result['status'] == 'exact'
    region = result['selected'][0]
    assert region['kind'] == 'sequence_literal'
    assert region['role'] == 'field_value'
    assert region['field_keys'] == ['answer']
    assert text(index, region) == '[1, 2]'
    field = select(index, 'answer: [1, 2]')['selected'][0]
    assert field['kind'] == 'field'
    assert index.features(field)['keys'] == ['answer']
    assert all(candidate['range'] == result['range'] for candidate in result['exact'])


@pytest.mark.parametrize('suffix,code,needle,expected', [
    ('.py', 'def check():\n data=(1, 2)\n assert data[0] == 1\n assert len(data) == 2\n',
     'assert data[0] == 1\n assert len(data) == 2', ['assert data[0] == 1', 'assert len(data) == 2']),
    ('.ts', 'it("case", () => { let a=1; expect(a).toBe(1); expect(a+1).toBe(2); });',
     'expect(a).toBe(1); expect(a+1).toBe(2);', ['expect(a).toBe(1);', 'expect(a+1).toBe(2);']),
    ('.go', 'package p\nfunc f() { a:=1; consume(a); check(a) }',
     'consume(a); check(a)', ['consume(a)', 'check(a)']),
    ('.rs', 'fn f() { let a=1; consume(a); check(a); }',
     'consume(a); check(a);', ['consume(a);', 'check(a);']),
])
def test_multistatement_selection_is_a_node_set(suffix, code, needle, expected):
    index = indexed(code, suffix)
    result = select(index, needle)
    assert result['status'] == 'node_set'
    assert [text(index, r) for r in result['selected']] == expected
    assert all(result['range'][0] <= r['range'][0] <= r['range'][1] <= result['range'][1] for r in result['selected'])
    assert all(r['ast_type'] not in {'function_definition', 'call_expression', 'function_item'} for r in result['selected'])


def test_whole_python_body_still_selects_its_statements_as_a_set():
    index = indexed('def f(x):\n assert x\n assert x > 0\n')
    result = select(index, 'assert x\n assert x > 0')
    assert any(r['ast_type'] == 'block' for r in result['exact'])
    assert result['status'] == 'node_set'
    assert [r['ast_type'] for r in result['selected']] == ['assert_statement', 'assert_statement']


def test_scope_features_exclude_nested_callbacks_and_terms_share_subtrees():
    index = indexed('def outer(x):\n consume(x)\n def nested():\n  unrelated()\n assert x\n')
    outer = next(r for r in index.regions if r['ast_type'] == 'function_definition' and r['range'][0] == 0)
    assert outer['candidate'] is False
    assert outer['contains_scope_boundary'] is True
    assert index.features(outer)['calls'] == ['consume']
    body = next(r for r in index.regions if r['ast_type'] == 'block' and r['parent'] == outer['id'])
    assert body['kind'] == 'observation_block'
    assert body['scope'] != outer['scope']
    call = select(index, 'consume(x)')['selected'][0]
    term = index.term(call)
    position = index.graph.raw.index(b'x', call['range'][0])
    leaf = index.select(position, position+1)['selected'][0]
    matching = next(t for t in flatten(term) if t['span'] == leaf['range'] and t['kind'] == 'reference')
    assert index.term(leaf) is matching
    assert matching['value'].endswith(':x')


@pytest.mark.parametrize('suffix,code,needle,kind', [
    ('.py', 'x={"answer": (1,2)}\n', '(1,2)', 'sequence_literal'),
    ('.js', 'const x={answer: [1,2]};', '[1,2]', 'sequence_literal'),
    ('.go', 'package p\nvar x = []int{1,2}', '[]int{1,2}', 'composite_literal'),
    ('.rs', 'fn f() { let x = Foo { answer: [1,2] }; }', 'Foo { answer: [1,2] }', 'object_literal'),
])
def test_language_literal_regions(suffix, code, needle, kind):
    index = indexed(code, suffix)
    region = select(index, needle)['selected'][0]
    assert region['kind'] == kind
    assert text(index, region) == needle


def test_embedded_go_raw_program_has_original_source_spans():
    source = 'package host\nfunc f() { src := `package p\nfunc value() int { return 7 }`; _ = src }'
    index = indexed(source, '.go')
    result = select(index, 'return 7')
    region = result['selected'][0]
    assert result['status'] == 'exact'
    assert region['embedded_language'] == 'go'
    assert region['ast_type'] == 'return_statement'
    assert text(index, region) == 'return 7'
    returned = next(t for t in flatten(index.term(region)) if t['kind'] == 'int_literal')
    assert source.encode()[slice(*returned['span'])] == b'7'
    embedded = next(e for e in index.embeddings if e['status'] == 'parsed_syntax')
    assert embedded['offset_map'] == [{'decoded': [0, 39], 'source': [32, 71], 'kind': 'identity'}]
    whole_input = index.by_id[embedded['id']]
    whole_term = index.term(whole_input)
    assert whole_term['kind'] == 'embedded_input:go'
    assert whole_term['span'] == whole_input['range']
    assert whole_term['children'][0][1] is index.term(embedded['root'])


def test_embedded_go_escaped_program_maps_the_escape_not_decoded_offsets():
    source = 'src = "package p\\nfunc f() string { return \\"é\\" }"\n'
    index = indexed(source)
    region = select(index, 'return \\"é\\"')['selected'][0]
    assert region['embedded_language'] == 'go'
    assert text(index, region) == 'return \\"é\\"'
    literal = next(t for t in flatten(index.term(region)) if t['kind'] == 'interpreted_string_literal')
    assert index.graph.raw[slice(*literal['span'])].decode() == '\\"é\\"'
    assert literal['value'] == '"é"'


def test_validated_json_input_maps_field_and_unicode_escape_exactly():
    source = r'''payload = '{"answer": [1, 2], "name": "\\u03bb"}'
'''
    index = indexed(source)
    region = select(index, '"answer": [1, 2]')['selected'][0]
    assert region['embedded_language'] == 'json'
    assert region['kind'] == 'field'
    assert index.features(region)['keys'] == ['answer']
    assert all(region['range'][0] <= n['span'][0] <= n['span'][1] <= region['range'][1] for n in flatten(index.term(region)))
    assert json.loads(json.dumps(index.term(region)))['kind'] == 'pair'


def test_host_unicode_escape_maps_decoded_json_character_to_whole_escape():
    index = indexed(r'''payload = '{"name": "\u03bb"}'
''')
    result = select(index, r'\u03bb')
    region = result['selected'][0]
    assert region['embedded_language'] == 'json'
    assert text(index, region) == r'\u03bb'
    assert index.term(region)['value'] == 'λ'


@pytest.mark.parametrize('suffix,code,needle', [
    ('.go', 'package p\nvar src = `a := func() { return 1 }`', 'func() { return 1 }'),
    ('.go', 'package p\nvar src = `package auth\nallow if { input.admin }`', 'allow if { input.admin }'),
    ('.rs', 'fn f() { let src = r#"(module (func (result i32) i32.const 1))"#; }', '(func (result i32) i32.const 1)'),
])
def test_unsupported_languages_remain_exact_opaque_fragments(suffix, code, needle):
    index = indexed(code, suffix)
    result = select(index, needle)
    assert result['status'] == 'opaque'
    region = result['selected'][0]
    assert text(index, region) == needle
    assert index.term(region)['value'] == needle
    assert index.features(region) == {'calls': [], 'members': [], 'keys': [], 'identifiers': []}
    assert not any('embedded_language' in r for r in index.regions)


def test_interpolated_literal_and_invalid_json_do_not_gain_input_ast():
    index = indexed('payload = f"{{{key}: 1}}"\nother = "{not json}"\n')
    assert all(e['status'] == 'opaque' for e in index.embeddings)
    assert any(e['reason'] == 'interpolated_literal' for e in index.embeddings)
    assert not any('embedded_language' in r for r in index.regions)


def test_reporter_member_in_real_javascript_template_is_host_ast():
    # The expression surrounding S081's F:lib/app.js endpoint.
    source = 'let e = new Error(`Bail out! ${report.bailReason} after ${report.testsRanBeforeBail} tests.`);'
    index = indexed(source, '.js')
    result = select(index, 'report.bailReason')
    assert result['status'] == 'exact'
    region = result['selected'][0]
    assert region['ast_type'] == 'member_expression'
    assert region['document'] == 'native'
    assert text(index, region) == 'report.bailReason'
    assert index.term(region)['kind'] == 'member_expression'
    assert index.features(region)['members'] == ['bailReason']
    assert select(index, 'Bail out! ')['status'] == 'opaque'
    assert select(index, 'Bail out! ${report.bailReason}')['status'] == 'opaque'


def test_string_literal_inside_interpolation_keeps_its_opaque_boundary():
    index = indexed('const result = `value: ${format("ordinary text")}`;', '.ts')
    expression = select(index, 'format("ordinary text")')
    assert expression['status'] == 'exact'
    assert expression['selected'][0]['ast_type'] == 'call_expression'
    literal = select(index, 'ordinary text')
    assert literal['status'] == 'opaque'
    assert index.term(literal['selected'][0])['value'] == 'ordinary text'


def test_python_formatted_string_interpolation_keeps_host_attribute():
    index = indexed('message = f"reason: {report.reason}"\n')
    expression = select(index, 'report.reason')
    assert expression['status'] == 'exact'
    assert expression['selected'][0]['ast_type'] == 'attribute'
    assert select(index, 'reason: ')['status'] == 'opaque'


def test_source_parse_error_is_retained_without_recovery_tree_regions():
    graph = SourceGraph({'id': 'bad', 'path': 'bad.py', 'raw': b'def f('})
    index = RegionIndex(graph)
    assert index.regions == []
    assert index.issues == graph.issues
    result = index.select(0, 3)
    assert result['status'] == 'fragment'
    assert index.term(result['selected'][0])['value'] == 'def'
