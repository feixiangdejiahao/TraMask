"""Independent lexical merge successes and semantic/alignment counterexamples."""
import textwrap

import pytest

from experimental.edit_square.core import edit_square


def codes(result):
    return [candidate['code'] for candidate in result['candidates']]


def test_joint_input_and_expected_wrapping_transports_nonoverlapping_value_changes():
    result = edit_square('assert f(1) == 2\n', 'assert f([1]) == [2]\n', 'assert f(3) == 6\n')
    assert result['status'] == 'hypothesis'
    assert codes(result) == ['assert f([3]) == [6]\n']
    assert all(result['checks'].values())
    assert result['alignment']['uniqueness'] == 'not_checked'


def test_setup_length_change_combines_with_existing_added_operation():
    A = 'x = f(1)\nassert x == 2\n'
    B = 'x = f(1)\ncheckpoint(x)\nassert x == 2\n'
    C = 'arg = 3\nx = f(arg)\nassert x == 6\n'
    result = edit_square(A, B, C)
    assert result['status'] == 'hypothesis'
    assert codes(result) == ['arg = 3\nx = f(arg)\ncheckpoint(x)\nassert x == 6\n']
    assert all(result['checks'].values())


def test_same_tokenizer_exposes_context_inside_strings():
    result = edit_square('assert parse("f(1)") == "out(2)"\n',
                         'assert parse("box(f(1))") == "box(out(2))"\n',
                         'assert parse("f(3)") == "out(6)"\n')
    assert result['status'] == 'hypothesis'
    assert codes(result) == ['assert parse("box(f(3))") == "box(out(6))"\n']


def test_conflicting_expected_replacements_are_rejected_without_an_oracle_guess():
    result = edit_square('assert f(1) == 2\n', 'assert f(1) == 8\n', 'assert f(1) == 6\n')
    assert result['status'] == 'unsupported'
    assert result['reason'] == 'conflicting_source_intervals'
    assert result['conflicts'][0]['reason'] == 'overlapping_replacements'
    assert all(result['checks'].values())


def test_same_position_insertions_have_two_bounded_orders():
    result = edit_square('start\nend\n', 'start\nleft()\nend\n', 'start\nright()\nend\n')
    assert result['status'] == 'hypothesis'
    assert set(codes(result)) == {'start\nleft()\nright()\nend\n', 'start\nright()\nleft()\nend\n'}
    assert len(result['shared_insertion_points']) == 1


def test_insertion_inside_another_replacement_conflicts_but_boundaries_do_not():
    result = edit_square('a+b', 'q', 'a+X+b')
    assert result['reason'] == 'conflicting_source_intervals'
    assert result['conflicts'][0]['reason'] == 'insertion_inside_replacement'
    boundary = edit_square('a', 'b', '[a]')
    assert codes(boundary) == ['[b]']


def test_multiple_shared_points_still_produce_only_two_global_orders():
    result = edit_square('a b c', 'a X b X c', 'a Y b Y c')
    assert len(result['shared_insertion_points']) == 2
    assert set(codes(result)) == {'a X Y b X Y c', 'a Y X b Y X c'}


def run(body, prelude):
    namespace = {}
    exec(prelude + '\ndef check():\n' + textwrap.indent(body, '    '), namespace)
    namespace['check']()


def test_nonoverlap_does_not_prove_binding_capture_safe():
    A = 'assert compute() == 1\n'
    B = 'cached = 7\nassert compute() == 1\n'
    C = 'assert compute() == 1\nassert cached == 3\n'
    prelude = 'cached = 3\ndef compute(): return 1\n'
    for source in (A, B, C):
        run(source, prelude)
    result = edit_square(A, B, C)
    assert result['status'] == 'hypothesis' and all(result['checks'].values())
    assert 'bindings_and_capture' in result['unproved']
    with pytest.raises(AssertionError):
        run(codes(result)[0], prelude)


def test_nonoverlap_does_not_prove_effect_independence():
    A = 'assert True\n'
    B = 'tick()\nassert True\n'
    C = 'assert True\nassert counter == 0\n'
    prelude = 'counter = 0\ndef tick():\n    global counter\n    counter += 1\n'
    for source in (A, B, C):
        run(source, prelude)
    result = edit_square(A, B, C)
    assert result['status'] == 'hypothesis'
    assert 'effects_and_aliases' in result['unproved']
    with pytest.raises(AssertionError):
        run(codes(result)[0], prelude)


def test_repeated_token_correspondence_is_deterministic_but_not_unique():
    A, B, C = 'item item', 'item', 'item changed'
    result = edit_square(A, B, C)
    assert result == edit_square(A, B, C)
    assert result['reason'] == 'conflicting_source_intervals'
    assert result['alignment']['repeated_source_token_kinds'] > 0
    assert result['alignment']['uniqueness'] == 'not_checked'
    # Another valid A->B script deletes the first occurrence, rather than the
    # last one chosen by this deterministic alignment. It would not conflict.
    assert A[5:] == B
    assert A[:5] + 'changed' == C
    assert 'changed' not in codes(result)


def test_utf8_byte_intervals_and_source_fragments_are_exact():
    A = '名 = f(1)\nassert 名 == 2\n'
    result = edit_square(A, '名 = f([1])\nassert 名 == [2]\n', '名 = f(3)\nassert 名 == 6\n')
    assert result['status'] == 'hypothesis'
    for edits in result['edits'].values():
        for edit in edits:
            assert A.encode()[edit['start_byte']:edit['end_byte']].decode() == edit['before']
    assert codes(result) == ['名 = f([3])\nassert 名 == [6]\n']


def test_budgets_and_unchanged_sides_are_explicit():
    assert edit_square('a', 'a b', 'a c', max_tokens=1)['reason'] == 'token_budget'
    assert edit_square('a', 'a b', 'a c', max_bytes=1)['reason'] == 'byte_budget'
    assert edit_square('a', 'a', 'b')['reason'] == 'unchanged_side'
    assert edit_square('a', 'b', 'b')['reason'] == 'identical_sides'
