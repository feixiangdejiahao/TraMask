"""Existing resource references are reused through source binding facts."""
from anchor_retrieval.syntax import Source
from generic_composition.corpus import build_corpus
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relational_gap.transforms import enumerate_transforms


def corpus_for(tmp_path, code):
    (tmp_path / 'test_identity.py').write_text(code)
    return build_corpus(tmp_path, 'python')


def identity(corpus, frontend=None):
    return [row for row in enumerate_transforms(corpus, frontend)['candidates'] if row['kind'] == 'shared_identity_input']


def test_two_resource_inputs_can_reuse_one_existing_value_without_constructor_changes(tmp_path):
    corpus = corpus_for(tmp_path, '''seen = []
class Carrier:
    def __init__(self, label):
        self.label = label

def consume(values, quota):
    seen.append((values[0] is values[1], quota))
    return True

def test_pair():
    first = Carrier('first')
    second = Carrier('second')
    assert consume([first, second], quota=2) is True
''')
    candidates = identity(corpus)
    assert candidates
    assert {(row['edits'][0]['before'], row['edits'][0]['after']) for row in candidates} == {
        ('first', 'second'), ('second', 'first')}
    output = emit(corpus, candidates)
    assert not output['unsupported']
    namespace = {}
    exec(next(iter(output['files'].values())), namespace)
    for row in output['obligations']:
        namespace[row['test_name']]()
    assert namespace['seen'] == [(True, 2)] * len(candidates)
    assert all(row['relation']['binding_precision'] == 'same_existing_lexical_value_at_edit_position' for row in candidates)
    assert all(row['oracle']['applicability'] == 'requires_independent_admission' for row in candidates)


def test_same_reference_reuse_covers_separate_arguments_and_assigned_container(tmp_path):
    corpus = corpus_for(tmp_path, '''class Carrier: pass

def test_arguments():
    first = Carrier()
    second = Carrier()
    assert consume(first, second)

def test_container():
    first = Carrier()
    second = Carrier()
    values = [first, second]
    assert consume(values)
''')
    candidates = identity(corpus)
    assert {corpus['tests'][row['base_test_id']]['name'] for row in candidates} == {'test_arguments', 'test_container'}
    assert any(row['relation']['source_argument_slot'] != row['relation']['target_argument_slot'] for row in candidates)
    assert all(len(row['edits']) == 1 for row in candidates)


def test_distinct_constructor_types_and_already_shared_aliases_are_not_new_identity_cells(tmp_path):
    corpus = corpus_for(tmp_path, '''class First: pass
class Second: pass

def test_distinct():
    first = First()
    second = Second()
    assert consume([first, second])

def test_shared():
    first = First()
    second = first
    assert consume([first, second])
''')
    assert identity(corpus) == []


def test_rebinding_rechecks_introduced_reference_at_actual_edit_site(tmp_path):
    corpus = corpus_for(tmp_path, '''class Carrier: pass

def test_rebind():
    first = Carrier()
    second = Carrier()
    values = [first, second]
    first = Carrier()
    assert consume(values, first)
''')
    candidates = identity(corpus)
    # The earlier list's first reference denotes the old object. Reusing its
    # spelling at the final call must not claim that old identity still exists.
    for row in candidates:
        relation = row['relation']
        if row['edits'][0]['after'] == 'first':
            assert relation['source_reference_span']['line'] == relation['target_reference_span']['line']


def test_same_declared_formal_type_can_supply_reference_reuse():
    code = '''class Carrier {}
function consume(first: Carrier, second: Carrier) { return true; }
test('typed inputs', (first: Carrier, second: Carrier) => {
  expect(consume(first, second)).toBe(true);
});
'''
    frontend = extract_frontend([Source('typed.test.ts', code, 'typescript')])
    corpus = to_emitter_corpus(frontend)
    candidates = identity(corpus, frontend)
    assert candidates
    assert all('declared_formal_type' in row['relation']['carrier_compatibility'] for row in candidates)
    assert not emit(corpus, candidates)['unsupported']


def test_unresolved_same_constructor_spelling_is_retained_as_explicit_hypothesis(tmp_path):
    corpus = corpus_for(tmp_path, '''def test_unknown_producer():
    first = external_factory('one')
    second = external_factory('two')
    assert consume([first, second])
''')
    candidates = identity(corpus)
    assert candidates
    assert all(any('return_type_unknown' in precision for precision in row['relation']['carrier_compatibility']) for row in candidates)


def test_callback_formal_shadow_does_not_become_outer_input_identity(tmp_path):
    corpus = corpus_for(tmp_path, '''class Carrier: pass

def test_shadow(first: Carrier, second: Carrier):
    assert consume((lambda first: first)(second), first)
''')
    assert identity(corpus) == []
