"""Static strategy comparison over every frozen source-pool candidate.

No issue text, target labels, oracle cache, subject execution, or provider input.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from prototypes.numeric_relation_buckets import refine_selections

CASES=tuple(f'P{i}' for i in range(1,8))+tuple(f'N{i:02d}' for i in range(1,11))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--inventory',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    if args.output.exists():
        raise ValueError('Use a new output directory; static results are immutable')
    args.output.mkdir(parents=True)
    code=[Path(__file__).resolve(),ROOT/'prototypes/numeric_relation_buckets.py',
          ROOT/'relation_search/semantic_selection.py',ROOT/'anchor_retrieval/syntax.py']
    protocol=dict(created_utc=datetime.now(timezone.utc).isoformat(),cases=list(CASES),budget=16,
        arms=['baseline','delta','context'],inventory=str(args.inventory.resolve()),
        inputs={case:{name:digest(args.inventory/case/name) for name in ('source_pool.json','corpus.json')} for case in CASES},
        code_sha256={str(path):digest(path) for path in code},entrypoint=[sys.executable,*sys.argv],
        scheduling='Identical isolated semantic_selection.select implementation; only shape function gains numeric relation signatures. Material and representative priorities unchanged.',
        target_inputs=False,provider_calls=0,subject_executions=0,
        delta='Mathematical order of replacement against original whole numeric AST literal.',
        context='Delta plus same-call literal coarguments and supported Python direct local assignment-to-comparison links.',
        limits='Input direction/coarguments are syntax. Python local def-use does not prove SUT dependency, dynamic feasibility, oracle correctness or bug detection.')
    (args.output/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
    for path in code:
        shutil.copyfile(path,args.output/path.name)
    selector=args.output/'semantic_selection.py'
    summary={}
    for case in CASES:
        start=time.monotonic()
        corpus=json.loads((args.inventory/case/'corpus.json').read_text())
        candidates=json.loads((args.inventory/case/'source_pool.json').read_text())['candidates']
        result=refine_selections(corpus,candidates,selector,16)
        counts=Counter()
        for rows in result['evidence'].values():
            if rows:counts['candidates_with_numeric_direction']+=1
            kinds={r['kind'] for row in rows for r in row['context']}
            counts.update(kinds)
        selected={arm:{row['id'] for row in data['ranking'][:16]} for arm,data in result['selections'].items()}
        metadata=dict(input_count=len(candidates),relation_support=dict(counts),
            shape_counts={arm:data['shape_count'] for arm,data in result['selections'].items()},
            first16_changed_from_baseline={arm:len(ids-selected['baseline']) for arm,ids in selected.items() if arm!='baseline'},
            all_ids_preserved=all({row['id'] for row in data['ranking']}=={c['id'] for c in candidates} for data in result['selections'].values()),
            elapsed_seconds=round(time.monotonic()-start,3))
        result.update(case=case,summary=metadata,protocol_sha256=digest(args.output/'protocol.json'))
        path=args.output/(case+'.json');path.write_text(json.dumps(result,indent=2)+'\n')
        summary[case]={**metadata,'output_sha256':digest(path)}
        print(json.dumps(dict(case=case,**metadata)),flush=True)
    (args.output/'summary.json').write_text(json.dumps(dict(protocol_sha256=digest(args.output/'protocol.json'),cases=summary),indent=2)+'\n')


if __name__=='__main__':
    main()
