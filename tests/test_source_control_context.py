"""Authored source fixtures; no trajectory, labels, providers, or native runs."""
import copy

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search.source_control_context import analyze


def prepare(code, before='"old"', after='"new"', extra=None):
    sources = [Source('tests/test_context.py', code, 'python')]
    sources += [Source(path, content, 'python') for path, content in (extra or {}).items()]
    frontend = extract_frontend(sources)
    corpus = to_emitter_corpus(frontend)
    identifier = next(t for t in corpus['tests'] if t.endswith(':test_new'))
    # Existing tests intentionally remain in complete sources, but are absent
    # from the emitter inventory, as happens for untouched repository tests.
    corpus['tests'] = {identifier: corpus['tests'][identifier]}
    start = code.encode().index(before.encode(), corpus['tests'][identifier]['span']['start_byte'])
    candidate = dict(id='authored', base_test_id=identifier, imports=[], source_test_ids=[], edits=[dict(
        span=dict(path='tests/test_context.py', start_byte=start, end_byte=start + len(before.encode())),
        before=before, after=after, role='input')])
    return corpus, frontend, candidate


BASE = '''import pytest
from library.reader import Reader
@pytest.fixture
def reader():
    return Reader()
def test_existing(reader):
    result = reader.consume("new-sample")
    assert result == 1
def test_new(reader):
    result = reader.consume("old")
    assert result == 1
'''


def test_recovers_existing_unindexed_test_using_fixture_identity():
    data = prepare(BASE)
    snapshot = copy.deepcopy(data)
    result = analyze(*data)
    control, = result['controls']
    assert result['status'] == 'analyzed' and control['name'] == 'test_existing'
    match, = control['matches']
    assert match['basis'] == 'same_fixture_definition_and_method'
    assert not match['equivalence_proved']
    assert '@pytest.fixture\ndef reader():' in match['fixture']['code']
    assert 'assert result == 1' in control['code']
    assert data == snapshot


def test_method_and_fixture_identity_must_both_match():
    code = BASE.replace('def test_existing(reader):', '''@pytest.fixture
def other():
    return Reader()
def test_wrong_fixture(other):
    assert other.consume("new") == 1
def test_wrong_method(reader):
    assert reader.write("new") == 1
def test_existing(reader):''')
    assert [r['name'] for r in analyze(*prepare(code))['controls']] == ['test_existing']


@pytest.mark.parametrize('change', [
    'reader = fake\n    result = reader.consume("old")',
    'try:\n        go()\n    except Error as reader:\n        result = reader.consume("old")',
    'match value:\n        case {"reader": reader}:\n            result = reader.consume("old")',
    'def reader():\n        pass\n    result = reader.consume("old")',
])
def test_rebound_fixture_is_unknown(change):
    code = BASE.replace('result = reader.consume("old")', change)
    result = analyze(*prepare(code))
    assert not result['controls'] and result['unknowns']


def test_parametrization_overrides_fixture_conservatively():
    code = BASE.replace('def test_new(reader):', '@pytest.mark.parametrize("reader", [fake])\ndef test_new(reader):')
    assert not analyze(*prepare(code))['controls']


def test_explicit_import_aliases_match_shared_api():
    code = '''from library import decode as parse
def test_existing():
    assert parse("new-record") == []
def test_new():
    assert parse("old") == []
'''
    control, = analyze(*prepare(code))['controls']
    assert control['matches'][0]['basis'] == 'same_explicit_import_binding'


@pytest.mark.parametrize('binding', ['parse = other\n', 'from other import *\n', 'import other as parse\n',
    'if condition:\n    from other import parse\n'])
def test_import_binding_ambiguity_is_not_name_equality(binding):
    code = 'from library import decode as parse\n' + binding + '''def test_existing():
    assert parse("new") == []
def test_new():
    assert parse("old") == []
'''
    assert not analyze(*prepare(code))['controls']


def test_local_function_identity_supported_without_production_body_output():
    code = '''def consume(value):
    return hidden_implementation(value)
def test_existing():
    assert consume("new-value") == 1
def test_new():
    assert consume("old") == 1
'''
    result = analyze(*prepare(code))
    control, = result['controls']
    assert control['matches'][0]['basis'] == 'same_local_function_declaration'
    assert 'hidden_implementation' not in str(result)


def test_fixed_literal_fragment_score_ranks_input_context_not_assert_expected_values():
    code = BASE.replace('def test_existing(reader):', '''def test_less_similar(reader):
    value = reader.consume("different")
    assert value == "prefix-new-value"
def test_existing(reader):''').replace('"new-sample"', '"prefix-new-value-extra"')
    result = analyze(*prepare(code, after='"prefix-new-value"'), max_controls=1)
    control, = result['controls']
    assert control['name'] == 'test_existing'
    assert control['literal_fragment_score'] == len('prefix-new-value')


def test_equal_scores_break_ties_by_source_order():
    code = BASE.replace('def test_existing(reader):', '''def test_first(reader):
    assert reader.consume("new-sample") == 1
def test_existing(reader):''')
    # Without setup/call literals outside assertions, first has score zero;
    # eliminate literals from both to verify the declared stable tie break.
    code = code.replace('result = reader.consume("new-sample")\n    assert result == 1', 'assert reader.consume("new-sample") == 1')
    assert [r['name'] for r in analyze(*prepare(code))['controls']] == ['test_first', 'test_existing']


def test_complete_decorated_control_is_kept_and_budget_never_truncates_code():
    code = BASE.replace('def test_existing(reader):', '@pytest.mark.parametrize("size", [1, 2])\ndef test_existing(reader, size):')
    control, = analyze(*prepare(code))['controls']
    assert control['code'].startswith('@pytest.mark.parametrize')
    assert not analyze(*prepare(code), max_control_bytes=1)['controls']
    assert not analyze(*prepare(code), max_controls=0)['controls']


def test_exact_unicode_byte_spans():
    code = BASE.replace('import pytest', '# 猫\nimport pytest')
    result = analyze(*prepare(code))
    control, = result['controls']
    span = control['span']
    # Edits are later in the module, so this control retains its original bytes.
    assert code.encode()[span['start_byte']:span['end_byte']].decode() == control['code']


def test_module_header_and_one_import_hop_urls_are_links_only():
    extra = {
      'src/library/reader.py': '# https://example.test/reader\nfrom library.table import TABLE\nclass Reader:\n    pass\n',
      'src/library/table.py': '"""Format specification: https://example.test/format"""\nTABLE = {}\n',
      'src/library/unrelated.py': '# https://example.test/unrelated\n',
    }
    result = analyze(*prepare(BASE, extra=extra))
    assert [r['url'] for r in result['documentation_links']] == ['https://example.test/format', 'https://example.test/reader']
    assert all(not r['fetched'] for r in result['documentation_links'])
    assert 'TABLE = {}' not in str(result)


def test_urls_inside_production_body_are_not_exported():
    extra = {'src/library/reader.py': 'class Reader:\n    def hidden(self):\n        return "https://example.test/secret"\n'}
    assert not analyze(*prepare(BASE, extra=extra))['documentation_links']


def test_other_languages_explicitly_unsupported_and_limits_validated():
    corpus, frontend, candidate = prepare(BASE)
    assert analyze(dict(corpus, language='go'), frontend, candidate)['status'] == 'unsupported_language'
    with pytest.raises(ValueError):
        analyze(corpus, frontend, candidate, max_controls=-1)


def test_injected_sibling_is_never_recovered_as_original_control():
    corpus, frontend, candidate = prepare(BASE)
    selected = corpus['tests'][candidate['base_test_id']]['span']
    before = BASE.encode()[selected['start_byte']:selected['end_byte']].decode()
    after = before.replace('"old"', '"new"') + '''
def test_injected(reader):
    result = reader.consume("new")
    assert result == "candidate-invented oracle"
'''
    candidate['edits'] = [dict(span=selected, before=before, after=after, role='input')]
    result = analyze(corpus, frontend, candidate)
    assert [r['name'] for r in result['controls']] == ['test_existing']
    assert 'candidate-invented oracle' not in str(result)
    assert result['controls'][0]['source_version'] == 'original'


def test_candidate_added_import_binding_is_suppressed_without_guessing():
    corpus, frontend, candidate = prepare(BASE)
    candidate['imports'] = [dict(name='Reader', module='different', imported_name='Fake')]
    result = analyze(corpus, frontend, candidate)
    assert result['status'] == 'unknown_added_import_bindings'
    assert not result['controls'] and not result['documentation_links']


@pytest.mark.parametrize('statement', ['reader = other\n', 'del reader\n',
    'if flag:\n    reader = other\n', 'for reader in values:\n    pass\n',
    'try:\n    go()\nexcept Error as reader:\n    pass\n'])
def test_module_reassignment_invalidates_fixture_identity(statement):
    code = BASE.replace('def test_existing(reader):', statement + 'def test_existing(reader):')
    assert not analyze(*prepare(code))['controls']


def test_module_reassignment_invalidates_local_function_identity():
    code = '''def consume(value):
    return value
consume = replacement
def test_existing():
    assert consume("new") == 1
def test_new():
    assert consume("old") == 1
'''
    assert not analyze(*prepare(code))['controls']


@pytest.mark.parametrize('parameters', ['reader=None', 'reader, /', '*reader', '**reader', '*, reader=None'])
def test_noninjectable_parameter_is_not_a_pytest_fixture(parameters):
    code = BASE.replace('def test_new(reader):', f'def test_new({parameters}):')
    assert not analyze(*prepare(code))['controls']


def test_required_keyword_only_parameter_can_be_a_fixture():
    code = BASE.replace('def test_new(reader):', 'def test_new(*, reader):')
    assert [r['name'] for r in analyze(*prepare(code))['controls']] == ['test_existing']


def test_expected_value_assignment_does_not_boost_literal_ranking():
    code = BASE.replace('def test_existing(reader):', '''def test_unrelated_expected(reader):
    expected = "new-sample"
    result = reader.consume("unrelated-input")
    assert result == expected
def test_existing(reader):''')
    result = analyze(*prepare(code, after='"new-sample"'), max_controls=1)
    assert result['controls'][0]['name'] == 'test_existing'
    assert result['controls'][0]['literal_fragment_score'] == len('new-sample')
    # Changing only an unrelated expected assignment cannot affect its score.
    other = code.replace('expected = "new-sample"', 'expected = "unrelated-expectation"')
    left = analyze(*prepare(code, after='"new-sample"'))
    right = analyze(*prepare(other, after='"new-sample"'))
    assert [(r['name'], r['literal_fragment_score']) for r in left['controls']] == [
        (r['name'], r['literal_fragment_score']) for r in right['controls']]


def test_matched_call_input_follows_simple_assignments_and_loop_provenance():
    code = BASE.replace('result = reader.consume("new-sample")\n    assert result == 1', '''prefix = "new-sample"
    data = prefix + "tail"
    for chunk in pieces(data):
        assert reader.consume(chunk) == 1''')
    control, = analyze(*prepare(code, after='"new-sample"'))['controls']
    assert control['literal_fragment_score'] == len('new-sample')


def test_original_and_modified_offsets_are_versioned_independently():
    # Put the example and fixture after the edited test, so every original
    # context offset differs from its modified-source position.
    code = '''import pytest
from library.reader import Reader
def test_new(reader):
    assert reader.consume("old") == 1
@pytest.fixture
def reader():
    return Reader()
def test_existing(reader):
    assert reader.consume("new-sample") == 1
'''
    data = prepare(code, after='"new-sample-longer"')
    result = analyze(*data)
    control, = result['controls']
    assert control['span']['version'] == 'original'
    assert code.encode()[control['span']['start_byte']:control['span']['end_byte']].decode() == control['code']
    match, = control['matches']
    assert match['example_call']['version'] == 'original'
    assert match['changed_call']['version'] == 'modified'
    assert match['fixture']['source_version'] == 'original'
    fixture = match['fixture']
    assert fixture['span']['version'] == 'original'
    assert code.encode()[fixture['span']['start_byte']:fixture['span']['end_byte']].decode() == fixture['code']
    assert result['original_source_sha256'] != result['modified_source_sha256']


@pytest.mark.parametrize('binding, adapter', [('import pytest', 'pytest.raises'), ('from pytest import raises as raises_error', 'raises_error')])
def test_functional_exception_adapter_expected_regex_is_not_an_input_seed(binding, adapter):
    code = f'''{binding}
from library import parse
def test_existing():
    {adapter}(ValueError, parse, "new", match="expected-regex")
def test_new():
    {adapter}(ValueError, parse, "old", match="new")
'''
    result = analyze(*prepare(code))
    assert not result['controls'] and result['unknowns']
