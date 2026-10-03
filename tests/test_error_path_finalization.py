import copy
import subprocess
import sys

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search import error_path_finalization as relation

ISSUE = ('Add `Response.iter_values()`. For streaming responses, iterating values '
         'must consume the response stream and close the response.')
CODE = '''import httpx
import pytest
def test_error():
    response = httpx.Response(200, content=b'{bad}', headers={'Content-Type': 'application/json'})
    with pytest.raises(httpx.DecodingError):
        list(response.iter_values())
    assert 2+2 == 4
def test_streamed():
    def body():
        yield b'{}'
    result = httpx.Response(200, content=body(), headers={'Content-Type': 'application/json'})
    assert list(result.iter_values()) == [{}]
    assert result.is_closed
'''


def fixture(code=CODE):
    frontend = extract_frontend([Source('test_values.py', code, 'python', 'repository')])
    return to_emitter_corpus(frontend), frontend


def test_source_postcondition_is_renamed_and_original_error_and_suffix_are_preserved():
    corpus, frontend = fixture()
    before = copy.deepcopy((corpus, frontend))
    result = relation.generate(corpus, frontend, ISSUE)
    candidate, = result['candidates']
    assert len(candidate['source_test_ids']) == 2
    assert b''.join(eval(candidate['edits'][0]['after'])) == b'{bad}'
    observer = candidate['edits'][1]
    assert observer['after'].startswith(observer['before'])
    assert observer['after'].endswith('assert response.is_closed')
    material = emit(corpus, [candidate])
    assert not material['unsupported']
    code = material['files']['test_values.py']
    assert code.count('assert 2+2 == 4') == 3
    assert (corpus, frontend) == before


def test_missing_failure_finalizer_is_detected_while_source_controls_pass(tmp_path):
    corpus, frontend = fixture()
    candidate, = relation.generate(corpus, frontend, ISSUE)['candidates']
    material = emit(corpus, [candidate])
    (tmp_path/'httpx.py').write_text('''import json
class DecodingError(Exception): pass
class Response:
    def __init__(self, status, *, content, headers):
        self.content=content
        self.is_closed=isinstance(content, bytes)
    def iter_values(self):
        data=self.content if isinstance(self.content,bytes) else b''.join(self.content)
        try: value=json.loads(data)
        except ValueError as error: raise DecodingError() from error
        yield value
        self.is_closed=True
''')
    target = tmp_path/'test_values.py'
    target.write_text(material['files']['test_values.py'])
    run = subprocess.run([sys.executable, '-m', 'pytest', '-q', str(target), '-o', 'addopts='],
                         cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert run.returncode == 1, run.stdout + run.stderr
    assert '1 failed, 4 passed' in run.stdout
    assert 'is_closed' in run.stdout


def test_incremental_exhaustion_requires_an_observed_stop_iteration():
    code = CODE.replace('    assert list(result.iter_values()) == [{}]', '''    iterator = result.iter_values()
    assert next(iterator) == {}
    with pytest.raises(StopIteration):
        next(iterator)''')
    corpus, frontend = fixture(code)
    assert len(relation.generate(corpus, frontend, ISSUE)['candidates']) == 1
    code = code.replace('    with pytest.raises(StopIteration):\n        next(iterator)\n', '')
    corpus, frontend = fixture(code)
    assert not relation.generate(corpus, frontend, ISSUE)['candidates']


def test_explicit_public_sync_stream_adapter_can_supply_the_same_close_observer():
    code = CODE.replace('def test_error():', '''class Stream(httpx.SyncByteStream):
    def __init__(self, items): self.items=items
    def __iter__(self): yield from self.items
def test_error():''').replace('content=body()', 'stream=Stream(body())')
    corpus, frontend = fixture(code)
    assert len(relation.generate(corpus, frontend, ISSUE)['candidates']) == 1
    assert frontend['sources']['test_values.py']['code'] == code


@pytest.mark.parametrize('change', [
    lambda s: s.replace("content=b'{bad}', headers={'Content-Type': 'application/json'}", "content=b'{bad}', headers={'Content-Type': 'application/json; charset=bad'}"),
    lambda s: s.replace('content=b\'{bad}\'', 'content=unknown()'),
    lambda s: s.replace('headers={\'Content-Type\': \'application/json\'}', 'headers=options', 1),
    lambda s: s.replace('    assert result.is_closed', '    result.close()\n    assert result.is_closed'),
    lambda s: s.replace('    assert result.is_closed', '    alias = result\n    assert result.is_closed'),
    lambda s: s.replace('def test_error():', 'def test_error(list):'),
    lambda s: s.replace('def test_error():', 'def test_error(pytest):'),
    lambda s: s.replace('def test_error():', 'async def test_error():'),
    lambda s: s.replace('with pytest.raises(httpx.DecodingError):', 'with pytest.raises(httpx.DecodingError):\n        observer()'),
])
def test_unproved_constructor_error_exhaustion_or_binding_conditions_abstain(change):
    corpus, frontend = fixture(change(CODE))
    assert not relation.generate(corpus, frontend, ISSUE)['candidates']


@pytest.mark.parametrize('issue', [
    'Add `Response.iter_values()`.',
    ISSUE.replace('must consume', 'must not consume'),
    ISSUE.replace('must consume', 'may consume'),
    ISSUE.replace('close the response.', 'close the response only on success.'),
    ISSUE.replace('close the response.', 'close the response when successfully exhausted.'),
])
def test_no_total_close_obligation_means_no_lifted_failure_postcondition(issue):
    corpus, frontend = fixture()
    assert not relation.generate(corpus, frontend, issue)['candidates']


def test_source_provenance_and_labels_do_not_change_the_source_only_decision():
    corpus, frontend = fixture()
    before = relation.generate(corpus, frontend, ISSUE)
    corpus['evaluation'] = {'valid': False}
    assert relation.generate(corpus, frontend, ISSUE) == before
    changed = copy.deepcopy(corpus)
    changed['sources']['test_values.py']['code'] += '\n'
    with pytest.raises(ValueError, match='frontend_source_mismatch'):
        relation.generate(changed, frontend, ISSUE)
