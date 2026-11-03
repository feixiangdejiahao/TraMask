#!/usr/bin/env python3
"""Score retained source spans against the separately frozen manual anchors."""
from collections import Counter
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from eviweave.artifacts import read_json, write_json
from eviweave.issue_filter import guide_query, rank_lexical

RUN = ROOT / 'results/behavioral_masking/20261031_issue_history_filter_n16_r02'


def retained_anchors(ids, anchors, *, cited_only=False):
    selected = set(ids)
    return [a['anchor_id'] for a in anchors if any(
        set(option['record_ids']) <= selected and (not cited_only or option['cited_action'])
        for option in a['alternatives'])]


def measure(ids, anchors, records):
    selected = set(ids)
    located = [a for a in anchors if a['locatable']]
    found = retained_anchors(ids, located)
    return {'selected_records': len(selected), 'selected_characters': sum(len(records[i]['text']) for i in selected),
            'eligible_anchors': len(located), 'recovered_anchors': len(found), 'recovered_ids': found,
            'recall': len(found) / len(located) if located else None,
            'all_cited_material_preserved': len(found) == len(located) if located else None,
            'cited_action_recovered': retained_anchors(ids, located, cited_only=True),
            'missed_ids': [a['anchor_id'] for a in located if a['anchor_id'] not in found]}


def read_selection(phase, sid, supplied):
    content = (RUN / 'calls' / phase / sid / 'completion.txt').read_text()
    try:
        value = json.loads(content)
    except json.JSONDecodeError:
        return None, ['empty_completion' if not content else 'invalid_json_completion'], []
    keep, ranked = value['keep_ids'], value['ranked_ids']
    errors = []
    if set(ranked) - supplied:
        errors.append('unknown_record_ids')
    if len(ranked) != len(set(ranked)):
        errors.append('duplicate_record_ids')
    if len(ranked) > 40:
        errors.append('more_than_40_ranked_records')
    keep_errors = []
    if set(keep) - supplied or len(keep) != len(set(keep)):
        keep_errors.append('invalid_keep_ids')
    if set(ranked) - set(keep):
        keep_errors.append('ranked_records_not_in_keep')
    return value, errors, keep_errors


def main():
    cases = read_json(RUN / 'cases.json')
    rows = []
    for case in cases:
        sid = case['case_id']
        records = {r['id']: r for r in read_json(RUN / 'cases' / sid / 'records.json')}
        anchors = read_json(RUN / 'evaluation/resolved_anchors' / (sid + '.json'))
        rankings = {'all_history': list(records),
                    'issue_lexical': read_json(RUN / 'cases' / sid / 'issue_lexical.json'),
                    'C_guide_lexical': read_json(RUN / 'cases' / sid / 'guide_lexical.json')}
        keep_sets, output_errors, keep_errors = {}, {}, {}
        for phase, name in [('early', 'early_issue_LLM'), ('late', 'late_patch_LLM'),
                            ('late_material', 'late_material_LLM'), ('late_no_C', 'late_no_C_LLM')]:
            pool_file = {'early': 'late_pool.json', 'late': 'late_pool.json',
                         'late_material': 'late_material_pool.json', 'late_no_C': 'late_no_C_pool.json'}[phase]
            supplied = set(records) if phase == 'early' else set(read_json(RUN / 'cases' / sid / pool_file))
            selected, errors, inconsistent = read_selection(phase, sid, supplied)
            output_errors[name] = errors
            keep_errors[name] = inconsistent
            if not errors:
                rankings[name] = selected['ranked_ids']
                keep_sets[name] = measure(selected['keep_ids'], anchors, records)
        cutoffs = {}
        for name, ranked in rankings.items():
            cutoffs[name] = {str(k): measure(ranked[:k], anchors, records) for k in (8, 16, 24, 40)}
            prefix, total = [], 0
            for identity in ranked:
                if total + len(records[identity]['text']) > 50000:
                    break
                prefix.append(identity)
                total += len(records[identity]['text'])
            cutoffs[name]['50000_characters'] = measure(prefix, anchors, records)
        # Failed model responses remain failures in the fixed-sample summary.
        # This is a measured output failure, not a replacement model selection.
        for name, errors in output_errors.items():
            if errors:
                cutoffs[name] = {cutoff: {**measure([], anchors, records), 'model_output_failure': errors}
                                 for cutoff in ('8', '16', '24', '40', '50000_characters')}
        guide = read_json(RUN / 'calls/requirements' / sid / 'parsed.json')
        issue = re.sub(r'\s+', ' ', (RUN / 'cases' / sid / 'issue.md').read_text())
        quotes = [{'id': q['id'], 'quote_in_issue': re.sub(r'\s+', ' ', q['quote']) in issue}
                  for q in guide['requirements']]
        material = [r for r in records.values() if any(o['kind'] in {'command', 'stdout', 'written_code'} for o in r['origins'])]
        sensitivity = {}
        for label, query in [('issue', issue), ('C', guide_query(guide))]:
            ranked = rank_lexical(material, query)
            sensitivity[label] = {str(k): measure(ranked[:k], anchors, records) for k in (24, 40)}
        rows.append({**case, 'located_anchors': sum(a['locatable'] for a in anchors),
                     'unavailable_anchors': [{k: a[k] for k in ('anchor_id', 'fragment_id', 'code', 'step_id')}
                                             for a in anchors if not a['locatable']],
                     'cutoffs': cutoffs, 'hard_keep': keep_sets, 'output_errors': output_errors, 'keep_consistency_errors': keep_errors,
                     'late_pool_upper_bound': measure(read_json(RUN / 'cases' / sid / 'late_pool.json'), anchors, records),
                     'material_pool_upper_bound': measure(read_json(RUN / 'cases' / sid / 'late_material_pool.json'), anchors, records),
                     'no_C_pool_upper_bound': measure(read_json(RUN / 'cases' / sid / 'late_no_C_pool.json'), anchors, records),
                     'material_only_lexical_diagnostic': sensitivity,
                     'guide': {'requirements': len(guide['requirements']),
                               'interaction_questions': len(guide['interaction_questions']), 'quotes': quotes}})
    aggregate = {}
    names = ['issue_lexical', 'C_guide_lexical', 'early_issue_LLM', 'late_patch_LLM', 'late_material_LLM', 'late_no_C_LLM']
    for group in ('all', 'seeded_sample', 'diagnostic'):
        grouped = [r for r in rows if group == 'all' or r['group'] == group]
        aggregate[group] = {}
        for name in names:
            aggregate[group][name] = {}
            for cutoff in ('8', '16', '24', '40', '50000_characters'):
                cells = [r['cutoffs'][name][cutoff] for r in grouped if name in r['cutoffs']]
                eligible = [c for c in cells if c['eligible_anchors']]
                denominator = sum(c['eligible_anchors'] for c in eligible)
                aggregate[group][name][cutoff] = {
                    'cases': len(cells), 'eligible_cases': len(eligible),
                    'recovered_anchors': sum(c['recovered_anchors'] for c in eligible),
                    'eligible_anchors': denominator,
                    'micro_recall': sum(c['recovered_anchors'] for c in eligible) / denominator,
                    'macro_recall': sum(c['recall'] for c in eligible) / len(eligible),
                    'all_cited_material_cases': sum(c['all_cited_material_preserved'] for c in eligible),
                    'retained_character_fraction': sum(c['selected_characters'] for c in cells) /
                        sum(r['characters'] for r in grouped if name in r['cutoffs'])}
    usage = []
    for path in sorted((RUN / 'calls').rglob('usage.json')):
        value = read_json(path)
        usage.append({'phase': path.parent.parent.name, 'case_or_batch': path.parent.name, **value})
    by_phase = {}
    for phase in ('requirements', 'early', 'late', 'late_material', 'late_no_C', 'audit'):
        selected = [r for r in usage if r['phase'] == phase]
        by_phase[phase] = {'calls': len(selected), **{
            field: sum(r['usage'][field] for r in selected)
            for field in ('prompt_tokens', 'completion_tokens', 'total_tokens')}}
    audited = [r for path in sorted((RUN / 'calls/audit').glob('*/parsed.json')) for r in read_json(path)['cases']]
    audited.extend(r for path in sorted((RUN / 'evaluation/audit_transcriptions').glob('*.json'))
                   for r in read_json(path)['cases'])
    audited.sort(key=lambda row: row['case_id'])
    assert [r['case_id'] for r in audited] == [f'S{i:03d}' for i in range(1, 89)]
    for edit in read_json(RUN / 'evaluation/issue_quote_corrections.json')['corrections']:
        row = next(r for r in audited if r['case_id'] == edit['case_id'])
        row['issue_quotes'] = [edit['to'] if quote == edit['from'] else quote for quote in row['issue_quotes']]
    hard_keep = {}
    for name in ('early_issue_LLM', 'late_patch_LLM', 'late_material_LLM', 'late_no_C_LLM'):
        cells = [r['hard_keep'][name] for r in rows if name in r['hard_keep']]
        hard_keep[name] = {'responses_with_keep_list': len(cells),
                          'recovered_anchors': sum(c['recovered_anchors'] for c in cells),
                          'fixed_sample_eligible_anchors': sum(r['located_anchors'] for r in rows),
                          'all_cited_material_cases': sum(c['all_cited_material_preserved'] is True for c in cells),
                          'retained_character_fraction': sum(c['selected_characters'] for c in cells) / sum(r['characters'] for r in rows)}
    result = {'cases': rows, 'aggregate': aggregate, 'hard_keep': hard_keep,
              'late_pool': {'recovered_anchors': sum(r['late_pool_upper_bound']['recovered_anchors'] for r in rows),
                            'eligible_anchors': sum(r['located_anchors'] for r in rows)},
              'material_pool': {'recovered_anchors': sum(r['material_pool_upper_bound']['recovered_anchors'] for r in rows),
                                'eligible_anchors': sum(r['located_anchors'] for r in rows)},
              'no_C_pool': {'recovered_anchors': sum(r['no_C_pool_upper_bound']['recovered_anchors'] for r in rows),
                            'eligible_anchors': sum(r['located_anchors'] for r in rows)},
              'provider_usage': by_phase,
              'response_models': dict(Counter(r['response_model'] for r in usage)),
              'issue_correspondence': {'rows': audited,
                  'support_counts': dict(Counter(r['issue_support'] for r in audited)),
                  'guide_coverage_counts': dict(Counter(r['guide_coverage'] for r in audited if r['guide_coverage'] != 'not_supplied'))},
              'all_history_baseline': {'cases': len(cases), 'eligible_anchors': sum(r['located_anchors'] for r in rows),
                                       'recall': 1.0, 'retained_character_fraction': 1.0},
              'scope': 'Retention of manually cited literal evidence available in original trajectory; not generated-test correctness or bug detection.'}
    write_json(RUN / 'analysis/results.json', result)
    write_json(RUN / 'analysis/usage.json', usage)
    print(json.dumps({'aggregate': aggregate['all'], 'provider_usage': by_phase,
                      'issue_support': result['issue_correspondence']['support_counts']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
