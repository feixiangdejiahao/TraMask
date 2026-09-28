"""Independent parser field examples; no discovery subjects or reports."""
import ast
import json

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relational_gap.parsed_field_coordinates import (
    ParsedFieldBudget, extract_parsed_coordinates, generate_parsed_field_cells,
)


BASE = '''import re
PATTERN = re.compile(r'<(.*)>')
def parse(value):
    match = PATTERN.fullmatch(value)
    if match is None:
        return ()
    head, body, tail = match.group(1).split(';')
    name, count = body.split(':')
    return head, name, count, tail
def test_first():
    assert len(parse('<a;red:1;z>')) == 4
def test_second():
    assert len(parse('<b;blue:2;y>')) == 4
'''


def fixture(code=BASE, **kwargs):
    texts = code if isinstance(code, dict) else {'test_fields.py': code}
    frontend = extract_frontend([Source(path, text, 'python') for path, text in texts.items()])
    corpus = to_emitter_corpus(frontend)
    return corpus, frontend, generate_parsed_field_cells(corpus, frontend, **kwargs)


def values(result):
    return {ast.literal_eval(candidate['edits'][0]['after']) for candidate in result['candidates']}


def simple(body, first='a;b;c', second='x;y;z'):
    return f'''import re
def parse(value):
    match = re.fullmatch(r'(.*)', value)
{body}
def test_first(): assert parse({first!r}) is not None
def test_second(): assert parse({second!r}) is not None
'''


def test_nested_unpacking_refines_capture_and_executes_without_changing_neighbors():
    corpus, frontend, result = fixture()
    assert len(result['coordinates']) == 4
    assert len(result['candidates']) == 8
    assert values(result) == {
        '<b;red:1;z>', '<a;blue:1;z>', '<a;red:2;z>', '<a;red:1;y>',
        '<a;blue:2;y>', '<b;red:2;y>', '<b;blue:1;y>', '<b;blue:2;z>',
    }
    assert {len(c['steps']) for c in result['coordinates']} == {1, 2}
    assert all(c['relation']['binding_status'] == 'source_actual_formal_flow' for c in result['candidates'])
    assert result == generate_parsed_field_cells(corpus, frontend)
    json.dumps(result)
    output = emit(corpus, result['candidates'])
    assert not output['unsupported']
    namespace = {}
    exec(output['files']['test_fields.py'], namespace)
    for row in output['obligations'] + output['controls']:
        namespace[row['test_name']]()


def test_source_assignment_aliases_and_constant_subscripts():
    code = simple('''    captured = match.group(1)
    alias = captured
    fields = alias.split(';')
    chosen = fields[1]
    return chosen''')
    _, _, result = fixture(code)
    assert values(result) == {'a;y;c', 'x;b;z'}
    assert result['coordinates'][0]['steps'] == [{'delimiter': ';', 'maxsplit': -1, 'index': 1, 'arity': None}]


def test_named_capture_and_group_tuple_unpacking():
    code = r'''import re
def parse(value):
    match = re.fullmatch(r'(?P<left>[^|]+)\|(?P<right>.+)', value)
    left, right = match.group('left', 'right')
    return left.split(':')[0], right.split(':')[1]
def test_first(): assert len(parse('a:1|b:2')) == 2
def test_second(): assert len(parse('x:3|y:4')) == 2
'''
    _, _, result = fixture(code)
    assert values(result) == {'x:1|b:2', 'a:1|b:4', 'a:3|y:4', 'x:3|y:2'}


def test_groups_unpacking_and_exact_arity_are_source_constraints():
    code = r'''import re
def parse(value):
    match = re.fullmatch(r'([^|]+)\|(.+)', value)
    left, right = match.groups()
    return left.split(':')[0], right.split(':')[1]
def test_first(): assert len(parse('a:1|b:2')) == 2
def test_second(): assert len(parse('x:3|y:4')) == 2
'''
    _, _, result = fixture(code)
    assert len(result['candidates']) == 4
    assert {coordinate['group_arity'] for coordinate in result['coordinates']} == {2}
    _, _, wrong = fixture(code.replace('left, right = match.groups()', 'left, right, extra = match.groups()'))
    assert not wrong['candidates']


def test_split_maxsplit_negative_index_and_module_constant_delimiter():
    code = simple('''    fields = match.group(1).split(SEP, maxsplit=1)
    return fields[-1]''').replace('import re', "import re\nSEP = ';'")
    _, _, result = fixture(code)
    assert values(result) == {'a;y;z', 'x;b;c'}


def test_local_delimiter_constant_and_reassignment_use_site_binding():
    code = simple('''    sep = ';'
    fields = match.group(1).split(sep)
    sep = ':'
    return fields[1]''')
    _, _, result = fixture(code)
    assert values(result) == {'a;y;c', 'x;b;z'}


def test_reassigned_match_after_capture_keeps_original_string_binding():
    code = simple('''    captured = match.group(1)
    match = None
    return captured.split(';')[1]''')
    assert values(fixture(code)[2]) == {'a;y;c', 'x;b;z'}


def test_branch_rebinding_is_unknown_and_does_not_restore_module_name():
    code = simple('''    fields = match.group(1).split(';')
    if value:
        fields = ['unrelated']
    return fields[0]''')
    result = fixture(code)[2]
    assert not result['candidates']
    assert 'ambiguous_branch_binding' in {row['kind'] for row in result['unknowns']}


def test_guarded_capture_use_and_walrus_match():
    code = '''import re
def parse(value):
    if (match := re.fullmatch(r'(.*)', value)):
        return match.group(1).split(';')[1]
    return None
def test_first(): assert parse('a;b;c') is not None
def test_second(): assert parse('x;y;z') is not None
'''
    assert values(fixture(code)[2]) == {'a;y;c', 'x;b;z'}


@pytest.mark.parametrize('operation', [
    "fields[0] = 'changed'", 'fields.reverse()', 'consume(fields)', 'alias[0] = \'changed\'',
    'consume((fields,))', 'del fields[0]', "for _ in range(2): fields[0] = 'changed'",
    'for _ in range(2): consume(fields)',
    'holder = {"items": fields}; consume(holder)', 'sink.parts = fields; mutate_sink()',
    "fields[mutate(fields)]", "match.group(1).split(mutate(fields))",
    'holder = [fields for _ in range(2)]',
])
def test_split_list_mutation_and_escape_invalidate_aliases(operation):
    code = simple(f'''    fields = match.group(1).split(';')
    alias = fields
    {operation}
    return fields[1]''')
    _, _, result = fixture(code)
    assert not result['candidates']
    assert result['unknowns']


def test_nested_callable_capture_cannot_hide_split_list_mutation():
    code = simple('''    def mutate():
        fields.reverse()
    fields = match.group(1).split(';')
    mutate()
    return fields[0]''')
    _, _, result = fixture(code)
    assert not result['candidates']
    assert 'deferred_scope_may_mutate_capture_list' in {row['kind'] for row in result['unknowns']}


def test_escaping_lambda_capture_cannot_hide_split_list_mutation():
    code = simple('''    fields = match.group(1).split(';')
    register(lambda: fields.reverse())
    return fields[0]''')
    assert not fixture(code)[2]['candidates']


def test_reverse_container_alias_cannot_restore_mutated_split_list():
    code = simple('''    fields = match.group(1).split(';')
    box = (fields,)
    consume(fields)
    return box[0][1]''')
    assert not fixture(code)[2]['candidates']


def test_match_subscript_and_empty_fallback_retain_capture_identity():
    code = simple("    value = match[1] or ''\n    return value.split(';')[1]")
    assert values(fixture(code)[2]) == {'a;y;c', 'x;b;z'}


@pytest.mark.parametrize('region', ['while True:', 'for unused in [0]:', 'try:'])
def test_fresh_regex_match_inside_loop_or_try_has_local_coordinates(region):
    code = '''import re
def parse(value):
    REGION
        match = re.fullmatch(r'(.*)', value)
        fields = match[1].split(';')
        return fields[1]
    SUFFIX
def test_first(): assert parse('a;b;c') is not None
def test_second(): assert parse('x;y;z') is not None
'''.replace('REGION', region).replace('SUFFIX', 'except ValueError: return None' if region == 'try:' else '')
    _, _, result = fixture(code)
    assert values(result) == {'a;y;c', 'x;b;z'}
    assert all(c['control_flow_status'] == 'local_match_region_runtime_unresolved' for c in result['coordinates'])


def test_loop_carried_capture_binding_is_not_reused_for_new_match():
    code = '''import re
def parse(value):
    old = None
    while True:
        match = re.fullmatch(r'(.*)', value)
        return old[1].split(';')[1]
def test_first(): assert parse('a;b;c') is not None
def test_second(): assert parse('x;y;z') is not None
'''
    assert not fixture(code)[2]['candidates']


def test_local_region_match_reassignment_and_mutation_stay_unknown():
    code = '''import re
def parse(value):
    while True:
        match = re.fullmatch(r'(.*)', value)
        match = unrelated(value)
        return match[1].split(';')[1]
def test_first(): assert parse('a;b;c') is not None
def test_second(): assert parse('x;y;z') is not None
'''
    assert not fixture(code)[2]['candidates']


def test_resolved_helper_receives_match_and_preserves_reordered_keyword_formals():
    code = simple("    return refine(unused=0, found=match)")
    code = code.replace('def parse(value):', "def refine(found, unused):\n    return found[1].split(';')[1]\ndef parse(value):")
    _, _, result = fixture(code)
    assert values(result) == {'a;y;c', 'x;b;z'}
    assert result['coordinates'][0]['source_call_bindings'][0]['binding_status'] == 'direct_actual_formal'


def test_resolved_receiver_method_maps_explicit_actual_after_self():
    code = '''import re
class Parser:
    def refine(self, unused, found):
        return found[1].split(';')[1]
    def parse(self, value):
        match = re.fullmatch(r'(.*)', value)
        return self.refine(0, match)
def test_first(): assert Parser().parse('a;b;c') is not None
def test_second(): assert Parser().parse('x;y;z') is not None
'''
    assert values(fixture(code)[2]) == {'a;y;c', 'x;b;z'}


def test_unpacked_capture_string_is_forwarded_through_import_alias():
    code = {
        'fields.py': "def refine(unused, text):\n    return text.split(';')[1]\n",
        'parser.py': '''import re
from fields import refine as alias
def parse(value):
    match = re.fullmatch(r'(.*)', value)
    captured, = match.groups()
    return alias(0, captured)
''',
        'test_fields.py': "from parser import parse\ndef test_first(): assert parse('a;b;c') is not None\ndef test_second(): assert parse('x;y;z') is not None\n",
    }
    _, _, result = fixture(code)
    assert values(result) == {'a;y;c', 'x;b;z'}
    assert {s['path'] for s in result['coordinates'][0]['source_spans']} == {'fields.py', 'parser.py'}


def test_helper_parameter_shadowing_does_not_keep_capture_symbol():
    code = simple("    return refine(match)").replace('def parse(value):', "def refine(found):\n    found = unrelated()\n    return found[1].split(';')[1]\ndef parse(value):")
    assert not fixture(code)[2]['candidates']


def test_callable_formal_shadowing_does_not_resolve_by_function_name():
    code = simple("    return refine(match)").replace('def parse(value):', "def refine(found):\n    return found[1].split(';')[1]\ndef parse(value, refine=None):")
    _, _, result = fixture(code)
    assert not result['candidates']
    assert 'capture_call_target_unresolved' in {u['kind'] for u in result['unknowns']}


def test_helper_can_return_split_carrier_for_caller_subscript():
    code = simple("    fields = refine(match)\n    return fields[1]").replace('def parse(value):', "def refine(found):\n    return found[1].split(';')\ndef parse(value):")
    assert values(fixture(code)[2]) == {'a;y;c', 'x;b;z'}


def test_unshadowed_length_guard_does_not_invalidate_split_input():
    code = simple("    fields = match[1].split(';')\n    return fields[1] if len(fields) > 1 else None")
    assert values(fixture(code)[2]) == {'a;y;c', 'x;b;z'}
    shadow = code.replace('def parse(value):', 'def parse(value, len=None):')
    assert not fixture(shadow)[2]['candidates']


def test_helper_try_body_refines_proven_immutable_capture_formal():
    code = simple("    return refine(match[1])").replace('def parse(value):', "def refine(text):\n    try:\n        return text.split(';')[1]\n    except ValueError:\n        return None\ndef parse(value):")
    _, _, result = fixture(code)
    assert values(result) == {'a;y;c', 'x;b;z'}
    assert result['coordinates'][0]['control_regions']


def test_source_call_depth_is_bounded_without_name_guess_fallback():
    helpers = "def f1(found): return f2(found)\ndef f2(found): return found[1].split(';')[1]\n"
    code = simple("    return f1(match)").replace('def parse(value):', helpers + 'def parse(value):')
    _, _, limited = fixture(code, budget=ParsedFieldBudget(max_call_depth=1))
    assert not limited['candidates']
    assert 'capture_call_depth_or_recursion_budget' in {u['kind'] for u in limited['unknowns']}
    _, _, deeper = fixture(code)
    assert values(deeper) == {'a;y;c', 'x;b;z'}


def test_conditional_empty_split_fallback_preserves_source_path_as_unknown():
    code = simple("    captured = match[1]\n    fields = captured.split(';') if captured else []\n    return fields[1] if len(fields) > 1 else None")
    _, _, result = fixture(code)
    assert values(result) == {'a;y;c', 'x;b;z'}
    assert 'conditional_capture_value_applicability_unresolved' in {u['kind'] for u in result['unknowns']}


@pytest.mark.parametrize('expression', [
    '[int(part) for part in match[1].split(";")]',
    'tuple(int(part) for part in match[1].split(";") if part)',
    'list(map(int, match[1].split(";")))',
])
def test_source_split_iteration_expands_only_finite_source_ordinals(expression):
    code = simple('    return ' + expression, first='1;2;3', second='4;5;6')
    corpus, _, result = fixture(code)
    assert values(result) == {'4;2;3', '1;5;3', '1;2;6', '1;5;6', '4;2;6', '4;5;3'}
    assert len(result['coordinates']) == 1
    assert result['coordinates'][0]['steps'][0]['index'] == '*'
    assert {c['relation']['steps'][0]['index'] for c in result['candidates']} == {0, 1, 2}
    assert all(c['provenance']['coordinate']['iteration_status'].endswith('semantics_unknown') for c in result['candidates'])
    output = emit(corpus, result['candidates'])
    namespace = {}
    exec(output['files']['test_fields.py'], namespace)
    for row in output['obligations'] + output['controls']:
        namespace[row['test_name']]()


def test_nested_iteration_and_split_index_form_hierarchical_leaf_paths():
    code = simple("    return [part.split(':')[1] for part in match[1].split(';')]", first='a:1;b:2', second='x:3;y:4')
    _, _, result = fixture(code)
    assert values(result) == {'a:3;b:2', 'a:1;b:4', 'x:1;y:4', 'x:3;y:2'}
    assert all(len(c['relation']['steps']) == 2 for c in result['candidates'])


def test_iteration_mapper_that_mutates_split_carrier_remains_unknown():
    code = simple("    fields = match[1].split(';')\n    return [mutate(fields) for part in fields]")
    _, _, result = fixture(code)
    assert not result['candidates']
    assert 'split_iteration_may_mutate_input' in {u['kind'] for u in result['unknowns']}


def test_map_callable_shadow_does_not_assume_mapper_purity():
    code = simple("    return list(map(int, match[1].split(';')))", first='1;2', second='3;4')
    assert not fixture(code.replace('def parse(value):', 'def parse(value, int=None):'))[2]['candidates']


def test_iteration_expansion_obeys_coordinate_and_attempt_budgets():
    code = simple("    return [int(part) for part in match[1].split(';')]", first='1;2;3;4;5', second='6;7;8;9;0')
    _, _, result = fixture(code, budget=ParsedFieldBudget(max_coordinates=2, max_attempts=3))
    assert result['counts']['attempts'] <= 3
    assert {c['relation']['steps'][0]['index'] for c in result['candidates']} <= {0, 1}


@pytest.mark.parametrize('body,reason', [
    ("    return match.group(1).split()[0]", 'nonconstant_or_whitespace_split'),
    ("    return match.group(1).split(value)[0]", 'nonconstant_or_whitespace_split'),
    ("    return match.group(1).split(';')[len(value)]", 'nonconstant_split_index'),
    ("    a, *rest = match.group(1).split(';')\n    return rest", 'starred_unpacking_unsupported'),
])
def test_ambiguous_or_unsupported_split_flow_is_explicit_unknown(body, reason):
    _, _, result = fixture(simple(body))
    assert not result['candidates']
    assert reason in {row['kind'] for row in result['unknowns']}


def test_split_arity_rejects_source_strings_that_cannot_follow_parser_path():
    code = simple("    a, b, c = match.group(1).split(';')\n    return a, b, c", second='x;y')
    assert not fixture(code)[2]['candidates']


def test_source_split_limit_outside_python_index_domain_does_not_crash_generator():
    code = simple("    return match.group(1).split(';', 9999999999999999999999999)[0]")
    assert not fixture(code)[2]['candidates']


def test_transport_cannot_introduce_outer_delimiter_through_nested_field():
    # Source parser takes the first semicolon field then the suffix after colon.
    # Both witnesses remain valid; donor value's inner content must not change
    # either outer split count or neighboring source-defined coordinates.
    code = simple("    return match.group(1).split(';', 1)[1].split(':', 1)[1]", first='a;b:one', second='x;y:two;tail')
    _, _, result = fixture(code)
    assert values(result) == {'a;b:two;tail', 'x;y:one'}


def test_alternative_overlapping_split_coordinates_are_not_independent():
    code = simple("    captured = match.group(1)\n    return captured.split(';')[0], captured.split(':')[0]", first='a:b;c', second='x:y;z')
    _, _, result = fixture(code)
    assert not result['candidates']
    assert result['counts']['skipped']['overlapping_parser_coordinates']


def test_unrelated_regex_group_backreference_blocks_changed_leaf():
    code = simple("    return match.group(1).split(';')[0]", first='a;b=a;b', second='x;y=x;y')
    code = code.replace("r'(.*)'", "r'([^=]+)=\\1'")
    _, _, result = fixture(code)
    assert not result['candidates']
    assert result['counts']['skipped']['regex_rematch_changed_other_coordinate_or_invalid']


def test_nested_regex_wrapper_capture_can_anchor_finer_split_leaf():
    code = simple("    return match.group(1).split(';')[1]").replace("r'(.*)'", "r'((.*))'")
    _, _, result = fixture(code)
    assert values(result) == {'a;y;c', 'x;b;z'}
    assert {c['relation']['regex_validation_group'] for c in result['candidates']} == {2}


def test_unicode_source_offsets_and_uncaptured_prefix_are_preserved():
    code = simple("    return match.group(1).split(';')[1]", first='雪[a;红;c]尾', second='別[x;蓝;z]終')
    code = code.replace('re.fullmatch', 're.search').replace("r'(.*)'", "r'\\[(.*)\\]'")
    _, _, result = fixture(code)
    assert values(result) == {'雪[a;蓝;c]尾', '別[x;红;z]終'}
    selected = next(c for c in result['candidates'] if c['relation']['before'] == '红')
    assert selected['relation']['capture_coordinate'] == {'unicode_span': [4, 5], 'utf8_span': [6, 9]}
    for span in selected['provenance']['source_spans']:
        assert code.encode()[span['start_byte']:span['end_byte']].decode()


def test_parameterized_fstring_restricts_entire_source_row_and_paired_ids():
    code = '''import re
import pytest
def parse(value):
    match = re.fullmatch(r'(.*)', value)
    return match.group(1).split(';')[1]
@pytest.mark.parametrize('head,body,tail,expected', [('a','red','z',True), ('b','blue','y',True)], ids=['red','blue'])
def test_rows(head,body,tail,expected):
    assert bool(parse(f'{head};{body};{tail}')) is expected
'''
    corpus, _, result = fixture(code)
    assert values(result) == {'a;blue;z', 'b;red;y'}
    assert result['finite_inputs']['added'] == 2
    assert all(len(c['edits']) == 3 for c in result['candidates'])
    output = emit(corpus, result['candidates'])
    assert not output['unsupported']
    namespace = {}
    exec(output['files']['test_fields.py'], namespace)
    for row in output['obligations']:
        fn = namespace[row['test_name']]
        args = fn.pytestmark[0].args[1][0]
        fn(*args)


def test_import_proof_rejects_shadowed_regex_module_and_arbitrary_strings():
    code = simple("    return match.group(1).split(';')[1]")
    assert not fixture(code.replace('def parse(value):', 'def parse(value, re=None):'))[2]['patterns']
    assert not fixture(code.replace('re.fullmatch', 'unrelated'))[2]['patterns']


def test_source_wrapper_forwarding_has_exact_binding_path():
    corpus, frontend, _ = fixture()
    code = {
        'parser.py': BASE[:BASE.index('def test_first')],
        'wrapper.py': 'from parser import parse\ndef wrap(value): return parse(value)\n',
        'test_fields.py': "from wrapper import wrap\ndef test_one(): assert len(wrap('<a;red:1;z>')) == 4\ndef test_two(): assert len(wrap('<b;blue:2;y>')) == 4\n",
    }
    _, _, result = fixture(code)
    assert len(result['candidates']) == 8
    assert all(len(c['relation']['binding_path']) == 2 for c in result['candidates'])


def test_budgets_bound_coordinates_attempts_output_and_preserve_test_fairness():
    _, _, result = fixture(budget=ParsedFieldBudget(max_candidates=2, max_attempts=8))
    assert len(result['candidates']) == 2
    assert len({c['base_test_id'] for c in result['candidates']}) == 2
    assert result['counts']['attempts'] <= 8
    _, _, small = fixture(budget=ParsedFieldBudget(max_split_depth=1))
    assert all(len(c['steps']) <= 1 for c in small['coordinates'])
    assert 'split_depth_budget' in {u['kind'] for u in small['unknowns']}
    with pytest.raises(ValueError):
        ParsedFieldBudget(max_split_depth=0)


def test_extraction_api_is_separate_from_candidate_enumeration():
    corpus, frontend, result = fixture()
    extracted = extract_parsed_coordinates(corpus, frontend)
    assert extracted['coordinates'] == result['coordinates']
    assert extracted['patterns'] == result['patterns']
