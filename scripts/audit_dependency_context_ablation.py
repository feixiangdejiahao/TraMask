"""Read-only evaluator for the frozen dependency-context paired experiment.

No provider calls, generator imports, candidate selection, or semantic truth
inference. Semantic reviews are supplied separately after inspecting full tests.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def request_candidate(request):
    assert len(request['offered']) == 1
    return next(iter(request['offered'].values()))['candidate']['id']


def verify_pair(pair):
    treatment = read(pair['treatment_request'])
    control = read(pair['control_request'])
    assert sha(pair['treatment_request']) == pair['treatment_request_sha256']
    assert sha(pair['control_request']) == pair['control_request_sha256']
    assert request_candidate(treatment) == request_candidate(control) == pair['candidate_id']
    assert treatment['offered'] == control['offered']
    left, right = json.loads(treatment['prompt']), json.loads(control['prompt'])
    expected = copy.deepcopy(left)
    for candidate in expected['candidates']:
        assert 'dependency_evidence' in candidate
        del candidate['dependency_evidence']
    assert expected == right, 'Intervention changed more than dependency evidence'
    assert treatment['system'] == control['system']
    arms, wires = {}, {}
    for arm, prepared in [('treatment', treatment), ('control', control)]:
        folder = Path(pair[arm + '_completion'])
        manifest = read(folder / 'manifest.json')
        wire = read(folder / 'request.json')
        assert sha(folder / 'request.json') == manifest['request_sha256']
        assert sha(folder / 'response.body') == manifest['response_sha256']
        assert wire['model'] == manifest['model'] == 'deepseek-v4-flash'
        assert wire['messages'] == [dict(role='system', content=prepared['system']),
                                    dict(role='user', content=prepared['prompt'])]
        assert manifest['external_model_calls'] == 1
        response = read(folder / 'response.json')
        assert response == read(folder / 'response.body')
        validation = read(folder / 'validation.json')
        wires[arm] = {k: v for k, v in wire.items() if k != 'messages'}
        arms[arm] = dict(finish_reason=manifest.get('finish_reason'),
                         seconds=manifest.get('seconds'), usage=manifest.get('usage'),
                         revised_count=len(validation['revisions']),
                         decisions=validation['decisions'],
                         answer=response['choices'][0]['message'].get('content'),
                         manifest_sha256=sha(folder / 'manifest.json'),
                         response_sha256=sha(folder / 'response.json'),
                         prompt_bytes=len(prepared['prompt'].encode()))
    assert wires['treatment'] == wires['control'], 'Model settings differ'
    return dict(candidate_id=pair['candidate_id'], arms=arms,
                verified_single_field_wire_intervention=True,
                treatment_request_sha256=pair['treatment_request_sha256'],
                control_request_sha256=pair['control_request_sha256'])


def audit(root):
    root = Path(root)
    stage = read(root / 'stage.json')
    for name, value in stage['code_sha256'].items():
        assert sha(name) == value, ('Code changed', name)
    campaign = Path(stage['campaign'])
    assert sha(campaign / 'configuration.json') == stage['configuration_sha256']
    assert stage['feedback_into_main_campaign'] is False
    rows = []
    for case in stage['cases']:
        result_path = root / case / 'result.json'
        if not result_path.exists():
            continue
        result = read(result_path)
        candidates = []
        for path in (campaign / case / 'round_000/semantic/requests').glob('request_[0-9][0-9][0-9].json'):
            cid = request_candidate(read(path))
            candidates.append((hashlib.sha256(cid.encode()).hexdigest(), cid, path.resolve()))
        chosen = sorted(candidates)[:stage['per_case']]
        assert [(p['candidate_id'], Path(p['treatment_request']).resolve()) for p in result['pairs']] == [(cid, p) for _, cid, p in chosen]
        for index, pair in enumerate(result['pairs']):
            rows.append(dict(case=case, index=index, **verify_pair(pair)))
    counts = {}
    for arm in ['treatment', 'control']:
        counts[arm] = dict(finish_reasons=dict(Counter(r['arms'][arm]['finish_reason'] for r in rows)),
                          structurally_accepted=sum(r['arms'][arm]['revised_count'] for r in rows),
                          seconds=sum(r['arms'][arm]['seconds'] for r in rows),
                          prompt_tokens=sum(r['arms'][arm]['usage'].get('prompt_tokens', 0) for r in rows),
                          completion_tokens=sum(r['arms'][arm]['usage'].get('completion_tokens', 0) for r in rows))
    return dict(stage='independent_dependency_ablation_audit',
                stage_sha256=sha(root / 'stage.json'),
                audit_code_sha256=sha(__file__),
                completed_cases=len({r['case'] for r in rows}),
                paired_requests=len(rows), max_pairs=stage['max_new_requests'],
                counts=counts, pairs=rows,
                semantic_correctness='not inferred from acceptance; independent full-program review required',
                main_campaign_credit=0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = audit(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({k: v for k, v in output.items() if k != 'pairs'}, ensure_ascii=False))
