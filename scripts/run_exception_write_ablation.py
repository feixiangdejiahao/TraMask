"""Paired fixed-budget execution of the optional source writer priority.

One round, eight proposals, all Python cases with the frozen source census.
The same physical-edit scheduler follows both input orders. No oracle model,
historical semantic cache, target labels, or new input constructors are used.
"""
from pathlib import Path
import argparse
from datetime import datetime, timezone
import json
import shutil
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from prototypes.candidate_scheduling import select
from relation_search.checkpoint import digest, read, write
from scripts.execute_relation_search import emit_batch, run


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--ranking', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(exist_ok=False)
    rank_protocol = read(args.ranking/'protocol.json')
    cases = rank_protocol['cases']
    code_files = [Path(__file__).resolve(), ROOT/'prototypes/candidate_scheduling.py',
        ROOT/'prototypes/source_edit_identity.py', ROOT/'prototypes/exception_write_priority.py',
        ROOT/'scripts/execute_relation_search.py', ROOT/'scripts/relational_phase_runner.py',
        ROOT/'generic_composition/emitter.py', ROOT/'generic_composition/runner.py',
        ROOT/'relation_search/instrument.py', ROOT/'relation_search/runtime.py']
    identity = {str(p.relative_to(ROOT)): digest(p) for p in code_files}
    for path in code_files:
        target = args.output/'algorithm_snapshot'/path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    protocol = dict(created_at=datetime.now(timezone.utc).isoformat(), cases=cases,
        arms=['fair', 'writer_then_fair'], budget=8, rounds=1, group_size=8,
        workers=1, timeout=180, oracle_mode='none', model_calls=0,
        inventory=str(args.inventory.resolve()), ranking=str(args.ranking.resolve()),
        ranking_protocol_sha256=digest(args.ranking/'protocol.json'), code_sha256=identity,
        source_sha256={case:{name:digest(args.inventory/case/name) for name in
            ('case.json','corpus.json','frontend.json','issue.md','selection.json','source_pool.json')}
            for case in cases},
        ranking_sha256={case:digest(args.ranking/(case+'.json')) for case in cases},
        evaluation_targets=False, interpretation='New execution of both fixed rankings; source expectations require independent review.')
    write(args.output/'protocol.json', protocol)
    results = []
    for case in cases:
        source = args.inventory/case
        pool = read(source/'source_pool.json')['candidates']
        by_id = {c['id']:c for c in pool}
        priority = [by_id[r['id']] for r in read(args.ranking/(case+'.json'))['ranking']]
        if sorted(c['id'] for c in priority) != sorted(by_id):
            raise ValueError('Ranked candidate set changed')
        for arm, ordered in [('fair', pool), ('writer_then_fair', priority)]:
            if any(digest(ROOT/path) != checksum for path, checksum in identity.items()):
                raise ValueError('Ablation code changed')
            directory = args.output/arm/case
            prepared = directory/'prepared'
            prepared.mkdir(parents=True)
            for name in ('case.json','corpus.json','frontend.json','issue.md','selection.json'):
                (prepared/name).symlink_to((source/name).resolve())
            selected = select(ordered, budget=8)
            write(prepared/'candidates.json', dict(candidates=selected, selected=len(selected),
                  source_count=len(pool), oracle_mode='none', arm=arm))
            write(prepared/'prepare.json', dict(status='prepared', case=case, arm=arm,
                  source_corpus_sha256=digest(source/'corpus.json'),
                  files_sha256={p.name:digest(p) for p in prepared.iterdir() if p.is_file()},
                  model_calls=0, protocol_sha256=digest(args.output/'protocol.json')))
            emission = emit_batch(SimpleNamespace(input=prepared, output=directory/'emitted',
                group_size=8, timeout=180, dependency_packages_root=ROOT/'data/relational_gap_v1_dependency_packages'))
            execution = run(SimpleNamespace(input=directory/'emitted', output=directory/'executed',
                workers=1, registry=ROOT/'data/relational_gap_v1/registry.json'))
            results.append(dict(case=case, arm=arm, selected_ids=[c['id'] for c in selected],
                emission=emission, execution=execution,
                runs_index=str((directory/'executed/runs.json').resolve())))
            write(args.output/'results.json', results)
            print(json.dumps(dict(case=case, arm=arm, selected=len(selected), groups=execution['artifacts'])), flush=True)
    write(args.output/'completed.json', dict(cases=len(cases), arms=2, model_calls=0,
          protocol_sha256=digest(args.output/'protocol.json'), results_sha256=digest(args.output/'results.json')))


if __name__ == '__main__':
    main()
