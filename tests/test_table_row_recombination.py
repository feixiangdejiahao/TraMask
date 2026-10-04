import copy
import json

import pytest

from anchor_retrieval.syntax import Source, child, walk
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search import table_row_recombination as relation
from relation_search import table_column_rotation as columns
from relation_search import compact_contract_guarded, oracle

CODE = '''package sample
import ("testing"; "example.org/subject"; "github.com/stretchr/testify/require")
// 中文 before edited bytes.
func TestPairs(t *testing.T) {
 rows := []struct{ left, right string }{
  {"α", "one"},
  {`bb`, "two"},
  {"ccc", "three"},
 }
 for _, row := range rows {
  got := subject.Combine(row.left, row.right)
  require.Equal(t, subject.Expected(row.right), got)
 }
 require.True(t, subject.Finished())
}
'''


def fixture(code=CODE):
    frontend = extract_frontend([Source('sample_test.go', code, 'go', 'repository')])
    return to_emitter_corpus(frontend), frontend


def test_projects_single_new_pair_but_preserves_complete_kernel_and_original_control():
    corpus, frontend = fixture(); before = copy.deepcopy((corpus, frontend))
    result = relation.generate(corpus, frontend)
    assert result['total_candidates'] == 6
    first = result['candidates'][0]
    assert first['edits'][0]['after'] == '[]struct{ left, right string }{{`bb`, "one"},}'
    assert first['source_evidence']['generated_row_count'] == 1
    assert first['source_evidence']['row_independence_proved'] is False
    code = oracle.preview(corpus, first)
    assert code.endswith('require.True(t, subject.Finished())\n}')
    assert 'require.Equal(t, subject.Expected(row.right), got)' in code
    emitted = emit(corpus, [first])
    assert not emitted['unsupported']
    assert (corpus, frontend) == before
    assert '"α", "one"' in CODE
    assert first['source_test_ids'] == [first['base_test_id']]
    json.dumps(result)


def test_exact_existing_tuples_and_duplicate_projection_programs_are_not_new_candidates():
    code = CODE.replace('{"ccc", "three"}', '{`bb`, "one"}')
    corpus, frontend = fixture(code)
    result = relation.generate(corpus, frontend)
    assert result['candidates']
    replacements = [c['edits'][0]['after'] for c in result['candidates']]
    assert len(replacements) == len(set(replacements))
    assert all('{{`bb`, "one"},}' not in text for text in replacements)


def test_duplicate_witnesses_keep_earliest_declared_recipient_before_column():
    corpus, frontend = fixture(CODE.replace('  {"ccc", "three"},\n', ''))
    result = relation.generate(corpus, frontend)
    assert result['total_candidates'] == 2
    assert [c['source_evidence']['recipient_row'] for c in result['candidates']] == [0, 0]
    assert [c['source_evidence']['column'] for c in result['candidates']] == [0, 1]
    assert '{{"α", "two"},}' in result['candidates'][1]['edits'][0]['after']


def test_multiline_unicode_cell_keeps_exact_go_literal_and_complete_review():
    corpus, frontend = fixture(CODE.replace('`bb`', '`b\n中`'))
    candidate = relation.generate(corpus, frontend)['candidates'][0]
    prepared = compact_contract_guarded.prepare(corpus, frontend, candidate,
        'Combine accepts independent left and right inputs; Expected specifies the right-input result.',
        max_prompt_bytes=100000)
    assert prepared['request'] is not None
    payload = json.loads(prepared['request']['prompt'])
    assert '`b\n中`' in payload['modified_test']
    assert payload['modified_test'] == oracle.preview(corpus, candidate)
    assert 'subject.Finished()' in payload['modified_test']
    assert not Source('sample_test.go', 'package sample\n'+payload['modified_test'], 'go').root.has_error


def test_inherits_source_binding_abstentions_instead_of_projecting_arbitrary_tables():
    code = CODE.replace('for _, row := range rows {', 'alias := rows\n for _, row := range alias {')
    corpus, frontend = fixture(code)
    assert relation.generate(corpus, frontend)['candidates'] == []


def test_case_identity_and_issue_words_do_not_select_projection():
    corpus, frontend = fixture()
    first = relation.generate(corpus, frontend, 'unrelated public requirement')
    second = relation.generate(corpus, frontend, 'another public requirement')
    assert first == second


@pytest.mark.parametrize('limit', [-1, 17, True, 1.5])
def test_projection_budget_is_explicit(limit):
    corpus, frontend = fixture()
    with pytest.raises(ValueError):
        relation.generate(corpus, frontend, limit=limit)


def test_complete_new_program_has_one_table_row_and_original_full_function_extent():
    corpus, frontend = fixture()
    candidate = relation.generate(corpus, frontend)['candidates'][0]
    source = Source('sample_test.go', 'package sample\n'+oracle.preview(corpus, candidate), 'go')
    table = next(n for n in walk(source.root) if n.type == 'composite_literal')
    assert len(columns._parts(child(table, 'body'))) == 1
