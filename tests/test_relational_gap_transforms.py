"""Independent miniature programs exercise source edits, not discovery labels."""
from generic_composition.corpus import build_corpus, expression, span
from generic_composition.emitter import emit
from anchor_retrieval.syntax import Source, child, walk
from relational_gap.transforms import TransformBudget, enumerate_transforms


def corpus_for(tmp_path, code, language='python'):
    filename = {'python': 'test_subject.py', 'typescript': 'subject.test.ts', 'go': 'subject_test.go'}[language]
    (tmp_path / filename).write_text(code)
    return build_corpus(tmp_path, language)


def run_python_candidates(corpus, candidates):
    output = emit(corpus, candidates)
    assert not output['unsupported']
    namespace = {}
    for text in output['files'].values():
        exec(compile(text, '<emitted-test>', 'exec'), namespace)
    for row in output['obligations'] + output['controls']:
        namespace[row['test_name']]()
    return output


def test_same_slot_substitution_preserves_other_input_and_runs(tmp_path):
    corpus = corpus_for(tmp_path, '''def accept(left, right):
    assert isinstance(left, str) and isinstance(right, str)
    return True

def test_first():
    assert accept("north", "red") is True

def test_second():
    assert accept("south", "blue") is True
''')
    result = enumerate_transforms(corpus)
    swaps = [item for item in result['candidates'] if item['kind'] == 'aligned_input_substitution']
    assert swaps
    assert {tuple((edit['before'], edit['after'])) for item in swaps for edit in item['edits']} == {
        ('"north"', '"south"'), ('"south"', '"north"'), ('"red"', '"blue"'), ('"blue"', '"red"')}
    assert all(len(item['edits']) == 1 for item in swaps)
    assert all(item['oracle']['applicability'] == 'requires_independent_admission' for item in swaps)
    run_python_candidates(corpus, swaps)


def test_record_mixed_presence_uses_real_fields_and_does_not_claim_default_contract(tmp_path):
    corpus = corpus_for(tmp_path, '''def accept(record):
    assert all(name in {'alpha', 'beta', 'gamma'} for name in record)
    return True

def test_full():
    assert accept({'alpha': 3, 'beta': 8, 'gamma': 13}) is True

def test_none():
    assert accept({}) is True
''')
    result = enumerate_transforms(corpus)
    mixed = [item for item in result['candidates'] if item['kind'] == 'partial_record_presence']
    assert len(mixed) == 6
    assert {len(item['relation']['cell']['present']) for item in mixed} == {1, 2}
    assert all(item['relation']['field_universe_basis'].endswith('contract_unknown') for item in mixed)
    assert all(item['provenance']['source_spans'] for item in mixed)
    run_python_candidates(corpus, mixed)


def test_nested_record_leaves_are_not_interchanged_by_shared_downstream_slot(tmp_path):
    corpus = corpus_for(tmp_path, '''def test_one():
    assert consume({'key': 3, 'other': 9}) == 1

def test_two():
    assert consume({'key': 4, 'other': 8}) == 1
''')
    candidates = enumerate_transforms(corpus)['candidates']
    assert candidates
    assert not any(edit['before'] in {'3', '4', '8', '9'} for item in candidates for edit in item['edits'])


def test_local_name_collision_and_missing_binding_are_rejected(tmp_path):
    corpus = corpus_for(tmp_path, '''def test_one():
    value = 7
    assert consume(value + 1) == 1

def test_two():
    value = "different"
    assert consume(value + "suffix") == 1
''')
    result = enumerate_transforms(corpus)
    assert result['counts']['skipped']['unresolved_transferred_bindings'] > 0
    assert not any(item['edits'][0]['after'] in {'value + 1', 'value + "suffix"'} for item in result['candidates'])


def test_source_constructor_expressions_can_cross_tests_with_shared_global_binding(tmp_path):
    corpus = corpus_for(tmp_path, '''def make(value):
    return value

def consume(value):
    return isinstance(value, int)

def test_one():
    assert consume(make(3)) is True

def test_two():
    assert consume(make(9)) is True
''')
    proposals = enumerate_transforms(corpus)['candidates']
    constructors = [item for item in proposals if item['edits'][0]['before'].startswith('make(')]
    assert len(constructors) == 2
    run_python_candidates(corpus, constructors)


def test_oracle_expressions_never_become_inputs_and_determinism_holds(tmp_path):
    corpus = corpus_for(tmp_path, '''def test_one():
    assert consume("one") == "secret-one"

def test_two():
    assert consume("two") == "secret-two"
''')
    first = enumerate_transforms(corpus)
    assert first == enumerate_transforms(corpus)
    assert all('secret' not in edit['before'] and 'secret' not in edit['after']
               for item in first['candidates'] for edit in item['edits'])


def test_typescript_partial_record_emits_in_original_suite_scope(tmp_path):
    corpus = corpus_for(tmp_path, '''describe('shared', () => {
  const first = 10;
  test('full', () => { expect(consume({x: first, y: 2})).toBe(true); });
  test('empty', () => { expect(consume({})).toBe(true); });
});
''', 'typescript')
    candidates = [item for item in enumerate_transforms(corpus)['candidates'] if item['kind'] == 'partial_record_presence']
    assert len(candidates) == 2
    output = emit(corpus, candidates)
    assert not output['unsupported']
    assert all(item['id'].startswith('shared ') for item in output['obligations'])


def test_record_spread_and_duplicate_keys_are_not_summarized_as_field_universes(tmp_path):
    corpus = corpus_for(tmp_path, '''def test_spread():
    assert consume({'x': 1, **other}) == 1

def test_duplicate():
    assert consume({'x': 1, 'x': 2}) == 1

def test_empty():
    assert consume({}) == 1
''')
    result = enumerate_transforms(corpus)
    assert not [item for item in result['candidates'] if item['kind'] == 'partial_record_presence']


def default_frontend(corpus):
    source = Source('test_subject.py', corpus['sources']['test_subject.py']['code'], 'python')
    function = next(node for node in walk(source.root) if node.type == 'function_definition'
                    and source.text(child(node, 'name')) == 'accept')
    default_node = next(node for node in walk(child(function, 'parameters')) if node.type == 'default_parameter')
    default = expression(source, child(default_node, 'value'))
    call = next(node for node in walk(source.root) if node.type == 'call' and source.text(child(node, 'function')) == 'accept')
    arguments = list(child(call, 'arguments').named_children)
    args = []
    bindings = []
    for index, node in enumerate(arguments):
        value = child(node, 'value') if node.type == 'keyword_argument' else node
        removal = span(source, node)
        if index:
            removal['start_byte'] = arguments[index - 1].end_byte
        elif len(arguments) > 1:
            removal['end_byte'] = arguments[index + 1].start_byte
        args.append(dict(expression(source, value), slot=index, keyword=source.text(child(node, 'name')) or None,
                         argument_span=span(source, node), removal_span=removal))
        bindings.append({'slot': index, 'parameter_index': index, 'parameter': ['payload', 'mode'][index],
                         'function_id': 'accept-id', 'resolution': 'resolved'})
    test_id = next(iter(corpus['tests']))
    return {'functions': [{'id': 'accept-id', 'parameters': [
        {'index': 0, 'name': 'payload', 'span': span(source, function), 'default': None},
        {'index': 1, 'name': 'mode', 'span': span(source, default_node), 'default': default}]}],
        'calls': [{'id': 'call', 'span': span(source, call), 'test_id': test_id,
                   'arguments': args, 'argument_bindings': bindings}]}


def test_explicit_default_omission_uses_declaration_and_runs(tmp_path):
    corpus = corpus_for(tmp_path, '''def accept(payload, mode="normal"):
    return mode == "normal"

def test_explicit():
    assert accept(7, mode="normal") is True
''')
    frontend = default_frontend(corpus)
    candidates = enumerate_transforms(corpus, frontend)['candidates']
    omissions = [item for item in candidates if item['kind'] == 'explicit_default_omission']
    assert len(omissions) == 1
    assert omissions[0]['edits'][0]['before'] == ', mode="normal"'
    assert omissions[0]['oracle']['basis']['kind'] == 'declared_immutable_default'
    run_python_candidates(corpus, omissions)


def test_mutable_defaults_do_not_claim_literal_value_equivalence(tmp_path):
    corpus = corpus_for(tmp_path, '''def accept(payload, mode=[]):
    return True

def test_explicit():
    assert accept(7, mode=[]) is True
''')
    assert not [item for item in enumerate_transforms(corpus, default_frontend(corpus))['candidates']
                if item['kind'] == 'explicit_default_omission']


def test_candidate_budget_round_robins_across_transforms(tmp_path):
    corpus = corpus_for(tmp_path, '''def test_full():
    assert consume({'a': 1, 'b': 2}) == 1

def test_empty():
    assert consume({}) == 1
''')
    result = enumerate_transforms(corpus, budget=TransformBudget(max_candidates=2))
    assert len(result['candidates']) == 2
    assert len({item['kind'] for item in result['candidates']}) == 2


def test_scalar_comparator_materializes_source_boundary_with_actual_parameter_binding(tmp_path):
    from relational_gap.frontend import extract_frontend
    corpus = corpus_for(tmp_path, '''seen = []
def accept(target, ceiling):
    seen.append((target, ceiling))
    if target < ceiling + 2:
        return True
    return True

def test_low():
    limit = 11
    assert accept(1, limit) is True
''')
    frontend = extract_frontend([Source(path, value['code'], 'python') for path, value in corpus['sources'].items()])
    candidates = [item for item in enumerate_transforms(corpus, frontend)['candidates']
                  if item['kind'] == 'scalar_comparison_boundary']
    assert len(candidates) == 3
    assert {item['relation']['cell'] for item in candidates} == {'<', '=', '>'}
    assert all('limit' in item['edits'][0]['after'] for item in candidates)
    assert all('ceiling' not in item['edits'][0]['after'] for item in candidates)
    output = run_python_candidates(corpus, candidates)
    namespace = {}
    exec(next(iter(output['files'].values())), namespace)
    for row in output['obligations']:
        namespace[row['test_name']]()
    assert {target for target, cap in namespace['seen']} == {12, 13, 14}


def test_scalar_boundary_does_not_duplicate_effectful_actual_argument(tmp_path):
    from relational_gap.frontend import extract_frontend
    corpus = corpus_for(tmp_path, '''def accept(target, ceiling):
    if target < ceiling:
        return True
    return True

def test_low():
    assert accept(1, next_limit()) is True
''')
    frontend = extract_frontend([Source(path, value['code'], 'python') for path, value in corpus['sources'].items()])
    result = enumerate_transforms(corpus, frontend)
    assert not [item for item in result['candidates'] if item['kind'] == 'scalar_comparison_boundary']
    assert result['counts']['skipped']['comparison_expression_unresolved'] >= 1


def test_existing_post_operation_observer_is_bound_to_exception_receiver(tmp_path):
    corpus = corpus_for(tmp_path, '''import pytest
class Resource:
    def __init__(self):
        self.done = False
    def act(self, reject):
        self.done = True
        if reject:
            raise ValueError("rejected")

def test_normal():
    original = Resource()
    original.act(False)
    assert original.done is True

def test_exception():
    current = Resource()
    with pytest.raises(ValueError):
        current.act(True)
''')
    result = enumerate_transforms(corpus)
    transferred = [item for item in result['candidates'] if item['kind'] == 'exception_exit_observation']
    assert len(transferred) == 1
    candidate = transferred[0]
    assert candidate['edits'][0]['after'] == '\n    assert current.done is True'
    assert candidate['relation']['receiver_binding']['source'] == 'original'
    assert candidate['relation']['receiver_binding']['target'] == 'current'
    assert candidate['oracle']['applicability'] == 'requires_independent_admission'
    run_python_candidates(corpus, transferred)


def test_exception_observer_never_binds_an_unrelated_constructor(tmp_path):
    corpus = corpus_for(tmp_path, '''import pytest
class First:
    pass
class Second:
    pass

def test_normal():
    first = First()
    assert first.done is True

def test_exception():
    second = Second()
    with pytest.raises(ValueError):
        second.act(True)
''')
    result = enumerate_transforms(corpus)
    assert not [item for item in result['candidates'] if item['kind'] == 'exception_exit_observation']


def test_compact_frontend_adapter_supports_source_transform_and_emission(tmp_path):
    from relational_gap.frontend import extract_frontend, to_emitter_corpus
    code = '''def accept(value, mode="standard"):
    if value < 5:
        return True
    return True

def test_first():
    assert accept(1, mode="standard") is True

def test_second():
    assert accept(9, mode="standard") is True
'''
    frontend = extract_frontend([Source('test_subject.py', code, 'python')])
    corpus = to_emitter_corpus(frontend)
    candidates = enumerate_transforms(corpus, frontend)['candidates']
    assert {'aligned_input_substitution', 'explicit_default_omission', 'scalar_comparison_boundary'} <= {item['kind'] for item in candidates}
    run_python_candidates(corpus, candidates)


def test_pool_collection_and_selection_reserve_domains_and_prioritize_retrieval(tmp_path):
    from relational_gap.frontend import extract_frontend, to_emitter_corpus
    code = '''def accept(value, mode="standard"):
    if value < 5:
        return True
    return True
'''
    for number in range(30):
        code += '\ndef test_' + str(number) + '():\n    assert accept(' + str(number) + ', mode="standard") is True\n'
    frontend = extract_frontend([Source('test_subject.py', code, 'python')])
    corpus = to_emitter_corpus(frontend)
    preferred = next(item for item in corpus['tests'].values() if item['name'] == 'test_29')
    preferred['retrieval_rank'] = 1
    result = enumerate_transforms(corpus, frontend, TransformBudget(max_candidates=3, max_pool=18, top_k=30))
    assert {item['kind'] for item in result['candidates']} == {
        'aligned_input_substitution', 'explicit_default_omission', 'scalar_comparison_boundary'}
    assert all(item['base_test_id'] == preferred['id'] for item in result['candidates'])
    assert result['counts']['candidate_pool'] <= 18


def test_null_and_undefined_are_not_equated_as_explicit_defaults(tmp_path):
    from relational_gap.frontend import extract_frontend, to_emitter_corpus
    code = '''function accept(value: number, mode = null) { return true; }
test('undefined', () => { expect(accept(3, undefined)).toBe(true); });
'''
    frontend = extract_frontend([Source('subject.test.ts', code, 'typescript')])
    corpus = to_emitter_corpus(frontend)
    result = enumerate_transforms(corpus, frontend)
    assert not [item for item in result['candidates'] if item['kind'] == 'explicit_default_omission']


def test_exception_receiver_rebinding_is_explicitly_unsupported(tmp_path):
    corpus = corpus_for(tmp_path, '''import pytest
class Resource:
    pass

def test_normal():
    original = Resource()
    assert original.done is True

def test_exception():
    current = Resource()
    with pytest.raises(ValueError):
        current.act(True)
        current = Resource()
''')
    result = enumerate_transforms(corpus)
    assert not [item for item in result['candidates'] if item['kind'] == 'exception_exit_observation']
    assert result['counts']['skipped']['exception_receiver_rebound_in_context'] >= 1


def test_source_field_default_propagates_through_wrapper_to_explicit_record(tmp_path):
    from relational_gap.frontend import extract_frontend, to_emitter_corpus
    code = '''function normalize({flavor = 'plain'} = {}) { return flavor; }
function wrapper(options) { return normalize(options); }
test('explicit', () => { expect(wrapper({flavor: 'plain', count: 3})).toBe('plain'); });
'''
    frontend = extract_frontend([Source('subject.test.ts', code, 'typescript')])
    corpus = to_emitter_corpus(frontend)
    result = enumerate_transforms(corpus, frontend)
    omitted = [item for item in result['candidates'] if item['kind'] == 'explicit_field_default_omission']
    assert len(omitted) == 1
    item = omitted[0]
    assert item['edits'][0]['before'] == "{flavor: 'plain', count: 3}"
    assert item['edits'][0]['after'] == '{count: 3}'
    assert len(item['relation']['binding_path']) >= 2
    assert item['relation']['applicability'] == 'source_default_not_proved_on_all_paths'
    output = emit(corpus, omitted)
    assert not output['unsupported']


def test_nested_default_omission_retains_siblings_and_uses_real_default_source(tmp_path):
    from relational_gap.frontend import extract_frontend, to_emitter_corpus
    code = '''function normalize({outer: {limit = 6}}) { return limit; }
test('explicit', () => { expect(normalize({outer: {limit: 6, keep: 7}, sibling: 8})).toBe(6); });
'''
    frontend = extract_frontend([Source('subject.test.ts', code, 'typescript')])
    corpus = to_emitter_corpus(frontend)
    result = enumerate_transforms(corpus, frontend)
    omitted = [item for item in result['candidates'] if item['kind'] == 'explicit_field_default_omission']
    assert len(omitted) == 1
    item = omitted[0]
    assert item['edits'][0]['before'] == '{limit: 6, keep: 7}'
    assert item['edits'][0]['after'] == '{keep: 7}'
    assert item['relation']['cell']['omitted_path'] == ['outer', 'limit']
    assert not emit(corpus, omitted)['unsupported']


def test_field_default_witness_is_kept_when_candidate_branch_skips_normalization(tmp_path):
    import json
    import shutil
    import subprocess
    import pytest
    from relational_gap.frontend import extract_frontend, to_emitter_corpus

    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is needed for the independent executable JavaScript witness')
    code = '''function normalize({flavor = 'plain'} = {}) { return flavor; }
function wrapper(options) {
    if (options.flavor !== undefined) return normalize(options);
    return options.flavor;
}
test('explicit', () => { expect(wrapper({flavor: 'plain'})).toBe('plain'); });
'''
    frontend = extract_frontend([Source('subject.test.ts', code, 'typescript')])
    corpus = to_emitter_corpus(frontend)
    omitted = [item for item in enumerate_transforms(corpus, frontend)['candidates']
               if item['kind'] == 'explicit_field_default_omission']
    assert len(omitted) == 1
    output = emit(corpus, omitted)
    assert not output['unsupported']
    driver = '''const failed = [];
globalThis.test = (name, body) => { try { body(); } catch (error) { failed.push(name); } };
globalThis.expect = (actual) => ({toBe: expected => { if (actual !== expected) throw Error('mismatch'); }});
'''
    execution = subprocess.run([node, '-e', driver + next(iter(output['files'].values()))
                                + '\nconsole.log(JSON.stringify(failed));'], text=True, capture_output=True, check=True)
    failures = json.loads(execution.stdout)
    assert failures == [output['obligations'][0]['test_name']]


def test_source_string_context_combines_fragment_with_unique_target_anchor(tmp_path):
    corpus = corpus_for(tmp_path, '''def accept(value):
    return isinstance(value, str)

def test_before():
    assert accept('[label=amber]') is True

def test_after():
    assert accept('[label=amber;extra=yes]') is True

def test_target():
    assert accept('parcel{label=violet}') is True
''')
    result = enumerate_transforms(corpus)
    selected = [item for item in result['candidates'] if item['kind'] == 'source_string_context'
                and item['edits'][0]['after'] == repr('parcel{label=violet;extra=yes}')]
    assert selected
    assert all(item['relation']['target_match_count'] == 1 for item in selected)
    assert all(item['relation']['source_before'] and item['relation']['source_after'] for item in selected)
    run_python_candidates(corpus, selected)
    assert result == enumerate_transforms(corpus)


def test_source_string_context_supports_deletion_and_replacement(tmp_path):
    corpus = corpus_for(tmp_path, '''def accept(value): return isinstance(value, str)
def test_before(): assert accept('[tag=amber;flag=yes]') is True
def test_delete(): assert accept('[tag=amber]') is True
def test_replace(): assert accept('[tag=amber;flag=no]') is True
def test_target(): assert accept('parcel{tag=violet;flag=yes}') is True
''')
    selected = [item for item in enumerate_transforms(corpus)['candidates'] if item['kind'] == 'source_string_context']
    replacements = {item['edits'][0]['after'] for item in selected}
    assert repr('parcel{tag=violet}') in replacements
    assert repr('parcel{tag=violet;flag=no}') in replacements
    run_python_candidates(corpus, selected)


def test_string_anchor_ambiguity_and_distinct_call_slots_are_not_guessed(tmp_path):
    corpus = corpus_for(tmp_path, '''def test_before(): assert accept('[key=amber]', 'untouched') == 1
def test_after(): assert accept('[key=amber;extra=yes]', 'untouched') == 1
def test_duplicate(): assert accept('[key=violet] [key=indigo]', 'untouched') == 1
def test_other_slot(): assert accept('other', 'parcel{key=violet}') == 1
''')
    result = enumerate_transforms(corpus)
    selected = [item for item in result['candidates'] if item['kind'] == 'source_string_context']
    assert not any(item['edits'][0]['before'] == "'parcel{key=violet}'" for item in selected)
    assert not any(item['edits'][0]['after'] in {
        repr('[key=violet;extra=yes] [key=indigo]'), repr('[key=violet] [key=indigo;extra=yes]')}
        for item in selected)


def test_string_rules_can_use_directly_bound_production_comparison_literals(tmp_path):
    from relational_gap.frontend import extract_frontend, to_emitter_corpus
    code = '''def accept(text):
    if text == '[tag=amber;extra=yes]':
        return True
    return True

def test_before(): assert accept('[tag=amber]') is True
def test_target(): assert accept('parcel{tag=violet}') is True
'''
    frontend = extract_frontend([Source('test_subject.py', code, 'python')])
    corpus = to_emitter_corpus(frontend)
    candidates = [item for item in enumerate_transforms(corpus, frontend)['candidates']
                  if item['kind'] == 'source_string_context'
                  and item['edits'][0]['after'] == repr('parcel{tag=violet;extra=yes}')]
    assert candidates
    assert any(any(source['kind'] == 'production_comparison_literal' and source['binding']
                   for source in item['relation']['source_facts']) for item in candidates)
    run_python_candidates(corpus, candidates)


def test_source_default_evidence_survives_identical_raw_slot_swap(tmp_path):
    from relational_gap.frontend import extract_frontend, to_emitter_corpus
    code = '''function normalize({flavor = 'plain'} = {}) { return flavor; }
test('explicit', () => { expect(normalize({flavor: 'plain'})).toBe('plain'); });
test('empty', () => { expect(normalize({})).toBe('plain'); });
'''
    frontend = extract_frontend([Source('subject.test.ts', code, 'typescript')])
    corpus = to_emitter_corpus(frontend)
    candidates = enumerate_transforms(corpus, frontend)['candidates']
    omitted = [item for item in candidates if item['edits'][0]['before'] == "{flavor: 'plain'}"
               and item['edits'][0]['after'] == '{}']
    assert len(omitted) == 1
    assert omitted[0]['kind'] == 'explicit_field_default_omission'
    assert omitted[0]['oracle']['basis']['kind'] == 'source_field_default'


def test_declared_field_defaults_support_partial_presence_without_empty_record_source(tmp_path):
    from relational_gap.frontend import extract_frontend, to_emitter_corpus
    code = '''function normalize({left = 0, right = 0}) { return left + right; }
test('both explicit', () => { expect(normalize({left: 3, right: 8})).toBe(11); });
'''
    frontend = extract_frontend([Source('subject.test.ts', code, 'typescript')])
    corpus = to_emitter_corpus(frontend)
    candidates = enumerate_transforms(corpus, frontend)['candidates']
    partial = [item for item in candidates if item['kind'] == 'partial_record_presence']
    assert len(partial) == 2
    assert {item['edits'][0]['after'] for item in partial} == {'{left: 3}', '{right: 8}'}
    assert all(item['relation']['default_declaration_span'] for item in partial)
    assert all(item['relation']['applicability'].endswith('expected_value_unknown') for item in partial)
    assert all(item['oracle']['applicability'] == 'requires_independent_admission' for item in partial)
    assert not emit(corpus, partial)['unsupported']


def test_partial_default_presence_does_not_require_default_expression_to_be_literal(tmp_path):
    from relational_gap.frontend import extract_frontend, to_emitter_corpus
    code = '''function fresh() { return []; }
function normalize({left = fresh(), right = 0}) { return true; }
test('explicit', () => { expect(normalize({left: [3], right: 8})).toBe(true); });
'''
    frontend = extract_frontend([Source('subject.test.ts', code, 'typescript')])
    corpus = to_emitter_corpus(frontend)
    candidates = [item for item in enumerate_transforms(corpus, frontend)['candidates'] if item['kind'] == 'partial_record_presence']
    assert any(item['edits'][0]['after'] == '{right: 8}' for item in candidates)
    assert not emit(corpus, candidates)['unsupported']


def test_record_syntax_alone_can_supply_unknown_presence_hypotheses(tmp_path):
    corpus = corpus_for(tmp_path, '''def test_only_full_record():
    assert consume({'first': 3, 'second': 8}) == 11
''')
    candidates = [item for item in enumerate_transforms(corpus)['candidates'] if item['kind'] == 'partial_record_presence']
    assert len(candidates) == 2
    assert all(item['relation']['evidence_level'] == 'record_syntax' for item in candidates)
    assert all(item['relation']['applicability'].startswith('unknown') for item in candidates)
    assert all(item['oracle']['applicability'] == 'requires_independent_admission' for item in candidates)
    assert not emit(corpus, candidates)['unsupported']


def test_nested_helper_declaration_is_not_mistaken_for_cross_test_global(tmp_path):
    corpus = corpus_for(tmp_path, '''def test_source():
    def local_builder(value):
        return value
    assert consume(local_builder(3)) == 1

def test_target():
    assert consume(global_builder(8)) == 1
''')
    result = enumerate_transforms(corpus)
    assert not any(item['edits'][0]['after'] == 'local_builder(3)' and item['edits'][0]['before'] == 'global_builder(8)'
                   for item in result['candidates'])
