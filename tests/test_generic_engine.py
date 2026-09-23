"""Independent miniature repositories: mechanics, never pilot outcomes."""
from generic_composition.corpus import build_corpus, source_text
from generic_composition.engine import Budget, _imports_for, expanded_donors, generate


def corpus_from(tmp_path, files, language='python', retrieval=None):
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return build_corpus(tmp_path, language, retrieval)


def test_parameter_expected_cells_are_never_exposed_as_editable_input(tmp_path):
    corpus = corpus_from(tmp_path, {'test_rows.py': '''import pytest
def check(actual, expected):
    assert actual == expected
@pytest.mark.parametrize("item, expected", [("item:1", "want:1"), ("item:2", "want:2"), ("item:3", "want:3")])
def test_values(item, expected):
    check(parse(item), expected)
'''})
    cells = [d for d in expanded_donors(corpus) if 'parameter_row' in d]
    assert cells and {d['parameter_row']['name'] for d in cells} == {'item'}
    generated = generate(corpus)
    assert generated['candidates']
    assert all('want:' not in edit['before'] for p in generated['candidates'] for edit in p['edits'])


def test_oracle_value_dependencies_are_frozen_beyond_assertion_text(tmp_path):
    code = '''def check(actual, expected):
    assert actual == expected
'''
    for name, value in [('one', 1), ('two', 2), ('three', 3)]:
        code += f'''\ndef test_{name}():
    want = "want:{value}"
    check(parse("item:{value}"), want)
'''
    corpus = corpus_from(tmp_path, {'test_values.py': code})
    generated = generate(corpus)
    assert generated['candidates']
    assert all('want:' not in edit['before'] for p in generated['candidates'] for edit in p['edits'])


def test_literal_rules_do_not_cross_distinct_call_ports(tmp_path):
    corpus = corpus_from(tmp_path, {'test_ports.py': '''def test_one():
    assert submit("left:1", "right:7") == 1
def test_two():
    assert submit("left:2", "right:8") == 2
def test_three():
    assert submit("left:3", "right:9") == 3
'''})
    generated = generate(corpus)
    assert generated['candidates']
    rules = {r['id']: r for r in generated['rules']}
    for candidate in generated['candidates']:
        rule = rules[candidate['rule_id']]
        assert rule['kind'] == 'literal_difference'
        category = 'left:' if rule['slot'][1] == 0 else 'right:'
        assert category in source_text(corpus, rule['before_span'])
        assert category in source_text(corpus, rule['after_span'])
        assert category in candidate['edits'][0]['before']
        assert category in candidate['edits'][0]['after']


def test_context_preserves_target_assertion_and_rejects_other_producer(tmp_path):
    corpus = corpus_from(tmp_path, {'test_wrap.py': '''def test_wrapper():
    assert surround(make(1)) == 1
def test_donor():
    assert make(2) == 2
def test_other():
    assert unrelated(3) == 3
'''})
    generated = generate(corpus)
    contexts = [p for p in generated['candidates'] if p['kind'] == 'ast_context']
    assert contexts
    assert any(p['edits'][0]['before'] == 'make(2)' and p['edits'][0]['after'] == 'surround(make(2))'
               for p in contexts)
    assert not any('unrelated' in p['edits'][0]['before'] for p in contexts)
    for p in contexts:
        assert p['oracle']['source_test_id'] == p['base_test_id']
        assert p['oracle']['assertion_ids'] == [a['id'] for a in corpus['capsules']
                                               if a['test_id'] == p['base_test_id']]
        assert p['provenance']['binding_precision'].endswith('effects_and_aliases_unproved')


def test_cross_file_import_shadow_is_unresolved(tmp_path):
    corpus = corpus_from(tmp_path, {
        'test_source.py': '''from widgets import surround
def test_source():
    assert surround(make(1)) == 1
''',
        'test_target.py': '''def test_target():
    surround = 7
    assert make(2) == 2
'''})
    source = next(d for d in corpus['donors'] if d.get('text') == 'make(1)')
    target = next(d for d in corpus['donors'] if d.get('text') == 'make(2)')
    imports, unknown = _imports_for(corpus, source, target, {'surround'})
    assert imports == [] and unknown == ['surround']


def test_same_file_different_enclosing_scope_is_not_automatic_visibility(tmp_path):
    corpus = corpus_from(tmp_path, {'scope.test.ts': '''describe('first', () => {
 const surround = (x) => x;
 test('source', () => { expect(surround(make(1))).toBe(1); });
});
describe('second', () => {
 test('target', () => { expect(make(2)).toBe(2); });
});
'''}, 'typescript')
    source = next(d for d in corpus['donors'] if d.get('text') == 'make(1)')
    target = next(d for d in corpus['donors'] if d.get('text') == 'make(2)')
    assert _imports_for(corpus, source, target, {'surround'}) == ([], ['surround'])


def test_pool_cap_keeps_two_seed_groups_represented(tmp_path):
    code = ''
    for name, function in [('first', 'alpha'), ('second', 'zeta')]:
        code += f'def test_{name}():\n'
        code += ''.join(f'    assert {function}("v:{i}") == {i}\n' for i in (1, 2, 3))
    corpus = corpus_from(tmp_path, {'test_groups.py': code})
    generated = generate(corpus, Budget(max_candidates=2, max_pool=2))
    assert len(generated['candidates']) == 2
    assert len({p['focus_test_id'] for p in generated['candidates']}) == 2
    assert generated['counts']['candidate_pool'] <= 2


def test_identical_contexts_on_distinct_producers_keep_both_source_relations(tmp_path):
    corpus = corpus_from(tmp_path, {'test_contexts.py': '''def test_alpha_wrapper():
    assert surround(alpha(1)) == 1
def test_beta_wrapper():
    assert surround(beta(1)) == 1
def test_alpha_plain():
    assert alpha(2) == 2
def test_beta_plain():
    assert beta(2) == 2
'''})
    generated = generate(corpus)
    before = {p['edits'][0]['before'] for p in generated['candidates'] if p['kind'] == 'ast_context'}
    assert {'alpha(2)', 'beta(2)'} <= before


def test_assertion_framework_wrappers_are_not_learned_as_input_contexts(tmp_path):
    corpus = corpus_from(tmp_path, {'values.test.ts': '''test('one', () => { expect(make(1)).toBe(1); });
test('two', () => { expect(make(2)).toBe(2); });
'''}, 'typescript')
    generated = generate(corpus)
    assert not [p for p in generated['candidates'] if p['kind'] == 'ast_context']


def test_generation_and_source_backed_candidate_ids_are_deterministic(tmp_path):
    corpus = corpus_from(tmp_path, {'test_same.py': '''def test_wrapped():
    assert surround(make(1)) == 1
def test_plain():
    assert make(2) == 2
'''})
    first, second = generate(corpus), generate(corpus)
    assert first == second
    ids = [p['id'] for p in first['candidates']]
    assert len(ids) == len(set(ids))
    by_id = {r['id']: r for r in first['rules']}
    for p in first['candidates']:
        rule = by_id[p['rule_id']]
        assert any(source_text(corpus, corpus['tests'][tid]['span']).find(
                   source_text(corpus, rule['before_span'])) >= 0 for tid in p['source_test_ids'])
