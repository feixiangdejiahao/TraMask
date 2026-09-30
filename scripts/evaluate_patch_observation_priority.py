"""Post-seal static exposure evaluation; no provider or subject calls.

Target acquisition is deliberately separate. The CLI verifies the source seal;
helpers compare fixed witnessed source programs without selecting or repairing them.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search.instrument import _program_edits
from relation_search.oracle_evidence import _modified_sources


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_seal(directory):
    """Verify the completed source scheduler before reading target material."""
    directory = Path(directory)
    seal = read(directory / 'seal.json')
    for relative, expected in seal['files_sha256'].items():
        if digest(directory / relative) != expected:
            raise ValueError('sealed_source_file_changed:' + relative)
    protocol = read(directory / 'protocol.json')
    for source, expected in protocol['input_sha256'].items():
        if digest(source) != expected:
            raise ValueError('source_input_changed:' + source)
    for relative, expected in protocol['code_sha256'].items():
        if digest(directory / 'code_snapshot' / relative) != expected:
            raise ValueError('frozen_code_changed:' + relative)
    summary = read(directory / 'summary.json')
    if len(summary['cases']) != 17 or summary['candidate_count'] != 4502:
        raise ValueError('fixed_denominator_changed')
    rank_checks=[]
    for case in protocol['cases']:
        pool=read(Path(protocol['source_inventory'])/case/'source_pool.json')
        rank_checks.append(verify_rank_case(directory,case,[r['id'] for r in pool['candidates']]))
    return dict(rank_checks=rank_checks,seal_sha256=digest(directory / 'seal.json'),
                summary_sha256=digest(directory / 'summary.json'),
                protocol_sha256=digest(directory / 'protocol.json'),
                sealed_files=len(seal['files_sha256']),
                source_inputs=len(protocol['input_sha256']),
                code_files=len(protocol['code_sha256']))


def verify_rank_case(directory, case, source_ids):
    directory=Path(directory)/case
    arms={name:read(directory/(name+'.json')) for name in ('shape','strict','may')}
    baseline={row['id']:row['rank'] for row in arms['shape']['ranking']}
    evidence={}
    eligibility={row['id']:row['eligible'] for row in read(directory/'eligibility.json')}
    if set(eligibility)!=set(source_ids):
        raise ValueError('shared_eligibility_denominator_changed:'+case)
    for arm,result in arms.items():
        ranking=result['ranking']
        ids=[row['id'] for row in ranking]
        if len(ids)!=len(source_ids) or set(ids)!=set(source_ids):
            raise ValueError('ranking_denominator_changed:'+case+':'+arm)
        if [row['rank'] for row in ranking]!=list(range(1,len(ids)+1)):
            raise ValueError('noncontiguous_rank:'+case+':'+arm)
        if [row['id'] for row in result['selected']]!=ids[:16]:
            raise ValueError('raw_prefix_changed:'+case+':'+arm)
        eligible=read(directory/(arm+'_eligible.json'))
        filtered=[cid for cid in ids if eligibility[cid]]
        if eligible['selected_ids']!=filtered[:16]:
            raise ValueError('eligible_prefix_changed:'+case+':'+arm)
        if [row['id'] for row in eligible['complete_ranking']]!=filtered:
            raise ValueError('eligible_complete_rank_changed:'+case+':'+arm)
        if arm!='shape':
            if any(row['baseline_rank']!=baseline[row['id']] for row in ranking):
                raise ValueError('baseline_rank_changed:'+case+':'+arm)
            key='strong_priority' if arm=='strict' else 'may_priority'
            if ranking!=sorted(ranking,key=lambda r:(not r['evidence'][key],baseline[r['id']])):
                raise ValueError('stable_partition_changed:'+case+':'+arm)
            evidence[arm]={r['id']:r['evidence'] for r in ranking}
    return dict(case=case,candidates=len(source_ids),raw_budget=16,
                eligibility_count=sum(eligibility.values()),
                cross_mode_evidence_exact=evidence['strict']==evidence['may'])


def source_program_signature(candidate, *, recorded_program_edits=False):
    """Exact original input edit descriptor; expectations are not input edits.

    For a semantic witness its recorded pre-oracle program snapshot is required;
    this option never guesses the input program from a revised assertion.
    """
    if recorded_program_edits:
        if 'program_edits' not in candidate:
            raise ValueError('witness_original_program_snapshot_missing')
        edits = candidate['program_edits']
    else:
        edits = _program_edits(candidate)
    if any(e.get('role') == 'semantic_expected' for e in edits):
        raise ValueError('snapshot_contains_oracle_expectation')
    descriptor = dict(base_test_id=candidate['base_test_id'],
        edits=sorted([dict(span=e['span'], before=e['before'], after=e['after'])
                      for e in edits], key=lambda e:(e['span']['path'], e['span']['start_byte'],
                                                    e['span']['end_byte'], e['before'], e['after'])),
        imports=candidate.get('imports', []))
    encoded = json.dumps(descriptor, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def exposure(ranking, ids, budget=16):
    ranks = {row['id']:row['rank'] for row in ranking}
    matches = sorted((dict(id=cid, rank=ranks[cid]) for cid in ids if cid in ranks),
                     key=lambda r:(r['rank'],r['id']))
    return dict(available=bool(matches), hit_at_budget=any(r['rank'] <= budget for r in matches),
                best_rank=matches[0]['rank'] if matches else None, matches=matches)


def aggregate(rows, key):
    available = [r for r in rows if r['source_pool_available']]
    hits = sum(r[key]['hit_at_budget'] for r in rows)
    return dict(hits=hits, all_trial_denominator=len(rows),
                available_trial_denominator=len(available),
                all_trial_rate=hits/len(rows) if rows else None,
                available_trial_rate=hits/len(available) if available else None)


def input_only(candidate):
    """Restore original assertions by discarding only recorded oracle edits."""
    return dict(base_test_id=candidate['base_test_id'],
        edits=[e for e in _program_edits(candidate) if e.get('role')!='semantic_expected'],
        imports=candidate.get('imports',[]))


def preview_signature(corpus,candidate):
    """Exact reconstructed owner bytes plus original test identity/imports.

    Different edit windows can produce identical programs. No AST, semantic,
    keyword, rank or runtime approximation is used for this match.
    """
    _,owner,_,bindings,unknowns=_modified_sources(corpus,input_only(candidate))
    value=dict(base_test_id=candidate['base_test_id'],owner_path=owner.path,
        modified_owner_sha256=hashlib.sha256(owner.data).hexdigest(),
        added_import_bindings=bindings,import_unknowns=unknowns)
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def evaluate(directory,historical_matching,checkpoint,output):
    directory=Path(directory);output=Path(output)
    # This is deliberately before opening either evaluator target bank.
    audit=verify_seal(directory)
    if output.exists():raise ValueError('evaluation_output_already_exists')
    protocol=read(directory/'protocol.json');inventory=Path(protocol['source_inventory'])
    historical=read(historical_matching);main=read(checkpoint)
    banks={'historical_fixed17':{r['case']:r for r in historical['cases']},
           'v3_supported17':{r['case']:r for r in main['cases']}}
    if any(set(rows)!=set(protocol['cases']) for rows in banks.values()):
        raise ValueError('evaluator_trial_denominator_changed')
    inputs={str(Path(p).resolve()):digest(p) for p in [historical_matching,checkpoint]}
    rows={name:[] for name in banks}
    for case in protocol['cases']:
        corpus=read(inventory/case/'corpus.json')
        pool=read(inventory/case/'source_pool.json')['candidates']
        by_signature={}
        for candidate in pool:
            by_signature.setdefault(preview_signature(corpus,candidate),[]).append(candidate['id'])
        case_record=read(inventory/case/'case.json')
        witnesses=[]
        files=[]
        for prefix in ['results/relation_search_20260929_v3/uniform_fresh_impact_v3',
                       'results/relation_search_20260929/uniform_warm_v1']:
            files.extend(sorted((ROOT/prefix/case).glob('round_*/semantic/candidates.json')))
            files.extend(sorted((ROOT/prefix/case).glob('round_*/emitted/raw_candidates.json')))
        unresolved=[]
        for witness_id in banks['v3_supported17'][case]['currently_supported_ids']:
            located=None
            for path in files:
                content=read(path);candidates=content.get('candidates',[]) if isinstance(content,dict) else content
                original=next((r for r in candidates if r['id']==witness_id),None)
                if original is not None:
                    located=(path,original);break
            if located is None:
                unresolved.append(witness_id)
                witnesses.append(dict(witness_id=witness_id,status='original_program_record_unavailable',matching_ids=[]))
                continue
            path,original=located;inputs[str(path.resolve())]=digest(path)
            signature=preview_signature(corpus,original)
            matched=by_signature.get(signature,[])
            witnesses.append(dict(witness_id=witness_id,status='exact_program_in_pool' if matched else 'exact_program_absent_from_pool',
                candidate_file=str(path.resolve()),candidate_file_sha256=digest(path),
                input_program_preview_signature=signature,
                semantic_parent=(original.get('semantic_revision') or {}).get('parent'),
                original_input_edit_signature=source_program_signature(input_only(original)),matching_ids=matched))
        all_ids={r['id'] for r in pool}
        target_ids={name:(set(banks[name][case]['matching_ids']) if name=='historical_fixed17' else
                         {cid for w in witnesses for cid in w['matching_ids']}) for name in banks}
        if not target_ids['historical_fixed17']<=all_ids:
            raise ValueError('historical_matcher_source_cohort_changed:'+case)
        arm_views={}
        for arm in ['shape','strict','may']:
            result=read(directory/case/(arm+'.json'))
            arm_views[arm]={'raw16':[{k:r[k] for k in ['id','rank']} for r in result['ranking']],
                           'legacy_eligible16':read(directory/case/(arm+'_eligible.json'))['complete_ranking']}
        for name in banks:
            ids=target_ids[name]
            row=dict(case=case,task=case_record['task'],source_pool_available=bool(ids),matching_ids=sorted(ids),
                requires_semantic_revision=banks['historical_fixed17'][case]['requires_semantic_revision'],
                arms={arm:{metric:exposure(ranking,ids) for metric,ranking in values.items()}
                      for arm,values in arm_views.items()})
            if name=='v3_supported17':
                row.update(witnesses=witnesses,unresolved_record_ids=unresolved,
                    old_fixed_configuration_correct=banks[name][case]['fixed_configuration_correct'])
            rows[name].append(row)
    summary={}
    for name,records in rows.items():
        metrics={}
        for metric in ['raw16','legacy_eligible16']:
            totals={};differences={}
            for arm in ['shape','strict','may']:
                flat=[dict(source_pool_available=r['source_pool_available'],metric=r['arms'][arm][metric]) for r in records]
                totals[arm]=aggregate(flat,'metric')
                differences[arm]=dict(gains=[r['case'] for r in records if r['arms'][arm][metric]['hit_at_budget'] and not r['arms']['shape'][metric]['hit_at_budget']],
                    losses=[r['case'] for r in records if not r['arms'][arm][metric]['hit_at_budget'] and r['arms']['shape'][metric]['hit_at_budget']])
            tasks=[]
            for task in sorted({r['task'] for r in records}):
                subset=[r for r in records if r['task']==task]
                tasks.append(dict(task=task,trials=[r['case'] for r in subset],available=any(r['source_pool_available'] for r in subset),
                    hits={arm:dict(any_trial=any(r['arms'][arm][metric]['hit_at_budget'] for r in subset),
                        all_trials=all(r['arms'][arm][metric]['hit_at_budget'] for r in subset)) for arm in totals}))
            metrics[metric]=dict(trials=totals,versus_shape=differences,tasks=tasks,
                task_totals={arm:dict(any_trial_hits=sum(t['hits'][arm]['any_trial'] for t in tasks),
                    all_trials_hits=sum(t['hits'][arm]['all_trials'] for t in tasks),all_task_denominator=len(tasks),
                    available_task_denominator=sum(t['available'] for t in tasks)) for arm in totals})
        semantic=[r for r in records if r['requires_semantic_revision']]
        summary[name]=dict(metrics=metrics,semantic5={m:{a:dict(hits=sum(r['arms'][a][m]['hit_at_budget'] for r in semantic),denominator=len(semantic))
            for a in ['shape','strict','may']} for m in ['raw16','legacy_eligible16']})
    value=dict(version='patch-observation-priority-posthoc-v1',role='independent_evaluator_only',
        source_audit=audit,generation_code_commit='7615f4e',evaluator_script_sha256=digest(Path(__file__)),
        evaluator_inputs_sha256=inputs,cases=rows,summary=summary,
        matching='Exact reconstructed original input-program owner bytes, same base test, and full added import bindings; original assertions restored. Historical bank uses previously sealed exact material IDs.',
        provider_calls=0,subject_executions=0,old_main_score=dict(confirmed=16,denominator=17,unchanged=True),
        limits=['Static exposure is not new oracle quality, native failure, patch repair, or hidden-test success.',
            'raw16 and legacy_eligible16 are source rank metrics; the current main CLI uses its actual prepare_requests eligibility and is a different prefix.',
            'The 17 trials cover 14 previously studied tasks; this is not blind generalization.',
            'Task any/all figures are descriptive; repeated tasks receive separate per-trial budgets.',
            'Only previously fixed witness programs are matched; alternative equivalent successful witnesses are not enumerated.',
            'A source may-path is not path feasibility, observed execution, expected-value correctness or bug proof.'])
    if any(digest(path)!=sha for path,sha in inputs.items()):raise ValueError('evaluator_inputs_changed')
    output.mkdir(parents=True,exist_ok=False)
    (output/'review.json').write_text(json.dumps(value,sort_keys=True,ensure_ascii=False,indent=2)+'\n')
    return summary


if __name__ == '__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--historical-matching',type=Path)
    parser.add_argument('--checkpoint',type=Path)
    args=parser.parse_args()
    if args.historical_matching or args.checkpoint:
        if not args.historical_matching or not args.checkpoint:parser.error('both evaluator target banks are required')
        print(json.dumps(evaluate(args.input,args.historical_matching,args.checkpoint,args.output),sort_keys=True))
        raise SystemExit(0)
    audit=verify_seal(args.input)
    audit['evaluator_script_sha256']=digest(Path(__file__))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(audit,sort_keys=True,indent=2)+'\n')
    print(json.dumps(audit,sort_keys=True))
