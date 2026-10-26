"""Independent descriptor and cache fixtures; no subjects, labels or answers."""
from __future__ import annotations

import copy
import difflib

import pytest

from anchor_retrieval.syntax import Source
from prototypes.patch_observation_priority import select as old_select
from prototypes.patch_observation_priority_v2 import Analyzer, select
from relational_gap.frontend import _flow_for_test, _test_walk, extract_frontend, to_emitter_corpus


def fixture(old, new, body, *, imports="Box"):
    patch = "".join(difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile="a/library.py", tofile="b/library.py", n=0,
    ))
    text = "from library import " + imports + "\ndef test_review():\n" + "".join(
        "    " + line + "\n" for line in body.splitlines()
    )
    front = extract_frontend([Source("library.py", new, "python"),
                              Source("test_review.py", text, "python")], patch=patch)
    return to_emitter_corpus(front), front, patch


def candidate(corpus, before="11", after="19", name="change"):
    base = next(iter(corpus["tests"]))
    extent = corpus["tests"][base]["span"]
    source = corpus["sources"][extent["path"]]["code"].encode()
    start = source.index(before.encode(), extent["start_byte"])
    return dict(id=name, base_test_id=base, operator="input", imports=[], edits=[dict(
        before=before, after=after, role="input", span=dict(path=extent["path"],
        start_byte=start, end_byte=start + len(before.encode()))
    )])


BODY = "instance = Box()\nvalue = 11\nresult = instance.compute(value)\nassert result == 22"


def method(receiver="self", expression="value * 2", decorator="", prefix=""):
    return prefix + "class Box:\n" + ("    @" + decorator + "\n" if decorator else "") + \
        "    def compute(" + receiver + ", value):\n        return " + expression + "\n"


def facts(c, f, p, row=None, **kwargs):
    row = candidate(c) if row is None else row
    return select(c, f, [row], p, **kwargs)["ranking"][0]["evidence"]


@pytest.mark.parametrize("receiver", ["self", "cls", "object_arg", "banana"])
def test_plain_method_binding_uses_position_not_first_parameter_spelling(receiver):
    old = method(receiver)
    c, f, p = fixture(old, old.replace("* 2", "* 3"), BODY)
    assert facts(c, f, p)["strong_priority"]
    assert not facts(c, f, p, disable_receiver_fix=True)["strong_priority"]


@pytest.mark.parametrize("receiver", ["self", "object_arg"])
def test_reading_receiver_is_not_dropped_when_explicit_argument_is_bound(receiver):
    old = method(receiver, receiver + ".factor * value * 2")
    c, f, p = fixture(old, old.replace("* 2", "* 3"), BODY)
    row = facts(c, f, p)
    assert not row["strong_priority"]
    assert any("heap_or_unknown_dependency" in reason for reason in row["unknowns"])


def test_receiver_alias_retains_a_proved_constructor_binding():
    old = method("object_arg")
    body = BODY.replace("value = 11", "alias = instance\nvalue = 11").replace(
        "result = instance.compute", "result = alias.compute")
    c, f, p = fixture(old, old.replace("* 2", "* 3"), body)
    assert facts(c, f, p)["strong_priority"]


def test_method_with_mutable_argument_effect_stays_outside_strict_summary():
    old = "class Box:\n    def compute(receiver, value):\n        value.append(7)\n        return value[0] * 2\n"
    body = BODY.replace("value = 11", "value = [11]")
    c, f, p = fixture(old, old.replace("* 2", "* 3"), body)
    row = facts(c, f, p)
    assert not row["strong_priority"]
    assert row["may_priority"]
    assert row["unknowns"]


def test_staticmethod_first_argument_named_self_is_a_real_explicit_argument():
    old = "class Box:\n    @staticmethod\n    def compute(self):\n        return self * 2\n"
    c, f, p = fixture(old, old.replace("* 2", "* 3"), BODY)
    analyzer = Analyzer(c, f, p)
    unit = next(unit for unit in analyzer.index.units.values() if unit.test)
    flow = _flow_for_test(analyzer.index, unit, list(_test_walk(unit.body)))
    call = next(call for call in flow.calls if flow.nodes[call.node]["call"] == "instance.compute")
    target, reason = analyzer._target(analyzer.index, unit, flow, call)
    assert reason is None
    assert target[1]["self"] == call.args[0].id
    assert target[1]["self"] != call.receiver.id
    # Existing Flow treats a formal spelled self as a receiver.  That scope
    # limitation must stay unknown instead of silently dropping this input.
    row = facts(c, f, p)
    assert not row["strong_priority"]
    assert any("heap_or_unknown_dependency" in reason for reason in row["unknowns"])


def test_staticmethod_does_not_get_an_invented_receiver_argument():
    old = method("self", decorator="staticmethod")
    c, f, p = fixture(old, old.replace("* 2", "* 3"), BODY)
    row = facts(c, f, p)
    assert not row["strong_priority"]
    assert "non_exact_argument_binding" in row["unknowns"]


@pytest.mark.parametrize("receiver", ["cls", "class_arg"])
def test_classmethod_ignored_class_parameter_can_bind_the_value_argument(receiver):
    old = method(receiver, decorator="classmethod")
    c, f, p = fixture(old, old.replace("* 2", "* 3"), BODY)
    assert facts(c, f, p)["strong_priority"]


@pytest.mark.parametrize("decorator", ["staticmethod", "classmethod"])
def test_shadowed_builtin_descriptor_is_unknown(decorator):
    prefix = "def passthrough(function):\n    return function\n" + decorator + " = passthrough\n"
    old = method("self", decorator=decorator, prefix=prefix)
    c, f, p = fixture(old, old.replace("* 2", "* 3"), BODY)
    row = facts(c, f, p)
    assert not row["strong_priority"]
    assert "decorator_binding_unknown" in row["unknowns"]


def test_arbitrary_descriptor_is_not_assumed_to_preserve_plain_method_binding():
    old = method("self", decorator="unknown_decorator")
    c, f, p = fixture(old, old.replace("* 2", "* 3"), BODY)
    row = facts(c, f, p)
    assert not row["strong_priority"]
    assert "decorator_binding_unknown" in row["unknowns"]


def test_plain_unbound_call_keeps_its_explicit_receiver_argument():
    old = method("object_arg")
    body = BODY.replace("instance.compute(value)", "Box.compute(instance, value)")
    c, f, p = fixture(old, old.replace("* 2", "* 3"), body)
    assert facts(c, f, p)["strong_priority"]


def test_explicit_receiver_is_not_accepted_as_extra_classmethod_argument():
    old = method("cls", decorator="classmethod")
    body = BODY.replace("instance.compute(value)", "Box.compute(instance, value)")
    c, f, p = fixture(old, old.replace("* 2", "* 3"), body)
    assert not facts(c, f, p)["strong_priority"]


def test_global_class_rebinding_does_not_keep_the_old_constructor_proof():
    other = "\nclass Other:\n    def compute(object_arg, value):\n        return value\n"
    old = method("object_arg") + other
    c, f, p = fixture(old, old.replace("* 2", "* 3"), BODY,
                      imports="Box, Other\nBox = Other")
    row = facts(c, f, p)
    assert not row["strong_priority"]
    assert not row["may_priority"]


def test_class_namespace_descriptor_shadow_is_not_a_builtin_staticmethod():
    old = "class Box:\n    staticmethod = classmethod\n    @staticmethod\n    def compute(value):\n        return value * 2\n"
    c, f, p = fixture(old, old.replace("* 2", "* 3"), BODY)
    row = facts(c, f, p)
    assert not row["strong_priority"]
    assert "decorator_binding_unknown" in row["unknowns"]


@pytest.mark.parametrize("mode", ["strict", "may"])
def test_cache_only_preserves_v1_complete_ranking_and_evidence(mode):
    old = method("self")
    c, f, p = fixture(old, old.replace("* 2", "* 3"), BODY)
    rows = [candidate(c, after=value, name="v" + value) for value in ["19", "123456", "30"]]
    frozen = copy.deepcopy((c, f, rows))
    first = old_select(c, f, rows, p, mode=mode)
    second = select(c, f, rows, p, mode=mode, disable_receiver_fix=True)
    assert first["ranking"] == second["ranking"]
    assert first["selected"] == second["selected"]
    assert first["unselected_ids"] == second["unselected_ids"]
    assert (c, f, rows) == frozen


def test_reused_analyzer_does_not_cache_a_previous_candidate_callee_or_offsets():
    old = method("object_arg") + "\nclass Other:\n    def compute(object_arg, value):\n        return value\n"
    body = BODY.replace("value = 11", "otherxxx = Other()\nvalue = 11")
    c, f, p = fixture(old, old.replace("* 2", "* 3"), body, imports="Box, Other")
    yes = candidate(c)
    changed = candidate(c, "instance.compute(value)", "otherxxx.compute(19)", "other_receiver")
    longer = candidate(c, after="123456", name="longer")
    unicode = candidate(c, name="unicode")
    insertion = candidate(c, "instance = Box()", "instance = Box()")["edits"][0]
    insertion.update(before="", after='label = "雪"\n    ')
    insertion["span"]["end_byte"] = insertion["span"]["start_byte"]
    unicode["edits"].insert(0, insertion)
    analyzer = Analyzer(c, f, p)
    for row in [yes, changed, longer, unicode, changed, yes]:
        reused = analyzer.evidence(row)
        fresh = Analyzer(c, f, p).evidence(row)
        assert reused == fresh
    assert analyzer.evidence(yes)["strong_priority"]
    assert not analyzer.evidence(changed)["strong_priority"]
