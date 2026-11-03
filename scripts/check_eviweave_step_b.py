#!/usr/bin/env python3
"""Check Step B against real A artifacts and the frozen retrieval pilot."""
from pathlib import Path
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from eviweave.artifacts import read_json, write_json
from eviweave.history import history_records, read_context, window_spans
from eviweave.issue_filter import history_records as pilot_history_records, rank_lexical
from eviweave.replay.trajectory import resolve_submission_actions

OUT = ROOT / 'results/behavioral_masking/20261102_recall_preservation_n88_r01/step_b'
A = ROOT / 'results/behavioral_masking/20261101_step_a_simplification_r02'
PILOT = ROOT / 'results/behavioral_masking/20261031_issue_history_filter_n16_r02'


def check_materials(manifest_path):
    records = history_records(manifest_path)
    assert all(set(r) == {'id', 'text', 'source'} for r in records)
    assert len(records) == len({r['id'] for r in records}) == len({(r['source'], r['text']) for r in records})
    contexts = {source: read_context(source) for source in {r['source'] for r in records}}
    assert all(r['text'] in contexts[r['source']] for r in records)
    manifest = read_json(manifest_path)
    texts = {r['text'] for r in records}
    indexed_versions, non_utf8 = 0, 0
    for entry in manifest['source_versions']:
        try:
            text = (manifest_path.parent / 'blobs' / entry['sha256']).read_bytes().decode('utf-8')
        except UnicodeDecodeError:
            non_utf8 += 1
            continue
        assert all(not text[start:end].strip() or text[start:end] in texts
                   for start, end in window_spans(text, 6000))
        indexed_versions += 1
    by_id = {r['id']: r for r in records}
    ranking = rank_lexical(records, 'iter_multipart IteratorByteStream is_closed DecodingError')
    assert 'iter_multipart' in by_id[ranking[0]]['text']
    required_tests = ('def test_multipart_response_malformed_framing',
                      'def test_multipart_response_streaming_consumes_and_closes')
    assert all(any(name in r['text'] for r in records) for name in required_tests)
    anchors = read_json(PILOT / 'evaluation/resolved_anchors/S030.json')
    normalized = [re.sub(r'\s+', '', r['text']) for r in records]
    recovered = [a['anchor_id'] for a in anchors if any(re.sub(r'\s+', '', a['code']) in text for text in normalized)]
    assert len(recovered) == len(anchors) == 4
    return records, {'manifest': str(manifest_path), 'records': len(records),
                     'characters': sum(len(r['text']) for r in records),
                     'source_references': len(contexts), 'indexed_file_versions': indexed_versions,
                     'non_utf8_file_versions': non_utf8,
                     'all_record_contexts_recoverable': True, 'all_text_file_windows_present': True,
                     'manual_S030_quotes_present': recovered, 'top_lexical_ids': ranking[:4]}


def main():
    OUT.mkdir(parents=True)
    checked = []
    for name, relative in [('full_history', 'recollected/S030/tests/manifest.json'),
                           ('live_checkpoint', 'live_collect/tests/manifest.json')]:
        records, result = check_materials(A / relative)
        write_json(OUT / (name + '.json'), records)
        checked.append(result)
    cohort = read_json(ROOT / 'results/behavioral_masking/20261026_fragment_reuse_n88_r01/cases.json')['cases']
    source_by_id = {c['screen_id']: Path(c['input_directory']) for c in cohort}
    pilot_records = 0
    for case in read_json(PILOT / 'cases.json'):
        sid = case['case_id']
        trajectory = read_json(source_by_id[sid] / 'trajectory.json')
        actions, _ = resolve_submission_actions(trajectory)
        corpus = pilot_history_records(actions, trajectory)
        assert corpus['records'] == read_json(PILOT / 'cases' / sid / 'records.json')
        assert corpus['sources'] == read_json(PILOT / 'cases' / sid / 'sources.json')
        pilot_records += len(corpus['records'])
    result = {'step_b': checked, 'record_fields': ['id', 'text', 'source'],
              'frozen_pilot_cases_equal': 16, 'frozen_pilot_records_equal': pilot_records,
              'llm_calls': 0, 'docker_replays': 0,
              'scope': 'Material construction, source recovery and lexical consumption; no new generated-test or bug-detection evaluation.'}
    write_json(OUT / 'verification.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
