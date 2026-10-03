"""Freeze a source-test-first ranking without labels or provider calls."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search.seed_frontier import POLICY, policy_sha, rank


def prepare(source, output):
    original = json.loads((source/'manifest.json').read_text())
    output.mkdir(parents=True, exist_ok=False)
    cases = []
    for entry in original['cases']:
        path = source/(entry['case']+'.json')
        prior = json.loads(path.read_text())
        updated = copy.deepcopy(prior)
        updated['ranking'] = rank(prior['ranking'])
        updated['policy_sha256'] = policy_sha()
        updated['prior_ranking'] = dict(path=str(path.resolve()), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        (output/path.name).write_text(json.dumps(updated,ensure_ascii=False,indent=2)+'\n')
        cases.append(dict(case=entry['case'], candidates=len(updated['ranking'])))
    manifest = dict(version=POLICY['version'], cases=cases,
        protocol=dict(policy=POLICY, policy_sha256=policy_sha(),
                      source_inventory=original['protocol']['source_inventory']),
        prior_frontier=dict(path=str((source/'manifest.json').resolve()),
                            sha256=hashlib.sha256((source/'manifest.json').read_bytes()).hexdigest()),
        provider_calls=0, native_executions=0, evaluation_labels_used=False)
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return dict(cases=len(cases), ranked_candidates=sum(row['candidates'] for row in cases))


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(prepare(args.source,args.output)))
