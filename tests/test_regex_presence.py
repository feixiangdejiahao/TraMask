"""Optional grammar coordinates learned only from independent source fixtures."""
import ast
import json
import subprocess

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relational_gap.regex_presence import (
    RegexPresenceBudget, generate_regex_presence, presence_plans,
)


PATTERN = r'(?P<word>[a-z]+)(?:\|(?P<count>[0-9]+))?:(?P<tail>[a-z]+)'
BASE = f'''import re
PATTERN = re.compile({PATTERN!r})
def parse(value):
    return PATTERN.fullmatch(value) is not None
def test_first():
    assert parse("red:end") is True
def test_second():
    assert parse("blue|19:fin") is True
'''


def plans(pattern, inputs, *, method='fullmatch', **limits):
    return presence_plans({'pattern': pattern, 'flags': 0, 'method': method}, inputs,
                          budget=RegexPresenceBudget(**limits))


def fixture(code=BASE, **kwargs):
    sources = ([Source(path, text, 'python') for path, text in code.items()]
               if isinstance(code, dict) else [Source('test_records.py', code, 'python')])
    frontend = extract_frontend(sources)
    corpus = to_emitter_corpus(frontend)
    return corpus, frontend, generate_regex_presence(corpus, frontend, **kwargs)


def test_donor_unit_is_inserted_and_all_other_base_coordinates_survive():
    result = plans(PATTERN, ['red:end', 'blue|19:fin'])
    candidate, = result['proposals']
    assert candidate['generated'] == 'red|19:end'
    assert candidate['fragment'] == '|19'
    assert candidate['before']['groups'] == ['red', None, 'end']
    assert candidate['after']['groups'] == ['red', '19', 'end']
    assert candidate['donor_unit_span'] == [4, 7]
    assert candidate['anchor_proof']['all_positions_checked']
    assert candidate['anchor_proof']['valid_positions'] == 1


def test_optional_other_capture_keeps_base_value():
    pattern = r'(?P<word>[a-z]+)(?:\|(?P<count>[0-9]+))?(?:;(?P<mode>[A-Z]))?'
    result = plans(pattern, ['red;A', 'blue|19;B'])
    candidate, = result['proposals']
    assert candidate['generated'] == 'red|19;A'
    assert candidate['after']['groups'] == ['red', '19', 'A']


def test_search_preserves_uncaptured_unicode_prefix_and_suffix():
    result = plans(PATTERN, ['雪[red:end]尾', '別[blue|19:fin]終'], method='search')
    candidate, = result['proposals']
    assert candidate['generated'] == '雪[red|19:end]尾'
    assert candidate['insertion'] == 5
    assert candidate['before']['span'] == [2, 9]
    assert candidate['after']['span'] == [2, 12]


def test_empty_participating_capture_differs_from_absence():
    result = plans(r'(?P<word>[a-z]+)(?:;(?P<flag>))?', ['red', 'blue;'])
    candidate, = result['proposals']
    assert candidate['generated'] == 'red;'
    assert candidate['before']['groups'] == ['red', None]
    assert candidate['after']['groups'] == ['red', '']


def test_enclosing_capture_expands_only_by_the_inserted_fragment():
    result = plans(r'(?P<whole>[a-z]+(?:;(?P<count>[0-9]+))?)', ['red', 'blue;12'])
    candidate, = result['proposals']
    assert candidate['generated'] == 'red;12'
    assert candidate['after']['groups'] == ['red;12', '12']


def test_nested_absent_capture_family_comes_from_single_source_unit():
    result = plans(r'[a-z]+(?P<outer>;(?P<inner>[0-9]+))?', ['red', 'blue;12'])
    candidate, = result['proposals']
    assert candidate['generated'] == 'red;12'
    assert candidate['after']['groups'] == [';12', '12']
    assert candidate['unit']['capture_family'] == [1, 2]


@pytest.mark.parametrize('optional', [r'(?:\|(?P<x>[0-9]+))??', r'(?:\|(?P<x>[0-9]+)|)',
                                       r'(?:\|(?P<x>[0-9]+))?+'])
def test_optional_quantifier_and_empty_alternative_syntax(optional):
    candidate, = plans(r'(?P<word>[a-z]+)' + optional + ':', ['red:', 'blue|7:'])['proposals']
    assert candidate['generated'] == 'red|7:'


def test_source_literal_wrappers_and_whitespace_frame_are_retained_exactly():
    candidate, = plans(r'(?P<word>[a-z]+)(?:\s*\((?P<n>[0-9]+)\))?',
                       ['red', 'blue \t(7)'])['proposals']
    assert candidate['fragment'] == ' \t(7)'
    assert candidate['generated'] == 'red \t(7)'


def test_finite_literal_class_separators_are_source_syntax():
    candidate, = plans(r'(?P<word>[a-z]+)(?:[|;](?P<n>[0-9]+))?',
                       ['red', 'blue;7'])['proposals']
    assert candidate['generated'] == 'red;7'


def test_multiple_valid_anchors_are_explicitly_ambiguous():
    result = plans(r'a*(?P<x>b)?a*', ['aaa', 'aba'])
    assert not result['proposals']
    assert result['skipped']['optional_insertion_anchor_ambiguous'] == 1


@pytest.mark.parametrize(('pattern', 'inputs', 'reason'), [
    (r'[a-z]+(?:;(?P<x>[0-9]+):(?P<y>[A-Z]+))?', ['red', 'blue;7:X'],
     'optional_has_multiple_capture_coordinates'),
    (r'[a-z]+(?:\w+:(?P<x>[0-9]+))?', ['red', 'bluefoo:7'],
     'optional_uncaptured_frame_not_structural'),
    (r'(?:a(?P<x>b)?)+', ['aaa', 'aba'], 'optional_under_repeated_ancestor'),
    (r'(?=(?P<x>b)?)[a-z]+', ['aaa', 'baa'], 'optional_under_lookaround'),
])
def test_unsupported_shapes_are_explicit(pattern, inputs, reason):
    result = plans(pattern, inputs)
    assert not result['proposals']
    assert result['skipped'][reason]


def test_backreference_dependency_cannot_modify_unrelated_base_capture():
    result = plans(r'(?P<word>[a-z]+)(?:;(?P<copy>(?P=word)))?', ['red', 'blue;blue'])
    assert not result['proposals']
    assert result['skipped']['optional_insertion_does_not_preserve_other_coordinates']


def test_nested_optionals_do_not_change_original_group_numbering():
    result = plans(r'(?P<word>[a-z]+)(?:;(?P<outer>(?P<inner>[0-9]+)?))?',
                   ['red', 'blue;7'])
    assert {p['generated'] for p in result['proposals']} == {'red;7'}
    assert all(p['after']['groups'] == ['red', '7', '7'] for p in result['proposals'])


def test_source_and_generated_capture_reference_numbers_remain_identical():
    candidate, = plans(r'([a-z]+)(?:;([0-9]+))?:\1', ['red:red', 'blue;7:blue'])['proposals']
    assert candidate['generated'] == 'red;7:red'


@pytest.mark.parametrize(('limits', 'reason'), [
    ({'max_anchor_positions': 2}, 'optional_anchor_search_budget'),
    ({'max_groups': 1}, 'optional_regex_unsupported:capture_group_budget'),
    ({'max_ast_nodes': 2}, 'optional_regex_unsupported:regex_ast_budget'),
    ({'max_input_bytes': 3}, 'optional_source_input_size_budget'),
    ({'max_pattern_bytes': 3}, 'optional_pattern_or_input_count_budget'),
])
def test_low_level_work_is_bounded(limits, reason):
    result = plans(PATTERN, ['red:end', 'blue|19:fin'], **limits)
    assert not result['proposals']
    assert result['skipped'][reason]


def test_bad_pattern_and_timeout_are_recorded_not_raised(monkeypatch):
    assert not plans('(', ['a', 'b'])['proposals']
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('regex_worker', 1)
    monkeypatch.setattr('relational_gap.regex_presence.subprocess.run', timeout)
    assert plans(PATTERN, ['red:end', 'blue|19:fin'])['skipped']['optional_regex_worker_timeout']


def test_source_binding_candidate_q_and_emission_execute():
    corpus, frontend, result = fixture()
    candidate, = result['candidates']
    assert ast.literal_eval(candidate['edits'][0]['after']) == 'red|19:end'
    assert candidate['relation']['binding_status'] == 'source_actual_formal_flow'
    assert candidate['relation']['group_name'] == 'count'
    assert candidate['target_capsule_id'] == candidate['source_observation_id']
    assert candidate['oracle']['assertion_ids'] == [candidate['target_capsule_id']]
    assert result == generate_regex_presence(corpus, frontend)
    json.dumps(result)
    output = emit(corpus, result['candidates'])
    assert not output['unsupported']
    namespace = {}
    exec(output['files']['test_records.py'], namespace)
    for item in output['obligations'] + output['controls']:
        namespace[item['test_name']]()


def test_cross_file_source_formal_flow():
    _, _, result = fixture({
        'pkg/parser.py': f'import re\ndef parse(value):\n    return re.fullmatch({PATTERN!r}, value) is not None\n',
        'pkg/wrapper.py': 'from .parser import parse\ndef wrap(value):\n    return parse(value)\n',
        'tests/test_records.py': '''from pkg.wrapper import wrap
def test_first(): assert wrap('red:end')
def test_second(): assert wrap('blue|19:fin')
''',
    })
    candidate, = result['candidates']
    assert len(candidate['relation']['binding_path']) == 2
    assert candidate['relation']['binding_status'] == 'source_actual_formal_flow'


def test_unproved_owner_proximity_is_recorded_as_hypothesis():
    code = f'''import re
class Parser:
    def __init__(self): self.buffer = ''
    def parse(self, value):
        self.buffer += value
        return re.fullmatch({PATTERN!r}, self.buffer) is not None
def test_first():
    p = Parser()
    assert p.parse('red:end')
def test_second():
    p = Parser()
    assert p.parse('blue|19:fin')
'''
    _, _, result = fixture(code)
    candidate, = result['candidates']
    assert candidate['relation']['binding_status'] == 'source_owner_proximity_unresolved'
    assert candidate['relation']['status'] == 'source_grammar_hypothesis_runtime_unconfirmed'
    assert not fixture(code, budget=RegexPresenceBudget(allow_proximity=False))[2]['candidates']


def test_parameter_rows_and_ids_are_preserved_with_generated_literal():
    code = f'''import re
import pytest
def parse(value):
    return re.fullmatch({PATTERN!r}, value) is not None
@pytest.mark.parametrize('word,optional,tail,ok', [('red','','end',True), ('blue','|19','fin',True)], ids=['red','blue'])
def test_rows(word,optional,tail,ok):
    assert parse(f'{{word}}{{optional}}:{{tail}}') is ok
'''
    corpus, _, result = fixture(code)
    candidate, = result['candidates']
    assert ast.literal_eval(candidate['edits'][0]['after']) == 'red|19:end'
    output = emit(corpus, result['candidates'])
    assert not output['unsupported']
    namespace = {}
    exec(output['files']['test_records.py'], namespace)
    item, = output['obligations']
    function = namespace[item['test_name']]
    mark, = function.pytestmark
    assert mark.args[1] == [('red', '', 'end', True)]
    assert mark.kwargs['ids'] == ['red']
    function(**candidate['relation']['parameter_instantiation']['bindings'])


def test_nonimported_regex_lookalike_and_dynamic_interpolation_do_not_supply_grammar():
    _, _, result = fixture(BASE.replace('import re', 're = arbitrary_factory()'))
    assert not result['candidates']
    _, _, result = fixture(BASE + '''def test_dynamic():
    assert parse(f'{effect()}:{tail()}')
''')
    assert len(result['candidates']) == 1


def test_candidate_budget_balances_recipient_tests():
    code = BASE + '''def test_third(): assert parse('green:end')
def test_fourth(): assert parse('blue|29:fin')
'''
    _, _, result = fixture(code, budget=RegexPresenceBudget(max_candidates=2))
    assert len(result['candidates']) == 2
    assert len({candidate['base_test_id'] for candidate in result['candidates']}) == 2
    assert result['budget_exhausted']


def test_attempt_budget_balances_source_inputs_before_enumerating_second_donors():
    result = plans(PATTERN, ['red:end', 'green:end', 'blue|19:fin', 'blue|29:fin'],
                   max_attempts=2)
    assert result['attempts'] == 2
    assert {p['base_index'] for p in result['proposals']} == {0, 1}
    assert result['exhausted']


def test_worker_proposal_cap_is_reported_by_high_level_budget():
    _, _, result = fixture(BASE + "def test_third(): assert parse('green:end')\n",
                           budget=RegexPresenceBudget(max_proposals_per_batch=1))
    assert len(result['candidates']) == 1
    assert result['budget_exhausted']


def test_high_level_unicode_offset_uses_utf8_source_input():
    code = BASE.replace('PATTERN.fullmatch', 'PATTERN.search')
    code = code.replace('red:end', '雪[red:end]尾').replace('blue|19:fin', '別[blue|19:fin]終')
    _, _, result = fixture(code)
    candidate, = result['candidates']
    assert candidate['provenance']['insertion_unicode_offset'] == 5
    assert candidate['provenance']['insertion_utf8_offset'] == 7
    assert ast.literal_eval(candidate['edits'][0]['after']) == '雪[red|19:end]尾'


def test_snapshot_observation_before_changed_operation_is_not_a_later_q():
    code = BASE.replace('    assert parse("red:end") is True',
                        '    result = True\n    parse("red:end")\n    assert result is True')
    _, _, result = fixture(code)
    assert not result['candidates']
    assert result['skipped']['optional_following_observation_not_recovered']


def test_case_flags_and_inline_flags_preserve_source_capture_values():
    pattern = {'pattern': r'(?i:(?P<word>[a-z]+))(?:;(?P<n>[0-9]+))?', 'flags': 0, 'method': 'fullmatch'}
    candidate, = presence_plans(pattern, ['RED', 'Blue;7'])['proposals']
    assert candidate['generated'] == 'RED;7'
    assert candidate['after']['groups'] == ['RED', '7']


def test_absent_optional_in_unselected_branch_has_no_source_insertion_anchor():
    result = plans(r'(?:a(?P<x>b)?|c)', ['c', 'ab'])
    assert not result['proposals']
    assert result['skipped']['absent_capture_has_no_empty_optional_unit_anchor']


def test_budget_validation():
    with pytest.raises(ValueError): RegexPresenceBudget(max_attempts=0)
    with pytest.raises(ValueError): RegexPresenceBudget(max_groups=True)
    with pytest.raises(ValueError): RegexPresenceBudget(allow_proximity=1)
