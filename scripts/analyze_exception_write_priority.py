"""Evaluate a source-only priority over frozen Python candidate pools."""
from pathlib import Path
import argparse
from datetime import datetime, timezone
import hashlib
import json
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from prototypes.exception_write_priority import prioritize


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--census', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(exist_ok=False)
    cases = []
    inputs = {}
    for folder in sorted(args.inventory.iterdir()):
        source = folder/'corpus.json'
        census = args.census/(folder.name+'.json')
        if source.exists() and census.exists() and json.loads(source.read_text())['language'] == 'python':
            cases.append(folder.name)
            inputs[folder.name] = {str(p.resolve()): sha(p) for p in [source, folder/'source_pool.json', census]}
    code = [Path(__file__).resolve(), ROOT/'prototypes/exception_write_priority.py',
            ROOT/'prototypes/assertion_write_origin.py']
    protocol = dict(cases=cases, inputs=inputs, created_at=datetime.now(timezone.utc).isoformat(),
                    code_sha256={str(p.relative_to(ROOT)): sha(p) for p in code},
                    target_labels=False, oracle_cache=False, provider_calls=0, subject_executions=0,
                    ordering='Stable boolean partition of each frozen source_pool candidates array. No removed candidate.',
                    hypothesis='A new exception catcher covers an operation on the object read by preserved q; a source path from that operation to a distinct field writer has a possible exceptional bypass.')
    (args.output/'protocol.json').write_text(json.dumps(protocol, indent=2)+'\n')
    for path in code:
        shutil.copyfile(path, args.output/path.name)
    summaries = []
    for case in cases:
        started = time.monotonic()
        corpus = json.loads((args.inventory/case/'corpus.json').read_text())
        pool = json.loads((args.inventory/case/'source_pool.json').read_text())['candidates']
        census = json.loads((args.census/(case+'.json')).read_text())
        for path, checksum in census['source_sha256'].items():
            if hashlib.sha256(corpus['sources'][path]['code'].encode()).hexdigest() != checksum:
                raise ValueError('Census and candidate sources differ: '+case+'/'+path)
        outcome = prioritize(corpus, pool, census)
        outcome.update(case=case, seconds=time.monotonic()-started, protocol_sha256=sha(args.output/'protocol.json'))
        path = args.output/(case+'.json')
        path.write_text(json.dumps(outcome, indent=2)+'\n')
        summary = {k:v for k,v in outcome.items() if k != 'ranking'}
        summary['output_sha256'] = sha(path)
        summaries.append(summary)
        print(json.dumps(summary), flush=True)
    (args.output/'summary.json').write_text(json.dumps(summaries, indent=2)+'\n')


if __name__ == '__main__':
    main()
