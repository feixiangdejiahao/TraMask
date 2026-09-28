"""Source fragment edits preserve executable interpolation, not sampled rows."""
import ast
import json

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relational_gap.symbolic_strings import SymbolicStringBudget, generate_symbolic_strings


PREFIX = '''seen = []
def take(value, extra=None):
    seen.append(value)
    return True

def test_before():
    assert take('[one]') is True

def test_after():
    assert take('[ one]') is True

'''


def corpus_for(code):
    return to_emitter_corpus(extract_frontend([Source('test_fragments.py', code, 'python')]))


def rows_for(corpus, name, *, budget=None):
    target = next(key for key, row in corpus['tests'].items() if row['name'] == name)
    result = generate_symbolic_strings(corpus, budget=budget)
    return [row for row in result['candidates'] if row['base_test_id'] == target]


def formatted_values(text):
    parsed = ast.parse(text, mode='eval').body
    assert isinstance(parsed, ast.JoinedStr)
    return [ast.dump(value, include_attributes=False) for value in parsed.values
            if isinstance(value, ast.FormattedValue)]


def emitted_namespace(corpus, candidate):
    output = emit(corpus, [candidate])
    assert not output['unsupported']
    namespace = {}
    for text in output['files'].values():
        exec(compile(text, '<symbolic-fragment-test>', 'exec'), namespace)
    return namespace, output['obligations'][0]['test_name'], output


def test_parameter_rows_and_nested_format_spec_remain_symbolic_for_each_value():
    corpus = corpus_for('import pytest\n' + PREFIX + '''@pytest.mark.parametrize('value,width', [('é', 4), ('long name', 12)])
def test_template(value, width):
    assert take(f'[{value!r:>{width}}]') is True
''')
    candidates = rows_for(corpus, 'test_template')
    assert candidates
    candidate = candidates[0]
    edit = candidate['edits'][0]
    assert formatted_values(edit['before']) == formatted_values(edit['after'])
    assert candidate['relation']['interpolation_count'] == 2
    assert candidate['relation']['parameter_frame'] == 'original_test_parameters_and_rows_retained'
    namespace, test_name, output = emitted_namespace(corpus, candidate)
    for value, width in [('é', 4), ('long name', 12), ('not in source rows', 22)]:
        namespace[test_name](value, width)
        assert namespace['seen'][-1] == f'[ {value!r:>{width}}]'
    assert "@pytest.mark.parametrize('value,width'" in next(iter(output['files'].values()))
    assert candidate['oracle']['applicability'] == 'requires_independent_admission'
    assert all(origin['source_expression_span'] in candidate['provenance']['source_spans']
               for origin in candidate['provenance']['source_fragments'])
    json.dumps(candidate)


def test_interpolation_call_and_nested_format_width_each_evaluate_exactly_once():
    corpus = corpus_for(PREFIX + '''events = []
def mark():
    events.append('value')
    return 'é'
def size():
    events.append('width')
    return 9

def test_template():
    assert take(f'head[{mark()!r:^{size()}}]tail') is True
''')
    candidate = rows_for(corpus, 'test_template')[0]
    namespace, test_name, _ = emitted_namespace(corpus, candidate)
    namespace[test_name]()
    assert namespace['events'] == ['value', 'width']
    assert namespace['seen'] == [f"head[ {'é'!r:^9}]tail"]
    assert formatted_values(candidate['edits'][0]['before']) == formatted_values(candidate['edits'][0]['after'])


@pytest.mark.parametrize('template', [
    'f"雪{{}}:[{value}]終"',
    'f"line\\n[{value}]\\tend"',
    'rf"literal\\n[{value}]{{brace}}"',
])
def test_braces_unicode_and_escape_values_round_trip(template):
    corpus = corpus_for(PREFIX + f'''def test_template(value):
    assert take({template}) is True
''')
    candidate = rows_for(corpus, 'test_template')[0]
    namespace, test_name, _ = emitted_namespace(corpus, candidate)
    for value in ['雪', 'α🙂', '{nested}']:
        namespace[test_name](value)
        original = eval(compile(ast.Expression(ast.parse(template, mode='eval').body), '<independent-template>', 'eval'),
                        {'value': value})
        assert namespace['seen'][-1] == original.replace('[', '[ ', 1)
    assert formatted_values(candidate['edits'][0]['before']) == formatted_values(candidate['edits'][0]['after'])


def test_repeated_anchors_across_static_segments_are_ambiguous():
    corpus = corpus_for(PREFIX + '''def test_template(left, right):
    assert take(f'[{left}] / [{right}]') is True
''')
    result = generate_symbolic_strings(corpus)
    assert result['candidates'] == []
    assert result['skipped']['static_context_ambiguous'] > 0


def test_format_spec_literals_and_interpolation_expressions_are_never_edit_targets():
    corpus = corpus_for(PREFIX + '''def test_template(value):
    assert take(f'{value:[>6}') is True
''')
    assert generate_symbolic_strings(corpus)['candidates'] == []
    corpus = corpus_for(PREFIX + '''def test_template():
    assert take(f'{"[one]"}') is True
''')
    assert generate_symbolic_strings(corpus)['candidates'] == []


def test_symbolic_source_pairs_align_outer_segments_and_transfer_to_another_context():
    corpus = corpus_for('''def take(value): return True

def test_before(part):
    assert take(f'code[{part}]') is True

def test_after(part):
    assert take(f'code[ {part}]') is True

def test_target(value):
    assert take(f'other[{value}]suffix') is True
''')
    candidates = rows_for(corpus, 'test_target')
    candidate = next(row for row in candidates if 'other[ {' in row['edits'][0]['after'])
    assert all(origin['source_family'] == ['symbolic', 1, 0]
               for origin in candidate['provenance']['source_fragments'])
    assert formatted_values(candidate['edits'][0]['before']) == formatted_values(candidate['edits'][0]['after'])


def test_callee_and_argument_position_both_constrain_source_pairs():
    corpus = corpus_for(PREFIX + '''def test_other(value):
    assert other(f'[{value}]') is True

def test_other_slot(value):
    assert take('same', f'[{value}]') is True
''')
    assert generate_symbolic_strings(corpus)['candidates'] == []


def test_expected_literals_do_not_supply_source_context_edits():
    corpus = corpus_for('''def test_before():
    assert take('same') == '[one]'

def test_after():
    assert take('same') == '[ one]'

def test_target(value):
    assert take(f'[{value}]') is True
''')
    assert generate_symbolic_strings(corpus)['candidates'] == []


def test_parent_budget_is_deterministic_and_retains_multiple_parameter_frames():
    corpus = corpus_for(PREFIX + ''.join(f'''def test_{name}(value):
    assert take(f'{name}[{{value}}]') is True

''' for name in ['north', 'south', 'east']))
    budget = SymbolicStringBudget(max_candidates=3)
    result = generate_symbolic_strings(corpus, budget=budget)
    assert len(result['candidates']) == 3
    assert len({row['base_test_id'] for row in result['candidates']}) == 3
    assert result['budget_exhausted']
    assert result == generate_symbolic_strings(corpus, budget=budget)


@pytest.mark.parametrize('budget', [SymbolicStringBudget(max_candidates=0), SymbolicStringBudget(max_rules_per_slot=-1)])
def test_nonpositive_budgets_are_rejected(budget):
    with pytest.raises(ValueError, match='positive integers'):
        generate_symbolic_strings(corpus_for(PREFIX), budget=budget)
