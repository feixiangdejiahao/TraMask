"""Check source-window preservation and evidence scoring used by the pilot."""
from pathlib import Path
import importlib.util

from eviweave.issue_filter import history_records, merge_rankings, rank_lexical, selection_prompt


def load_analysis_script():
    path = Path(__file__).resolve().parents[1] / 'scripts/analyze_issue_filter_pilot.py'
    spec = importlib.util.spec_from_file_location('issue_filter_analysis', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_window_sources_are_complete_and_do_not_add_issue_or_manual_labels():
    text = 'first line\nsecond line\nthird line\n'
    action = {'id': 's3_c0', 'step_id': 3, 'command': "cat > test_x.py <<'PY'\nassert True\nPY",
              'expected': {'output': text}}
    trajectory = {'steps': [{'step_id': 2, 'source': 'user', 'message': 'ISSUE_ONLY'},
                            {'step_id': 3, 'source': 'agent', 'message': text, 'reasoning_content': 'a hypothesis'}]}
    value = history_records([action], trajectory, window_chars=20)
    assert all('ISSUE_ONLY' not in source['text'] for source in value['sources'])
    for source in value['sources']:
        pieces = sorted((origin['start'], origin['end'], record['text'])
                        for record in value['records'] for origin in record['origins']
                        if origin['source_id'] == source['source_id'])
        assert ''.join(piece[2] for piece in pieces) == source['text']
    prompt = selection_prompt('public issue', value['records'])
    assert 'a hypothesis' in prompt and 'assert True' in prompt


def test_lexical_retrieval_uses_api_words_and_keeps_full_rankings():
    records = [{'id': 'R1', 'text': 'git status branch commit'},
               {'id': 'R2', 'text': 'response.is_closed after stream decoding error'},
               {'id': 'R3', 'text': 'parse a normal multipart response'}]
    ranked = rank_lexical(records, 'close streaming response is_closed')
    assert ranked[0] == 'R2' and set(ranked) == {'R1', 'R2', 'R3'}
    assert merge_rankings([['a', 'b', 'c'], ['a', 'c', 'b']], 2) == ['a', 'b']


def test_a_multiwindow_source_fragment_needs_all_its_windows():
    analysis = load_analysis_script()
    anchors = [{'anchor_id': 'A1', 'alternatives': [{'record_ids': ['R1', 'R2'], 'cited_action': True}]},
               {'anchor_id': 'A2', 'alternatives': [{'record_ids': ['R3'], 'cited_action': False},
                                                  {'record_ids': ['R4'], 'cited_action': True}]}]
    assert analysis.retained_anchors(['R1'], anchors) == []
    assert analysis.retained_anchors(['R1', 'R2', 'R3'], anchors) == ['A1', 'A2']
    assert analysis.retained_anchors(['R3'], anchors, cited_only=True) == []


def test_no_C_ablation_uses_issue_patch_and_records_without_a_guide():
    records = [{'id': 'R0001', 'text': 'historical source',
                'origins': [{'kind': 'stdout', 'source_id': 's1_c0:output'}]}]
    prompt = selection_prompt('original issue', records, patch='submitted patch')
    assert 'original issue' in prompt and 'submitted patch' in prompt and 'historical source' in prompt
    assert 'ISSUE GUIDE:' not in prompt and 'an issue-derived guide' not in prompt
