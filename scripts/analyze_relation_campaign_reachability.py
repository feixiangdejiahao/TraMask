"""Read-only diagnosis of where previously confirmed witness inputs disappear.

This evaluator never imports or calls generation, ranking, providers, or runners.
Historical IDs locate evidence; stage matching uses the original source test,
materialized edits and import bindings.  Input and assertion identities are
tracked separately.  A named pass/fail report is required for actual execution.
This measures reachability of known witnesses, not semantic correctness of new
tests, and unfinished cases are never classified as misses.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.evaluate_relational_gap import matches_runtime, runtime_tests


def read(path):
    return json.loads(Path(path).read_text())


def sha(value):
    return hashlib.sha256(value).hexdigest()


def canonical(value):
    return sha(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def frozen(path):
    path = Path(path)
    return dict(path=str(path.resolve()), sha256=sha(path.read_bytes()))


def candidate_rows(value):
    """Read candidate objects from old list, wrapper and oracle result formats."""
    if isinstance(value, dict):
        if {'id', 'base_test_id', 'edits'} <= value.keys():
            yield value
            return
        for item in value.values():
            yield from candidate_rows(item)
    elif isinstance(value, list):
        for item in value:
            yield from candidate_rows(item)


class MaterialIdentity:
    def __init__(self, corpus):
        self.corpus = corpus
        self.bases = {}

    def base(self, identifier):
        if identifier not in self.bases:
            test = self.corpus['tests'][identifier]
            span = test['span']
            path = span['path']
            source = self.corpus['sources'][path]['code'].encode()
            start, end = span['start_byte'], span['end_byte']
            identity = dict(test_id=identifier, path=path, start_byte=start, end_byte=end,
                            source_sha256=sha(source), original_body_sha256=sha(source[start:end]))
            self.bases[identifier] = identity, source[start:end]
        return self.bases[identifier]

    def signature(self, candidate, include_expected=False):
        identity, original = self.base(candidate['base_test_id'])
        edits = candidate.get('program_edits', candidate['edits'])
        edits = [row for row in edits if row.get('role') != 'relation_runtime_probe'
                 and (include_expected or row.get('role') != 'semantic_expected')]
        operations = []
        for edit in edits:
            span = edit['span']
            a, b = span['start_byte'], span['end_byte']
            if (span['path'] != identity['path'] or
                    not identity['start_byte'] <= a <= b <= identity['end_byte']):
                raise ValueError('edit_outside_original_base_test')
            a, b = a-identity['start_byte'], b-identity['start_byte']
            if original[a:b].decode() != edit['before']:
                raise ValueError('edit_before_does_not_match_source')
            operations.append((a, b, edit['after']))
        operations.sort(key=lambda item: (item[0], item[1]))
        for left, right in zip(operations, operations[1:]):
            if left[1] > right[0] or left[0] == left[1] == right[0]:
                raise ValueError('overlapping_program_edits')
        body = original
        for a, b, after in reversed(operations):
            body = body[:a] + after.encode() + body[b:]
        bindings = [{key: value for key, value in item.items()
                     if key in {'name', 'module', 'imported_name', 'source_path', 'kind', 'namespace'}}
                    for item in candidate.get('imports', [])]
        bindings.sort(key=lambda item: json.dumps(item, sort_keys=True))
        return canonical(dict(base=identity, body_sha256=sha(body), imports=bindings))


def historical_candidates(roots, wanted):
    records = defaultdict(list)
    for root in roots:
        for path in sorted(Path(root).rglob('*.json')):
            if path.is_symlink() or any(part.startswith('uniform_') or part in
                                       {'algorithm_snapshot', 'evaluation'} for part in path.parts):
                continue
            if not ('candidate' in path.name or path.name == 'validation.json'
                    or re.fullmatch(r'[NP]\d+\.json', path.name)):
                continue
            for row in candidate_rows(read(path)):
                if row['id'] in wanted:
                    records[row['id']].append((row, path))
    return records


def reference_catalog(checkpoint, prior_checkpoint, source_root, search_roots):
    current, previous = read(checkpoint), read(prior_checkpoint)
    confirmed = {(row['case'], row['id']) for row in
                 [*previous['deliveries'], *current['fresh_evaluation']['deliveries']]
                 if row['controlled_target_detection']}
    wanted = {identifier for row in current['cases']
              for identifier in [*row['inherited_ids'], *row['fresh_correct_ids']]}
    found = historical_candidates(search_roots, wanted)
    catalog = []
    for row in current['cases']:
        case = row['case']
        corpus_path = source_root/case/'corpus.json'
        identity = MaterialIdentity(read(corpus_path))
        witnesses = []
        for identifier in sorted(set(row['inherited_ids']+row['fresh_correct_ids'])):
            if (case, identifier) not in confirmed:
                raise ValueError('Witness lacks prior controlled detection: '+case+'/'+identifier)
            variants, rejected = {}, []
            for candidate, path in found.get(identifier, []):
                try:
                    program = identity.signature(candidate)
                    complete = identity.signature(candidate, include_expected=True)
                except (ValueError, KeyError, TypeError) as error:
                    rejected.append(dict(path=str(path), reason=str(error)))
                    continue
                key = (program, complete)
                if key not in variants:
                    variants[key] = dict(program_signature=program, complete_signature=complete,
                        base_test_id=candidate['base_test_id'],
                        program_parent_id=candidate.get('semantic_revision', {}).get('parent', identifier),
                        semantic_revision=bool(candidate.get('semantic_revision')), sources=[])
                variants[key]['sources'].append({**frozen(path), 'candidate_sha256': canonical(candidate)})
            witnesses.append(dict(id=identifier, status='resolved' if len(variants) == 1 else
                                  'unresolved' if not variants else 'ambiguous',
                                  variants=list(variants.values()), rejected=rejected))
        catalog.append(dict(case=case, source_corpus=frozen(corpus_path), witnesses=witnesses))
    return catalog


def read_candidates(path):
    return list(candidate_rows(read(path))) if path.exists() else []


def classify_loss(stages, complete, resolved=True):
    if not complete:
        return None, 'case_incomplete_no_miss_classification'
    if not resolved:
        return 'reference_unresolved', 'historical_candidate_identity_not_unique'
    reasons = [
        ('source_pool', 'program_input_not_proposed_in_any_completed_round'),
        ('selected', 'program_input_proposed_but_not_selected_within_round_budget'),
        ('semantic_input', 'selected_program_input_absent_after_semantic_stage'),
        ('semantic_complete', 'input_selected_but_confirmed_assertion_variant_absent'),
        ('emitted_complete', 'confirmed_test_not_admitted_to_runnable_emission'),
        ('executed_complete', 'admitted_test_has_no_named_pass_or_fail_outcome'),
    ]
    for stage, reason in reasons:
        if not stages[stage]:
            return stage, reason
    return None, 'confirmed_material_variant_reached_named_execution'


def round_index(folder, identity):
    """Return content signatures and actual named outcomes, without verdicts."""
    index = {stage: defaultdict(list) for stage in
             ['source_pool', 'selected', 'semantic_input', 'semantic_complete',
              'emitted_input', 'emitted_complete', 'executed_input', 'executed_complete']}
    errors, evidence = [], []
    documents = [('source_pool', folder/'prepared/source_pool.json'),
                 ('selected', folder/'prepared/candidates.json'),
                 ('semantic_input', folder/'semantic/candidates.json')]
    for stage, path in documents:
        if not path.exists():
            continue
        evidence.append(frozen(path))
        for rank, candidate in enumerate(read_candidates(path), 1):
            if candidate.get('is_source_profile'):
                continue
            try:
                info = dict(id=candidate['id'], rank=rank, round=folder.name,
                            path=str(path.resolve()), base_test_id=candidate['base_test_id'])
                index[stage][identity.signature(candidate)].append(info)
                if stage == 'semantic_input':
                    index['semantic_complete'][identity.signature(candidate, True)].append(info)
            except (ValueError, KeyError, TypeError) as error:
                errors.append(dict(stage=stage, id=candidate['id'], error=str(error)))
    accepted_path = folder/'emitted/accepted.json'
    accepted = {row['id']: row for row in read_candidates(accepted_path)}
    if accepted_path.exists():
        evidence.append(frozen(accepted_path))
    emitted = set()
    rejections = []
    for path in sorted((folder/'emitted').glob('group_*/emission.json')):
        value = read(path)
        rejections.extend(value.get('unsupported', []))
        manifest = path.parent/'manifest.json'
        if manifest.exists():
            evidence.append(frozen(manifest))
            emitted.update(row['candidate_id'] for row in read(manifest).get('obligations', []))
        unsupported = path.parent/'unsupported.json'
        if unsupported.exists():
            rejections.append(dict(group=path.parent.name, harness=read(unsupported),
                                   ids=[row['candidate_id'] for row in value.get('obligations', [])]))
    for identifier in sorted(emitted):
        candidate = accepted.get(identifier)
        if candidate is None or candidate.get('is_source_profile'):
            continue
        try:
            info = dict(id=identifier, round=folder.name, path=str(accepted_path.resolve()))
            index['emitted_input'][identity.signature(candidate)].append(info)
            index['emitted_complete'][identity.signature(candidate, True)].append(info)
        except (ValueError, KeyError, TypeError) as error:
            errors.append(dict(stage='emitted', id=identifier, error=str(error)))
    runs_path = folder/'executed/runs.json'
    indexed = []
    reports = {}
    if runs_path.exists():
        evidence.append(frozen(runs_path))
        for run in read(runs_path):
            if run.get('role') != 'generated' or run.get('candidate_id') not in accepted:
                continue
            candidate = accepted[run['candidate_id']]
            if candidate.get('is_source_profile'):
                continue
            result = Path(run['result'])
            if result not in reports:
                reports[result] = runtime_tests(result)
                evidence.extend(frozen(path) for path in reports[result][2])
            tests, report_errors, _ = reports[result]
            requested = run.get('test_ids', [])
            selected = [test for test in tests if any(matches_runtime(test['id'], name) for name in requested)]
            actual = [test for test in selected if test['status'] in {'pass', 'fail'}]
            info = dict(id=candidate['id'], round=folder.name, path=str(runs_path.resolve()),
                        result=str(result.resolve()), requested_test_ids=requested, named_tests=selected,
                        report_errors=report_errors, actual_execution=bool(actual))
            try:
                program, full = identity.signature(candidate), identity.signature(candidate, True)
            except (ValueError, KeyError, TypeError) as error:
                errors.append(dict(stage='executed', id=candidate['id'], error=str(error)))
                continue
            indexed.append({**info, 'program_signature': program, 'complete_signature': full})
            if actual:
                index['executed_input'][program].append(info)
                index['executed_complete'][full].append(info)
    return dict(index=index, errors=errors, indexed_runs=indexed, materialization_rejections=rejections,
                evidence_files=list({row['path']: row for row in evidence}.values()))


def analyze(campaign, catalog):
    configuration = read(campaign/'configuration.json')
    completed_rows = {row['case']: row for row in read(campaign/'campaign.json')} if (campaign/'campaign.json').exists() else {}
    results, matches = [], []
    for reference in catalog:
        case = reference['case']
        source = Path(configuration['source_root'])/case/'corpus.json'
        if sha(source.read_bytes()) != reference['source_corpus']['sha256']:
            raise ValueError('Campaign/source witness corpus mismatch: '+case)
        identity = MaterialIdentity(read(source))
        folder = campaign/case
        rounds = [round_index(path, identity) for path in sorted(folder.glob('round_*'))]
        completion = completed_rows.get(case, {})
        complete = (len(completion.get('rounds', [])) == configuration['rounds'])
        if completion.get('stopped_reason') == 'exhausted':
            exhausted = completion.get('exhausted_prepare', completion.get('exhausted_prepare_manifest'))
            complete = bool(exhausted) and not read_candidates(Path(exhausted).parent/'candidates.json')
        witnesses = []
        for witness in reference['witnesses']:
            stages = {stage: [] for stage in ['source_pool', 'selected', 'semantic_input', 'semantic_complete',
                        'emitted_input', 'emitted_complete', 'executed_input', 'executed_complete']}
            indexed_runs = []
            if witness['status'] == 'resolved':
                variant = witness['variants'][0]
                for measured in rounds:
                    for stage in stages:
                        signature = variant['complete_signature' if stage.endswith('_complete') else 'program_signature']
                        stages[stage].extend(measured['index'][stage].get(signature, []))
                    indexed_runs.extend(row for row in measured['indexed_runs']
                                        if row['program_signature'] == variant['program_signature'])
                for run in indexed_runs:
                    matches.append(dict(case=case, reference_id=witness['id'],
                        complete_signature_matches=run['complete_signature'] == variant['complete_signature'], **run))
            lost, reason = classify_loss(stages, complete, witness['status'] == 'resolved')
            witnesses.append(dict(reference_id=witness['id'], reference_status=witness['status'],
                                  stages=stages, earliest_lost_stage=lost, reason=reason,
                                  indexed_matching_inputs=indexed_runs))
        reachable = any(row['stages']['executed_complete'] for row in witnesses)
        if reachable:
            lost, reason = None, 'at_least_one_confirmed_material_variant_reached_named_execution'
        elif not complete:
            lost, reason = None, 'case_incomplete_no_miss_classification'
        else:
            order = ['reference_unresolved', 'source_pool', 'selected', 'semantic_input',
                     'semantic_complete', 'emitted_complete', 'executed_complete']
            best = max(witnesses, key=lambda row: order.index(row['earliest_lost_stage']))
            lost, reason = best['earliest_lost_stage'], best['reason']
        results.append(dict(case=case, campaign_status='completed' if complete else 'in_progress' if folder.exists() else 'not_started',
                            known_witness_reached_execution=reachable, earliest_lost_stage=lost, reason=reason,
                            witnesses=witnesses, stage_errors=[row for current in rounds for row in current['errors']],
                            materialization_rejections=[row for current in rounds for row in current['materialization_rejections']],
                            evidence_files=list({row['path']: row for current in rounds
                                                for row in current['evidence_files']}.values())))
    return dict(created_utc=datetime.now(timezone.utc).isoformat(), campaign=str(campaign.resolve()),
                configuration=frozen(campaign/'configuration.json'), evaluator=frozen(Path(__file__)),
                interpretation='Known-witness reachability only; full material identity and named outcomes do not independently certify semantics or failure cause.',
                limits=['Identity applies recorded program edits to the frozen original seed; runtime probes and generated registration names are excluded.',
                        'Independent campaign evaluation must verify emitted-file and execution receipts, source controls, oracle validity and failure cause.',
                        'An absent known witness does not prove that every possible correct combination is absent.'],
                counts=dict(completed=sum(row['campaign_status'] == 'completed' for row in results),
                    completed_reached=sum(row['campaign_status'] == 'completed' and row['known_witness_reached_execution'] for row in results),
                    pending=sum(row['campaign_status'] != 'completed' for row in results),
                    completed_earliest_losses=dict(Counter(row['earliest_lost_stage'] for row in results
                        if row['campaign_status'] == 'completed' and row['earliest_lost_stage']))),
                references=catalog, cases=results, matching_executions_for_review=matches)


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--checkpoint', type=Path, default=ROOT/'results/relation_search_20260929/evaluation/checkpoint_07.json')
    parser.add_argument('--prior-checkpoint', type=Path, default=ROOT/'results/relation_search_20260928/evaluation/checkpoint_08_evaluation.json')
    parser.add_argument('--source-root', type=Path, default=ROOT/'results/relational_gap_20260928/batch7')
    parser.add_argument('--reference-root', action='append', type=Path)
    args = parser.parse_args()
    roots = args.reference_root or [ROOT/'results/relation_search_20260928',
                                   ROOT/'results/relation_search_20260929', args.source_root]
    catalog = reference_catalog(args.checkpoint, args.prior_checkpoint, args.source_root, roots)
    result = analyze(args.campaign, catalog)
    result['reference_checkpoints'] = [frozen(args.checkpoint), frozen(args.prior_checkpoint)]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name+'.tmp')
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True)+'\n')
    temporary.replace(args.output)
    print(json.dumps(result['counts'], sort_keys=True))
    for row in result['cases']:
        print(row['case'], row['campaign_status'], row['earliest_lost_stage'] or row['reason'])


if __name__ == '__main__':
    main()
