"""First-dispatch malformed JSON schemas cannot abort an entire campaign."""
import json

import pytest

from relation_search.checkpoint import read, write
from scripts.run_relation_campaign import semantic_batch
from test_campaign_batch_recovery import prepared


@pytest.mark.parametrize('payload', [
    [], None, 'not an object', {'revisions': [None]}, {'revisions': [1]},
    {'revisions': [{'candidate': 'C0', 'basis': 'Source contract', 'updates': [None]}]},
])
def test_complete_records_invalid_schema_without_split_or_losing_candidates(tmp_path, monkeypatch, payload):
    source, args = prepared(tmp_path)
    calls = []

    def dispatch(request, output, *, root):
        calls.append(request)
        output.mkdir(parents=True, exist_ok=False)
        manifest = dict(status='complete', request_id=request['id'], external_model_calls=1,
                        finish_reason='stop')
        write(output/'manifest.json', manifest)
        (output/'completion.txt').write_text(json.dumps(payload))
        return manifest

    # Exercise production complete() and its first-dispatch validation, rather
    # than replacing complete() and testing only the coordinator's resume path.
    monkeypatch.setattr('relational_gap.provider.dispatch', dispatch)
    output = tmp_path/'semantic'
    result = semantic_batch(source, output, args, [])
    assert len(calls) == 1 and len(calls[0]['offered']) == 2
    assert result['provider_calls'] == 1 and result['recovery_calls'] == 0
    assert result['revised_count'] == 0
    assert read(output/'candidates.json')['candidates'] == read(source/'candidates.json')['candidates']
    validation = read(output/'completions/request_000/validation.json')
    assert validation == {'revisions': [], 'decisions': [], 'error': 'AttributeError'}
    assert read(output/'completions/request_000/manifest.json')['status'] == 'complete'
    assert json.loads((output/'completions/request_000/completion.txt').read_text()) == payload
    recovery = read(output/'recovery/request_000.json')
    assert not recovery['eligible'] and recovery['requests'] == []
    assert recovery['reason'] == 'completed_parseable_json'
    assert semantic_batch(source, output, args, []) == result
    assert len(calls) == 1
