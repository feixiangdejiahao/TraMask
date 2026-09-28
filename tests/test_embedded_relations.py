"""Independent SQL relation fixtures; no subject reports or evaluation labels."""
import ast
from decimal import Decimal
import sqlite3

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.embedded_relations import (
    EmbeddedRelationBudget, format_source_string, generate_embedded_relations, parse_sql_program,
)
from relational_gap.frontend import extract_frontend, to_emitter_corpus


def fixture(code, language='python'):
    path = {'python': 'test_relations.py', 'go': 'relations_test.go', 'typescript': 'relations.test.ts'}[language]
    frontend = extract_frontend([Source(path, code, language)])
    corpus = to_emitter_corpus(frontend)
    for rank, test in enumerate(corpus['tests'].values(), 1):
        test['retrieval_rank'] = rank
    return corpus, frontend


def source_test(read='SELECT id FROM samples WHERE score > 10',
                write='UPDATE samples SET label = 3 WHERE id = 1'):
    return f'''import sqlite3

def test_changes():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE samples(id INTEGER PRIMARY KEY, score INTEGER, label INTEGER)")
    db.execute("INSERT INTO samples VALUES (1, 11, 0), (2, 11, 0)")
    query = {read!r}
    before = db.execute(query).fetchall()
    db.execute({write!r})
    after = db.execute(query).fetchall()
    assert isinstance(after, list)
'''


def database():
    db = sqlite3.connect(':memory:')
    db.execute('CREATE TABLE samples(id INTEGER PRIMARY KEY, score INTEGER, label INTEGER)')
    db.execute('INSERT INTO samples VALUES (1, 11, 0), (2, 11, 0)')
    return db


def test_sql_predicate_boundaries_change_membership_and_preserve_other_rows():
    corpus, frontend = fixture(source_test())
    result = generate_embedded_relations(corpus, frontend)
    assert len(result['candidates']) == 3
    assert result == generate_embedded_relations(corpus, frontend)
    for candidate in result['candidates']:
        edit, = candidate['edits']
        sql = ast.literal_eval(edit['after'])
        assert sql.startswith('UPDATE samples SET label = 3, score = ')
        assert sql.endswith(' WHERE id = 1')
        with database() as db:
            before = db.execute('SELECT id FROM samples WHERE score > 10').fetchall()
            db.execute(sql)
            after = db.execute('SELECT id FROM samples WHERE score > 10').fetchall()
            assert (before == after) == candidate['relation']['cell']['assigned_predicate_truth']
            assert db.execute('SELECT * FROM samples WHERE id = 2').fetchall() == [(2, 11, 0)]
            assert db.execute('SELECT label FROM samples WHERE id = 1').fetchone() == (3,)
        assert candidate['oracle']['applicability'] == 'requires_independent_admission'
        assert candidate['oracle']['basis'] is None
        assert candidate['relation']['table_identity'] == 'same_explicit_source_identifier'
        assert 'database_receiver_identity' in candidate['relation']['unknowns']
        predicate_fact = candidate['provenance']['source_facts'][0]
        assert predicate_fact['role'] == 'read_predicate'
        assert predicate_fact['text'] == 'score > 10'
    output = emit(corpus, result['candidates'])
    assert not output['unsupported']
    namespace = {}
    exec(compile(output['files']['test_relations.py'], 'test_relations.py', 'exec'), namespace)
    for row in output['obligations'] + output['controls']:
        namespace[row['test_name']]()


def test_assertion_retention_is_not_an_oracle_transfer_proof():
    code = source_test().replace('assert isinstance(after, list)', 'assert after == [(1,), (2,)]')
    corpus, frontend = fixture(code)
    candidate = next(c for c in generate_embedded_relations(corpus, frontend)['candidates']
                     if c['relation']['assigned_value'] == '10')
    output = emit(corpus, [candidate])
    namespace = {}
    exec(output['files']['test_relations.py'], namespace)
    namespace['test_changes']()
    with pytest.raises(AssertionError):
        namespace[output['obligations'][0]['test_name']]()
    assert candidate['oracle']['applicability'] == 'requires_independent_admission'


def test_existing_field_changes_rhs_without_duplicate_assignment():
    code = source_test(write='UPDATE samples SET label = 3, score = 99 WHERE id = 1')
    corpus, frontend = fixture(code)
    candidates = generate_embedded_relations(corpus, frontend)['candidates']
    assert len(candidates) == 3
    for candidate in candidates:
        sql = ast.literal_eval(candidate['edits'][0]['after'])
        assert sql.count('score =') == 1
        assert candidate['relation']['source_assigned_predicate_truth'] is True
        with database() as db:
            db.execute(sql)


def test_source_assignment_value_reused_only_at_aligned_slots():
    code = source_test(write='UPDATE samples SET score = 9 WHERE id = 1') + '''
def test_assignment_source():
    db = open_database()
    db.execute("UPDATE samples SET score = 40 WHERE id = 2")
    assert db is not None
'''
    corpus, frontend = fixture(code)
    candidates = generate_embedded_relations(corpus, frontend)['candidates']
    source_values = [c for c in candidates if c['relation']['value_basis'] == 'source_assignment']
    assert len(source_values) == 1
    assert source_values[0]['relation']['assigned_value'] == '40'
    assert len(source_values[0]['source_test_ids']) == 2
    assert source_values[0]['provenance']['source_facts'][-1]['text'] == 'score = 40'
    other, other_frontend = fixture(code.replace('db.execute("UPDATE samples SET score = 40', 'different_slot("UPDATE samples SET score = 40'))
    assert not [c for c in generate_embedded_relations(other, other_frontend)['candidates']
                if c['relation']['value_basis'] == 'source_assignment']


@pytest.mark.parametrize('sql,field,operator,threshold', [
    ('SELECT * FROM samples WHERE score >= - 2', 'score', '>=', '-2'),
    ('SELECT * FROM samples WHERE 1.5e1 < score', 'score', '>', '15'),
    ('SELECT * FROM samples s WHERE (s.score != 0)', 'score', '!=', '0'),
    ('SELECT * FROM "samples" AS s WHERE NOT (s."score" < 3)', '"score"', '>=', '3'),
    ('SELECT * FROM samples WHERE label = \'score > 999\' AND score > 7', 'score', '>', '7'),
    ('SELECT * FROM samples /* WHERE fake > 3 */ WHERE score > 4 -- score < 900', 'score', '>', '4'),
])
def test_source_predicate_parser_handles_quoted_identifiers_comments_and_comparison_direction(sql, field, operator, threshold):
    program = parse_sql_program(sql)
    assert program is not None
    predicate, = program.predicates
    assert predicate.field.leaf.key == (field,)
    assert predicate.operator == operator
    assert predicate.threshold == Decimal(threshold)


@pytest.mark.parametrize('sql', [
    'SELECT * FROM samples a JOIN other b ON a.id = b.id WHERE a.score > 1',
    'SELECT * FROM samples WHERE unknown.score > 1',
    'SELECT * FROM samples WHERE score BETWEEN 0 AND 1',
    'SELECT * FROM samples WHERE score > ?',
    'SELECT * FROM samples WHERE score > (SELECT max(score) FROM other)',
    'SELECT * FROM samples WHERE score > 1; UPDATE samples SET score = 0',
    'SELECT * FROM samples WHERE score > 1 UNION SELECT * FROM other',
    'SELECT * FROM samples WHERE score > 1 /* unfinished',
    'SELECT * FROM samples WHERE (score > 1',
    'UPDATE samples SET score = 1, score = 2',
    'UPDATE samples SET (score, label) = (1, 2)',
    'UPDATE samples SET score = 1 RETURNING score',
])
def test_unsupported_sql_is_rejected_or_has_no_numeric_predicate(sql):
    program = parse_sql_program(sql)
    assert program is None or not program.predicates


def test_other_table_and_expected_sql_never_supply_relation_inputs():
    corpus, frontend = fixture(source_test(write='UPDATE unrelated SET label = 3 WHERE id = 1'))
    result = generate_embedded_relations(corpus, frontend)
    assert not result['candidates']
    assert result['counts']['skipped']['different_or_unresolved_table'] == 1
    corpus, frontend = fixture('''def test_expected_only():
    apply("UPDATE samples SET label = 3 WHERE id = 1")
    assert observed() == "SELECT id FROM samples WHERE score > 10"
''')
    assert not generate_embedded_relations(corpus, frontend)['candidates']


def test_select_inside_observed_expression_can_supply_predicate():
    corpus, frontend = fixture('''def test_inline():
    db.execute("UPDATE samples SET label = 3 WHERE id = 1")
    assert db.execute("SELECT id FROM samples WHERE score > 10").fetchall() == [(1,)]
''')
    assert len(generate_embedded_relations(corpus, frontend)['candidates']) == 3


def test_nested_string_leaf_uses_explicit_path_but_unobserved_write_is_excluded():
    corpus, frontend = fixture('''def test_nested():
    select("SELECT id FROM samples WHERE score > 10")
    apply({"query": "UPDATE samples SET label = 3 WHERE id = 1"})
    assert observed()
def test_late_write():
    select("SELECT id FROM samples WHERE score > 10")
    assert observed()
    apply("UPDATE samples SET label = 3 WHERE id = 1")
''')
    candidates = generate_embedded_relations(corpus, frontend)['candidates']
    assert len(candidates) == 3
    assert all(c['base_test_id'].endswith(':test_nested') for c in candidates)
    assert all(c['relation']['write_structural_path'] == [{'kind': 'key', 'value': 'query'}] for c in candidates)


@pytest.mark.parametrize('original', ['"source"', "'source'", 'r"source"', 'u"source"', '"""source"""', "'''source'''"])
def test_python_literal_format_preserves_prefix_delimiter_and_value(original):
    value = "UPDATE samples SET label = 'quote'\nWHERE id = 1"
    after = format_source_string(value, 'python', original)
    if original.startswith('r"'):
        assert after is None  # A one-line raw literal cannot contain a newline.
    else:
        assert ast.literal_eval(after) == value
        assert after[:original.index('source')] == original[:original.index('source')]


@pytest.mark.parametrize('language,original', [('go', '`source`'), ('go', '"source"'),
                                             ('typescript', '"source"'), ('typescript', "'source'"),
                                             ('typescript', '`source`')])
def test_go_and_typescript_literal_format_keeps_host_quotes(language, original):
    value = 'UPDATE samples SET score = 2 WHERE id = 1'
    after = format_source_string(value, language, original)
    assert after[0] == after[-1] == original[0]
    wrapped = ('package sample\nvar query = ' + after) if language == 'go' else ('const query = ' + after + ';')
    assert not Source('sample', wrapped, language).root.has_error


def test_budget_truncates_deterministically_and_decimal_boundaries_execute():
    corpus, frontend = fixture(source_test(read='SELECT id FROM samples WHERE score > 10.5'))
    result = generate_embedded_relations(corpus, frontend, budget=EmbeddedRelationBudget(max_candidates=2))
    assert len(result['candidates']) == 2
    assert [c['relation']['assigned_value'] for c in result['candidates']] == ['10.5', '9.5']
    for candidate in result['candidates']:
        with database() as db:
            db.execute(ast.literal_eval(candidate['edits'][0]['after']))


def test_aligned_source_predicate_transfers_into_neutral_recipient_with_two_edits():
    code = source_test(read='SELECT count(*) FROM samples') + '''
def test_predicate_source():
    db = open_database()
    rows = db.execute("SELECT count(*) FROM samples WHERE score > 10").fetchall()
    assert isinstance(rows, list)
'''
    corpus, frontend = fixture(code)
    result = generate_embedded_relations(corpus, frontend)
    assert len(result['candidates']) == 3
    for candidate in result['candidates']:
        assert len(candidate['edits']) == 2
        assert len(candidate['source_test_ids']) == 2
        write, read = candidate['edits']
        assert ast.literal_eval(read['after']) == 'SELECT count(*) FROM samples WHERE score > 10'
        assert candidate['relation']['read_source_basis'] == 'aligned_source_query_transfer'
        assert candidate['oracle']['applicability'] == 'requires_independent_admission'
        with database() as db:
            db.execute(ast.literal_eval(write['after']))
            rows = db.execute(ast.literal_eval(read['after'])).fetchall()
            assert rows == [(2 if candidate['relation']['cell']['assigned_predicate_truth'] else 1,)]
    output = emit(corpus, result['candidates'])
    assert not output['unsupported']
    namespace = {'open_database': database}
    exec(output['files']['test_relations.py'], namespace)
    for row in output['obligations'] + output['controls']:
        namespace[row['test_name']]()
    other, other_frontend = fixture(code.replace('rows = db.execute(', 'rows = unrelated('))
    assert not generate_embedded_relations(other, other_frontend)['candidates']


def test_transferred_predicate_requires_same_table_and_keeps_recipient_host_quote():
    code = source_test(read='SELECT count(*) FROM samples') + '''
def test_predicate_source():
    db = open_database()
    rows = db.execute("SELECT count(*) FROM elsewhere WHERE score > 10").fetchall()
    assert isinstance(rows, list)
'''
    corpus, frontend = fixture(code)
    assert not generate_embedded_relations(corpus, frontend)['candidates']
    corpus, frontend = fixture(code.replace('FROM elsewhere', 'FROM samples'))
    for candidate in generate_embedded_relations(corpus, frontend)['candidates']:
        assert candidate['edits'][1]['before'][0] == candidate['edits'][1]['after'][0] == "'"


def test_alias_quoted_field_multiline_sql_and_comments_retain_exact_where():
    read = 'SELECT id FROM samples AS source WHERE source."score" > 10'
    write = 'UPDATE samples AS destination SET label = 3 /* keep */\nWHERE destination.id = 1; -- trailing'
    corpus, frontend = fixture(source_test(read=read, write=write))
    candidates = generate_embedded_relations(corpus, frontend)['candidates']
    assert len(candidates) == 3
    for candidate in candidates:
        sql = ast.literal_eval(candidate['edits'][0]['after'])
        assert '/* keep */\nWHERE destination.id = 1; -- trailing' in sql
        assert ', "score" = ' in sql
        with database() as db:
            db.execute(sql)


@pytest.mark.parametrize('language,code,quote', [
    ('go', '''package samples
import "testing"
func TestRelation(t *testing.T) {
    db.Execute(`SELECT id FROM samples WHERE score > 10`)
    db.Execute(`UPDATE samples SET label = 3 WHERE id = 1`)
    assert.Equal(t, true, observed())
}
''', '`'),
    ('typescript', """test('relation', () => {
    db.execute('SELECT id FROM samples WHERE score > 10');
    db.execute('UPDATE samples SET label = 3 WHERE id = 1');
    expect(observed()).toBe(true);
});
""", "'"),
])
def test_sql_relations_emit_in_go_and_typescript_host_syntax(language, code, quote):
    corpus, frontend = fixture(code, language)
    candidates = generate_embedded_relations(corpus, frontend)['candidates']
    assert len(candidates) == 3
    assert all(candidate['edits'][0]['after'][0] == quote for candidate in candidates)
    output = emit(corpus, candidates)
    assert not output['unsupported']
    for path, text in output['files'].items():
        assert not Source(path, text, language).root.has_error


def test_identifier_renaming_equivariance_and_no_generated_schema_names():
    corpus, frontend = fixture(source_test())
    renamed, renamed_frontend = fixture(source_test().replace('samples', 'measurements').replace('score', 'temperature'))
    original = generate_embedded_relations(corpus, frontend)['candidates']
    changed = generate_embedded_relations(renamed, renamed_frontend)['candidates']
    assert len(original) == len(changed) == 3
    for left, right in zip(original, changed):
        assert left['edits'][0]['after'].replace('samples', 'measurements').replace('score', 'temperature') == right['edits'][0]['after']


def test_escaped_typescript_template_is_skipped_instead_of_using_raw_frontend_value():
    corpus, frontend = fixture(r"""test('escaped', () => {
    db.execute(`SELECT id FROM samples WHERE score > 10`);
    db.execute(`UPDATE samples SET label = 3\nWHERE id = 1`);
    expect(observed()).toBe(true);
});
""", 'typescript')
    result = generate_embedded_relations(corpus, frontend)
    assert not result['candidates']
    assert result['counts']['skipped']['unsupported_host_literal'] >= 1


def test_shared_before_after_query_is_immutable_evidence_not_expected_input_edit():
    code = source_test().replace('assert isinstance(after, list)', 'assert after == before')
    corpus, frontend = fixture(code)
    candidates = generate_embedded_relations(corpus, frontend)['candidates']
    assert len(candidates) == 3
    assert all(len(c['edits']) == 1 and c['oracle']['immutable_read_input_feeds_expected'] for c in candidates)
    assert all('UPDATE' in c['edits'][0]['before'] for c in candidates)
    neutral = code.replace('SELECT id FROM samples WHERE score > 10', 'SELECT count(*) FROM samples') + '''
def test_predicate_source():
    rows = db.execute("SELECT count(*) FROM samples WHERE score > 10").fetchall()
    assert isinstance(rows, list)
'''
    corpus, frontend = fixture(neutral)
    assert not generate_embedded_relations(corpus, frontend)['candidates']


def test_shared_expected_update_input_is_never_edited():
    corpus, frontend = fixture('''def test_shared():
    read("SELECT id FROM samples WHERE score > 10")
    statement = "UPDATE samples SET label = 3 WHERE id = 1"
    result = apply(statement)
    assert result == statement
''')
    assert not generate_embedded_relations(corpus, frontend)['candidates']
