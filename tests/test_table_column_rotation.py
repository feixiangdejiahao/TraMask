import copy
import hashlib
import json
from collections import Counter

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search import table_column_rotation as relation
from relation_search import candidate_edit_transport, compact_contract_guarded, oracle


CODE = '''package sample
import ("testing"; "example.org/subject"; "github.com/stretchr/testify/require")
// Unicode before every byte offset: 中文.
func TestPairs(t *testing.T) {
 rows := []struct{ left, right string }{
  {"α", "one"}, // row one stays here
  {`bb`, "two"},
  {"ccc", "three"},
 }
 for _, row := range rows {
  got := subject.Combine(row.left, row.right)
  want := subject.Expected(row.right)
  require.Equal(t, want, got)
 }
 require.True(t, subject.Finished())
}
'''


def fixture(code=CODE, extra=(), origin='repository'):
    sources = [Source('sample_test.go', code, 'go', origin)]
    sources.extend(Source(path, text, 'go', 'repository') for path, text in extra)
    frontend = extract_frontend(sources)
    return to_emitter_corpus(frontend), frontend


def generate(code=CODE, **kwargs):
    corpus, frontend = fixture(code, **kwargs)
    previous = copy.deepcopy((corpus, frontend))
    result = relation.generate(corpus, frontend)
    assert (corpus, frontend) == previous
    json.dumps(result)
    return result, corpus, frontend


def test_entire_column_rotates_with_all_other_table_and_test_bytes_preserved():
    result, corpus, _ = generate()
    assert result['total_candidates'] == 4
    assert [(c['source_evidence']['shift'], c['source_evidence']['column'])
            for c in result['candidates']] == [(1, 0), (1, 1), (2, 0), (2, 1)]
    candidate = result['candidates'][0]
    assert [e['before'] for e in candidate['edits']] == ['"α"', '`bb`', '"ccc"']
    assert [e['after'] for e in candidate['edits']] == ['`bb`', '"ccc"', '"α"']
    assert len(candidate['edits']) == 3
    assert all(e['role'] == 'input' for e in candidate['edits'])
    expected = CODE[CODE.index('func TestPairs'):].rstrip().replace(
        '{"α", "one"}', '{`bb`, "one"}').replace(
        '{`bb`, "two"}', '{"ccc", "two"}').replace(
        '{"ccc", "three"}', '{"α", "three"}')
    assert oracle.preview(corpus, candidate) == expected
    evidence = candidate['source_evidence']
    assert evidence['original_test']['text'] == CODE[CODE.index('func TestPairs'):].rstrip()
    assert evidence['oracle_preservation_proved'] is False
    assert candidate['source_test_ids'] == [candidate['base_test_id']]
    for mapping in evidence['rotation']:
        for role in ['target', 'donor']:
            receipt = mapping[role]
            assert CODE.encode()[receipt['start_byte']:receipt['end_byte']].decode() == receipt['text']
    assert Counter(m['target']['text'] for m in evidence['rotation']) == Counter(m['donor']['text'] for m in evidence['rotation'])


def test_multiline_raw_cells_keep_exact_text_and_var_table_binding():
    code = CODE.replace('rows :=', 'var rows =').replace('`bb`', '`b\n中`')
    result, corpus, frontend = generate(code)
    candidate = result['candidates'][0]
    assert candidate['edits'][0]['after'] == '`b\n中`'
    assert candidate['edits'][1]['before'] == '`b\n中`'
    assert not Source('sample_test.go', 'package sample\n' + oracle.preview(corpus, candidate), 'go').root.has_error
    prepared = compact_contract_guarded.prepare(corpus, frontend, candidate, 'Compare both row inputs.', max_prompt_bytes=200000)
    assert prepared['request'] is not None
    payload = json.loads(prepared['request']['prompt'])
    assert payload['input_edits'][0] == dict(before='"α"', after='`b\n中`', role='input')
    assert payload['modified_test'] == oracle.preview(corpus, candidate)


def test_closed_boolean_integer_and_float_columns_have_builtin_type_bindings():
    code = '''package sample
import ("testing"; "example.org/subject"; "github.com/stretchr/testify/require")
func TestScalars(t *testing.T) {
 rows := []struct{ flag bool; number int; fraction float64 }{{true,1,0.5},{false,-2,+3.5}}
 for _, row := range rows { got := subject.Consume(row.flag,row.number,row.fraction); require.Equal(t,42,got) }
}
'''
    result, _, _ = generate(code)
    assert [c['source_evidence']['field_type'] for c in result['candidates']] == ['bool', 'int', 'float64']
    assert not generate(code.replace('func TestScalars', 'var true = false\nfunc TestScalars'))[0]['candidates']


def test_duplicate_test_registration_in_source_abstains():
    result, _, _ = generate(extra=[('duplicate_test.go', CODE)])
    assert not result['candidates']
    assert {s['reason'] for s in result['skipped']} == {'test_registration_not_unique'}


def test_shared_input_and_dynamic_oracle_column_is_retained_but_expected_only_is_not():
    result, _, _ = generate()
    assert {c['source_evidence']['field'] for c in result['candidates']} == {'left', 'right'}
    modified = CODE.replace('subject.Combine(row.left, row.right)', 'subject.Combine(row.left)')
    result, _, _ = generate(modified)
    assert {c['source_evidence']['field'] for c in result['candidates']} == {'left'}
    assert any(s.get('field') == 'right' and s['reason'] == 'no_non_oracle_input_consumer' for s in result['skipped'])


def test_direct_expected_and_diagnostic_columns_cannot_establish_input_roles():
    modified = CODE.replace('subject.Combine(row.left, row.right)', 'subject.Combine(row.left)').replace(
        'want := subject.Expected(row.right)', 'want := row.right\n  t.Logf("label %s", row.right)')
    result, _, _ = generate(modified)
    assert {c['source_evidence']['field'] for c in result['candidates']} == {'left'}


def test_bare_imported_output_calls_do_not_make_a_diagnostic_column_an_input():
    code = CODE.replace('"testing";', '"testing"; "fmt";').replace(
        'subject.Combine(row.left, row.right)', 'subject.Combine(row.left)').replace(
        'want := subject.Expected(row.right)',
        'fmt.Printf("diagnostic %s", row.right)\n  want := subject.Expected(row.right)')
    result, _, _ = generate(code)
    assert {c['source_evidence']['field'] for c in result['candidates']} == {'left'}


@pytest.mark.parametrize(('before', 'after'), [
    ('for _, row := range rows {', 'alias := rows\n _ = alias\n for _, row := range rows {'),
    ('for _, row := range rows {', 'rows = rows\n for _, row := range rows {'),
    ('for _, row := range rows {', '{ rows := 1; _ = rows }\n for _, row := range rows {'),
    ('for _, row := range rows {', 'for _, other := range rows { _ = other }\n for _, row := range rows {'),
    ('got := subject.Combine', 'row = row\n  got := subject.Combine'),
    ('got := subject.Combine', 'alias := row\n  _ = alias\n  got := subject.Combine'),
    ('got := subject.Combine', 'row.left = "x"\n  got := subject.Combine'),
    ('got := subject.Combine', '{ row := 1; _ = row }\n  got := subject.Combine'),
    ('got := subject.Combine', 'address := &row.left\n  _ = address\n  got := subject.Combine'),
    ('got := subject.Combine', 'callback := func(){subject.Combine(row.left)}\n  _ = callback\n  got := subject.Combine'),
    ('got := subject.Combine', 'go subject.Combine(row.left)\n  got := subject.Combine'),
    ('got := subject.Combine', 'defer subject.Combine(row.left)\n  got := subject.Combine'),
    ('for _, row := range rows {', 'for _, row = range rows {'),
    ('for _, row := range rows {', 'for index, row := range rows {\n _ = index'),
])
def test_table_row_alias_shadow_rebinding_mutation_escape_and_capture_abstain(before, after):
    result, _, _ = generate(CODE.replace(before, after))
    assert not result['candidates']


@pytest.mark.parametrize(('before', 'after'), [
    ('rows :=', 'rows, extra :='),
    ('[]struct{ left, right string }', '[3]struct{ left, right string }'),
    ('[]struct{ left, right string }', '[]struct{ left, right custom }'),
    ('{"α", "one"}', '{left:"α", right:"one"}'),
    ('{"α", "one"}', '{"α"}'),
    ('{"α", "one"}', '{subject.Build(), "one"}'),
    ('{"α", "one"}', '{external, "one"}'),
    ('{"α", "one"}', '{nil, "one"}'),
    ('rows := []struct', 'if subject.Ready() { rows := []struct'),
])
def test_unsupported_table_shapes_or_nonclosed_cells_do_not_generate(before, after):
    result, _, _ = generate(CODE.replace(before, after))
    assert not result['candidates']


@pytest.mark.parametrize('declaration', ['type string = int\n', 'var string = replacement\n'])
def test_shadowed_builtin_scalar_types_abstain(declaration):
    code = CODE.replace('func TestPairs', declaration + 'func TestPairs')
    assert not generate(code)[0]['candidates']


def test_builtin_shadow_in_another_package_does_not_poison_current_package():
    extra = [('other/types.go', 'package other\ntype string = int\n')]
    assert generate(extra=extra)[0]['total_candidates'] == 4


def test_local_import_shadow_and_unresolved_function_inputs_abstain():
    for code in [CODE.replace('rows :=', 'subject := replacement\n rows :='),
                 CODE.replace('subject.Combine', 'unknown').replace('subject.Expected', 'unknown')]:
        assert not generate(code)[0]['candidates']


def test_scalar_field_alias_does_not_guess_binding_through_another_variable():
    code = CODE.replace('got := subject.Combine(row.left, row.right)',
                        'value := row.left\n  got := subject.Combine(value, row.right)')
    result, _, _ = generate(code)
    assert {c['source_evidence']['field'] for c in result['candidates']} == {'right'}
    assert any(s.get('field') == 'left' and s['reason'] == 'field_use_not_direct_stable_call_argument' for s in result['skipped'])


def test_unique_cross_file_source_returning_helper_is_bound_without_api_names():
    code = CODE.replace('subject.Combine(row.left, row.right)', 'assemble(t, row.left, row.right)')
    helper = '''package sample
import "testing"
func assemble(t *testing.T, a, b string) string { t.Helper(); return a+b }
'''
    result, _, _ = generate(code, extra=[('helper_test.go', helper)])
    assert result['total_candidates'] == 4
    proof = result['candidates'][0]['source_evidence']['input_consumers'][0]
    assert proof['parameter'] == 'a'
    assert proof['declaration']['path'] == 'helper_test.go'
    assert proof['kind'] == 'unique_source_returning_function_argument'
    assert not generate(code.replace('rows :=', 'assemble := replacement\n rows :='),
                        extra=[('helper_test.go', helper)])[0]['candidates']
    assert not generate(code, extra=[('helper_test.go', helper), ('duplicate_test.go', helper)])[0]['candidates']


def test_void_assertion_helper_is_not_an_input_consumer():
    code = CODE.replace('got := subject.Combine(row.left, row.right)',
                        'verify(t, row.left, row.right)\n  got := "unchanged"')
    helper = '''package sample
import "testing"
func verify(t *testing.T, a, b string) { if a!=b {t.Fatal("mismatch")} }
'''
    assert not generate(code, extra=[('helper_test.go', helper)])[0]['candidates']


def test_assertion_helper_returning_status_does_not_establish_subject_input():
    code = CODE.replace('subject.Combine(row.left, row.right)', 'verify(t,row.left,row.right)')
    helper = '''package sample
import ("testing"; "github.com/stretchr/testify/require")
func verify(t *testing.T, a,b string) bool {require.Equal(t,a,b); return true}
'''
    assert not generate(code, extra=[('helper_test.go', helper)])[0]['candidates']


def test_source_setup_helper_can_check_errors_after_consuming_its_argument():
    code = CODE.replace('subject.Combine(row.left, row.right)',
                        'subject.Combine(decode(t,row.left),decode(t,row.right))')
    helper = '''package sample
import ("testing"; "example.org/codec")
func decode(t *testing.T, value string) string {
 result, err := codec.Decode(value)
 if err != nil { t.Fatal(err) }
 return result
}
'''
    result, _, _ = generate(code, extra=[('helper_test.go', helper)])
    assert result['total_candidates'] == 4


def test_failure_guard_only_operands_do_not_guess_actual_expected_direction():
    code = CODE.replace('got := subject.Combine(row.left, row.right)\n  want := subject.Expected(row.right)\n  require.Equal(t, want, got)',
                        'want := subject.Expected(row.right)\n  if subject.Combine(row.left) != want { t.Fatal("mismatch") }')
    assert not generate(code)[0]['candidates']


def test_repeated_periodic_values_deduplicate_shifts_and_skip_identity_rotations():
    code = CODE.replace('  {"α", "one"}, // row one stays here\n  {`bb`, "two"},\n  {"ccc", "three"},',
                        '  {"a", "one"}, {"b", "one"}, {"a", "one"}, {"b", "one"},')
    result, _, _ = generate(code)
    assert result['total_candidates'] == 1
    assert len(result['candidates'][0]['edits']) == 4
    assert result['candidates'][0]['source_evidence']['shift'] == 1


def test_no_task_names_api_names_field_names_or_issue_terms_select_rotations():
    code = CODE.replace('left', 'oldExpectation').replace('right', 'label').replace(
        'subject', 'different').replace('Combine', 'Transform').replace('Expected', 'Oracle').replace('TestPairs', 'TestInputs')
    result, corpus, frontend = generate(code)
    assert result['total_candidates'] == 4
    assert relation.generate(corpus, frontend, 'unrelated issue') == result
    corpus['evaluation_label'] = 'private label'
    assert relation.generate(corpus, frontend, 'another issue') == result


def test_retrieval_order_then_shift_then_column_and_limit_sixteen():
    second = CODE[CODE.index('func TestPairs'):].replace('TestPairs', 'TestEarlier')
    corpus, frontend = fixture(CODE + second)
    for t in corpus['tests'].values():
        t['retrieval_rank'] = 1 if t['name'] == 'TestEarlier' else 5
    result = relation.generate(corpus, frontend, limit=3)
    assert result['total_candidates'] == 8 and len(result['candidates']) == 3
    assert all('TestEarlier' in c['base_test_id'] for c in result['candidates'])
    assert [(c['source_evidence']['shift'], c['source_evidence']['column']) for c in result['candidates']] == [(1,0),(1,1),(2,0)]
    rows = '\n'.join('  {"a%d", "b%d"},' % (i,i) for i in range(12))
    code = CODE[:CODE.index('  {"α"')] + rows + CODE[CODE.index('\n }'):]
    corpus, frontend = fixture(code)
    result = relation.generate(corpus, frontend, limit=100)
    assert result['total_candidates'] == 22 and len(result['candidates']) == 16


def test_origin_complete_span_and_frontend_byte_receipts():
    assert not generate(origin='trajectory')[0]['candidates']
    corpus, frontend = fixture()
    next(iter(corpus['tests'].values()))['span']['end_byte'] -= 1
    assert relation.generate(corpus, frontend)['skipped'][0]['reason'] == 'incomplete_original_test_span'
    corpus, frontend = fixture()
    corpus = copy.deepcopy(corpus)
    corpus['sources']['sample_test.go']['code'] += '\n'
    with pytest.raises(ValueError, match='frontend_source_mismatch'):
        relation.generate(corpus, frontend)
    assert relation.generate({'language':'python'}, {})['status'] == 'language_unsupported'


def test_multiple_utf8_input_edits_reach_compact_full_test_review_and_real_transport(tmp_path):
    result, corpus, frontend = generate()
    candidate = result['candidates'][0]
    review = compact_contract_guarded.prepare(corpus, frontend, candidate,
        'Combine and Expected define an input relation. Judge all original assertions for the changed pairings.',
        max_prompt_bytes=200000)
    assert review['request'] is not None
    payload = json.loads(review['request']['prompt'])
    assert payload['modified_test'] == oracle.preview(corpus, candidate)
    assert payload['original_test'] == candidate['source_evidence']['original_test']['text']
    assert len(payload['input_edits']) == 3
    assert {e['role'] for e in payload['input_edits']} == {'input'}
    assert 'require.Equal(t, want, got)' in payload['modified_test']
    assert 'require.True(t, subject.Finished())' in payload['modified_test']
    transported = candidate_edit_transport.rewrite_view(candidate)
    material = emit(corpus, [transported])
    assert not material['unsupported']
    artifact = tmp_path / 'emitted'; artifact.mkdir()
    source = artifact / 'sample_test.go'
    source.write_text(material['files']['sample_test.go'])
    manifest = dict(obligations=material['obligations'], mounts=[dict(
        source=str(source), target='staged/sample_test.go', sha256=hashlib.sha256(source.read_bytes()).hexdigest())])
    plan = dict(phases=[dict(role='generated', files=[dict(target='sample_test.go', staged='staged/sample_test.go')])])
    for path, value in [(artifact/'manifest.json', manifest), (artifact/'phase_plan.json', plan),
                        (tmp_path/'accepted.json', [transported])]:
        path.write_text(json.dumps(value))
    assert candidate_edit_transport.verify_emission(corpus, candidate, artifact)['status'] == 'matched'
    source.write_text(source.read_text().replace('require.True(t, subject.Finished())', 'require.True(t, true)'))
    manifest['mounts'][0]['sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
    (artifact/'manifest.json').write_text(json.dumps(manifest))
    assert candidate_edit_transport.verify_emission(corpus, candidate, artifact)['reason'] == 'complete_test_ast_changed'
