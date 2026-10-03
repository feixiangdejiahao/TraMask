import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search.byte_stream_refinement import generate

CODE = r'''import httpx
import pytest
def test_buffered():
    response = httpx.Response(200, content=b'"\xc2\xb5"')
    assert list(response.iter_values()) == ['\u00b5']
def test_streamed():
    def body():
        yield b'"\xc2\xb5"'
    response = httpx.Response(200, content=body())
    assert list(response.iter_values()) == ['\u00b5']
'''
ISSUE = 'Add `Response.iter_values()`. Parse values from buffered and streaming responses.'


def fixture(code=CODE):
    frontend = extract_frontend([Source('test_values.py', code, 'python', 'repository')])
    return to_emitter_corpus(frontend), frontend


def test_byte_identity_is_exact_for_every_closed_payload_and_chunk_size():
    corpus, frontend = fixture()
    original = copy.deepcopy((corpus, frontend))
    result = generate(corpus, frontend, ISSUE)
    assert result['total_candidates'] == 4
    for candidate in result['candidates']:
        edit = candidate['edits'][0]
        assert b''.join(eval(edit['after'])) == eval(edit['before'])
        assert len(candidate['source_test_ids']) == 2
        assert candidate['source_evidence']['exact_byte_concatenation']
    assert (corpus, frontend) == original


def test_new_chunks_expose_decoder_error_while_both_source_controls_pass(tmp_path):
    corpus, frontend = fixture()
    candidate = generate(corpus, frontend, ISSUE)['candidates'][0]
    material = emit(corpus, [candidate])
    assert not material['unsupported']
    # A deliberately wrong chunk-local UTF-8 decoder. Both original source
    # tests supply complete code points, but single-byte refinement must fail.
    (tmp_path/'httpx.py').write_text('''import json
class Response:
    def __init__(self, status, *, content): self.content=content
    def iter_values(self):
        chunks=[self.content] if isinstance(self.content,bytes) else self.content
        yield json.loads(''.join(chunk.decode('utf-8') for chunk in chunks))
''')
    path = tmp_path/'test_values.py'
    path.write_text(material['files']['test_values.py'])
    run = subprocess.run([sys.executable, '-m', 'pytest', '-q', str(path), '-o', 'addopts='],
                         cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert run.returncode == 1, run.stdout + run.stderr
    assert '1 failed, 4 passed' in run.stdout, run.stdout
    assert 'UnicodeDecodeError' in run.stdout


@pytest.mark.parametrize('extra', [
    '\n    assert response.is_closed',
    '\n    assert list(response.iter_values()) == ["\\u00b5"]',
    '\n    alias = response',
    '\n    assert response.headers == {}',
])
def test_representation_sensitive_or_repeated_receiver_uses_are_not_lifted(extra):
    code = CODE.replace('def test_streamed():', extra + '\ndef test_streamed():')
    corpus, frontend = fixture(code)
    assert not generate(corpus, frontend, ISSUE)['candidates']


def test_chunk_observer_is_not_a_semantic_iterator():
    corpus, frontend = fixture(CODE.replace('iter_values', 'iter_raw'))
    assert not generate(corpus, frontend, ISSUE.replace('iter_values', 'iter_raw'))['candidates']


def test_existing_streaming_control_is_required():
    corpus, frontend = fixture(CODE.split('def test_streamed():')[0])
    result = generate(corpus, frontend, ISSUE)
    assert not result['candidates']
    assert result['skipped'][0]['reason'] == 'no_source_streaming_control'


def test_closed_parametrization_transports_every_bytes_value_without_reordering():
    code = CODE.replace('def test_buffered():', '@pytest.mark.parametrize("data", [b"[]", b"{}", b"\\x00\\xff"])\ndef test_buffered(data):')
    code = code.replace("content=b'\"\\xc2\\xb5\"'", 'content=data', 1)
    corpus, frontend = fixture(code)
    candidates = generate(corpus, frontend, ISSUE)['candidates']
    assert len(candidates) == 4
    for candidate in candidates:
        for data in [b'[]', b'{}', b'\x00\xff']:
            assert b''.join(eval(candidate['edits'][0]['after'], {'data': data})) == data
        assert candidate['source_evidence']['body_lengths'] == [2, 2, 2]


@pytest.mark.parametrize('replacement', ['content=unknown()', 'content="text"'])
def test_dynamic_or_text_bodies_do_not_receive_a_bytes_contract(replacement):
    code = CODE.replace("content=b'\"\\xc2\\xb5\"'", replacement, 1)
    corpus, frontend = fixture(code)
    assert not generate(corpus, frontend, ISSUE)['candidates']


def test_shadowed_constructor_or_builtins_and_async_tests_are_not_selected():
    for code in [CODE.replace('def test_buffered():', 'def test_buffered(len):'),
                 CODE.replace('def test_buffered():', 'def test_buffered(*len):'),
                 CODE.replace('def test_buffered():', 'def test_buffered():\n    def len(x): return 1'),
                 CODE.replace('def test_buffered():', 'def test_buffered():\n    from somewhere import range'),
                 CODE.replace('def test_buffered():', 'async def test_buffered():'),
                 CODE.replace('def test_buffered():', 'def test_buffered():\n    httpx.Response = Other'),
                 CODE.replace('def test_buffered():', 'def test_buffered():\n    httpx = other')]:
        corpus, frontend = fixture(code)
        assert not generate(corpus, frontend, ISSUE)['candidates']


def test_generation_does_not_consume_labels_and_refuses_source_mismatch():
    corpus, frontend = fixture()
    result = generate(corpus, frontend, ISSUE)
    corpus['evaluation'] = {'valid': False}
    assert result == generate(corpus, frontend, ISSUE)
    changed = copy.deepcopy(corpus)
    changed['sources']['test_values.py']['code'] += '\n'
    with pytest.raises(ValueError, match='frontend_source_mismatch'):
        generate(changed, frontend, ISSUE)
