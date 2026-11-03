"""Step B uses real A-shaped files and retains recoverable source content."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from eviweave.artifacts import read_json, resolve_references, write_json
from eviweave.blobs import BlobStore
from eviweave.history import history_records, read_context
from eviweave.issue_filter import rank_lexical


@pytest.fixture
def collected(tmp_path):
    replay = tmp_path / 'replay'
    tests = replay / 'tests'
    blobs = tests / 'blobs'
    BlobStore(blobs).create()

    def version(path, raw):
        digest = hashlib.sha256(raw).hexdigest()
        BlobStore(blobs).put(raw)
        return {'path': path, 'sha256': digest}

    old = 'def test_close():\r\n    assert response.is_closed\r\n'
    new = 'def test_close():\n    assert response.was_consumed\n'
    stock = "keywordCase: 'upper'\nexpect(sql).toEqual('AGGREGATE')\n"
    literal = 'def test_deleted():\n    assert value == 7\n'
    versions = [version('/app/test_close.py', old.encode()),
                version('/app/test_close.py', new.encode()),
                version('/app/test_stock.ts', stock.encode()),
                version('/app/tests/data.bin', b'\xff\x00binary fixture')]
    orphan = version('/tmp/test_deleted.py', literal.encode()) | {'action_id': 's2_c0'}
    manifest = tests / 'manifest.json'
    write_json(manifest, {'replay': str(replay), 'source_versions': versions,
                         'unobserved_source_candidates': [orphan]})
    write_json(replay / 'plan.json', {'action_ids': ['s1_c0', 's2_c0']})
    write_json(replay / 'inputs/trajectory.json', {'steps': [
        {'reasoning_content': 'REASONING_SENTINEL', 'message': 'PROGRESS_SENTINEL'}]})
    for action, command, expected, output in [
        ('s1_c0', 'cat /usr/local/go/src/embed/embed.go',
         {'output': 'return int64(len(f.data))'}, b'return int64(len(f.data))'),
        ('s2_c0', 'python /tmp/test_deleted.py',
         {'output_head': 'original failure header', 'output_tail': 'original failure footer'}, b'replayed failure')]:
        directory = replay / 'runtime/calls' / action
        directory.mkdir(parents=True)
        (directory / 'command.sh').write_text(command)
        write_json(directory / 'archived_expected.json', expected)
        (directory / 'output.bin').write_bytes(output)
    extra = replay / 'runtime/calls/UNEXECUTED'
    extra.mkdir()
    (extra / 'command.sh').write_text('UNEXECUTED_SENTINEL')
    return manifest, old, new, stock, literal


def test_files_versions_unobserved_code_and_all_tool_outputs_are_searchable(collected):
    manifest, old, new, stock, literal = collected
    records = history_records(manifest)
    texts = {r['text'] for r in records}
    assert {old, new, stock, literal, 'original failure header', 'original failure footer',
            'replayed failure', 'return int64(len(f.data))'} <= texts
    assert len(records) == len({r['id'] for r in records}) == len({(r['source'], r['text']) for r in records})
    assert all(set(r) == {'id', 'text', 'source'} for r in records)
    assert not any('SENTINEL' in r['text'] for r in records)
    assert all(r['text'] in read_context(r['source']) for r in records)
    assert next(r for r in records if r['text'] == old)['source'] != next(
        r for r in records if r['text'] == new)['source']
    by_id = {r['id']: r for r in records}
    best = by_id[rank_lexical(records, 'keywordCase upper AGGREGATE')[0]]
    assert best['text'] == stock and read_context(best['source']) == stock


def test_equal_text_keeps_every_distinct_source_context(collected):
    manifest, *_ = collected
    records = history_records(manifest)
    copies = [r for r in records if r['text'] == 'return int64(len(f.data))']
    assert len(copies) == 2
    assert len({r['source'] for r in copies}) == 2
    assert {r['source'].rsplit('/', 1)[-1] for r in copies} == {'output', 'output.bin'}
    assert all(read_context(r['source']) == r['text'] for r in copies)


def test_unmatched_and_unparseable_material_stays_in_the_full_ranking(collected):
    manifest, *_ = collected
    replay = Path(read_json(manifest)['replay'])
    (replay / 'runtime/calls/s2_c0/output.bin').write_text('def broken(:\n    unknown()\n')
    records = history_records(manifest)
    ranked = rank_lexical(records, 'iter_multipart')
    assert set(ranked) == {r['id'] for r in records}
    assert any(r['text'] == 'def broken(:\n    unknown()\n' for r in records)


def test_window_keeps_a_reference_to_full_context_and_preserves_line_endings(collected):
    manifest, old, *_ = collected
    records = history_records(manifest, window_chars=24)
    pieces = [r for r in records if r['source'].endswith('#/source_versions/0')]
    assert len(pieces) > 1
    assert all(read_context(r['source']) == old for r in pieces)
    assert ''.join(r['text'] for r in pieces) == old


def test_binary_fixture_is_preserved_in_A_and_not_indexed_as_text(collected):
    manifest, *_ = collected
    records = history_records(manifest)
    assert not any(r['source'].endswith('#/source_versions/3') for r in records)
    entry = read_json(manifest)['source_versions'][3]
    assert BlobStore(manifest.parent / 'blobs').read(entry['sha256']) == b'\xff\x00binary fixture'


def test_missing_replay_artifact_is_a_program_error(collected):
    manifest, *_ = collected
    replay = Path(read_json(manifest)['replay'])
    (replay / 'runtime/calls/s2_c0/output.bin').unlink()
    with pytest.raises(FileNotFoundError):
        history_records(manifest)


def test_history_cli_exports_records_with_working_source_references(collected, tmp_path):
    manifest, *_ = collected
    output = tmp_path / 'history.json'
    subprocess.run([sys.executable, '-m', 'eviweave', 'history', '--manifest', str(manifest),
                    '--out', str(output)], cwd=Path(__file__).resolve().parents[1] / 'src',
                   check=True, capture_output=True)
    records = json.loads(output.read_text())
    assert resolve_references(records, output.parent) == history_records(manifest)
    assert all(r['text'] in read_context(r['source'],base=output.parent) for r in records)
