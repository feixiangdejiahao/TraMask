"""Declared runtime observations must survive reporter formatting, not aliases."""
import pytest

from relation_search.feedback import match_declared_tests


def test_empty_root_suite_whitespace_matches_only_declared_test():
    rows=[dict(id=' suite gc_changed ',status='fail'),dict(id=' suite unrelated',status='skip')]
    matched,errors=match_declared_tests(rows,['suite gc_changed'])
    assert matched==[rows[0]] and errors==[]


def test_internal_whitespace_is_not_collapsed():
    rows=[dict(id=' suite  gc_changed ',status='fail')]
    assert match_declared_tests(rows,['suite gc_changed'])==([],['missing_declared_test_id'])


@pytest.mark.parametrize('names',[
 [' gc_changed','gc_changed '],['pkg_a::gc_changed','pkg_b::gc_changed'],
 ['gc_changed','gc_changed']])
def test_multiple_normalized_matches_are_unknown_not_arbitrarily_selected(names):
    rows=[dict(id=name,status='fail' if index else 'pass') for index,name in enumerate(names)]
    assert match_declared_tests(rows,['gc_changed'])==([],['ambiguous_normalized_runtime_test_id'])


def test_distinct_subtests_and_parameter_cases_remain_independent_named_outcomes():
    rows=[dict(id=' pkg::gc_changed/first ',status='pass'),dict(id='pkg::gc_changed/second',status='fail')]
    assert match_declared_tests(rows,['gc_changed'])==(rows,[])
    rows=[dict(id=' gc_changed[one] ',status='pass'),dict(id='gc_changed[two]',status='fail')]
    assert match_declared_tests(rows,['gc_changed'])==(rows,[])


def test_ambiguous_declared_names_and_prefix_siblings_never_match():
    rows=[dict(id='gc_changed_suffix',status='fail')]
    assert match_declared_tests(rows,['gc_changed'])==([],['missing_declared_test_id'])
    assert match_declared_tests(rows,['gc_changed',' gc_changed'])==([],['ambiguous_normalized_declared_test_id'])


def test_missing_one_of_several_declared_tests_keeps_evidence_but_invalidates_control():
    rows=[dict(id=' A ',status='pass'),dict(id='unrelated',status='skip')]
    assert match_declared_tests(rows,['A','B'])==([rows[0]],['missing_declared_test_id'])
    rows.append(dict(id=' B ',status='pass'))
    assert match_declared_tests(rows,['A','B'])==([rows[0],rows[2]],[])
