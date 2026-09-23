"""Language/framework adapter regressions for the separately staged patch."""
import pytest

from generic_composition.corpus import build_corpus, source_text


def corpus_for(tmp_path, code, language):
    name = 'oracle_test.go' if language == 'go' else 'oracle.test.ts'
    (tmp_path / name).write_text(code)
    return build_corpus(tmp_path, language)


def go_test(body):
    return 'package sample\nimport "testing"\nfunc TestOracle(t *testing.T) {\n' + body + '\n}\n'


def test_go_failure_guard_is_negated_and_same_literals_have_distinct_spans(tmp_path):
    corpus = corpus_for(tmp_path, go_test('if run(1) != 1 { t.Fatalf("wrong: %d", 1) }'), 'go')
    assert len(corpus['capsules']) == 1
    capsule = corpus['capsules'][0]
    assert capsule['assertion_adapter'] == 'go_testing_failure_guard'
    assert capsule['predicate'] == '=='
    assert capsule['observed']['text'] == 'run(1)'
    assert capsule['expected']['text'] == '1'
    text = corpus['sources']['oracle_test.go']['code']
    assert capsule['expected']['span']['start_byte'] == text.index('!= 1') + 3
    assert source_text(corpus, capsule['expected']['span']) == '1'


def test_go_initializer_is_kept_in_observation_value_flow(tmp_path):
    corpus = corpus_for(tmp_path, go_test('if got := run("input"); got != "expected" { t.Error("wrong") }'), 'go')
    capsule = corpus['capsules'][0]
    assert capsule['observed']['text'] == 'got'
    assert capsule['expected']['literal_value'] == 'expected'
    donor = next(d for d in corpus['donors'] if d.get('text') == '"input"')
    assert donor['observation_dependency'] and not donor['oracle_dependency']


@pytest.mark.parametrize('body', [
    'if run(1) != 1 { t.Fatal("bad") } else { observe() }',
    'if run(1) != 1 { counter++; t.Fatal("bad") }',
    'if run(1) != 1 { mutate(); t.Fatal("bad") }',
    'if run(1) != 1 { t.Fatal(message()) }',
    'if run(1) != 1 { t.Log("only a message") }',
])
def test_go_else_or_effectful_failure_branch_is_not_invented_as_oracle(tmp_path, body):
    assert corpus_for(tmp_path, go_test(body), 'go')['capsules'] == []


def test_go_report_requires_testing_receiver_type_not_just_method_name(tmp_path):
    code = 'package sample\nfunc TestOracle(t *Other) { if run(1)!=1 { t.Fatal("bad") } }'
    assert corpus_for(tmp_path, code, 'go')['capsules'] == []


def test_go_literal_left_ordered_guard_has_correct_swapped_negation(tmp_path):
    capsule = corpus_for(tmp_path, go_test('if 3 < run() { t.Fail() }'), 'go')['capsules'][0]
    assert capsule['observed']['text'] == 'run()'
    assert capsule['expected']['text'] == '3'
    assert capsule['predicate'] == '<='


def test_go_standard_guard_inside_helper_preserves_parameter_origins(tmp_path):
    code = '''package sample
import "testing"
func verify(t *testing.T, got int, want int) {
 if got != want { t.Fatal("wrong") }
}
func TestOracle(t *testing.T) { verify(t, run(1), 2) }
'''
    helper = corpus_for(tmp_path, code, 'go')['capsules'][0]['helper_assertions'][0]
    assert helper['caller_expected']['text'] == '2'
    assert helper['observed_parameter_origins'][0]['actual']['text'] == 'run(1)'


@pytest.mark.parametrize('declaration, call', [
    ("import assert from 'node:assert';", 'assert.strictEqual(run(1), 1)'),
    ("import * as check from 'assert';", 'check.deepEqual(run(1), 1)'),
    ("import { strictEqual as same } from 'node:assert';", 'same(run(1), 1)'),
    ("import { strict as check } from 'node:assert';", 'check.equal(run(1), 1)'),
    ("import check from 'node:assert/strict';", 'check.deepStrictEqual(run(1), 1)'),
])
def test_node_assert_import_variants_preserve_actual_expected_argument_spans(tmp_path, declaration, call):
    code = declaration + "\ntest('value', () => { " + call + '; });'
    corpus = corpus_for(tmp_path, code, 'typescript')
    capsule = corpus['capsules'][0]
    assert capsule['assertion_adapter'] == 'node_assert_import'
    assert capsule['observed']['text'] == 'run(1)'
    assert capsule['expected']['text'] == '1'
    assert capsule['expected']['span']['start_byte'] == code.index(', 1') + 2
    assert capsule['expected']['span']['start_byte'] > capsule['observed']['span']['end_byte']


@pytest.mark.parametrize('declaration, call', [
    ("import check from 'node:assert';", 'check(ready())'),
    ("import {ok as check} from 'assert';", 'check(ready())'),
    ("import * as check from 'node:assert';", 'check.ok(ready())'),
])
def test_node_assert_truth_checks_do_not_treat_message_as_expected(tmp_path, declaration, call):
    capsule = corpus_for(tmp_path, declaration + "\ntest('ready', () => { " + call + '; });', 'typescript')['capsules'][0]
    assert capsule['predicate'] == 'truthy'
    assert capsule['observed']['text'] == 'ready()'
    assert capsule['expected'] is None


@pytest.mark.parametrize('code', [
    "test('not an assert', () => { obj.equal(run(1), 1); });",
    "import obj from 'other-library'; test('ordinary', () => { obj.equal(run(1),1); });",
    "import obj from 'node:assert'; test('shadowed', () => { const obj = other; obj.equal(run(1),1); });",
    "import obj from 'node:assert'; test('parameter shadows', (obj) => { obj.equal(run(1),1); });",
    "import obj from 'node:assert'; describe('shadowed', () => { const obj = other; test('ordinary', () => { obj.equal(run(1),1); }); });",
])
def test_node_assert_must_have_an_unshadowed_standard_import(tmp_path, code):
    assert corpus_for(tmp_path, code, 'typescript')['capsules'] == []


def test_node_assert_helper_discovery_uses_same_import_proof(tmp_path):
    code = '''import {strictEqual as same} from 'node:assert';
function verify(actual, wanted) { same(actual, wanted); }
test('value', () => { verify(run(1), 2); });
'''
    helper = corpus_for(tmp_path, code, 'typescript')['capsules'][0]['helper_assertions'][0]
    assert helper['caller_expected']['text'] == '2'
    assert helper['observed_parameter_origins'][0]['actual']['text'] == 'run(1)'


def test_nonstandard_assert_named_object_does_not_create_false_helper_oracle(tmp_path):
    code = '''import assert from 'ordinary-library';
function verify(actual, wanted) { assert.equal(actual, wanted); }
test('ordinary call', () => { verify(run(1), 2); });
'''
    assert corpus_for(tmp_path, code, 'typescript')['capsules'] == []


@pytest.mark.parametrize('condition, predicate', [('!ready()', 'truthy'), ('ready()', 'falsy')])
def test_go_boolean_failure_guards_retain_the_correct_polarity(tmp_path, condition, predicate):
    capsule = corpus_for(tmp_path, go_test('if ' + condition + ' { t.FailNow() }'), 'go')['capsules'][0]
    assert capsule['predicate'] == predicate
    assert capsule['observed']['text'] == 'ready()'
    assert capsule['expected'] is None


def test_go_stateful_channel_receive_in_failure_message_is_unsupported(tmp_path):
    assert corpus_for(tmp_path, go_test('if bad() { t.Fatal(<-messages) }'), 'go')['capsules'] == []
