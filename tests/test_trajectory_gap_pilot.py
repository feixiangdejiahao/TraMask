"""Trust boundaries and executable-test transport for the paired pilot.

These tests use small source repositories and fake native execution. They do not
call a provider, execute generated subject code, or encode benchmark solutions.
"""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search import oracle
from scripts import run_trajectory_gap_pilot as pilot


PY_CODE = 'from api import double\n\ndef test_value():\n    assert double(3) == 6\n'
PY_API = 'def double(value):\n    """Return twice the input."""\n    return value * 2\n'
HISTORY = 'from api import double\n\ndef test_old():\n    assert double(91) == PRIVATE_HISTORY_SENTINEL\n'


def fixture(language='python'):
    if language == 'python':
        sources = [Source('test_value.py', PY_CODE, 'python', 'repository'),
                   Source('api.py', PY_API, 'python', 'repository')]
    else:
        sources = [Source('value.test.ts', 'import {test,expect} from "vitest";\n'
                         'import {double} from "./api";\n'
                         'test("value", () => { expect(double(3)).toBe(6); });\n',
                         'typescript', 'repository'),
                   Source('api.ts', 'export function double(x:number) { return x*2; }\n'
                         'export function transform(x:string) { return x.length; }\n',
                         'typescript', 'repository'),
                   Source('donor.test.ts', 'import {transform} from "./api";\n'
                         'export const original = transform("abc");\n',
                         'typescript', 'repository')]
    frontend = extract_frontend(sources)
    corpus = to_emitter_corpus(frontend)
    identifier = next(k for k in corpus['tests'] if k.startswith('test_value.py' if language == 'python' else 'value.test.ts'))
    source, test, _ = pilot.core._source_test(corpus, identifier)
    seed = dict(seed_alias='S1', base_test_id=identifier, span=test['span'],
                body_span=test['body_span'], source_sha256=hashlib.sha256(source.data).hexdigest())
    case = dict(case='P2', seeds=[seed], permitted_imports=[])
    return corpus, frontend, case, oracle.text(corpus, test['span'])


def answer(rewritten, imports=(), alias='S1'):
    return json.dumps({'tests': [{'seed_alias': alias, 'rewritten_test': rewritten, 'imports': list(imports)}]})


def normalized_input(case='P2', seed_id='original:test'):
    return dict(case=case, seed_ids=[seed_id],
                original_issue={'text': 'Public issue.'},
                original_steps=[{'step_id': 2, 'message': 'ORIGINAL_STEP_SENTINEL',
                                 'tool_calls': [], 'observation': {'results': []}}],
                extra_original_source=[], permitted_import_additions=[],
                manual_selection_reason='PRIVATE_REASON_SENTINEL',
                target_gap='PRIVATE_TARGET_SENTINEL',
                selection_limits=['PRIVATE_LIMIT_SENTINEL'],
                manual_other={'hidden_answer': 'PRIVATE_OTHER_SENTINEL'})


def test_normalization_does_not_serialize_manual_evaluation_fields():
    row = normalized_input()
    before = copy.deepcopy(row)
    result = pilot.normalize(row)
    serialized = json.dumps(result)
    assert 'PRIVATE_' not in serialized
    assert 'Public issue.' in serialized and 'ORIGINAL_STEP_SENTINEL' in serialized
    assert row == before


def test_nested_generation_input_uses_only_source_allowlist():
    row = dict(case='N01', manual_selection_reason='PRIVATE_REASON_SENTINEL',
               generation_input=dict(issue={'text': 'Public issue.', 'evaluation': 'PRIVATE_ISSUE_SENTINEL'},
                   seeds=[{'test_id': 'original:test', 'target': 'PRIVATE_SEED_SENTINEL'}],
                   trajectory={'steps': [{'step_id': 2, 'message': 'ORIGINAL_STEP_SENTINEL'}],
                               'analysis': 'PRIVATE_TRAJECTORY_SENTINEL'},
                   extra_source_blocks=[{'path': 'api.py', 'start_line': 1, 'end_line': 1,
                                         'code': 'PUBLIC_SOURCE_SENTINEL', 'target': 'PRIVATE_BLOCK_SENTINEL'}],
                   rationale='PRIVATE_GENERATION_SENTINEL'))
    result = json.dumps(pilot.normalize(row))
    assert 'PRIVATE_' not in result
    assert 'PUBLIC_SOURCE_SENTINEL' in result and 'ORIGINAL_STEP_SENTINEL' in result


def prepared_pair(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot, 'ROOT', tmp_path)
    monkeypatch.setattr(pilot, 'CASES', ['P2'])
    sources = [Source('test_value.py', PY_CODE, 'python', 'repository'),
               Source('api.py', PY_API, 'python', 'repository'),
               Source('history.py', HISTORY, 'python', 'trajectory')]
    frontend = extract_frontend(sources)
    corpus = to_emitter_corpus(frontend)
    source = tmp_path/'source'
    pilot.write(source/'corpus.json', corpus)
    pilot.write(source/'frontend.json', frontend)
    pilot.write(source/'case.json', {})
    pilot.write(source/'selection.json', {})
    (source/'issue.md').write_text('Public issue.')
    identifier = next(k for k in corpus['tests'] if k.startswith('test_value.py'))
    row = normalized_input(seed_id=identifier)
    trajectory = tmp_path/'data/relational_gap_v1/P2/trajectory.json'
    pilot.write(trajectory, {'steps': row['original_steps']})
    repository = trajectory.parent/'repository'
    repository.mkdir()
    (repository/'test_value.py').write_text(PY_CODE)
    (repository/'api.py').write_text(PY_API)
    pilot.write(tmp_path/'results/evidence_restart_20261004/round18_contract_gap_generation/prepared.json',
                {'cases': [{'case': 'P2', 'source': str(source)}]})
    manual = tmp_path/'manual.json'
    pilot.write(manual, {'cases': [row]})
    output = tmp_path/'experiment'
    pilot.prepare(output, [manual])
    p = pilot.read(output/'prepared.json')
    requests = {r['arm']: pilot.read(r['request']['path']) for r in p['requests']}
    return output, p, requests


def test_prepared_arms_differ_only_by_complete_original_steps(tmp_path, monkeypatch):
    _, _, requests = prepared_pair(tmp_path, monkeypatch)
    plain = requests['source_only']; history = requests['source_and_trajectory']
    a = json.loads(plain['prompt']); b = json.loads(history['prompt'])
    selected = b.pop('original_trajectory_steps')
    assert selected == normalized_input()['original_steps']
    assert a == b
    for field in ['system', 'thinking', 'reasoning_effort', 'max_tokens']:
        assert plain[field] == history[field]
    for request in requests.values():
        assert 'PRIVATE_' not in request['prompt']
        assert request['query_sha256'] == pilot.core._identity(request)
    assert 'ORIGINAL_STEP_SENTINEL' not in plain['prompt']
    assert 'ORIGINAL_STEP_SENTINEL' in history['prompt']
    assert a['seeds'][0]['original_source_file']['text'] == PY_CODE
    assert a['seeds'][0]['original_test'] in PY_CODE


@pytest.mark.parametrize('response', ['null', '[]', '{"tests": [], "rationale": "x"}',
                                      '{"tests": [], "tests": []}'])
def test_non_schema_json_cannot_create_a_candidate(response):
    corpus, _, case, _ = fixture()
    result = pilot.decode(corpus, case, response, 'stop')
    assert not result['candidates'] and result['status'] == 'unknown'


def test_non_string_test_is_rejected_without_aborting_other_proposal():
    corpus, _, case, original = fixture()
    valid = original.replace('double(3) == 6', 'double(4) == 8')
    payload = {'tests': [{'seed_alias': 'S1', 'rewritten_test': 37, 'imports': []},
                         {'seed_alias': 'S1', 'rewritten_test': valid, 'imports': []}]}
    result = pilot.decode(corpus, case, json.dumps(payload), 'stop')
    assert len(result['rejected']) == 1 and len(result['candidates']) == 1
    assert oracle.preview(corpus, result['candidates'][0]) == valid


def test_complete_test_rewrite_retains_registration_and_source_receipts():
    corpus, _, case, original = fixture()
    rewritten = original.replace('double(3) == 6', 'double(4) == 8')
    result = pilot.decode(corpus, case, answer(rewritten), 'stop')
    assert result['rejected'] == [] and len(result['candidates']) == 1
    candidate = result['candidates'][0]
    assert oracle.preview(corpus, candidate) == rewritten
    assert candidate['source_provenance']['modified_test_utf8_sha256'] == pilot.sha(rewritten)
    assert candidate['source_provenance']['seed'] == case['seeds'][0]['base_test_id']
    assert emit(corpus, [candidate])['unsupported'] == []


@pytest.mark.parametrize('kind', ['rename', 'extra_test', 'import', 'dynamic_execution'])
def test_rewrite_cannot_escape_registration_or_add_dynamic_code(kind):
    corpus, _, case, original = fixture()
    rewritten = {
        'rename': original.replace('test_value', 'test_other'),
        'extra_test': original + '\n\ndef test_extra():\n    assert False',
        'import': original.replace('    assert', '    import os\n    assert'),
        'dynamic_execution': original.replace('    assert', '    eval("1+1")\n    assert'),
    }[kind]
    result = pilot.decode(corpus, case, answer(rewritten), 'stop')
    assert not result['candidates'] and result['rejected']


@pytest.mark.parametrize('imports', [['os'], ['transform', 'transform'], [{'name': 'transform'}]])
def test_import_list_cannot_escape_named_source_allowlist(imports):
    corpus, _, case, original = fixture('typescript')
    case['permitted_imports'] = [dict(name='transform', module='./api',
                                    imported_name='transform', source_path='donor.test.ts')]
    result = pilot.decode(corpus, case, answer(original.replace('double(3)', 'transform("abcd")'), imports), 'stop')
    assert not result['candidates'] and result['rejected']


def test_allowed_typescript_import_reaches_emitted_source_with_original_identity():
    corpus, _, case, original = fixture('typescript')
    binding = dict(name='transform', module='./api', imported_name='transform', source_path='donor.test.ts')
    case['permitted_imports'] = [binding]
    rewritten = original.replace('double(3)', 'transform("abcdef")')
    decoded = pilot.decode(corpus, case, answer(rewritten, ['transform']), 'stop')
    assert not decoded['rejected'] and len(decoded['candidates']) == 1
    candidate = decoded['candidates'][0]
    assert candidate['imports'] == [binding]
    emitted = emit(corpus, [candidate])
    assert not emitted['unsupported']
    assert oracle.preview(corpus, candidate) == rewritten
    # The emitter result must actually contain the exact import member. Merely
    # recording an allowed symbol in candidate metadata does not supply it.
    path = emitted['obligations'][0]['path']
    code = emitted['files'][path]
    check = pilot.import_provenance_repair.verify_bindings(corpus, candidate, path, code)
    assert check['status'] == 'matched' and len(check['checks']) == 1
    wrong = code.replace('import { transform } from "./api";', 'import { transform } from "./other";')
    assert wrong != code
    assert pilot.import_provenance_repair.verify_bindings(corpus, candidate, path, wrong)['status'] == 'mismatch'


def native_fixture(tmp_path, monkeypatch):
    corpus, _, case, original = fixture()
    decoded = pilot.decode(corpus, case, answer(original.replace('double(3) == 6', 'double(4) == 8')), 'stop')
    source = tmp_path/'source'; pilot.write(source/'corpus.json', corpus)
    case.update(source=str(source))
    d = tmp_path/'cases/P2/source_only'
    pilot.write(d/'decoded.json', decoded)
    pilot.write(d/'candidate_01/program.json', decoded['candidates'][0])
    summary = {'stage': 'generation_complete', 'results': [dict(case='P2', arm='source_only',
                decoded=pilot.frozen(d/'decoded.json'), manifest=None)]}
    pilot.write(tmp_path/'generation_summary.json', summary)
    pilot.write(tmp_path/'generation_summary_seal.json', pilot.frozen(tmp_path/'generation_summary.json'))
    protocol = {'cases': [case], 'requests': [{'case': 'P2', 'arm': 'source_only'}]}
    monkeypatch.setattr(pilot, 'load_protocol', lambda _: protocol)
    calls = []
    def forbidden_native(*args, **kwargs):
        calls.append(True)
        raise AssertionError('unverified candidate reached native execution')
    monkeypatch.setattr(pilot, 'execute', forbidden_native)
    monkeypatch.setattr(pilot, 'try_emit', forbidden_native)
    return d, calls


def test_native_rejects_decoded_receipt_tampering_before_execution(tmp_path, monkeypatch):
    d, calls = native_fixture(tmp_path, monkeypatch)
    decoded = pilot.read(d/'decoded.json')
    decoded['candidates'][0]['edits'][0]['after'] += '\n    assert False\n'
    (d/'decoded.json').write_text(json.dumps(decoded))
    with pytest.raises(ValueError):
        pilot.run_native(tmp_path)
    assert calls == []


def test_native_rejects_program_record_disagreement_before_execution(tmp_path, monkeypatch):
    d, calls = native_fixture(tmp_path, monkeypatch)
    program = pilot.read(d/'candidate_01/program.json')
    program['edits'][0]['after'] += '\n    assert False\n'
    (d/'candidate_01/program.json').write_text(json.dumps(program))
    with pytest.raises(ValueError):
        pilot.run_native(tmp_path)
    assert calls == []
