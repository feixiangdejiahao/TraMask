import ast

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relation_search.constructors import generate
from relational_gap.frontend import extract_frontend, to_emitter_corpus


def corpus(code):
    front = extract_frontend([Source('test_routes.py', code, 'python')])
    return to_emitter_corpus(front), front


def test_sequence_extension_changes_its_joint_string_representation():
    code = '''from library import Open as Run
def test_observe():
    item = Run("warm|file", modes=["warm"], alternate="named")
    assert item.alias == "named"
def test_modes():
    item = Run("cold|warm|folder", modes=["cold", "warm"])
    assert item.modes == ("cold", "warm")
'''
    source, front = corpus(code)
    rows = generate(source, front)
    target = [r for r in rows if r['base_test_id'].endswith(':test_observe')]
    assert len(target) == 1
    assert [e['after'] for e in target[0]['edits']] == ["['warm', 'cold']", "'warm|cold|file'"]
    rendered = emit(source, target)
    assert len(rendered['obligations']) == 1
    assert 'assert item.alias == "named"' in rendered['files']['test_routes.py']


def test_expected_calls_and_nested_local_scopes_are_not_input_constructors():
    code = '''from library import Run
def test_one():
    item = Run("warm|file", modes=["warm"])
    def helper():
        return Run("cold|warm|file", modes=["cold", "warm"])
    assert item == Run("cold|warm|file", modes=["cold", "warm"])
'''
    source, front = corpus(code)
    assert generate(source, front) == []


def test_source_frame_changes_and_symbolic_payload_survives():
    code = '''def test_phase(reader, phase):
    result = reader.consume(f"@41|7:{phase!s}X")
    assert result.phase == phase
def test_chunked(reader):
    header = "@9Z"
    packet = header + "DATA"
    for piece in partition(packet, 2):
        result = reader.consume(piece)
    assert result.tag == "tag"
'''
    source, front = corpus(code)
    rows = generate(source, front)
    assert len(rows) == 1
    after = ast.parse(rows[0]['edits'][0]['after'], mode='eval').body
    assert after.values[0].value == '@9|7:'
    assert after.values[-1].value == 'Z'
    assert after.values[1].conversion == ord('s')
    assert rows[0]['source_contexts'][0]['code'].startswith('def test_chunked')


def test_complete_file_donor_survives_recipient_ranking_and_name_changes():
    code = '''def test_observation(transport, flag):
    value = transport.parse(f"~104,1:{flag}A")
    assert value.flag == flag
def test_old_constructor(transport):
    value = transport.parse("~58B")
    assert value.kind == "other"
'''
    source, front = corpus(code)
    source['tests'] = {k:v for k,v in source['tests'].items() if k.endswith(':test_observation')}
    rows = generate(source, front)
    assert len(rows) == 1
    assert ast.parse(rows[0]['edits'][0]['after'], mode='eval').body.values[0].value == '~58,1:'
