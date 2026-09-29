import importlib.util
import json
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('declarations_review',Path(__file__).parents[1]/'scripts/audit_source_declarations_ablation.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def block(code):
    return 'SOURCE '+json.dumps({'span':{'start_byte':7,'end_byte':7+len(code.encode())}})+'\n'+code+'\n'

def test_embedded_header_text_does_not_split_a_declaration():
    code='def f():\n    return "SOURCE {not a header} 界"\n'
    rows=m.parse_blocks(block(code)+block('x=1'))
    assert [body.decode() for _,body in rows]==[code,'x=1']

def test_truncated_span_is_rejected():
    with pytest.raises(AssertionError):
        m.parse_blocks(block('long_source')[:-3])

def test_unannotated_graph_text_after_complete_source_is_rejected():
    with pytest.raises((AssertionError,ValueError)):
        m.parse_blocks(block('x=1')+'E0 -> O0\n')

def test_renderer_source_hash_alias_is_unambiguous():
    assert m.source_hash({'sha256':'abc'})=='abc'
    assert m.source_hash({'source_sha256':'abc'})=='abc'
    with pytest.raises(AssertionError):
        m.source_hash({'sha256':'abc','source_sha256':'def'})
