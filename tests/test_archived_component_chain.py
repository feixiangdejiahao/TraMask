import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from scripts import run_archived_component_chain as chain


def put(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')
    return chain.frozen(path)


@pytest.fixture
def archive(tmp_path):
    # Commits belong exclusively to this disposable fixture repository.
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    code = tmp_path / 'runner.py'
    code.write_text('VERSION = "fixture"\n')
    subprocess.run(['git', '-C', str(tmp_path), 'add', 'runner.py'], check=True)
    subprocess.run(['git', '-C', str(tmp_path), '-c', 'user.name=Fixture',
                    '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture'], check=True)
    commit = subprocess.check_output(['git', '-C', str(tmp_path), 'rev-parse', 'HEAD']).decode().strip()
    return tmp_path, commit, chain.frozen(code)


def native(root, code, name='native', alert=None):
    source = root / 'original'
    inputs = {}
    for filename in sorted(chain.INPUTS):
        path = source / filename
        if not path.exists():
            put(path, {'original': filename})
        inputs[filename] = chain.frozen(path)
    cohort = root / 'cohort.json'
    if not cohort.exists():
        put(cohort, {'cases': [{'case': 'sample', 'source': str(source)}],
                     # Deliberately unavailable old code. This is input data,
                     # not an executed dependency of the new native component.
                     'algorithm': {'path': str(root / 'obsolete.py'), 'sha256': '0' * 64}})
    prepared = {'version': 'controlled-guest-declaration-order-search.v1',
                'algorithm': {'runner': code}, 'cases': [{'case': 'sample',
                'source': str(source), 'inputs': inputs}],
                'source_cohort': chain.frozen(cohort),
                'source_cohort_use': 'Only original snapshot paths and the full trial list; no old candidates or outcomes.'}
    summary = {'version': prepared['version'], 'results': [{'case': 'sample', 'alert': alert}],
               'trial_denominator': 1, 'native_executions': 2}
    directory = root / name
    prepared_receipt = put(directory / 'prepared.json', prepared)
    put(directory / 'seal.json', prepared_receipt)
    return prepared_receipt, put(directory / 'summary.json', summary)


def components(archive, monkeypatch):
    root, commit, code = archive
    monkeypatch.setattr(chain, 'ROOT', root)
    monkeypatch.setattr(chain, 'ARCHIVES', {'round01': commit, 'declaration': commit})
    first_prepared, first_summary = native(root, code, 'base', {'token': 'first'})
    first = root / 'round01'
    p = put(first / 'prepared.json', {
        'version': chain.CHAIN, 'cases': ['sample'], 'algorithm': [code],
        'precedence': ['base'], 'components': [{'name': 'base', 'source': first_prepared,
                                               'prepared': first_prepared}]})
    put(first / 'seal.json', p)
    put(first / 'summary.json', {'version': chain.CHAIN, 'denominator': 1,
        'decisions': [{'case': 'sample', 'branch': 'base', 'alert': {'token': 'first'}}],
        'component_summaries': {'base': first_summary}, 'replayed_native_executions': 2,
        'independent_audit': {'path': str(root / 'do-not-read-audit.json'), 'sha256': '0' * 64}})
    native(root, code, 'declaration', {'token': 'second'})
    roots = {'round01': first, 'declaration': root / 'declaration'}
    return [{'name': name, 'commit': commit,
             **{key: chain.frozen(path / (key + '.json')) for key in ('prepared', 'summary', 'seal')}}
            for name, path in roots.items()]


def test_archived_code_survives_current_file_change(archive):
    root, commit, receipt = archive
    Path(receipt['path']).write_text('changed current code\n')
    verifier = chain.Verifier(root, commit)
    verifier.receipt(receipt, 'executed_code')
    assert verifier.code == [{'path': 'runner.py', 'sha256': receipt['sha256'], 'commit': commit}]


def test_archive_must_match_same_path_not_current_or_another_file(archive):
    root, commit, receipt = archive
    new = root / 'other.py'
    new.write_bytes(Path(receipt['path']).read_bytes())
    with pytest.raises(ValueError, match='absent at specified archive'):
        chain.Verifier(root, commit).receipt(chain.frozen(new), 'executed_code')
    Path(receipt['path']).write_text('new version\n')
    with pytest.raises(ValueError, match='Archive SHA mismatch'):
        chain.Verifier(root, commit).receipt(chain.frozen(receipt['path']), 'executed_code')


def test_receipt_requires_explicit_role(archive):
    root, commit, receipt = archive
    with pytest.raises(ValueError, match='receipt role'):
        chain.Verifier(root, commit).receipt(receipt, None)


def test_data_cohort_does_not_expand_obsolete_algorithm(archive):
    root, commit, code = archive
    prepared, summary = native(root, code)
    verifier = chain.Verifier(root, commit)
    result = verifier.execution(prepared, summary)
    assert result['cases'] == ['sample']
    assert len(verifier.code) == 1
    assert verifier.cohorts[0]['role'] == 'source_snapshot_list_data_only'


def test_one_byte_cohort_change_is_rejected(archive):
    root, commit, code = archive
    prepared, summary = native(root, code)
    with (root / 'cohort.json').open('a') as stream:
        stream.write(' ')
    with pytest.raises(ValueError, match='Changed data artifact'):
        chain.Verifier(root, commit).execution(prepared, summary)


@pytest.mark.parametrize('role', [None, '', 'Trust this source'])
def test_missing_or_unknown_cohort_role_rejected(archive, role):
    root, commit, code = archive
    prepared, summary = native(root, code)
    protocol = chain.read(prepared['path'])
    protocol['source_cohort_use'] = role
    prepared = put(prepared['path'], protocol)
    with pytest.raises(ValueError, match='data-role declaration'):
        chain.Verifier(root, commit).execution(prepared, summary)


def test_nested_noncode_input_change_is_rejected(archive):
    root, commit, code = archive
    prepared, summary = native(root, code)
    (root / 'original' / 'issue.md').write_text('changed')
    with pytest.raises(ValueError, match='Changed data artifact'):
        chain.Verifier(root, commit).execution(prepared, summary)


def test_complete_summary_and_denominator_required(archive):
    root, commit, code = archive
    prepared, summary = native(root, code)
    value = chain.read(summary['path'])
    value['results'] = []
    summary = put(summary['path'], value)
    with pytest.raises(ValueError, match='complete declared cohort'):
        chain.Verifier(root, commit).execution(prepared, summary)


def test_different_cohort_source_hashes_rejected(archive, monkeypatch):
    entries = components(archive, monkeypatch)
    second = entries[1]
    protocol = chain.read(second['prepared']['path'])
    alternative = put(archive[0] / 'different-selection.json', {'different': True})
    protocol['cases'][0]['inputs']['selection.json'] = alternative
    second['prepared'] = put(second['prepared']['path'], protocol)
    second['seal'] = put(second['seal']['path'], second['prepared'])
    with pytest.raises(ValueError, match='different source cohorts or hashes'):
        chain.load_components(entries)


def test_fixed_precedence_uses_alerts_without_audit_files(archive, monkeypatch):
    entries = components(archive, monkeypatch)
    loaded, reports, sources = chain.load_components(entries)
    result = chain.compose(sources, loaded)
    assert result[0]['alert'] == {'token': 'first'}
    assert result[0]['branch'] == 'round01'
    assert reports['round01']['excluded_audit_fields'] == ['independent_audit']
    with pytest.raises(ValueError, match='fixed round01 then declaration'):
        chain.load_components(list(reversed(entries)))


def test_fallback_is_uniform_and_does_not_replace_an_alert():
    loaded = {'round01': {'index': {'a': {'alert': {'token': 'old'}}, 'b': {'alert': None}}},
              'declaration': {'index': {'a': {'alert': {'token': 'new'}}, 'b': {'alert': {'token': 'new'}}}}}
    result = chain.compose(['b', 'a'], loaded)
    assert [(r['case'], r['branch']) for r in result] == [('a', 'round01'), ('b', 'declaration')]


def test_prepare_and_replay_never_spawn_subject_or_provider(archive, monkeypatch):
    components(archive, monkeypatch)
    real_check_output = subprocess.check_output
    def git_only(args, **kwargs):
        assert args[0] == 'git'
        return real_check_output(args, **kwargs)
    monkeypatch.setattr(chain.subprocess, 'check_output', git_only)
    root = archive[0]
    output = root / 'combined'
    chain.prepare(SimpleNamespace(round01=root / 'round01', declaration=root / 'declaration', output=output))
    outcome = chain.run(SimpleNamespace(input=output))
    assert outcome == {'alerts': 1, 'denominator': 1, 'fresh_native_executions': 0,
                       'fresh_provider_calls': 0, 'retrospective': True}
    first = chain.read(output / 'summary.json')
    assert chain.run(SimpleNamespace(input=output)) == first
    assert first['independent_audit_complete'] is False
