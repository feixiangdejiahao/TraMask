"""Resumable source-only search rounds driven by actual runtime profiles."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search.checkpoint import read, write, digest, start, completed, seal


def algorithm_files():
    return sorted({*[p for p in ROOT.glob('relation_search/*.py') if p.name != 'oracle.py'],
                   *ROOT.glob('relational_gap/*.py'), *ROOT.glob('anchor_retrieval/*.py'),
                   *ROOT.glob('experimental/relation_search_*.py'),
                   *[ROOT/'experimental'/name for name in ('assertion_operand_guard.py', 'source_edit_identity.py',
                       'candidate_scheduling.py', 'go_arity_guard.py', 'oracle_batch_recovery.py', 'owner_prefix_slice.py',
                       'exception_write_priority.py', 'assertion_write_origin.py',
                       'singleton_oracle_slots.py', 'call_dependency_evidence.py')],
                   *[ROOT/'experimental'/name for name in ('patch_observation_priority.py',
                       'modified_observation_impact.py', 'local_helper_evidence.py',
                       'go_assertion_helper.py', 'source_failure_evidence.py')],
                   ROOT/'scripts/analyze_assertion_write_origin_census.py',
                   ROOT/'scripts/run_relation_search.py', ROOT/'scripts/execute_relation_search.py',
                   ROOT/'scripts/relational_go_test_runner.py',
                   ROOT/'scripts/relational_phase_runner.py', ROOT/'generic_composition/emitter.py',
                   ROOT/'generic_composition/runner.py', ROOT/'generic_composition/corpus.py'})


def prepare(args):
    from relation_search.frontier import select_round
    from relation_search.instrument import compose_neighbors, instrument_candidates
    previous = read(args.previous) if args.previous else {}
    algorithm = {str(path.relative_to(ROOT)): digest(path) for path in algorithm_files()}
    source_hashes = {name: digest(args.source/name) for name in
                     ('corpus.json', 'frontend.json', 'case.json', 'selection.json', 'issue.md', 'candidates.json')
                     if (args.source/name).exists()}
    request = dict(stage='prepare', source=str(args.source.resolve()), source_sha256=source_hashes,
                   previous_sha256=digest(args.previous) if args.previous else None,
                   strategy=args.strategy, limit=args.limit, pool=args.pool,
                   max_edits=args.max_edits, include_baseline=args.include_baseline,
                   writer_priority=getattr(args, 'writer_priority', False),
                   representations_only=args.representations_only, algorithm_sha256=algorithm)
    if getattr(args, 'campaign_configuration', None):
        request['global_configuration_sha256'] = digest(args.campaign_configuration)
    start(args.output, request)
    existing = completed(args.output)
    if existing is not None:
        return {**existing, 'resumed': True}
    if previous.get('source_identity') and previous['source_identity'] != source_hashes:
        raise ValueError('Previous feedback belongs to different frozen source input')
    corpus, frontend = read(args.source/'corpus.json'), read(args.source/'frontend.json')
    candidates, counts = [], {}
    if corpus['language'] == 'python':
        from relation_search.representations import generate
        rows = generate(corpus, frontend, budget=args.pool)
        candidates.extend(rows)
        counts['resource_representation'] = len(rows)
        if not args.representations_only:
            from relation_search.constructors import generate as constructor_generate
            rows = constructor_generate(corpus, frontend, budget=args.pool)
            candidates.extend(rows)
            counts['source_constructors'] = len(rows)
            from experimental.relation_search_python import generate as python_generate
            rows = python_generate(corpus, frontend)
            candidates.extend(rows)
            counts['python_contexts'] = len(rows)
    else:
        from experimental.relation_search_go_ts import enrich
        rows = enrich(corpus, frontend, budget=args.pool)
        candidates.extend(rows)
        counts['typed_contexts'] = len(rows)
    if args.include_baseline:
        old = read(args.source/'candidates.json')['candidates']
        candidates.extend(old)
        counts['baseline_candidates'] = len(old)
    if previous.get('candidate_pool'):
        pool_record = previous['candidate_pool']
        if digest(pool_record['path']) != pool_record['sha256']:
            raise ValueError('Previous source candidate pool changed')
        candidates.extend(read(pool_record['path'])['candidates'])
    candidates = list({row['id']: row for row in candidates if not row.get('is_source_profile')}.values())
    extensions = compose_neighbors(previous.get('eligible_parents', []), candidates,
                                   max_edits=args.max_edits, budget=args.pool, strategy=args.strategy)
    candidates.extend(extensions)
    counts['feedback_extensions'] = len(extensions)
    if corpus['language'] == 'go':
        from anchor_retrieval.syntax import Source
        from experimental.owner_prefix_slice import propose_candidate
        sources = [Source(path, entry['code'], 'go') for path, entry in corpus['sources'].items()
                   if entry.get('language', corpus['language']) == 'go' and not entry.get('parse_error')]
        prefix_records, prefix_candidates = [], []
        for candidate in candidates:
            if candidate.get('prefix_slice') or not any(e.get('role') == 'state_prefix' for e in candidate['edits']):
                continue
            proposal = propose_candidate(candidate, sources=sources)
            prefix_records.append(dict(parent_id=candidate['id'], analysis=proposal['analysis'],
                                       child_id=proposal['candidate']['id'] if proposal['candidate'] else None))
            if proposal['candidate']:
                prefix_candidates.append(proposal['candidate'])
        candidates = list({row['id']: row for row in [*candidates, *prefix_candidates]}.values())
        counts['bounded_owner_prefix_proposals'] = len(prefix_candidates)
        write(args.output/'prefix_construction.json', dict(records=prefix_records,
            claim='new_construction_hypotheses_not_semantics_preserving_slices'))
        from experimental.go_arity_guard import filter_candidates
        validation = filter_candidates(corpus, candidates, frontend)
        candidates = validation.pop('candidates')
        counts['static_arity_rejected'] = len(validation['rejected'])
        write(args.output/'static_validation.json', validation)
    if getattr(args, 'writer_priority', False):
        original_ids = [row['id'] for row in candidates]
        if corpus['language'] == 'python':
            from scripts.analyze_assertion_write_origin_census import analyze_corpus
            from experimental.exception_write_priority import prioritize
            census = analyze_corpus(corpus)
            priority = prioritize(corpus, candidates, census)
            # The stable partition precedes the existing fair scheduler. Keep
            # each original candidate, even if metadata IDs were duplicated.
            candidates = [candidates[row['original_rank'] - 1] for row in priority['ranking']]
            priority.update(status='applied', analysis_summary=census['summary'],
                            analyzed_source_sha256=census['source_sha256'])
        else:
            priority = dict(status='unsupported_language', input_count=len(candidates),
                supported_candidates=0, ranking=[dict(id=row['id'], original_rank=i+1,
                rank=i+1, evidence=[]) for i, row in enumerate(candidates)],
                selection='original order retained', provider_calls=0, subject_executions=0)
        priority.update(enabled=True, language=corpus['language'], source_sha256=source_hashes,
                        original_order=original_ids, ranked_order=[row['id'] for row in candidates],
                        interpretation='Static may-bypass priority; no online writer feedback or oracle proof.')
        counts['writer_priority_supported'] = priority['supported_candidates']
        write(args.output/'writer_priority.json', priority)
    selected = select_round(candidates, args.limit, previous.get('attempted_candidate_ids', []))
    for name in ['corpus.json', 'frontend.json', 'case.json', 'selection.json', 'issue.md']:
        source = args.source/name
        target = args.output/name
        if source.exists() and not target.exists():
            target.symlink_to(source.resolve())
    for row in candidates:
        row.setdefault('source_provenance', dict(seed=row['base_test_id'],
                         seed_snapshot=str((args.source/'corpus.json').resolve()),
                         algorithm=row.get('operator', row.get('kind'))))
        row['execution_lane'] = 'relation_search'
        row.setdefault('static_parent_id', row['id'])
    write(args.output/'source_pool.json', dict(candidates=candidates, counts=counts))
    write(args.output/'candidates.json', dict(candidates=selected, counts=counts,
          pool_size=len(candidates), selected=len(selected), strategy=args.strategy,
          selection='fair source/operator rotation; extension parents gated by recorded execution feedback'))
    # Preserve raw input edits for optional semantic interpretation. The emitter
    # instruments the final candidate list again, including any oracle revisions.
    instrumentation = instrument_candidates(corpus, selected)
    write(args.output/'instrumentation.json', instrumentation)
    for relative in algorithm:
        path = args.output/'algorithm_snapshot'/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT/relative).read_bytes())
    manifest = dict(status='prepared', case=read(args.source/'case.json')['id'],
                    source_prepare=str((args.source/'prepare.json').resolve()), source_identity=source_hashes,
                    model_calls=0, strategy=args.strategy,
                    files_sha256={p.name: digest(p) for p in args.output.iterdir() if p.is_file()
                                  and p.name not in {'prepare.json', 'checkpoint.json'}},
                    algorithm_sha256=algorithm)
    write(args.output/'prepare.json', manifest)
    result = dict(pool=len(candidates), selected=len(selected), families=counts,
                  source_profiles=instrumentation['metadata']['source_profile_count'],
                  dynamic_profile_support='python_pure_reads' if corpus['language'] == 'python' else 'unsupported')
    seal(args.output, result)
    return result


def feedback(args):
    from relation_search.feedback import collect
    previous = read(args.previous) if args.previous else {}
    output = collect(args.source, previous)
    runs = read(args.source/'runs.json')
    prepared = None
    if runs:
        manifests = {row['manifest'] for row in runs}
        inputs = {read(Path(path))['original_input'] for path in manifests}
        if len(inputs) != 1:
            raise ValueError('One feedback checkpoint must use one prepared source batch')
        prepared = Path(next(iter(inputs)))
    elif (args.source/'stage.json').exists():
        emitted = Path(read(args.source/'stage.json')['input'])
        prepared = Path(read(emitted/'execution_lanes.json')['source'])
    if prepared is not None:
        manifest = read(prepared/'prepare.json')
        source_manifest, visited = manifest, set()
        while not source_manifest.get('source_identity') and source_manifest.get('source_prepare'):
            ancestor = Path(source_manifest['source_prepare'])
            if str(ancestor.resolve()) in visited or not ancestor.is_file():
                break
            visited.add(str(ancestor.resolve()))
            source_manifest = read(ancestor)
        output['source_identity'] = source_manifest.get('source_identity', previous.get('source_identity'))
        pool = prepared/'source_pool.json'
        if pool.exists():
            output['candidate_pool'] = dict(path=str(pool.resolve()), sha256=digest(pool))
    output['checkpoint_inputs'] = dict(execution=str(args.source.resolve()),
          execution_sha256=digest(args.source/'checkpoint.json') if (args.source/'checkpoint.json').exists() else digest(args.source/'runs.json'),
          previous_sha256=digest(args.previous) if args.previous else None)
    if args.output.exists() and json.dumps(read(args.output), sort_keys=True) != json.dumps(output, sort_keys=True):
        raise ValueError('Refusing to replace a different feedback checkpoint')
    write(args.output, output)
    return dict(executed=len(output['executed_candidate_ids']), attempted=len(output['attempted_candidate_ids']),
                profiles=output['measured_profile_count'], eligible_parents=len(output['eligible_parents']))


def loop(args):
    from scripts.execute_relation_search import emit_batch, run
    configuration = dict(source=str(args.source.resolve()), rounds=args.rounds, limit=args.limit,
        pool=args.pool, strategy=args.strategy, max_edits=args.max_edits, workers=args.workers,
        group_size=args.group_size, timeout=args.timeout, include_baseline=args.include_baseline,
        representations_only=args.representations_only,
        writer_priority=getattr(args, 'writer_priority', False),
        source_sha256=digest(args.source/'corpus.json'),
        algorithm_sha256={str(p.relative_to(ROOT)): digest(p) for p in algorithm_files()})
    if getattr(args, 'campaign_configuration', None):
        configuration['global_configuration_sha256'] = digest(args.campaign_configuration)
    start(args.output, dict(stage='loop', **configuration))
    write(args.output/'configuration.json', configuration)
    previous, summaries = args.previous, []
    for index in range(args.rounds):
        if {str(p.relative_to(ROOT)): digest(p) for p in algorithm_files()} != configuration['algorithm_sha256']:
            raise ValueError('Algorithm files changed during campaign; completed rounds are preserved')
        folder = args.output/f'round_{index:03d}'
        preparation = prepare(SimpleNamespace(**{**vars(args), 'output': folder/'prepared', 'previous': previous}))
        if read(folder/'prepared/prepare.json')['algorithm_sha256'] != configuration['algorithm_sha256']:
            raise ValueError('Algorithm snapshot changed while preparing a round')
        if not preparation['selected']:
            summaries.append(dict(round=index, prepared=preparation, stopped='no_unexecuted_hypothesis'))
            break
        emitted = emit_batch(SimpleNamespace(input=folder/'prepared', output=folder/'emitted',
            group_size=args.group_size, timeout=args.timeout, dependency_packages_root=args.dependency_packages_root))
        execution = run(SimpleNamespace(input=folder/'emitted', output=folder/'executed',
                                        workers=args.workers, registry=args.registry))
        measured = feedback(SimpleNamespace(source=folder/'executed', output=folder/'feedback.json', previous=previous))
        previous = folder/'feedback.json'
        summaries.append(dict(round=index, prepared=preparation, emitted=emitted, feedback=measured,
                              execution_artifacts=execution['artifacts'],
                              execution_wall_seconds=execution['wall_seconds'], checkpoint=str(previous.resolve())))
        write(args.output/'rounds.json', summaries)
    result = dict(strategy=args.strategy, rounds=summaries,
                  final_feedback=str(previous.resolve()) if previous else None,
                  execution_wall_seconds=sum(row.get('execution_wall_seconds', 0) for row in summaries),
                  configuration_sha256=digest(args.output/'configuration.json'))
    write(args.output/'result.json', result)
    return result


def batch(args):
    # Cases are directories in an explicit supplied source root, not built-in IDs.
    cases = args.cases or sorted(path.name for path in args.source.iterdir() if (path/'case.json').exists())
    if args.previous:
        raise ValueError('A multi-case campaign resumes from its own case checkpoints, not one shared previous file')
    configuration = dict(source_root=str(args.source.resolve()), cases=cases,
        rounds=args.rounds, limit=args.limit, pool=args.pool, strategy=args.strategy,
        max_edits=args.max_edits, workers=args.workers, group_size=args.group_size, timeout=args.timeout,
        include_baseline=args.include_baseline, representations_only=args.representations_only,
        writer_priority=getattr(args, 'writer_priority', False),
        source_corpus_sha256={case: digest(args.source/case/'corpus.json') for case in cases},
        algorithm_sha256={str(p.relative_to(ROOT)): digest(p) for p in algorithm_files()})
    start(args.output, dict(stage='batch', **configuration))
    write(args.output/'configuration.json', configuration)
    records = []
    for case in cases:
        if not (args.source/case/'case.json').exists():
            raise ValueError('Missing prepared case: ' + case)
        result = loop(SimpleNamespace(**{**vars(args), 'source': args.source/case, 'output': args.output/case,
                     'campaign_configuration': args.output/'configuration.json'}))
        records.append(dict(case=case, result=result))
        write(args.output/'batch.json', records)
    return dict(cases=records)


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['prepare', 'feedback', 'loop', 'batch'])
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=128)
    parser.add_argument('--pool', type=int, default=512)
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--include-baseline', action='store_true')
    parser.add_argument('--representations-only', action='store_true')
    parser.add_argument('--writer-priority', action='store_true',
                        help='Prioritize source-supported Python exception contexts before fair scheduling')
    parser.add_argument('--strategy', choices=['profile', 'rotation'], default='profile')
    parser.add_argument('--max-edits', type=int, default=4)
    parser.add_argument('--rounds', type=int, default=2)
    parser.add_argument('--group-size', type=int, default=16)
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--cases', nargs='*')
    parser.add_argument('--registry', type=Path, default=ROOT/'data/relational_gap_v1/registry.json')
    parser.add_argument('--dependency-packages-root', type=Path, default=ROOT/'data/relational_gap_v1_dependency_packages')
    args = parser.parse_args()
    print(json.dumps({'prepare': prepare, 'feedback': feedback, 'loop': loop, 'batch': batch}[args.stage](args)))


if __name__ == '__main__':
    main()
