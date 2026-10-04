import copy

import pytest

from anchor_retrieval.syntax import Source, child, walk
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search import quantity_bound as relation


PRODUCTION = '''package sample
// Options controls the result decoration.
type Options struct { Suffix string; Enabled bool }
// Fit returns text whose visible extent, including decoration, is at most limit.
func Fit(limit int, options Options, text string) string { return text }
// Extent reports the visible extent of text.
func Extent(text string) int { return 0 }
'''
TEST = '''package sample
import "testing"
func TestExisting(t *testing.T) {
 _ = "abcdef"
 _ = "xy"
 _ = ""
 t.Log("original expectation stays here")
}
'''
ISSUE = 'The complete output extent must not exceed the positive limit, including any decoration.'


def fixture(production=PRODUCTION, test=TEST, *, extra=(), modules=None, origin='repository'):
    sources = [Source('api.go', production, 'go', 'repository'), Source('api_test.go', test, 'go', origin), *extra]
    frontend = extract_frontend(sources, go_modules=modules)
    return to_emitter_corpus(frontend), frontend


def make_ir(corpus, frontend, issue=ISSUE):
    catalog = relation.catalog(corpus, issue, frontend)
    pair = catalog['pairs'][0]
    record = dict(id='public_extent', law=relation.LAW, unit='visible cells',
                  transform=dict(declaration=catalog['functions'][pair['transform']]['declaration'],
                                 **{key: pair[key] for key in ['string_parameter', 'bound_parameter', 'options_parameter']}),
                  measure=dict(declaration=catalog['functions'][pair['measure']]['declaration']),
                  evidence=[catalog['evidence'][0]], semantic_status='hypothesis_pending_independent_audit')
    return dict(version=relation.IR_VERSION, relations=[record])


def generated(corpus, frontend, **kwargs):
    return relation.generate(corpus, frontend, ISSUE, make_ir(corpus, frontend), **kwargs)


def test_catalog_uses_signatures_and_receipts_without_an_existing_target_call():
    corpus, frontend = fixture()
    catalog = relation.catalog(corpus, ISSUE, frontend)
    assert catalog['status'] == 'source_pairs'
    assert len(catalog['pairs']) == 1
    pair = catalog['pairs'][0]
    assert (pair['string_parameter'], pair['bound_parameter'], pair['options_parameter']) == (2, 0, 1)
    transform = catalog['functions'][pair['transform']]
    assert transform['public_header']['text'] == 'func Fit(limit int, options Options, text string) string '
    assert 'return text' not in transform['public_docs'][0]['text']
    assert [field['name'] for field in transform['options_fields']] == ['Suffix', 'Enabled']
    assert all('return text' not in field['declaration']['text'] for field in transform['options_fields'])
    assert 'Fit(' not in TEST


def test_one_candidate_per_option_preserves_original_test_and_evaluates_each_call_once():
    corpus, frontend = fixture()
    before = copy.deepcopy((corpus, frontend))
    result = generated(corpus, frontend)
    assert result['relations_accepted'] == 1
    # Four source strings, a zero configuration, and both boolean values.
    assert result['total_candidates'] == 7
    candidate = result['candidates'][1]
    edit = candidate['edits'][0]
    assert edit['before'] == '' and edit['span']['start_byte'] == edit['span']['end_byte']
    assert candidate['source_test_ids'] == [candidate['base_test_id']]
    evidence = candidate['source_evidence']
    assert evidence['option_configuration']['fields'] == {'Suffix': '"abcdef"'}
    assert evidence['transform_call_upper_bound'] == evidence['measure_call_upper_bound'] == 16
    assert edit['after'].count('Fit(') == edit['after'].count('Extent(') == 1
    assert 'range []int{1, 2, 4, 8}' in edit['after']
    materialized = emit(corpus, [candidate])
    assert not materialized['unsupported']
    text = materialized['files']['api_test.go']
    source = Source('api_test.go', text, 'go')
    assert not source.root.has_error
    original_body = TEST[TEST.index('{')+1:TEST.rindex('}')]
    assert text.count(original_body) >= 2
    assert (corpus, frontend) == before


def test_local_and_same_module_imported_aliases_resolve_to_public_struct_fields():
    production = '''package sample
import x "example.org/mod/inner"
type Options = x.Settings
type Local = Options
// Fit limits the extent including decoration.
func Fit(s string, n int, options Local) string {return s}
// Extent measures the output.
func Extent(s string) int {return 0}
'''
    inner = Source('inner/settings.go', 'package inner\ntype Settings struct { Suffix string; Enabled bool }\n', 'go')
    corpus, frontend = fixture(production, extra=[inner], modules={'': 'example.org/mod'})
    catalog = relation.catalog(corpus, ISSUE, frontend)
    assert len(catalog['pairs']) == 1
    transform = catalog['functions'][catalog['pairs'][0]['transform']]
    assert len(transform['type_declarations']) == 3
    assert transform['options_fields'][0]['declaration']['path'] == 'inner/settings.go'
    assert generated(corpus, frontend)['total_candidates'] == 7
    assert relation.catalog(corpus, ISSUE)['pairs'] == []
    wrong = copy.deepcopy(frontend)
    wrong['module_resolution']['go_modules'] = {'': 'example.org/unrelated'}
    assert relation.catalog(corpus, ISSUE, wrong)['pairs'] == []


@pytest.mark.parametrize('fields', ['hidden string', 'N int', 'Other', 'Data []string', 'Data map[string]string'])
def test_unsupported_or_private_struct_fields_abstain(fields):
    corpus, frontend = fixture(PRODUCTION.replace('Suffix string; Enabled bool', fields))
    assert not relation.catalog(corpus, ISSUE, frontend)['pairs']


@pytest.mark.parametrize('production', [
    PRODUCTION.replace('type Options struct { Suffix string; Enabled bool }', 'type Options = Next\ntype Next = Options'),
    PRODUCTION + '\nfunc Fit(n int, o Options, s string) string {return s}',
    PRODUCTION.replace('limit int', 'limit Count') + '\ntype Count int',
    PRODUCTION.replace('text string) string', 'text ...string) string'),
    PRODUCTION.replace('func Fit(', 'func fit('),
])
def test_recursive_types_ambiguous_functions_defined_scalars_and_variadics_abstain(production):
    corpus, frontend = fixture(production)
    assert not relation.catalog(corpus, ISSUE, frontend)['pairs']


def test_builtin_scalar_aliases_are_assignable():
    production = PRODUCTION.replace('limit int', 'limit Count').replace('text string', 'text Text')
    production += '\ntype Count = int\ntype Text = string\n'
    corpus, frontend = fixture(production)
    assert len(relation.catalog(corpus, ISSUE, frontend)['pairs']) == 1
    assert generated(corpus, frontend)['candidates']


def test_no_options_and_parameter_order_are_supported():
    production = '''package sample
func Fit(n int, s string) string {return s}
func Extent(s string) int {return 0}
'''
    corpus, frontend = fixture(production)
    result = generated(corpus, frontend)
    assert result['total_candidates'] == 1
    assert result['candidates'][0]['source_evidence']['option_configuration']['expression'] is None


@pytest.mark.parametrize('statement', [
    'return', 't.Skip("reason")', 't.Fatalf("stop")', 't.Parallel()',
    'go work()', 'defer work()', 't.Cleanup(work)', 'for {}',
    'if true { work() }', 'f := func() {}; _ = f', 'panic("stop")',
    'var Fit string; _ = Fit', 'const Extent = 1; _ = Extent',
    'type Options struct{}', 'var string int; _ = string',
    't = replacement', 't := replacement; _ = t',
])
def test_nonstraightline_or_shadowed_host_scopes_abstain(statement):
    corpus, frontend = fixture(test=TEST.replace('t.Log("original expectation stays here")', statement))
    result = generated(corpus, frontend)
    assert result['total_candidates'] == 0
    assert result['skipped']


@pytest.mark.parametrize('test', [
    TEST.replace('*testing.T', '*Other'),
    TEST.replace('package sample', 'package sample_test'),
    TEST.replace('import "testing"', 'import . "testing"').replace('*testing.T', '*T'),
])
def test_unknown_test_parameter_and_external_package_abstain(test):
    corpus, frontend = fixture(test=test)
    assert generated(corpus, frontend)['total_candidates'] == 0


def test_test_import_alias_and_parameter_name_are_bound():
    test = TEST.replace('import "testing"', 'import unit "testing"').replace('*testing.T', '*unit.T')
    test = test.replace('(t *unit.T)', '(check *unit.T)').replace('t.Log', 'check.Log')
    corpus, frontend = fixture(test=test)
    assert 'check.Fatalf' in generated(corpus, frontend)['candidates'][0]['edits'][0]['after']


def test_other_test_file_package_declaration_cannot_shadow_generated_bindings():
    other = Source('other_test.go', 'package sample\ntype string = []byte\n', 'go')
    corpus, frontend = fixture(extra=[other])
    result = generated(corpus, frontend)
    assert result['total_candidates'] == 0
    assert any(row['reason'] == 'generated_expression_test_package_binding_shadowed' for row in result['skipped'])


def test_trajectory_literals_are_never_generated_inputs():
    trajectory = Source('history_test.go', 'package sample\nimport "testing"\nfunc TestHistory(t *testing.T){_="secret-old-witness"}', 'go', 'trajectory')
    corpus, frontend = fixture(extra=[trajectory])
    result = generated(corpus, frontend)
    assert all('secret-old-witness' not in row['expression'] for row in result['source_literals'])
    assert all('secret-old-witness' not in candidate['edits'][0]['after'] for candidate in result['candidates'])


def test_literal_budget_and_option_budget_are_fixed_and_ordered():
    test = TEST.replace('_ = "abcdef"', '\n'.join('_ = "value-%d"' % i for i in range(30)))
    corpus, frontend = fixture(test=test)
    result = generated(corpus, frontend, limit=2)
    assert len(result['source_literals']) == 8
    assert [r['expression'] for r in result['source_literals']] == ['"value-%d"' % i for i in range(8)]
    assert result['total_candidates'] == 11
    assert len(result['candidates']) == 2
    assert result['candidates'][0]['source_evidence']['option_configuration']['expression'] == 'Options{}'
    assert result['candidates'][0]['source_evidence']['transform_call_upper_bound'] == 32
    assert generated(corpus, frontend, limit=2) == result


@pytest.mark.parametrize('mutation', ['law', 'unit', 'signature', 'roles', 'evidence', 'implementation_evidence'])
def test_invalid_relation_receipts_and_roles_are_rejected(mutation):
    corpus, frontend = fixture()
    ir = make_ir(corpus, frontend)
    record = ir['relations'][0]
    if mutation == 'law': record['law'] = 'looks_like_truncate'
    elif mutation == 'unit': record['unit'] = ''
    elif mutation == 'signature': record['transform']['declaration']['source_sha256'] = 'x'
    elif mutation == 'roles': record['transform']['bound_parameter'] = 2
    elif mutation == 'evidence': record['evidence'][0]['text'] = 'invented'
    else:
        code = corpus['sources']['api.go']['code']
        start = code.index('return text')
        record['evidence'] = [relation.receipt('api.go', code, start, start+len('return text'))]
    result = relation.generate(corpus, frontend, ISSUE, ir)
    assert result['relations_accepted'] == 0 and result['rejected']


def test_frontend_source_bytes_must_match():
    corpus, frontend = fixture()
    ir = make_ir(corpus, frontend)
    frontend = copy.deepcopy(frontend)
    frontend['sources']['api.go']['code'] += '\n'
    with pytest.raises(ValueError, match='frontend_source_mismatch'):
        relation.generate(corpus, frontend, ISSUE, ir)


def test_raw_printable_ascii_is_copied_without_interpreting_backslashes():
    test = TEST.replace('_ = "abcdef"', '_ = `plain ASCII \\x1b[0m`')
    corpus, frontend = fixture(test=test)
    result = generated(corpus, frontend)
    text = emit(corpus, [result['candidates'][1]])['files']['api_test.go']
    assert '`plain ASCII \\x1b[0m`' in text
    assert result['source_literals'][0]['expression'] == '`plain ASCII \\x1b[0m`'
    assert not Source('api_test.go', text, 'go').root.has_error


@pytest.mark.parametrize('expression', [
    '`line one\nline two`', '"\\u754c\\x1b[0m"', '"\\033]11;rgb:fa/fa/fa"',
    '"non-ASCII 界"', '`界`', '"quoted \\" text"', '"path\\\\name"', '`tab\ttext`',
])
def test_controls_unicode_and_interpreted_escapes_are_outside_the_input_domain(expression):
    test = TEST.replace('_ = "abcdef"', '_ = '+expression)
    corpus, frontend = fixture(test=test)
    result = generated(corpus, frontend)
    assert expression not in [row['expression'] for row in result['source_literals']]
    assert [row['expression'] for row in result['source_literals']] == ['"xy"', '""', '"original expectation stays here"']


def test_domain_filter_runs_before_the_eight_literal_budget():
    excluded = ['_ = "\\x1b[%dm"' % i for i in range(12)]
    included = ['_ = "plain-%d"' % i for i in range(12)]
    test = TEST.replace('_ = "abcdef"', '\n'.join(excluded + included))
    corpus, frontend = fixture(test=test)
    result = generated(corpus, frontend)
    assert [row['expression'] for row in result['source_literals']] == ['"plain-%d"' % i for i in range(8)]
    assert result['total_candidates'] == 11


def test_generated_upper_bound_comparison_uses_observed_output_only():
    corpus, frontend = fixture()
    candidate = generated(corpus, frontend)['candidates'][0]
    after = candidate['edits'][0]['after']
    source = Source('standalone.go', 'package p\nfunc test(){' + after + '}', 'go')
    calls = [source.text(child(node, 'function')) for node in walk(source.root) if node.type == 'call_expression']
    assert calls.count('Fit') == calls.count('Extent') == 1
    assert len(calls) == 3
    assert ' > ' in after and ' == ' not in after


def test_recognized_workflow_suffix_is_not_contract_evidence():
    corpus, frontend = fixture()
    issue = '  '+ISSUE+'\n## Recommended Workflow\nRun invented-tool\n## Command Execution Rules\ncommit now'
    catalog = relation.catalog(corpus, issue, frontend)
    evidence = catalog['evidence'][0]
    assert evidence['text'] == ISSUE
    assert evidence['start_byte'] == 2
    assert evidence == relation.receipt('issue.md', issue, 2, 2+len(ISSUE))
    ir = make_ir(corpus, frontend, issue)
    start = issue.index('Run invented-tool')
    ir['relations'][0]['evidence'] = [relation.receipt('issue.md', issue, start, start+len('Run invented-tool'))]
    assert relation.generate(corpus, frontend, issue, ir)['rejected']
    ordinary = ISSUE+'\n## Recommended Workflow\nThis is part of an ordinary issue.'
    assert relation.catalog(corpus, ordinary, frontend)['evidence'][0]['text'] == ordinary
    suffix = '\n\nIMPORTANT: Please work on this in a new branch from main and commit everything when you are done.'
    assert relation.catalog(corpus, ISSUE+suffix+'\n', frontend)['evidence'][0]['text'] == ISSUE
    nonterminal = ISSUE+suffix+'\nThis next sentence is still issue text.'
    assert relation.catalog(corpus, nonterminal, frontend)['evidence'][0]['text'] == nonterminal
