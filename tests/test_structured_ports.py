"""Independent literal-container carrier fixtures."""
import ast

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.embedded_relations import generate_embedded_relations
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relational_gap.structured_ports import carrier_ports, structural_slot_key
from relational_gap.transforms import _root_ports


def fixture(code, language="python"):
    path = {"python": "test_sample.py", "typescript": "sample.test.ts", "go": "sample_test.go"}[language]
    source = Source(path, code, language)
    frontend = extract_frontend([source])
    return source, frontend, to_emitter_corpus(frontend)


def donor(corpus, value):
    return next(d for d in corpus["donors"] if d.get("literal_known") and d.get("literal_value") == value)


def test_inline_nested_record_list_path_does_not_change_root_contract():
    source, frontend, corpus = fixture('''def test_values():
    consume([{"sql": "payload", "other": "different"}])
    assert True
''')
    leaf = donor(corpus, "payload")
    assert not _root_ports(source, leaf)
    port, = carrier_ports(source, leaf, frontend)
    assert port["structural_path"] == [{"kind": "index", "value": 0}, {"kind": "key", "value": "sql"}]
    other, = carrier_ports(source, donor(corpus, "different"), frontend)
    assert structural_slot_key(port) != structural_slot_key(other)
    assert not carrier_ports(source, donor(corpus, "sql"), frontend)


def test_source_bound_container_retains_leaf_location_and_alias_origin():
    source, frontend, corpus = fixture('''def test_values():
    payload = [{"sql": "query"}]
    alias = payload
    consume(alias)
    assert True
''')
    port, = carrier_ports(source, donor(corpus, "query"), frontend)
    assert port["carrier_kind"] == "source_bound_literal"
    assert port["leaf_span"] == donor(corpus, "query")["span"]
    assert port["runtime_container_state"] == "unknown"


@pytest.mark.parametrize("expression", [
    '{"sql": "query", "sql": "replacement"}',
    '{"sql": "query", **extra}',
    '[*extra, "query"]',
    'build("query") + suffix',
    '{dynamic: "query"}',
])
def test_ambiguous_structures_and_effectful_intermediates_are_not_transparent(expression):
    source, frontend, corpus = fixture(f"def test_values():\n    consume({expression})\n    assert True\n")
    leaf = donor(corpus, "query")
    ports = carrier_ports(source, leaf, frontend)
    assert not any(p["callee"] == "consume" for p in ports)


def test_conditional_binding_does_not_establish_container_carrier():
    source, frontend, corpus = fixture('''def test_values():
    payload = ["query"]
    if flag:
        payload = other
    consume(payload)
    assert True
''')
    assert not carrier_ports(source, donor(corpus, "query"), frontend)


def test_go_literal_container_and_typescript_fields():
    source, frontend, corpus = fixture('''package sample
import "testing"
func TestValues(t *testing.T) { consume([]map[string]string{{"sql": "query"}}); if !ok() { t.Fatal("bad") } }
''', "go")
    port, = carrier_ports(source, donor(corpus, "query"), frontend)
    assert port["structural_path"] == [{"kind": "index", "value": 0}, {"kind": "key", "value": "sql"}]
    source, frontend, corpus = fixture('test("values", () => { consume([{sql: "query"}]); expect(ok()).toBe(true); });', "typescript")
    port, = carrier_ports(source, donor(corpus, "query"), frontend)
    assert port["structural_path"] == [{"kind": "index", "value": 0}, {"kind": "key", "value": "sql"}]


def test_sql_update_inside_container_is_mutated_at_leaf_only():
    _, frontend, corpus = fixture('''def test_values():
    before = read("SELECT id FROM rows WHERE count > 6")
    batch = [{"sql": "UPDATE rows SET title = 3 WHERE id = 1", "label": "keep"}]
    apply(batch)
    assert before is not None
''')
    result = generate_embedded_relations(corpus, frontend)
    assert len(result["candidates"]) == 3
    for candidate in result["candidates"]:
        edit, = candidate["edits"]
        assert ast.literal_eval(edit["after"]).startswith("UPDATE rows SET title = 3, count = ")
        assert candidate["relation"]["write_structural_path"] == [{"kind": "index", "value": 0}, {"kind": "key", "value": "sql"}]
        assert '"label"' not in edit["before"]


def test_sql_source_assignment_transfer_keeps_field_path():
    code = '''def test_values():
    read("SELECT id FROM rows WHERE count > 6")
    consume({"sql": "UPDATE rows SET count = 2", "unrelated": "opaque"})
    assert True
def test_other():
    consume({"sql": "opaque", "unrelated": "UPDATE rows SET count = 40"})
    assert True
'''
    _, frontend, corpus = fixture(code)
    result = generate_embedded_relations(corpus, frontend)
    assert not [c for c in result["candidates"] if c["relation"]["value_basis"] == "source_assignment"]


def test_predicate_fragment_requires_same_slot_sql_evidence():
    code = '''def test_values():
    read("count > 6")
    consume(["UPDATE rows SET title = 3 WHERE id = 1"])
    assert True
def test_query_source():
    read("SELECT id FROM rows WHERE count > 2")
    assert True
'''
    _, frontend, corpus = fixture(code)
    result = generate_embedded_relations(corpus, frontend)
    assert len(result["candidates"]) == 3
    assert all(c["relation"]["read_embedded_form"] == "predicate_fragment" for c in result["candidates"])
    assert all(c["relation"]["read_embedding_evidence"]["kind"] == "same_structural_slot_source_select" for c in result["candidates"])
    _, frontend, corpus = fixture(code.replace('read("SELECT', 'different("SELECT'))
    assert not generate_embedded_relations(corpus, frontend)["candidates"]


def test_predicate_fragment_keeps_container_field_alignment():
    code = '''def test_values():
    read({"predicate": "count > 6", "other": "opaque"})
    consume(["UPDATE rows SET title = 3"])
    assert True
def test_query_source():
    read({"predicate": "opaque", "other": "SELECT id FROM rows WHERE count > 2"})
    assert True
'''
    _, frontend, corpus = fixture(code)
    assert not generate_embedded_relations(corpus, frontend)["candidates"]


@pytest.mark.parametrize("construction", [
    '"SELECT id FROM rows WHERE " + predicate',
    'f"SELECT id FROM rows WHERE {predicate}"',
])
def test_resolved_production_sql_template_establishes_fragment_grammar(construction):
    code = f'''def inner(predicate):
    return database_call({construction})
def wrapper(predicate):
    return inner(predicate)
def test_values():
    wrapper("count > 6")
    consume(["UPDATE rows SET title = 3"])
    assert True
'''
    _, frontend, corpus = fixture(code)
    result = generate_embedded_relations(corpus, frontend)
    assert len(result["candidates"]) == 3
    for candidate in result["candidates"]:
        evidence = candidate["relation"]["read_embedding_evidence"]
        assert evidence["kind"] == "resolved_source_string_template"
        assert len(evidence["binding_path"]) == 2
        assert candidate["provenance"]["source_facts"][0]["text"] == "count > 6"


def test_fragment_without_source_embedding_never_gets_sql_from_api_name():
    _, frontend, corpus = fixture('''def test_values():
    execute_sql("count > 6")
    consume(["UPDATE rows SET title = 3"])
    assert True
''')
    assert not generate_embedded_relations(corpus, frontend)["candidates"]
