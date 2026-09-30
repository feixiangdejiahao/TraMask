"""Independent source-only counterexamples, with no pilot labels or runtime.

The miniature subjects are parsed as source data, never imported or executed.
"""
from __future__ import annotations

import difflib

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus


def repository(old, new, body, *, extra_sources=(), imports="calculate"):
    patch = "".join(difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile="a/library.py", tofile="b/library.py", n=0,
    ))
    test = "from library import " + imports + "\n\ndef test_review():\n" + "".join(
        "    " + line + "\n" for line in body.splitlines()
    )
    frontend = extract_frontend([
        Source("library.py", new, "python"),
        Source("test_review.py", test, "python"),
        *extra_sources,
    ], patch=patch)
    corpus = to_emitter_corpus(frontend)
    return corpus, frontend, patch


def edit(corpus, before, after, *, name="change", occurrence=0):
    test_id = next(iter(corpus["tests"]))
    extent = corpus["tests"][test_id]["span"]
    data = corpus["sources"][extent["path"]]["code"].encode()
    start = extent["start_byte"]
    for index in range(occurrence + 1):
        start = data.index(before.encode(), start)
        if index < occurrence:
            start += len(before.encode())
    return dict(id=name, base_test_id=test_id, imports=[], operator="input_change",
                edits=[dict(before=before, after=after, role="input", span=dict(
                    path=extent["path"], start_byte=start,
                    end_byte=start + len(before.encode()),
                ))])


RETURN_OLD = "def calculate(value):\n    return value * 2\n"
RETURN_NEW = "def calculate(value):\n    return value * 3\n"


def evidence(corpus, frontend, patch, candidate, mode):
    from experimental.patch_observation_priority import select
    result = select(corpus, frontend, [candidate], patch, mode=mode)
    assert result["input_count"] == 1
    assert result["selected_count"] == 1
    assert result["selected"][0]["id"] == candidate["id"]
    row = result["ranking"][0]["evidence"]
    return dict(row, review_priority=row["strong_priority" if mode == "strict" else "may_priority"],
                review_witnesses=row["witnesses"] if mode == "strict" else [*row["witnesses"], *row["may_witnesses"]])


@pytest.mark.parametrize("mode", ["strict", "may"])
def test_real_same_call_input_return_observation_chain_is_prioritized(mode):
    c, f, p = repository(RETURN_OLD, RETURN_NEW,
                        "value = 11\nresult = calculate(value)\nassert result == 22")
    row = evidence(c, f, p, edit(c, "11", "19"), mode)
    assert row["review_priority"]
    assert row["review_witnesses"]
    assert all("may" in w["status"] for w in row["review_witnesses"])


def test_changed_diagnostic_statement_is_not_a_strict_return_dependency():
    old = 'def calculate(value):\n    note = "old"\n    return value\n'
    new = old.replace('"old"', '"new"')
    c, f, p = repository(old, new,
                        "value = 11\nresult = calculate(value)\nassert result == 11")
    assert not evidence(c, f, p, edit(c, "11", "19"), "strict")["review_priority"]
    may = evidence(c, f, p, edit(c, "11", "19"), "may")
    assert may["review_priority"]
    assert all("may" in w["status"] for w in may["review_witnesses"])


def test_changed_diagnostic_on_same_line_does_not_mark_unchanged_return():
    old = 'def calculate(value): note = "old"; return value\n'
    new = old.replace('"old"', '"new"')
    c, f, p = repository(old, new,
                        "value = 11\nresult = calculate(value)\nassert result == 11")
    assert not evidence(c, f, p, edit(c, "11", "19"), "strict")["review_priority"]
    may = evidence(c, f, p, edit(c, "11", "19"), "may")
    assert may["review_priority"]
    assert all("may" in w["status"] for w in may["review_witnesses"])


@pytest.mark.parametrize("mode", ["strict", "may"])
def test_overwritten_result_does_not_reach_actual(mode):
    c, f, p = repository(RETURN_OLD, RETURN_NEW,
                        "value = 11\nresult = calculate(value)\nresult = 0\nassert result == 0")
    assert not evidence(c, f, p, edit(c, "11", "19"), mode)["review_priority"]


@pytest.mark.parametrize("mode", ["strict", "may"])
def test_changed_call_on_different_object_does_not_reach_observation(mode):
    old = "def calculate(box):\n    box[0] = 2\n    return 0\n"
    new = old.replace("= 2", "= 3")
    c, f, p = repository(old, new,
                        "a = [11]\nb = [23]\ncalculate(a)\nresult = b[0]\nassert result == 23")
    assert not evidence(c, f, p, edit(c, "11", "19"), mode)["review_priority"]


@pytest.mark.parametrize("mode", ["strict", "may"])
def test_same_callee_two_calls_keep_the_actual_call_site_binding(mode):
    c, f, p = repository(RETURN_OLD, RETURN_NEW,
                        "active = 11\nother = 23\nfirst = calculate(active)\nsecond = calculate(other)\nassert first == 22")
    assert not evidence(c, f, p, edit(c, "23", "31"), mode)["review_priority"]
    assert evidence(c, f, p, edit(c, "11", "19"), mode)["review_priority"]


@pytest.mark.parametrize("mode", ["strict", "may"])
def test_patch_leg_and_edit_leg_cannot_join_through_different_actual_calls(mode):
    other = "\ndef identity(value):\n    return value\n"
    c, f, p = repository(RETURN_OLD + other, RETURN_NEW + other,
                        "active = 11\nother = 23\nfirst = calculate(active)\nsecond = identity(other)\nassert first + second == 45",
                        imports="calculate, identity")
    assert not evidence(c, f, p, edit(c, "23", "31"), mode)["review_priority"]


def test_unused_callee_argument_is_not_a_strict_return_dependency():
    old = "def calculate(value, unused):\n    return value * 2\n"
    new = old.replace("* 2", "* 3")
    c, f, p = repository(old, new,
                        "active = 11\nother = 23\nresult = calculate(active, other)\nassert result == 22")
    row = edit(c, "23", "31")
    assert not evidence(c, f, p, row, "strict")["review_priority"]
    may = evidence(c, f, p, row, "may")
    assert may["review_priority"]
    assert all("may" in w["status"] for w in may["review_witnesses"])


def test_opaque_return_is_only_a_may_path():
    old = "def calculate(value):\n    return opaque(value, 2)\n"
    new = old.replace(", 2", ", 3")
    c, f, p = repository(old, new,
                        "value = 11\nresult = calculate(value)\nassert result == 22")
    strict = evidence(c, f, p, edit(c, "11", "19"), "strict")
    assert not strict["review_priority"]
    assert strict["unknowns"]
    may = evidence(c, f, p, edit(c, "11", "19"), "may")
    assert may["review_priority"]
    assert all("may" in w["status"] for w in may["review_witnesses"])


def test_callee_loop_is_only_a_may_path():
    old = "def calculate(value):\n    result = 0\n    for i in range(value):\n        result += i * 2\n    return result\n"
    new = old.replace("* 2", "* 3")
    c, f, p = repository(old, new,
                        "value = 11\nresult = calculate(value)\nassert result == 110")
    strict = evidence(c, f, p, edit(c, "11", "19"), "strict")
    assert not strict["review_priority"]
    assert strict["unknowns"]
    may = evidence(c, f, p, edit(c, "11", "19"), "may")
    assert may["review_priority"]
    assert all("may" in w["status"] for w in may["review_witnesses"])


@pytest.mark.parametrize("mode", ["strict", "may"])
def test_missing_callback_edge_is_not_promoted_or_filtered(mode):
    c, f, p = repository(RETURN_OLD, RETURN_NEW,
                        "runner = calculate\nvalue = 11\nresult = runner(value)\nassert result == 22")
    row = evidence(c, f, p, edit(c, "11", "19"), mode)
    assert not row["review_priority"]


@pytest.mark.parametrize("mode", ["strict", "may"])
def test_unresolved_same_spelling_method_is_not_a_callee_proof(mode):
    c, f, p = repository(RETURN_OLD, RETURN_NEW,
                        "value = 11\nresult = unknown.calculate(value)\nassert result == 22")
    assert not evidence(c, f, p, edit(c, "11", "19"), mode)["review_priority"]


@pytest.mark.parametrize("mode", ["strict", "may"])
def test_replaced_callee_does_not_keep_original_patch_path(mode):
    other = "\ndef identity(value):\n    return value\n"
    c, f, p = repository(RETURN_OLD + other, RETURN_NEW + other,
                        "value = 11\nresult = calculate(value)\nassert result == 22",
                        imports="calculate, identity")
    row = edit(c, "calculate(value)", "identity(19)")
    assert not evidence(c, f, p, row, mode)["review_priority"]


@pytest.mark.parametrize("mode", ["strict", "may"])
def test_module_import_rebinding_is_not_a_production_callee_proof(mode):
    other = "\ndef identity(value):\n    return value\n"
    c, f, p = repository(RETURN_OLD + other, RETURN_NEW + other,
                        "value = 11\nresult = calculate(value)\nassert result == 11",
                        imports="calculate, identity\ncalculate = identity")
    assert not evidence(c, f, p, edit(c, "11", "19"), mode)["review_priority"]


@pytest.mark.parametrize("mode", ["strict", "may"])
def test_rebound_production_export_is_not_the_original_function(mode):
    other = "\ndef identity(value):\n    return value\n\ncalculate = identity\n"
    c, f, p = repository(RETURN_OLD + other, RETURN_NEW + other,
                        "value = 11\nresult = calculate(value)\nassert result == 11")
    assert not evidence(c, f, p, edit(c, "11", "19"), mode)["review_priority"]


@pytest.mark.parametrize("mode", ["strict", "may"])
def test_patch_in_expected_only_is_not_an_actual_path(mode):
    c, f, p = repository(RETURN_OLD, RETURN_NEW,
                        "value = 11\nresult = 22\nexpected = calculate(value)\nassert result == expected")
    assert not evidence(c, f, p, edit(c, "11", "19"), mode)["review_priority"]


def test_unreachable_branch_witness_does_not_claim_execution_or_value_change():
    old = "def calculate(value):\n    if False:\n        return value * 2\n    return value\n"
    new = old.replace("* 2", "* 3")
    c, f, p = repository(old, new,
                        "value = 11\nresult = calculate(value)\nassert result == 11")
    for mode in ("strict", "may"):
        row = evidence(c, f, p, edit(c, "11", "19"), mode)
        # Strict denotes a finite source dependency chain, not feasible execution.
        for witness in row["review_witnesses"]:
            assert "may" in witness["status"]
            assert "not_execution" in witness["status"] or "unproved" in witness["status"]
