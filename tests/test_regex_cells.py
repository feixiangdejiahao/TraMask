"""Source parser grammars, independent of discovery subjects and reports."""
import ast
import json

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relational_gap.regex_cells import RegexBudget, generate_regex_cells


def fixture(code, **kwargs):
    sources = [Source(path, text, 'python') for path, text in code.items()] if isinstance(code, dict) else [Source('test_records.py', code, 'python')]
    frontend = extract_frontend(sources)
    corpus = to_emitter_corpus(frontend)
    return corpus, frontend, generate_regex_cells(corpus, frontend, **kwargs)


BASE = '''import re
PATTERN = re.compile(r'(?P<word>[a-z]+):(?P<count>[0-9]+)')
def parse(value):
    return PATTERN.fullmatch(value) is not None
def test_first():
    assert parse("red:1") is True
def test_second():
    assert parse("blue:2") is True
'''


def values(result):
    return {ast.literal_eval(c['edits'][0]['after']) for c in result['candidates']}


def test_source_capture_coordinates_recombine_only_captured_values_and_execute():
    corpus, frontend, result = fixture(BASE)
    assert values(result) == {'red:2', 'blue:1'}
    assert len(result['candidates']) == 4
    assert {c['relation']['group_name'] for c in result['candidates']} == {'word', 'count'}
    assert all(c['relation']['binding_status'] == 'source_actual_formal_flow' for c in result['candidates'])
    assert result == generate_regex_cells(corpus, frontend)
    output = emit(corpus, result['candidates'])
    assert not output['unsupported']
    namespace = {}
    exec(output['files']['test_records.py'], namespace)
    for item in output['obligations'] + output['controls']:
        namespace[item['test_name']]()
    json.dumps(result)


def test_cross_file_forwarded_formals_and_local_aliases_are_exact():
    _, _, result = fixture({
        'pkg/parser.py': '''from re import fullmatch as recognize
def parse(value):
    alias = value
    return recognize(r'([a-z]+):([0-9]+)', alias) is not None
''',
        'pkg/wrapper.py': 'from .parser import parse\ndef wrap(value):\n    return parse(value)\n',
        'tests/test_records.py': '''from pkg.wrapper import wrap
def test_first(): assert wrap('red:1')
def test_second(): assert wrap('blue:2')
''',
    })
    assert len(result['candidates']) == 4
    assert {len(c['relation']['binding_path']) for c in result['candidates']} == {2}
    assert all(c['relation']['binding_status'] == 'source_actual_formal_flow' for c in result['candidates'])


def test_unresolved_incremental_input_is_retained_as_owner_proximity_hypothesis():
    _, _, result = fixture('''import re
class Parser:
    def __init__(self): self.buffer = ''
    def parse(self, value):
        self.buffer += value
        return re.fullmatch(r'([a-z]+):([0-9]+)', self.buffer) is not None
def test_first():
    p = Parser()
    assert p.parse('red:1')
def test_second():
    p = Parser()
    assert p.parse('blue:2')
''')
    assert len(result['candidates']) == 4
    assert all(c['relation']['binding_status'] == 'source_owner_proximity_unresolved' for c in result['candidates'])
    assert all(c['relation']['status'] == 'source_grammar_hypothesis_runtime_unconfirmed' for c in result['candidates'])


def test_proximity_requires_two_matching_aligned_inputs():
    _, _, result = fixture(BASE.replace('blue:2', 'not a record'))
    assert not result['candidates']
    _, _, result = fixture(BASE, budget=RegexBudget(allow_proximity=False))
    assert result['candidates']


def test_nested_groups_select_leaves_and_preserve_ancestor_consistency():
    _, _, result = fixture(BASE.replace("(?P<word>[a-z]+):(?P<count>[0-9]+)", "(([a-z]+):([0-9]+))"))
    assert len(result['candidates']) == 4
    assert {c['relation']['group'] for c in result['candidates']} == {2, 3}
    assert all(c['relation']['rematch'] == 'only_selected_leaf_and_ancestor_captures_changed' for c in result['candidates'])


def test_backreference_dependency_cannot_be_changed_as_an_independent_coordinate():
    code = BASE.replace("(?P<word>[a-z]+):(?P<count>[0-9]+)", r"([a-z]+)-\1:([0-9]+)")
    code = code.replace('red:1', 'red-red:1').replace('blue:2', 'blue-blue:2')
    _, _, result = fixture(code)
    assert values(result) == {'red-red:2', 'blue-blue:1'}
    assert {c['relation']['group'] for c in result['candidates']} == {2}
    assert result['counts']['skipped']['rematch_changed_other_coordinate_or_invalid']


def test_overlapping_lookahead_captures_are_not_independent_fields():
    code = BASE.replace("(?P<word>[a-z]+):(?P<count>[0-9]+)", r"(?=([a-z]+))([a-z]+):([0-9]+)")
    _, _, result = fixture(code)
    assert {c['relation']['group'] for c in result['candidates']} == {3}
    assert values(result) == {'red:2', 'blue:1'}


def test_search_preserves_uncaptured_prefix_suffix_and_utf8_coordinates():
    code = BASE.replace("(?P<word>[a-z]+):(?P<count>[0-9]+)", r"([a-z]+):([0-9]+)")
    code = code.replace('PATTERN.fullmatch', 'PATTERN.search').replace('red:1', '雪[red:1]尾').replace('blue:2', '別[blue:2]終')
    _, _, result = fixture(code)
    assert values(result) == {'雪[red:2]尾', '雪[blue:1]尾', '別[red:2]終', '別[blue:1]終'}
    target = next(c for c in result['candidates'] if c['relation']['before'] == 'red')
    assert target['relation']['capture_coordinate'] == {'unicode_span': [2, 5], 'utf8_span': [4, 7]}


def test_parameterized_fstrings_restrict_complete_original_row_and_ids():
    code = '''import re
import pytest
def parse(value):
    return re.fullmatch(r'([a-z]+):([0-9]+)', value) is not None
@pytest.mark.parametrize('word,n,ok', [('red',1,True), ('blue',2,True)], ids=['red','blue'])
def test_rows(word,n,ok):
    assert parse(f'{word}:{n}') is ok
'''
    corpus, _, result = fixture(code)
    assert result['finite_inputs']['added'] == 2
    assert len(result['candidates']) == 4
    output = emit(corpus, result['candidates'])
    assert not output['unsupported']
    namespace = {}
    exec(output['files']['test_records.py'], namespace)
    for candidate, obligation in zip(result['candidates'], output['obligations']):
        function = namespace[obligation['test_name']]
        mark, = function.pytestmark
        assert len(mark.args[1]) == len(mark.kwargs['ids']) == 1
        bindings = candidate['relation']['parameter_instantiation']['bindings']
        assert tuple(bindings.values()) == mark.args[1][0]
        function(**bindings)
        assert candidate['edits'][0]['before'] == "f'{word}:{n}'"
    assert len(namespace['test_rows'].pytestmark[0].args[1]) == 2


def test_dynamic_interpolation_is_not_executed_or_closed():
    code = BASE + '''def test_dynamic():
    assert parse(f'{dangerous()}:{other()}')
'''
    _, _, result = fixture(code)
    assert not any(c['base_test_id'].endswith(':test_dynamic') for c in result['candidates'])


def test_regex_literals_in_docstrings_or_unused_compiles_are_not_grammars():
    _, _, result = fixture('''import re
UNUSED = re.compile(r'([a-z]+):([0-9]+)')
def parse(value):
    """Example grammar: ([a-z]+):([0-9]+)"""
    return True
def test_first(): assert parse('red:1')
def test_second(): assert parse('blue:2')
''')
    assert not result['patterns']
    assert not result['candidates']


@pytest.mark.parametrize('prefix', ['import fake as re', 'import re\nre = fake'])
def test_regex_module_binding_must_be_import_proved(prefix):
    _, _, result = fixture(BASE.replace('import re', prefix))
    assert not result['patterns']


@pytest.mark.parametrize('outer_binding', ['re = replacement', 'import fake as re', 'from fake import re'])
def test_enclosing_function_regex_shadow_does_not_resolve_module_import(outer_binding):
    _, _, result = fixture(f'''import re
def factory():
    {outer_binding}
    def parse(value):
        return re.fullmatch(r'([a-z]+):([0-9]+)', value)
    return parse
parse = factory()
def test_first(): assert parse('red:1')
def test_second(): assert parse('blue:2')
''')
    assert not result['patterns']


def test_enclosing_function_pattern_literal_precedes_module_pattern():
    _, _, result = fixture('''import re
PATTERN = r'([a-z]+):([0-9]+)'
def factory():
    PATTERN = r'([A-Z]+)-([0-9]+)'
    def parse(value):
        return re.fullmatch(PATTERN, value)
    return parse
parse = factory()
def test_first(): assert parse('RED-1')
def test_second(): assert parse('BLUE-2')
''')
    assert [p['pattern'] for p in result['patterns']] == [r'([A-Z]+)-([0-9]+)']


def test_inner_import_wins_over_enclosing_function_shadow():
    _, _, result = fixture('''import re
def factory():
    re = replacement
    def parse(value):
        import re
        return re.fullmatch(r'([a-z]+):([0-9]+)', value)
    return parse
parse = factory()
def test_first(): assert parse('red:1')
def test_second(): assert parse('blue:2')
''')
    assert len(result['patterns']) == 1


def test_method_bare_regex_name_skips_class_namespace():
    _, _, result = fixture('''import re
class Parser:
    re = replacement
    def parse(self, value):
        return re.fullmatch(r'([a-z]+):([0-9]+)', value)
def test_first(): assert Parser().parse('red:1')
def test_second(): assert Parser().parse('blue:2')
''')
    assert len(result['patterns']) == 1


@pytest.mark.parametrize('binding', ["from fake import PATTERN", "PATTERN = dynamic()"])
def test_closure_unknown_pattern_does_not_fall_back_to_module_literal(binding):
    _, _, result = fixture(f'''import re
PATTERN = r'([a-z]+):([0-9]+)'
def factory():
    {binding}
    def parse(value):
        return re.fullmatch(PATTERN, value)
    return parse
parse = factory()
def test_first(): assert parse('red:1')
def test_second(): assert parse('blue:2')
''')
    assert not result['patterns']


@pytest.mark.parametrize('directive', ['global PATTERN', 'nonlocal PATTERN'])
def test_explicit_scope_directives_remain_unknown_without_binding_proof(directive):
    _, _, result = fixture(f'''import re
PATTERN = r'([a-z]+):([0-9]+)'
def factory():
    PATTERN = r'([A-Z]+)-([0-9]+)'
    def parse(value):
        {directive}
        return re.fullmatch(PATTERN, value)
    return parse
parse = factory()
def test_first(): assert parse('red:1')
def test_second(): assert parse('blue:2')
''')
    assert not result['patterns']


def test_regex_class_constant_has_source_owned_binding():
    _, _, result = fixture('''import re
class Parser:
    pattern = re.compile(r'([a-z]+):([0-9]+)')
    def parse(self, value):
        return self.pattern.fullmatch(value) is not None
def test_first(): assert Parser().parse('red:1')
def test_second(): assert Parser().parse('blue:2')
''')
    assert len(result['patterns']) == 1
    assert len(result['candidates']) == 4


def test_constructor_compiled_regex_field_remains_source_owned():
    _, _, result = fixture('''import re
class Parser:
    def __init__(self):
        self.pattern = re.compile(r'([a-z]+):([0-9]+)')
    def parse(self, value):
        return self.pattern.fullmatch(value) is not None
def test_first(): assert Parser().parse('red:1')
def test_second(): assert Parser().parse('blue:2')
''')
    assert len(result['patterns']) == 1
    assert len(result['candidates']) == 4


def test_source_compiled_pattern_import_and_reexport_chain():
    _, _, result = fixture({
        'pkg/grammar.py': "import re\nRECORD = re.compile(r'([a-z]+):([0-9]+)')\n",
        'pkg/public.py': 'from .grammar import RECORD\n',
        'pkg/parser.py': '''from .public import RECORD as PATTERN
def parse(value): return PATTERN.fullmatch(value) is not None
''',
        'tests/test_records.py': '''from pkg.parser import parse
def test_first(): assert parse('red:1')
def test_second(): assert parse('blue:2')
''',
    })
    assert len(result['candidates']) == 4
    assert {p['pattern_span']['path'] for p in result['patterns']} == {'pkg/grammar.py'}


def test_flags_follow_resolved_re_import_aliases():
    code = BASE.replace('import re', 'from re import compile as make, IGNORECASE as IC')
    code = code.replace('re.compile(', 'make(').replace("[0-9]+)')", "[0-9]+)', IC)").replace('red:1', 'RED:1')
    _, _, result = fixture(code)
    assert values(result) == {'RED:2', 'blue:1'}


def test_proven_argument_flow_excludes_other_argument_slots():
    code = BASE.replace('def parse(value):', 'def parse(value, other):').replace('parse("red:1")', 'parse("red:1", "first:8")').replace('parse("blue:2")', 'parse("blue:2", "second:9")')
    _, _, result = fixture(code)
    assert values(result) == {'red:2', 'blue:1'}
    assert all(c['edits'][0]['before'] in {'"red:1"', '"blue:2"'} for c in result['candidates'])


def test_expected_literals_are_not_source_coordinate_donors():
    code = '''import re
def parse(value): return re.fullmatch(r'([a-z]+):([0-9]+)', value)
def test_first(): assert parse('red:1') == 'blue:2'
'''
    _, _, result = fixture(code)
    assert not result['candidates']


def test_worker_and_generation_budgets_are_bounded():
    _, _, result = fixture(BASE, budget=RegexBudget(max_candidates=2, max_attempts=2))
    assert len(result['candidates']) == 2
    assert result['counts']['attempt_budget_exhausted']
    _, _, result = fixture(BASE, budget=RegexBudget(max_groups=1))
    assert not result['candidates']
    assert result['counts']['skipped']['unsupported_regex_or_capture_budget']
    with pytest.raises(ValueError):
        RegexBudget(max_inputs_per_slot=0)
