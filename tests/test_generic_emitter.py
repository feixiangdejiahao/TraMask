import copy
from pathlib import Path

from anchor_retrieval.syntax import Source
from generic_composition.corpus import build_corpus
from generic_composition.emitter import emit


def corpus_for(tmp_path, code, language='python', path='test_sample.py'):
    file = tmp_path / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(code)
    corpus = build_corpus(tmp_path, language)
    return corpus, next(iter(corpus['tests'])), file


def candidate(corpus, test_id, before, after, identifier='first', imports=()):
    test = corpus['tests'][test_id]
    path = test['span']['path']
    data = corpus['sources'][path]['code'].encode()
    offset = data.index(before.encode(), test['span']['start_byte'], test['span']['end_byte'])
    return {'id': identifier, 'base_test_id': test_id, 'imports': list(imports),
            'edits': [{'span': {'path': path, 'start_byte': offset, 'end_byte': offset + len(before.encode())},
                       'before': before, 'after': after}]}


def test_unicode_byte_edit_and_original_files_remain_unchanged(tmp_path):
    original = 'def test_猫():\n    value = run("猫")\n    assert value == 7\n'
    corpus, test_id, path = corpus_for(tmp_path, original)
    snapshot = copy.deepcopy(corpus)
    result = emit(corpus, [candidate(corpus, test_id, '"猫"', '"猫猫"')])
    assert not result['unsupported']
    generated = result['files']['test_sample.py']
    assert 'def test_gc_first()' in generated
    assert 'run("猫猫")' in generated
    assert generated.count('assert value == 7') == 3
    assert len(result['controls']) == 1
    assert result['obligations'][0]['control_id'] == result['controls'][0]['id']
    assert path.read_text() == original
    assert corpus == snapshot


def test_python_decorators_parameter_rows_and_class_scope_are_preserved(tmp_path):
    code = '''import pytest
class TestGrouped:
    @pytest.mark.parametrize("value, wanted", [("a", 1), ("bb", 2)])
    def test_width(self, value, wanted):
        assert width(value) == wanted
'''
    corpus, test_id, _ = corpus_for(tmp_path, code)
    result = emit(corpus, [candidate(corpus, test_id, '"a"', '"aa"')])
    assert not result['unsupported']
    text = result['files']['test_sample.py']
    assert text.count('@pytest.mark.parametrize') == 3
    assert '    def test_gc_first(self, value, wanted)' in text
    assert '[("aa", 1), ("bb", 2)]' in text
    compile(text, '<generated>', 'exec')


def test_ts_clones_remain_inside_nested_describe_and_have_runtime_ids(tmp_path):
    code = '''describe('outer', () => {
  describe('inner', () => {
    const local = 3;
    test('source', () => { expect(run(local)).toBe(3); });
  });
});
'''
    corpus, test_id, _ = corpus_for(tmp_path, code, 'typescript', 'nested.test.ts')
    result = emit(corpus, [candidate(corpus, test_id, 'run(local)', 'adapt(run(local))')])
    assert not result['unsupported']
    text = result['files']['nested.test.ts']
    assert text.index('gc_first') < text.rfind('  });')
    assert result['obligations'][0]['id'] == 'outer inner gc_first'
    assert result['controls'][0]['id'].startswith('outer inner gc_control_')
    assert not Source('nested.test.ts', text, 'typescript').root.has_error


def test_multiple_clones_of_same_test_are_stable_and_share_one_control(tmp_path):
    corpus, test_id, _ = corpus_for(tmp_path, 'def test_one():\n    assert run(1) == 1\n')
    a = candidate(corpus, test_id, 'run(1)', 'run(2)', 'aaa')
    b = candidate(corpus, test_id, 'run(1)', 'run(3)', 'bbb')
    first, second = emit(corpus, [a, b]), emit(corpus, [b, a])
    assert first == second
    assert len(first['controls']) == 1
    assert len(first['obligations']) == 2
    assert 'run(2)' in first['files']['test_sample.py']
    assert 'run(3)' in first['files']['test_sample.py']


def test_invalid_and_overlapping_edits_are_explicit_unsupported(tmp_path):
    corpus, test_id, _ = corpus_for(tmp_path, 'def test_one():\n    assert run(1) == 1\n')
    broken = candidate(corpus, test_id, 'run(1)', 'run(')
    result = emit(corpus, [broken])
    assert not result['files'] and not result['controls']
    assert 'syntax_error' in result['unsupported'][0]['reason']
    overlapping = candidate(corpus, test_id, 'run(1)', 'run(3)')
    overlapping['edits'].append(candidate(corpus, test_id, '1', '2')['edits'][0])
    result = emit(corpus, [overlapping])
    assert 'overlapping_edits' in result['unsupported'][0]['reason']
    assert not result['obligations']


def test_go_function_names_and_new_imports_are_valid_syntax(tmp_path):
    corpus, test_id, _ = corpus_for(tmp_path, '''package sample
import "testing"
func TestSource(t *testing.T) { if run(1) != 1 { t.Fatal("bad") } }
''', 'go', 'sample_test.go')
    proposal = candidate(corpus, test_id, 'run(1)', 'extra.Adapt(run(1))', imports=[
        {'name': 'extra', 'module': 'example.org/extra', 'imported_name': None, 'source_path': 'other_test.go'}])
    result = emit(corpus, [proposal])
    assert not result['unsupported']
    text = result['files']['sample_test.go']
    assert 'func TestGC_first(t *testing.T)' in text
    assert 'import extra "example.org/extra"' in text
    assert not Source('sample_test.go', text, 'go').root.has_error


def test_ts_relative_import_is_rebased_without_changing_original_imports(tmp_path):
    corpus, test_id, _ = corpus_for(tmp_path, "test('source', () => { expect(run(1)).toBe(1); });\n",
                                      'typescript', 'tests/deep/sample.test.ts')
    proposal = candidate(corpus, test_id, 'run(1)', 'adapt(run(1))', imports=[
        {'name': 'adapt', 'module': '../actions/adapt.ts', 'imported_name': 'transform',
         'source_path': 'tests/other.test.ts'}])
    result = emit(corpus, [proposal])
    assert not result['unsupported']
    assert 'import { transform as adapt } from "../../actions/adapt.ts";' in result['files']['tests/deep/sample.test.ts']


def test_import_identifier_conflicts_are_not_silently_overwritten(tmp_path):
    corpus, test_id, _ = corpus_for(tmp_path, 'from left import adapt\ndef test_one():\n    assert run(1) == 1\n')
    proposal = candidate(corpus, test_id, 'run(1)', 'adapt(run(1))', imports=[
        {'name': 'adapt', 'module': 'right', 'imported_name': 'adapt', 'source_path': 'test_other.py'}])
    result = emit(corpus, [proposal])
    assert not result['files']
    assert result['unsupported'][0]['reason'] == 'import_conflicts_with_existing_import:adapt'


def test_python_import_header_preserves_docstring_and_future_position(tmp_path):
    code = '''"""Module documentation."""
from __future__ import annotations
def test_one():
    assert run(1) == 1
'''
    corpus, test_id, _ = corpus_for(tmp_path, code)
    proposal = candidate(corpus, test_id, 'run(1)', 'adapt(run(1))', imports=[
        {'name': 'adapt', 'module': 'other', 'imported_name': 'adapt', 'source_path': 'test_other.py'}])
    result = emit(corpus, [proposal])
    text = result['files']['test_sample.py']
    assert text.index('from __future__') < text.index('from other import adapt')
    assert text.startswith('"""Module documentation."""')


def test_original_donor_tests_get_explicit_controls(tmp_path):
    corpus, test_id, _ = corpus_for(tmp_path, '''def test_one():
    assert run(1) == 1
def test_two():
    assert run(2) == 2
''')
    donor = next(key for key, value in corpus['tests'].items() if value['name'] == 'test_two')
    proposal = candidate(corpus, test_id, 'run(1)', 'run(3)')
    proposal['source_test_ids'] = [donor]
    result = emit(corpus, [proposal])
    assert len(result['controls']) == 2
    assert len(result['obligations'][0]['control_ids']) == 2


def test_parameterized_ts_title_reports_unsupported_instead_of_collapsing_rows(tmp_path):
    code = "test.each([1, 2])('number %s', (value) => { expect(run(value)).toBe(value); });"
    corpus, test_id, _ = corpus_for(tmp_path, code, 'typescript', 'rows.test.ts')
    result = emit(corpus, [candidate(corpus, test_id, 'run(value)', 'adapt(run(value))')])
    assert not result['files']
    assert result['unsupported'][0]['reason'] == 'typescript_parameterized_title_requires_runtime_row_mapping'


def test_import_cannot_silently_bind_to_existing_outer_ts_local(tmp_path):
    code = '''describe('outer', () => {
 const adapt = (x) => x;
 test('source', () => { expect(run(1)).toBe(1); });
});'''
    corpus, test_id, _ = corpus_for(tmp_path, code, 'typescript', 'scope.test.ts')
    proposal = candidate(corpus, test_id, 'run(1)', 'adapt(run(1))', imports=[
        {'name': 'adapt', 'module': 'unrelated', 'imported_name': 'adapt', 'source_path': 'other.test.ts'}])
    result = emit(corpus, [proposal])
    assert not result['files']
    assert result['unsupported'][0]['reason'] == 'import_conflicts_with_test_local:adapt'
