"""Paired source-evidence ablation on outcome-blind samples of a frozen campaign.

Reuse the main arm's fresh response only as the treatment observation. New
control requests differ solely by removal of dependency_evidence from the
prompt. They cannot feed back into candidate generation or the main campaign.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search.checkpoint import digest, read, write, start


def without_dependency_evidence(request):
    clone = copy.deepcopy(request)
    payload = json.loads(clone['prompt'])
    for candidate in payload['candidates']:
        if 'dependency_evidence' not in candidate:
            raise ValueError('Treatment request lacks dependency evidence')
        del candidate['dependency_evidence']
    clone['prompt'] = json.dumps(payload, ensure_ascii=False)
    clone['id'] = hashlib.sha256(clone['prompt'].encode()).hexdigest()
    clone['context_ablation'] = dict(treatment_request_id=request['id'],
        intervention='remove dependency_evidence only; all other prompt fields and system unchanged')
    return clone


def sample_requests(directory, limit):
    """Hash order uses candidate source IDs, never provider outcomes."""
    rows = []
    for path in sorted(directory.glob('request_[0-9][0-9][0-9].json')):
        request = read(path)
        if len(request['offered']) != 1:
            raise ValueError('Paired ablation requires singleton requests')
        candidate = next(iter(request['offered'].values()))['candidate']
        rows.append((hashlib.sha256(candidate['id'].encode()).hexdigest(), path, request))
    return [(path, request) for _, path, request in sorted(rows)[:limit]]


def run(args):
    configuration = read(args.campaign/'configuration.json')
    if configuration.get('oracle_mode') != 'fresh' or configuration.get('oracle_evidence') != 'dependency':
        raise ValueError('Treatment must be a fresh dependency-evidence campaign')
    if not 1 <= args.per_case <= 2:
        raise ValueError('This preregistered experiment permits one or two requests per case')
    paths = [Path(__file__), args.frozen_root/'scripts/relation_search_semantics.py',
             args.frozen_root/'relation_search/oracle.py', args.frozen_root/'relational_gap/provider.py']
    protocol = dict(stage='dependency_context_ablation', cases=configuration['cases'], round=0,
        campaign=str(args.campaign.resolve()), configuration_sha256=digest(args.campaign/'configuration.json'),
        sample='first K singleton requests in SHA256(candidate.id) order; no outcome selection',
        per_case=args.per_case, max_new_requests=args.per_case*len(configuration['cases']),
        intervention='remove only dependency_evidence field; retain system, issue, all tests/assertions/edits/imports/settings',
        historical_oracle_reused=False, feedback_into_main_campaign=False,
        code_sha256={str(path.resolve()):digest(path) for path in paths})
    start(args.output, protocol)
    remaining = set(configuration['cases'])
    while remaining:
        progressed = False
        for case in configuration['cases']:
            if case not in remaining:
                continue
            destination = args.output/case
            if (destination/'result.json').exists():
                result = read(destination/'result.json')
                for item in result['pairs']:
                    if digest(item['treatment_request']) != item['treatment_request_sha256']:
                        raise ValueError('Treatment request changed')
                remaining.remove(case)
                continue
            semantic = args.campaign/case/'round_000/semantic'
            if not (semantic/'semantic_result.json').exists():
                # Cases exhausted before an oracle round have no treatment.
                completed = read(args.campaign/'campaign.json') if (args.campaign/'campaign.json').exists() else []
                row = next((row for row in completed if row['case'] == case), None)
                if row and row['stopped_reason'] == 'exhausted' and not row['rounds']:
                    write(destination/'result.json', dict(case=case,status='no_treatment_requests',pairs=[]))
                    remaining.remove(case)
                continue
            pairs = []
            for index, (path, request) in enumerate(sample_requests(semantic/'requests', args.per_case)):
                local_request = destination/'requests'/f'request_{index:03d}.json'
                control = without_dependency_evidence(request)
                if local_request.exists() and read(local_request) != control:
                    raise ValueError('Ablation request changed')
                write(local_request, control)
                completion = destination/'completions'/local_request.stem
                if completion.exists():
                    manifest = read(completion/'manifest.json')
                    if manifest['status'] in {'prepared','dispatching'}:
                        raise ValueError('An in-flight control attempt requires process audit; no restart')
                else:
                    invocation = [str(args.frozen_root/'.venv/bin/python'),
                                  str(args.frozen_root/'scripts/relation_search_semantics.py'), 'complete',
                                  '--input', str(local_request.resolve()), '--output', str(completion.resolve())]
                    result = subprocess.run(invocation, cwd=args.frozen_root, capture_output=True, text=True)
                    (completion/'driver.stdout').write_text(result.stdout)
                    (completion/'driver.stderr').write_text(result.stderr)
                    if result.returncode:
                        raise RuntimeError('Frozen control completion driver failed; inspect preserved output')
                pairs.append(dict(treatment_request=str(path.resolve()), treatment_request_sha256=digest(path),
                    treatment_completion=str((semantic/'completions'/path.stem).resolve()),
                    control_request=str(local_request.resolve()), control_request_sha256=digest(local_request),
                    control_completion=str(completion.resolve()),
                    candidate_id=next(iter(request['offered'].values()))['candidate']['id']))
            record = dict(case=case,status='complete',pairs=pairs)
            write(destination/'result.json', record)
            print(json.dumps(dict(case=case, completed_pairs=len(pairs))), flush=True)
            remaining.remove(case)
            progressed = True
        if not progressed and remaining:
            time.sleep(10)
    write(args.output/'result.json', dict(status='complete', cases=len(configuration['cases']),
        pairs=sum(len(read(args.output/case/'result.json')['pairs']) for case in configuration['cases'])))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--campaign',type=Path,required=True)
    parser.add_argument('--frozen-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--per-case',type=int,default=2)
    run(parser.parse_args())
