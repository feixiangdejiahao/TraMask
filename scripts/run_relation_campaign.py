"""Run one fixed full-corpus configuration, with explicit oracle accounting."""
from __future__ import annotations

import argparse
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import shutil
import sys
import threading
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search.checkpoint import digest, read, write, start
from scripts.run_relation_search import algorithm_files, prepare, feedback
from scripts.execute_relation_search import emit_batch, run
from experimental.oracle_batch_recovery import POLICY as RECOVERY_POLICY, plan_recovery
from relation_search.semantic_frontier import POLICY as SEMANTIC_FRONTIER_POLICY


def code_identity():
    paths = [*algorithm_files(), ROOT/'relation_search/oracle.py',
             ROOT/'relational_gap/provider.py', ROOT/'scripts/relation_search_semantics.py',
             Path(__file__).resolve()]
    return {str(path.relative_to(ROOT)): digest(path) for path in sorted(set(paths))}


def preserve_configuration(path, value):
    if path.exists() and read(path) != value:
        raise ValueError('Frozen campaign configuration changed: '+str(path))
    write(path, value)


def semantic_batch(prepared, output, args, previous_selected, previous_semantic=None):
    from relation_search.semantic_cache import apply_cache
    candidates = read(prepared/'candidates.json')['candidates']
    corpus = read(prepared/'corpus.json')
    request = dict(stage='semantic', input=str(prepared.resolve()),
                   input_sha256=digest(prepared/'prepare.json'), mode=args.oracle_mode,
                   code_sha256=code_identity(), budget=args.semantic_budget,
                   per_request=args.per_request, model_workers=args.model_workers,
                   batch_recovery=RECOVERY_POLICY,
                   semantic_frontier_policy=SEMANTIC_FRONTIER_POLICY,
                   previous_semantic_sha256=digest(previous_semantic/'semantic_frontier.json') if previous_semantic else None,
                   cache_sha256=digest(args.oracle_cache) if args.oracle_cache else None,
                   selection_policy=getattr(args, 'semantic_policy', 'shape'),
                   evidence_mode=getattr(args, 'oracle_evidence', 'baseline'),
                   previously_selected=sorted(previous_selected))
    start(output, request)
    done = output/'semantic_result.json'
    if done.exists() and (output/'prepare.json').exists():
        record = read(done)
        for name, checksum in read(output/'prepare.json')['files_sha256'].items():
            if digest(output/name) != checksum:
                raise ValueError('Frozen semantic artifact changed')
        return record
    selected_ids, calls, offered_ids, recovery_calls, pending_count = [], 0, [], 0, 0
    if args.oracle_mode == 'replay':
        outcome = apply_cache(corpus, candidates, read(args.oracle_cache), (prepared/'issue.md').read_text())
        offered_ids = [row['id'] for row in candidates]
        write(output/'semantic_replay.json', outcome)
        revised = outcome['candidates']
    elif args.oracle_mode == 'fresh':
        from relation_search.semantic_frontier import advance
        from relation_search.oracle import prepare_requests
        from scripts.relation_search_semantics import complete
        prior = read(previous_semantic/'semantic_frontier.json') if previous_semantic else {}
        identity = dict(corpus_sha256=digest(prepared/'corpus.json'), issue_sha256=digest(prepared/'issue.md'))
        if prior and prior.get('source_identity') != identity:
            raise ValueError('Semantic backlog belongs to different source or issue')
        frontend = read(prepared/'frontend.json')
        queued = advance(corpus, candidates, prior, budget=args.semantic_budget, selected_ids=previous_selected,
                         frontend=frontend, selection_policy=getattr(args, 'semantic_policy', 'shape'))
        selection = queued['selection']
        selected = selection['selected']
        selected_ids = [row['id'] for row in selected]
        requests = prepare_requests(corpus, frontend, selected,
                                    (prepared/'issue.md').read_text(),
                                    max_requests=args.semantic_budget, per_request=args.per_request,
                                    evidence_mode=getattr(args, 'oracle_evidence', 'baseline'),
                                    impact_evidence_by_id={row['id']: row['evidence']
                                        for row in selection['ranking'] if 'evidence' in row})
        offered_ids = [item['candidate']['id'] for request in requests for item in request['offered'].values()]
        # Selection is an opportunity, not evidence that a model received the
        # candidate. Preserve selected-but-unoffered programs in the backlog.
        served = set(prior.get('selected_ids', [])) | set(previous_selected) | set(offered_ids)
        pending_ids = [row['id'] for row in selection['ranking'] if row['id'] not in served
                       and row.get('evidence', {}).get('eligible', True)]
        queued['frontier'].update(selected_ids=sorted(served), pending_ids=pending_ids)
        selection.update(offered_ids=offered_ids,
                         selected_but_unoffered_ids=[cid for cid in selected_ids if cid not in set(offered_ids)],
                         pending_count=len(pending_ids))
        pending_count = len(pending_ids)
        write(output/'semantic_frontier.json', dict(**queued['frontier'], source_identity=identity))
        write(output/'semantic_selection.json', selection)
        request_paths = []
        for index, value in enumerate(requests):
            value['source_prepared'] = str(prepared.resolve())
            path = output/'requests'/f'request_{index:03d}.json'
            if path.exists() and read(path) != value:
                raise ValueError('Semantic request changed on resume')
            write(path, value); request_paths.append(path)

        def finish(path):
            destination = output/'completions'/path.stem
            if destination.exists():
                # Never restart an in-flight or failed provider attempt merely
                # because observation was interrupted. Its record stays visible.
                manifest = read(destination/'manifest.json')
                if manifest['status'] in {'prepared', 'dispatching'}:
                    raise ValueError('Provider attempt requires live-process audit: '+str(destination))
            else:
                complete(SimpleNamespace(input=path, output=destination))
            manifest = read(destination/'manifest.json')
            if manifest['status'] == 'complete' and not (destination/'validation.json').exists():
                from relation_search.oracle import validate
                try:
                    outcome = validate(read(path), (destination/'completion.txt').read_text(), corpus)
                except (ValueError, TypeError, KeyError, AttributeError) as error:
                    outcome = dict(revisions=[], decisions=[], error=type(error).__name__)
                write(destination/'validation.json', outcome)
            return destination

        with ThreadPoolExecutor(max_workers=args.model_workers) as pool:
            completions = list(pool.map(finish, request_paths))
        # A completed malformed batch can be split once without introducing a
        # new candidate, new source evidence, or execution-result feedback.
        recovery_paths = []
        for path, directory in zip(request_paths, completions):
            manifest = read(directory/'manifest.json')
            text = (directory/'completion.txt').read_text() if (directory/'completion.txt').exists() else None
            plan = plan_recovery(read(path), manifest, text)
            preserve_configuration(output/'recovery'/f'{path.stem}.json', plan)
            for index, child in enumerate(plan['requests']):
                child_path = output/'requests'/f'{path.stem}_split_{index:02d}.json'
                preserve_configuration(child_path, child)
                recovery_paths.append(child_path)
        with ThreadPoolExecutor(max_workers=args.model_workers) as pool:
            recovery_completions = list(pool.map(finish, recovery_paths))
        recovery_calls = sum(read(directory/'manifest.json').get('external_model_calls', 0)
                             for directory in recovery_completions)
        completions.extend(recovery_completions)
        revised = list(candidates)
        for directory in completions:
            manifest = read(directory/'manifest.json')
            calls += manifest.get('external_model_calls', 0)
            if (directory/'validation.json').exists():
                revised.extend(read(directory/'validation.json')['revisions'])
        revised = list({row['id']: row for row in revised}.values())
    else:
        revised = candidates
    for path in prepared.iterdir():
        target = output/path.name
        if (path.is_file() and path.name not in {'prepare.json', 'candidates.json', 'checkpoint.json', 'stage.json'}
                and not target.exists()):
            target.symlink_to(path.resolve())
    write(output/'candidates.json', dict(candidates=revised, source_count=len(candidates),
          semantic_count=len(revised)-len(candidates), mode=args.oracle_mode,
          program_selection_before_semantics=True,
          semantic_selection_applies=args.oracle_mode == 'fresh'))
    record = dict(mode=args.oracle_mode, source_count=len(candidates),
                  revised_count=len(revised)-len(candidates), selected_ids=selected_ids,
                  offered_ids=offered_ids, distinct_offered_candidates=len(set(offered_ids)),
                  recovery_calls=recovery_calls, batch_recovery_policy=RECOVERY_POLICY,
                  pending_semantic_count=pending_count, semantic_frontier_policy=SEMANTIC_FRONTIER_POLICY,
                  provider_calls=calls, previous_selected=sorted(set(previous_selected)|
                      set(offered_ids if args.oracle_mode == 'fresh' else selected_ids)))
    write(done, record)
    write(output/'prepare.json', dict(status='prepared', case=read(prepared/'case.json')['id'],
          source_prepare=str((prepared/'prepare.json').resolve()),
          source_identity=read(prepared/'prepare.json').get('source_identity'),
          files_sha256={path.name: digest(path) for path in output.iterdir()
                        if path.is_file() and path.name not in {'prepare.json', 'stage.json'}},
          model_calls=calls, oracle_mode=args.oracle_mode))
    return record


def campaign(args):
    cases = args.cases or sorted(path.name for path in args.source.iterdir() if (path/'case.json').exists())
    configuration = dict(source_root=str(args.source.resolve()), cases=cases, rounds=args.rounds,
        limit=args.limit, pool=args.pool, strategy=args.strategy, max_edits=args.max_edits,
        workers=args.workers, group_size=args.group_size, timeout=args.timeout,
        isolate_go_compilation=getattr(args, 'isolate_go_compilation', False),
        include_baseline=args.include_baseline, representations_only=False,
        writer_priority=getattr(args, 'writer_priority', False),
        oracle_mode=args.oracle_mode, semantic_budget=args.semantic_budget,
        semantic_policy=getattr(args, 'semantic_policy', 'shape'),
        oracle_evidence=getattr(args, 'oracle_evidence', 'baseline'),
        per_request=args.per_request, model_workers=args.model_workers,
        case_workers=getattr(args, 'case_workers', 1),
        case_schedule=getattr(args, 'case_schedule', 'case'),
        batch_recovery=RECOVERY_POLICY,
        semantic_frontier_policy=SEMANTIC_FRONTIER_POLICY,
        oracle_cache_sha256=digest(args.oracle_cache) if args.oracle_cache else None,
        source_corpus_sha256={case: digest(args.source/case/'corpus.json') for case in cases},
        algorithm_sha256=code_identity())
    start(args.output, dict(stage='campaign', **configuration))
    for relative, checksum in configuration['algorithm_sha256'].items():
        target = args.output/'algorithm_snapshot'/relative
        if target.exists():
            if digest(target) != checksum:
                raise ValueError('Frozen campaign algorithm changed: '+relative)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT/relative, target)
    preserve_configuration(args.output/'configuration.json', configuration)
    case_workers = getattr(args, 'case_workers', 1)
    schedule = getattr(args, 'case_schedule', 'case')
    if not 1 <= case_workers <= 4 or schedule not in {'case', 'round'}:
        raise ValueError('Unsupported case scheduling configuration')
    states, state_lock = {}, threading.Lock()
    for case in cases:
        case_root = args.output/case
        preserve_configuration(case_root/'configuration.json',
                               {**configuration, 'source': str((args.source/case).resolve()), 'case': case})
        states[case] = dict(previous=None, previous_semantic=None, selected=[], rounds=[],
                            stopped_reason='in_progress', exhausted_prepare=None, finished=False)

    def record(case):
        state = states[case]
        return dict(case=case, source_corpus=str((args.source/case/'corpus.json').resolve()),
                    execution_configuration=str((args.output/case/'configuration.json').resolve()),
                    rounds=state['rounds'], stopped_reason=state['stopped_reason'],
                    exhausted_prepare=state['exhausted_prepare'])

    def save():
        with state_lock:
            snapshot = copy.deepcopy([record(case) for case in cases
                if states[case]['rounds'] or states[case]['finished']])
        write(args.output/'campaign.json', snapshot)

    def step(case, index):
        state, case_root = states[case], args.output/case
        if state['finished']:
            return
        if code_identity() != configuration['algorithm_sha256']:
            raise ValueError('Campaign code changed; completed work is preserved')
        folder = case_root/f'round_{index:03d}'
        preparation = prepare(SimpleNamespace(source=args.source/case, output=folder/'prepared', previous=state['previous'],
            strategy=args.strategy, limit=args.limit, pool=args.pool, max_edits=args.max_edits,
            include_baseline=args.include_baseline, representations_only=False,
            writer_priority=getattr(args, 'writer_priority', False),
            campaign_configuration=args.output/'configuration.json'))
        pending_semantics = (args.oracle_mode == 'fresh' and state['previous_semantic'] is not None
                             and read(state['previous_semantic']/'semantic_frontier.json')['pending_ids'])
        if not preparation['selected'] and not pending_semantics:
            with state_lock:
                state.update(stopped_reason='exhausted', finished=True,
                             exhausted_prepare=str((folder/'prepared/prepare.json').resolve()))
            return
        semantic = semantic_batch(folder/'prepared', folder/'semantic', args, state['selected'],
                                  state['previous_semantic'] if args.oracle_mode == 'fresh' else None)
        emission = emit_batch(SimpleNamespace(input=folder/'semantic', output=folder/'emitted',
              group_size=args.group_size, timeout=args.timeout,
              isolate_go_compilation=getattr(args, 'isolate_go_compilation', False),
              dependency_packages_root=args.dependency_packages_root))
        execution = run(SimpleNamespace(input=folder/'emitted', output=folder/'executed',
                                        workers=args.workers, registry=args.registry))
        measured = feedback(SimpleNamespace(source=folder/'executed', output=folder/'feedback.json', previous=state['previous']))
        row = dict(round=index, prepare_manifest=str((folder/'semantic/prepare.json').resolve()),
                   candidates=str((folder/'semantic/candidates.json').resolve()),
                   runs_index=str((folder/'executed/runs.json').resolve()),
                   program_prepare_manifest=str((folder/'prepared/prepare.json').resolve()),
                   prepared=preparation, semantic=semantic, emitted=emission,
                   execution=execution, feedback=measured)
        rounds = [*state['rounds'], row]
        write(case_root/'rounds.json', rounds)
        with state_lock:
            state.update(rounds=rounds, previous=folder/'feedback.json', previous_semantic=folder/'semantic',
                         selected=semantic['previous_selected'])
            if index+1 == args.rounds:
                state.update(stopped_reason='round_budget', finished=True)
        print(json.dumps(dict(case=case, round=index, selected=preparation['selected'],
              revised=semantic['revised_count'], profiles=measured['profiles'])), flush=True)

    if schedule == 'case':
        for case in cases:
            for index in range(args.rounds):
                step(case, index)
                save()
                if states[case]['finished']:
                    break
    else:
        # A barrier between rounds gives every case its first-round budget
        # before any case receives the next one. Each case owns its files.
        for index in range(args.rounds):
            pending = [case for case in cases if not states[case]['finished']]
            errors = []
            with ThreadPoolExecutor(max_workers=case_workers) as pool:
                futures = {pool.submit(step, case, index): case for case in pending}
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as error:
                        errors.append(error)
                    save()
            if errors:
                raise errors[0]
    return dict(cases=len(cases), configuration=str((args.output/'configuration.json').resolve()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cases', nargs='*')
    parser.add_argument('--rounds', type=int, default=2)
    parser.add_argument('--limit', type=int, default=128)
    parser.add_argument('--pool', type=int, default=512)
    parser.add_argument('--strategy', choices=['profile', 'rotation'], default='profile')
    parser.add_argument('--max-edits', type=int, default=4)
    parser.add_argument('--include-baseline', action='store_true')
    parser.add_argument('--writer-priority', action='store_true',
                        help='Prioritize source-supported Python exception contexts before fair scheduling')
    parser.add_argument('--group-size', type=int, default=16)
    parser.add_argument('--isolate-go-compilation', action='store_true',
                        help='Build each generated Go candidate in a separate compilation unit')
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--oracle-mode', choices=['none', 'replay', 'fresh'], default='none')
    parser.add_argument('--oracle-cache', type=Path)
    parser.add_argument('--semantic-budget', type=int, default=16)
    parser.add_argument('--semantic-policy', choices=['shape', 'impact'], default='shape')
    parser.add_argument('--oracle-evidence', choices=['baseline', 'dependency'], default='baseline')
    parser.add_argument('--per-request', type=int, default=4)
    parser.add_argument('--model-workers', type=int, default=2)
    parser.add_argument('--case-workers', type=int, default=1)
    parser.add_argument('--case-schedule', choices=['case', 'round'], default='case')
    parser.add_argument('--registry', type=Path, default=ROOT/'data/relational_gap_v1/registry.json')
    parser.add_argument('--dependency-packages-root', type=Path, default=ROOT/'data/relational_gap_v1_dependency_packages')
    arguments = parser.parse_args()
    if arguments.oracle_mode == 'replay' and arguments.oracle_cache is None:
        parser.error('--oracle-cache is required for replay')
    print(json.dumps(campaign(arguments)))
