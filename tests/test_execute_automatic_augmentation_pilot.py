"""Check append-only transport, source-derived imports, and execution controls."""
import copy
import json
from pathlib import Path

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search import oracle
from scripts import execute_automatic_augmentation_pilot as adapter


def fixture(language='python', extra=()):
    if language == 'python':
        files = [Source('test_value.py', 'from api import twice\n\ndef test_value():\n    assert twice(3) == 6\n',
                        'python', 'repository'),
                 Source('api.py', 'def twice(x):\n    return x * 2\n', 'python', 'repository')]
    else:
        files = [Source('value.test.ts', 'import { test, expect } from "vitest";\n'
                        'import { twice } from "./api.ts";\n'
                        'test("value", () => { expect(twice(3)).toBe(6); });\n', 'typescript', 'repository'),
                 Source('api.ts', 'export function twice(x:number) { return x*2; }\n', 'typescript', 'repository')]
    corpus = to_emitter_corpus(extract_frontend([*files, *extra]))
    seed_id = next(k for k in corpus['tests'] if k.startswith('test_value.py' if language == 'python' else 'value.test.ts'))
    case = dict(seeds=[dict(seed_alias='S1', base_test_id=seed_id)], goals=[dict(goal_id='G1', seed_alias='S1')])
    original = oracle.text(corpus, corpus['tests'][seed_id]['span'])
    rewritten = original.replace('twice(3) == 6', 'twice(4) == 8').replace('twice(3)).toBe(6)', 'twice(4)).toBe(8)')
    return corpus, case, original, rewritten


def response(code, imports=(), goal='G1'):
    return json.dumps(dict(tests=[dict(goal_id=goal, seed_alias='S1', rewritten_test=code, imports=list(imports))]))


def decode(corpus, case, code, imports=()):
    return adapter.decode(corpus, case, response(code, imports), 'stop')


def test_appended_copy_keeps_original_test_and_production_source():
    corpus, case, original, rewritten = fixture()
    decoded = decode(corpus, case, rewritten)
    assert not decoded['rejected']
    candidate = decoded['candidates'][0]
    adapter.verify_candidate(corpus, candidate)
    emitted = emit(corpus, [candidate])
    assert list(emitted['files']) == ['test_value.py']
    generated = emitted['files']['test_value.py']
    assert original in generated
    assert 'assert twice(4) == 8' in generated
    assert len(emitted['controls']) == len(emitted['obligations']) == 1
    assert emitted['controls'][0]['test_name'] != emitted['obligations'][0]['test_name']
    assert 'api.py' not in emitted['files']


def test_frozen_goal_must_match_selected_seed_and_no_oracle_gate_is_used():
    corpus, case, _, rewritten = fixture()
    result = adapter.decode(corpus, case, response(rewritten, goal='G2'), 'stop')
    assert not result['candidates'] and result['rejected'][0]['reason'] == 'goal_seed_binding_mismatch'
    # Structurally valid but wrong expectations must remain visible to the
    # independent oracle audit; a source check cannot silently filter them.
    result = decode(corpus, case, rewritten.replace('== 8', '== 999'))
    assert len(result['candidates']) == 1


@pytest.mark.parametrize('code', [None, 3, [], {'source': 'assert False'}])
def test_bad_row_does_not_drop_following_valid_candidate(code):
    corpus, case, _, rewritten = fixture()
    data = json.loads(response(rewritten))
    data['tests'].insert(0, dict(data['tests'][0], rewritten_test=code))
    result = adapter.decode(corpus, case, json.dumps(data), 'stop')
    assert len(result['rejected']) == len(result['candidates']) == 1
    assert result['candidates'][0]['order'] == [2]


@pytest.mark.parametrize('payload', ['{"tests":[],"tests":[]}', '{"tests":[],"note":"x"}', 'null'])
def test_strict_response_schema(payload):
    corpus, case, _, _ = fixture()
    assert adapter.decode(corpus, case, payload, 'stop')['status'] == 'unknown'


@pytest.mark.parametrize('kind', ['rename', 'extra_test', 'local_import', 'dynamic'])
def test_test_rewrite_cannot_escape_original_boundary(kind):
    corpus, case, _, rewritten = fixture()
    rewritten = dict(rename=rewritten.replace('test_value', 'test_other'),
                     extra_test=rewritten+'\n\ndef test_extra():\n    assert False',
                     local_import=rewritten.replace('    assert', '    import os\n    assert'),
                     dynamic=rewritten.replace('    assert', '    eval("1")\n    assert'))[kind]
    result = decode(corpus, case, rewritten)
    assert result['rejected'] and not result['candidates']


def test_format_normalization_never_changes_assertions():
    corpus, case, _, rewritten = fixture()
    candidate = decode(corpus, case, rewritten+'\n\n')['candidates'][0]
    assert oracle.preview(corpus, candidate) == rewritten
    assert candidate['augmentation_provenance']['normalization'] == ['trailing_whitespace_only']
    corpus, case, _, rewritten = fixture('typescript')
    candidate = decode(corpus, case, rewritten[:-1]+'\n')['candidates'][0]
    assert oracle.preview(corpus, candidate) == rewritten
    assert candidate['augmentation_provenance']['normalization'] == ['trailing_whitespace_only', 'optional_registration_semicolon_only']


def test_nested_typescript_registration_is_rejected_before_native():
    corpus, case, _, rewritten = fixture('typescript')
    rewritten = rewritten.replace('expect(twice(4))', 'test("extra", () => {}); expect(twice(4))')
    result = decode(corpus, case, rewritten)
    assert result['rejected'][0]['reason'] == 'additional_test_registration_in_body'
    assert not result['candidates']


def test_long_barrel_export_works_without_donor_or_manual_api_allowlist(tmp_path):
    repository = tmp_path/'repository'
    repository.mkdir()
    # The requested symbol occurs after 40 exports and its implementation is
    # absent from the corpus, but present in the original repository snapshot.
    exports = ''.join(f"export * from './part{i}.ts';\n" for i in range(40))
    exports += "export * from './last/index.ts';\n"
    for i in range(40):
        (repository/f'part{i}.ts').write_text(f'export const value{i} = {i};\n')
    (repository/'last').mkdir()
    (repository/'last/index.ts').write_text("export * from './transform.ts';\n")
    (repository/'last/transform.ts').write_text('export function transform(x:string) { return x.length; }\n')
    corpus, case, _, rewritten = fixture('typescript', [Source('barrel.ts', exports, 'typescript', 'repository')])
    for path, row in corpus['sources'].items():
        target = repository/path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(row['code'])
    case['repository'] = str(repository)
    rewritten = rewritten.replace('twice(4)).toBe(8)', 'transform("abcd")).toBe(4)')
    imported = dict(name='transform', module='./barrel.ts', imported_name='transform')
    result = decode(corpus, case, rewritten, [imported])
    assert not result['rejected']
    candidate = result['candidates'][0]
    adapter.verify_candidate(corpus, candidate, repository)
    proof = candidate['augmentation_provenance']['import_proofs'][0]
    assert proof['endpoint'] == ['last/transform.ts', 'transform']
    assert len(proof['sources']) == 3
    generated = emit(corpus, [candidate])['files']['value.test.ts']
    assert 'import { transform } from "./barrel.ts";' in generated
    # Changing source after decode invalidates the import proof before native.
    (repository/'last/transform.ts').write_text('export function transform(x:string) { return 0; }\n')
    with pytest.raises(ValueError, match='source_reconstruction'):
        adapter.verify_candidate(corpus, candidate, repository)


@pytest.mark.parametrize('module,member', [('../outside.ts', 'transform'), ('node:fs', 'readFile'), ('./api.ts', 'privateThing')])
def test_unproved_or_external_import_is_refused(module, member):
    corpus, case, _, rewritten = fixture('typescript')
    result = decode(corpus, case, rewritten, [dict(name='added', module=module, imported_name=member)])
    assert not result['candidates'] and result['rejected']


def test_type_only_export_does_not_become_runtime_api():
    corpus, case, _, rewritten = fixture('typescript', [Source('types.ts', 'export type Thing = string;\n', 'typescript', 'repository')])
    result = decode(corpus, case, rewritten, [dict(name='Thing', module='./types.ts', imported_name='Thing')])
    assert not result['candidates']


def native_fixture(tmp_path):
    corpus, case, _, rewritten = fixture()
    candidate = decode(corpus, case, rewritten)['candidates'][0]
    source = tmp_path/'source'
    source.mkdir()
    repository = tmp_path/'repository'
    repository.mkdir()
    for path, row in corpus['sources'].items():
        (repository/path).write_text(row['code'])
    adapter.write(source/'corpus.json', corpus)
    adapter.write(source/'case.json', dict(repository=str(repository), candidate_patch=str(source/'patch.diff')))
    adapter.write(source/'frontend.json', {})
    adapter.write(source/'selection.json', {})
    (source/'issue.md').write_text('Public issue')
    (source/'patch.diff').write_text('original patch bytes')
    return corpus, candidate, source


@pytest.mark.parametrize('status,expected_calls', [('pass', 1), ('fail', 2)])
def test_native_runs_all_phases_and_reuses_only_sealed_logs(tmp_path, monkeypatch, status, expected_calls):
    _, candidate, source = native_fixture(tmp_path)
    calls = []
    def emitted(candidate, source, directory, policy):
        directory.mkdir(parents=True)
        (directory/'stdout.txt').write_text('full native output')
        return directory, None
    def execute(*args):
        calls.append(args)
        return dict(controls=dict(status='all_source_controls_passed'), tests=[dict(status=status)],
                    parser_errors=[], controlled_failure=status == 'fail')
    monkeypatch.setattr(adapter, 'try_emit', emitted)
    monkeypatch.setattr(adapter.native.csi_repair_transport, 'verify', lambda *args: dict(status='matched'))
    monkeypatch.setattr(adapter, '_native_execute', execute)
    output = tmp_path/'output'
    result = adapter.execute(candidate, source, output)
    assert len(calls) == expected_calls
    assert result['repeated_controlled_failure'] == (status == 'fail')
    assert result['independent_validity'] == 'pending_complete_test_contract_audit'
    adapter.execute(candidate, source, output)
    assert len(calls) == expected_calls
    (output/'initial/native/stdout.txt').write_text('tampered')
    with pytest.raises(ValueError, match='Changed input'):
        adapter.execute(candidate, source, output)


def test_transport_mismatch_prevents_execution(tmp_path, monkeypatch):
    _, candidate, source = native_fixture(tmp_path)
    monkeypatch.setattr(adapter, 'try_emit', lambda *args: (tmp_path, None))
    monkeypatch.setattr(adapter.native.csi_repair_transport, 'verify', lambda *args: dict(status='mismatch'))
    monkeypatch.setattr(adapter, '_native_execute', lambda *args: pytest.fail('Must not execute mismatched code'))
    result = adapter.execute(candidate, source, tmp_path/'output')
    assert result['outcomes'][0]['status'] == 'transport_refused'


def test_tampered_candidate_stops_before_emission(tmp_path, monkeypatch):
    _, candidate, source = native_fixture(tmp_path)
    candidate['edits'][0]['after'] = candidate['edits'][0]['after'].replace('== 8', '== 9')
    monkeypatch.setattr(adapter, 'try_emit', lambda *args: pytest.fail('Must reconstruct before emission'))
    with pytest.raises(ValueError):
        adapter.execute(candidate, source, tmp_path/'output')


def test_import_transport_verified_before_native_execution(tmp_path, monkeypatch):
    corpus, case, _, rewritten = fixture('typescript', [Source('more.ts', 'export const added = 8;\n', 'typescript', 'repository')])
    candidate = decode(corpus, case, rewritten, [dict(name='added', module='./more.ts', imported_name='added')])['candidates'][0]
    source = tmp_path/'source'; source.mkdir()
    repository = tmp_path/'repository'; repository.mkdir()
    for path, row in corpus['sources'].items():
        (repository/path).write_text(row['code'])
    # Decode with repository receipts as actual execution will do.
    case['repository'] = str(repository)
    candidate = decode(corpus, case, rewritten, [dict(name='added', module='./more.ts', imported_name='added')])['candidates'][0]
    adapter.write(source/'corpus.json', corpus)
    adapter.write(source/'case.json', dict(repository=str(repository), candidate_patch=str(source/'patch.diff')))
    for name in ['frontend.json', 'selection.json']:
        adapter.write(source/name, {})
    (source/'issue.md').write_text('issue'); (source/'patch.diff').write_text('patch')
    artifact = tmp_path/'artifact'
    (artifact/'generated/files').mkdir(parents=True)
    (artifact/'generated/files/value.test.ts').write_text('import { added } from "./wrong.ts";\n')
    monkeypatch.setattr(adapter, 'try_emit', lambda *args: (artifact, None))
    monkeypatch.setattr(adapter.native, 'verify_emission', lambda *args: dict(status='matched'))
    monkeypatch.setattr(adapter, '_native_execute', lambda *args: pytest.fail('Bad import must block native'))
    result = adapter.execute(candidate, source, tmp_path/'output')
    assert result['outcomes'][0]['status'] == 'transport_refused'


def test_one_adapter_refusal_does_not_suppress_next_candidate(tmp_path, monkeypatch):
    visited = []
    def run(candidate, source, output, timeout):
        visited.append(candidate['id'])
        if candidate['id'] == 'first':
            raise ValueError('unavailable materialization')
        return dict(candidate_id=candidate['id'], repeated_controlled_failure=False)
    monkeypatch.setattr(adapter, 'execute', run)
    result = adapter.execute_all([dict(id='first'), dict(id='second')], tmp_path, tmp_path/'out')
    assert visited == ['first', 'second']
    assert result[0]['status'] == 'adapter_error'
    assert result[1]['candidate_id'] == 'second'
