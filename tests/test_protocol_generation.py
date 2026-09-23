import ast
import json

from combination_testing.protocol import (
    Fact,
    Packet,
    UNKNOWN,
    extract_facts,
    generate_protocol_transports,
    infer_dependencies,
    learn_and_complete,
    predict,
    render_probe,
)


def test_wire_codec_preserves_nested_fields_and_bit_union():
    packet = Packet.parse("\x1b[100:120:121;5:3;97:98u")
    assert packet == Packet("100u", ("120", "121"), 5, "3", ("97", "98"))
    row = list(packet.vector(3))
    row[2] = 1
    combined = Packet.from_vector(tuple(row), 3)
    assert combined.modifiers == 6
    assert Packet.parse(combined.encode()) == combined
    assert Packet.parse("\x1b[<12;45;99M") is None


def test_unique_dependency_ignores_irrelevant_coordinates():
    rows = [(("alpha", 1), "start"), (("alpha", 2), "end"), (("beta", 1), "start")]
    dependencies, reason = infer_dependencies(rows)
    assert dependencies == [(1,)]
    assert reason == "empirical_minimum_dependency"
    assert predict(("beta", 2), rows, dependencies) == "end"


def test_all_minimum_explanations_must_agree():
    rows = [(("alpha", 1), "start"), (("beta", 2), "end")]
    dependencies, _ = infer_dependencies(rows)
    assert dependencies == [(0,), (1,)]
    assert predict(("alpha", 2), rows, dependencies) is UNKNOWN


def test_new_lookup_and_no_contrast_are_not_assumed():
    rows = [((1, 0), "start"), ((2, 0), "end")]
    dependencies, _ = infer_dependencies(rows)
    assert predict((3, 0), rows, dependencies) is UNKNOWN
    assert infer_dependencies([((1, 0), "same"), ((2, 1), "same")]) == ([], "no_output_contrast")
    assert infer_dependencies([((1, 0), "start"), ((1, 0), "end")]) == ([], "conflicting_examples")


def test_inference_is_explicitly_empirical_not_a_soundness_claim():
    # A hidden interaction is indistinguishable from independence on three
    # examples. This counterexample documents the method's actual limit.
    rows = [((0, 0), 0), ((1, 0), 1), ((0, 1), 0)]
    dependencies, _ = infer_dependencies(rows)
    prediction = predict((1, 1), rows, dependencies)
    actual_with_interaction = 2
    assert prediction == 1
    assert prediction != actual_with_interaction


def test_ast_extractor_parameter_frames_and_receiver_origin(tmp_path):
    path = tmp_path / "test_wire.py"
    path.write_text('''
import pytest
@pytest.mark.parametrize("mode,state", [("1", "first"), ("2", "second")])
def test_receive(receiver, mode, state):
    [message] = receiver.feed(f"\\x1b[42;1:{mode}u")
    assert message.status == state
    app = unrelated()
    assert app.status == "unrelated"
''')
    facts, _ = extract_facts(path, "test_wire.py", {"test_receive"})
    assert len(facts) == 2
    assert [f.expected for f in facts] == ["first", "second"]
    assert all(f.field == "status" for f in facts)
    assert [Packet.parse(f.sequence).phase for f in facts] == ["1", "2"]


def test_ast_extractor_tracks_reassigned_sequence_and_event_alias(tmp_path):
    path = tmp_path / "test_wire.py"
    path.write_text('''
def test_receive(receiver):
    events = list(receiver.feed("\\x1b[42;1:1u"))
    message = events[0]
    assert message.status == "first"
    events = list(receiver.feed("\\x1b[42;1:2u"))
    message = events[0]
    assert message.status == "second"
''')
    facts, _ = extract_facts(path, "test_wire.py", {"test_receive"})
    assert [f.expected for f in facts] == ["first", "second"]
    assert [Packet.parse(f.sequence).phase for f in facts] == ["1", "2"]


def test_completion_uses_registry_keys_and_refuses_single_alias_claim():
    facts = [Fact("\x1b[42;1:1u", "status", "eq", "first", {}),
             Fact("\x1b[42;1:2u", "status", "eq", "second", {}),
             Fact("\x1b[42;1:1u", "names", "contains", "control+x", {})]
    obligations, models, _ = learn_and_complete(facts, ["7~", "1A"])
    values = {(Packet.parse(o["sequence"]).key, Packet.parse(o["sequence"]).phase, o["expected"])
              for o in obligations if o["field"] == "status"}
    assert ("7~", "2", "second") in values
    assert ("1A", "1", "first") in values
    assert not any(o["field"] == "names" for o in obligations)
    assert next(m for m in models if m["field"] == "names")["reason"] == "no_output_contrast"


def test_rendered_probe_is_executable_python_without_dynamic_eval():
    source = render_probe({"module": "pkg.wire", "class": "Receiver", "method": "feed"},
                          [{"id": "synthetic", "sequence": "\x1b[42u", "field": "status", "op": "eq", "expected": "first"}])
    tree = ast.parse(source)
    assert "eval(" not in source
    assert "Subject" in source
    assert {n.name for n in tree.body if isinstance(n, ast.FunctionDef)} == {
        "normalize", "matches", "test_combination_projection"}


def test_guards_retain_correlated_context_and_exclude_derived_properties():
    facts = [Fact("\x1b[42;1:1u", "status", "eq", "first", {}),
             Fact("\x1b[42;1:2u", "status", "eq", "second", {}),
             Fact("\x1b[42;1:1u", "is_first", "eq", True, {}),
             Fact("\x1b[42;1:2u", "is_first", "eq", False, {})]
    obligations, _, _ = learn_and_complete(facts, ["7~"], guarded=True,
                                            derived_fields={"is_first": ["status"]})
    status = [o for o in obligations if o["field"] == "status"]
    assert status
    assert all(not o["guards"] for o in status)
    derived = [o for o in obligations if o["field"] == "is_first"]
    assert all(any(g["field"] == "status" for g in o["guards"]) for o in derived)


def test_guards_are_executable_abstention_and_not_posthoc_filtering():
    source = render_probe({"module": "pkg.wire", "class": "Receiver", "method": "feed"}, [])
    assert 'pytest.skip("projected context guard not established")' in source


def test_unadmitted_transports_retain_positive_membership_and_packet_provenance(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "src/pkg").mkdir(parents=True)
    (tmp_path / "src/pkg/wire.py").write_text('from pkg.table import TOKENS\nclass Receiver: pass\n')
    (tmp_path / "src/pkg/table.py").write_text('TOKENS = {"8~": "end", "1A": "up"}\n')
    source = '''
import pytest
from pkg.wire import Receiver
@pytest.fixture
def receiver():
    return Receiver()
def test_first(receiver):
    [message] = receiver.feed("\\x1b[44:55;5u")
    assert "control+symbol" in message.names
def test_donor(receiver):
    [message] = receiver.feed("\\x1b[40;2u")
    assert message.payload == "x"
'''
    (tmp_path / "tests/test_wire.py").write_text(source)
    anchors = []
    for fn in ast.parse(source).body:
        if isinstance(fn, ast.FunctionDef) and fn.name.startswith("test_"):
            assertion = next(n for n in fn.body if isinstance(n, ast.Assert))
            anchors.append({"id": fn.name, "test_id": fn.name, "path": "tests/test_wire.py",
                            "name": fn.name, "line": assertion.lineno, "origin": "repository"})
    result = generate_protocol_transports(tmp_path, {"anchors": anchors,
                                                    "rankings": {"full": [a["id"] for a in anchors]}})
    row = next(r for r in result["candidates"] if r["field"] == "names" and r["followup_packet"]["modifiers"] == 6)
    assert row["source_packet"]["modifiers"] == 5
    assert row["expected"] == "control+symbol"
    assert row["op"] == "contains"
    assert row["relation"] == "unadmitted_one_factor_oracle_transport"
    assert row["source_assertion"]["assertion"] == 'assert "control+symbol" in message.names'
    assert set(row["source_packet"]) == {"key", "alternate", "modifiers", "phase", "text"}
    assert row["donor_sources"]


def test_printed_protocol_literal_does_not_replace_parser_origin(tmp_path):
    path = tmp_path / "test_wire.py"
    path.write_text('''
def test_receive(receiver):
    [message] = receiver.feed("\\x1b[42u")
    print("\\x1b[99u")
    assert message.status == "first"
''')
    facts, _ = extract_facts(path, "test_wire.py", {"test_receive"})
    assert facts[0].sequence == "\x1b[42u"
