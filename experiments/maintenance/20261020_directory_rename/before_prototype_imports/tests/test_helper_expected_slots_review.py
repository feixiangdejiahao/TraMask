"""Independent source fixtures for editable helper argument boundaries.

No fixture executes Go or model code. Expected slots must not be inferred from
same-spelling local diagnostic methods or functions that can mutate state.
"""
import copy
import json

import pytest

from anchor_retrieval.syntax import Source, child
from experimental.go_assertion_helper import summarize_helper
from experimental.helper_expected_slots import apply_response, prepare_request
from relation_search.oracle import preview
from relational_gap.frontend import extract_frontend, to_emitter_corpus


PRELUDE = '''package sample
import ("testing"; "strings")
var _ = strings.Trim
var changed string
type Box struct { value string }
type Evil struct {}
func (Evil) ReplaceAll(a,b,c string) string { changed=a; return a }
func evilLen(s string) int { changed=s; return 1 }
func (Evil) Errorf(msg string, args ...interface{}) { changed=msg }
'''


def summary(body):
    source = Source('sample/check_test.go', PRELUDE +
        'func check(t *testing.T, box *Box, want string) {' + body + '}', 'go')
    assert not source.root.has_error
    declaration = next(node for node in source.root.named_children
        if node.type == 'function_declaration'
        and source.text(child(node, 'name')) == 'check')
    return summarize_helper(source, declaration)


def test_local_var_package_alias_cannot_prove_a_pure_diagnostic_call():
    # Other.ReplaceAll mutates package state; the stdlib spelling is irrelevant.
    result = summary('if box.value != want { '
        'var strings=Evil{}; t.Error(strings.ReplaceAll(want,"a","b")) }')
    assert result['status'] == 'unknown', result


def test_local_var_builtin_alias_cannot_prove_a_pure_diagnostic_call():
    # Keeping check/t/box fixed does not stop a new want from changing this action.
    result = summary('if box.value != want { var len=evilLen; t.Error(len(want)) }')
    assert result['status'] == 'unknown', result


def test_local_type_alias_cannot_prove_the_testing_failure_receiver():
    # This is the ordinary method expression Evil.Errorf, not *testing.T.Errorf.
    result = summary('if box.value != want { type t=Evil; t.Errorf(Evil{},want) }')
    assert result['status'] == 'unknown', result


def test_real_expected_also_used_to_compute_subject_output_stays_unknown():
    result = summary('got:=produce(box.value,want); if got!=want {t.Error(got)}')
    assert result['status'] == 'unknown', result


def test_failure_control_cannot_hide_an_expected_independent_subject_action():
    # Changing want changes whether mutate(box) runs even without a value-flow
    # edge from want to mutate's arguments. A comparison body is still code.
    result = summary('if box.value!=want {mutate(box);t.Error(want)}')
    assert result['status'] == 'unknown', result


def test_failure_local_assignment_cannot_change_later_subject_action_arguments():
    # Merely checking calls inside the branch misses a local write whose result
    # is consumed later. Diagnostic formatting must not overwrite this actual.
    result = summary('got:=box.value; if got!=want {got="bad";t.Error(want)}; '
        'consume(got)')
    assert result['status'] == 'unknown', result


def test_real_slot_keeps_earlier_terminating_guard_in_source_evidence():
    result = summary('err:=validate(box.value); if err!=nil {t.Fatal(err)}; '
        'if box.value!=want {t.Error(want)}')
    assert result['status'] == 'supported', result
    assert result['expected_parameter_index'] == 2
    assert len(result['prerequisite_guards']) == 1
    assert result['prerequisite_guards'][0]['condition'] == 'err!=nil'
    assert result['prerequisite_guards'][0]['failure_methods'] == ['Fatal']


CALLER_CODE = '''package review
import "testing"
type Box struct{value string}
func validate(v string) error {return nil}
func makeBox(v string) *Box {return &Box{value:v}}
func touch(b *Box) string {b.value="changed";return "old"}
func check(t *testing.T,box *Box,want string) {
    err:=validate(box.value)
    if err!=nil {t.Fatal(err)}
    if box.value!=want {t.Errorf("actual=%q want=%q",box.value,want)}
}
func TestReview(t *testing.T) {
    b:=&Box{value:"旧输入"}
    check(t,b,"old")
    check(t,b,"old")
}
'''


def caller_fixture(code=CALLER_CODE):
    frontend = extract_frontend([Source('review/caller_test.go', code, 'go')])
    corpus = to_emitter_corpus(frontend)
    candidate = dict(id='fixed-source', base_test_id=next(iter(corpus['tests'])), edits=[])
    return corpus, frontend, candidate


def input_edit(corpus, candidate, before, after):
    extent = corpus['tests'][candidate['base_test_id']]['span']
    data = corpus['sources'][extent['path']]['code'].encode()
    start = data.index(before.encode(), extent['start_byte'])
    candidate['edits'].append(dict(span=dict(path=extent['path'], start_byte=start,
        end_byte=start+len(before.encode())), before=before, after=after, role='input'))


def answers(request, replacements=None):
    replacements = replacements or {}
    return dict(decisions=[dict(id=row['id'], status='adapt', expected=replacements[row['id']])
        if row['id'] in replacements else dict(id=row['id'], status='preserve')
        for row in request['inventory'] if row['editable']])


def test_actual_callpoint_edit_distinguishes_identical_text_after_utf8_input_shift():
    corpus, frontend, candidate = caller_fixture()
    input_edit(corpus, candidate, '"旧输入"', '"新的更长组合输入"')
    original = copy.deepcopy((corpus, candidate))
    request = prepare_request(corpus, frontend, candidate, 'Required behavior')['request']
    result = apply_response(request, answers(request, {'H1':'"second only"'}), corpus, frontend)
    assert result['status'] == 'adapt', result
    before = preview(corpus, candidate)
    at = before.rindex('check(t,b,"old")')
    expected = before[:at] + before[at:].replace('check(t,b,"old")', 'check(t,b,"second only")', 1)
    assert preview(corpus, result['candidate']) == result['modified_test'] == expected
    assert result['modified_test'].count('check(t,b,"old")') == 1
    assert result['oracle_validity'] == 'unconfirmed'
    declaration, = json.loads(request['prompt'])['helper_declarations']
    assert 'if err!=nil {t.Fatal(err)}' in declaration['code']
    assert (corpus, candidate) == original


def test_slot_inside_input_call_replacement_keeps_the_actual_setup_call():
    corpus, frontend, candidate = caller_fixture()
    input_edit(corpus, candidate, 'check(t,b,"old")', 'check(t,makeBox("new input"),"old")')
    request = prepare_request(corpus, frontend, candidate, 'Required behavior')['request']
    result = apply_response(request, answers(request, {'H0':'"required"'}), corpus, frontend)
    assert result['status'] == 'adapt', result
    assert preview(corpus, result['candidate']) == preview(corpus, candidate).replace(
        'check(t,makeBox("new input"),"old")', 'check(t,makeBox("new input"),"required")')
    assert result['candidate']['edits'][0]['after'] == 'check(t,makeBox("new input"),"required")'


def test_original_expected_action_is_readonly_and_survives_other_slot_adaptation():
    corpus, frontend, candidate = caller_fixture(CALLER_CODE.replace('check(t,b,"old")',
        'check(t,b,touch(b))', 1))
    request = prepare_request(corpus, frontend, candidate, 'Required behavior')['request']
    first = next(row for row in request['inventory'] if row['id'] == 'H0')
    assert not first['editable'] and first['reason'] == 'expected_not_scalar_literal'
    result = apply_response(request, answers(request, {'H1':'"required"'}), corpus, frontend)
    assert result['status'] == 'adapt', result
    assert 'check(t,b,touch(b))' in result['modified_test']
    invalid = answers(request)
    invalid['decisions'].append(dict(id='H0', status='adapt', expected='"removed action"'))
    assert apply_response(request, invalid, corpus, frontend)['status'] == 'unknown'


@pytest.mark.parametrize('replacement', ['touch(b)', 'box.value', 'string("new")'])
def test_new_expected_cannot_add_an_action_or_replace_a_checked_actual(replacement):
    corpus, frontend, candidate = caller_fixture()
    request = prepare_request(corpus, frontend, candidate, 'Required behavior')['request']
    result = apply_response(request, answers(request, {'H0':replacement}), corpus, frontend)
    assert result['status'] == 'unknown' and result['candidate'] is None
