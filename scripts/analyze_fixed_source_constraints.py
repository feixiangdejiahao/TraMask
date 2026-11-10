#!/usr/bin/env python3
"""Recount fixed-source policies against the reviewed alternative material sets."""
import argparse
import csv
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path


CODE = {'agent_validation', 'temporary_probe', 'repo_test'}
AGENT = {'agent_validation', 'temporary_probe'}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    source = args.source
    output = args.output
    index = json.loads((source / 'case_index.json').read_text())
    reviews = {entry['case']: json.loads((source / 'cases' / entry['case'] / 'manual_review.json').read_text())
               for entry in index}
    materials = {sid: {m['id']: m for m in review['materials']} for sid, review in reviews.items()}
    recipes = {sid: {r['id']: r for r in review['recipes']} for sid, review in reviews.items()}
    with (source / 'source_groups.tsv').open(newline='') as stream:
        original = list(csv.DictReader(stream, delimiter='\t'))
    supported_families = {(sid, g['id']) for sid, review in reviews.items()
                          for g in review['evaluation_families'] if g['verifier_validity'] == 'supported'}
    supported = []
    for row in original:
        if row['verifier_validity'] != 'supported':
            continue
        mids = row['materials'].split(',')
        counts = Counter(materials[row['case']][mid]['kind'] for mid in mids)
        supported.append({**row, 'material_ids': mids, 'kind_counts': dict(counts),
                          'code_units': sorted(mid for mid in mids if materials[row['case']][mid]['kind'] in CODE),
                          'attachments': sorted(mid for mid in mids if materials[row['case']][mid]['kind'] not in CODE),
                          'all_materials_in_trajectory': row['all_materials_in_trajectory'] == 'True'})
    assert len(supported) == 5741
    available_families = {(r['case'], r['gap']) for r in supported}
    no_av = {sid for sid, ms in materials.items() if not any(m['kind'] == 'agent_validation' for m in ms.values())}
    policies = {}

    def policy(name, rows, meaning):
        families = {(r['case'], r['gap']) for r in rows}
        policies[name] = {'meaning': meaning, 'source_sets': len(rows),
                          'source_sets_removed_fraction': 1 - len(rows) / len(supported),
                          'families': len(families), 'cases': len({r['case'] for r in rows}),
                          'families_missing_of_150': [list(k) for k in sorted(supported_families - families)],
                          'additional_families_lost_of_148': [list(k) for k in sorted(available_families - families)],
                          'retained_group_ids': [r['group_id'] for r in rows]}

    policy('all_supported', supported, 'All recorded qualified source sets, including source-derived constructions without a test/probe.')
    for kind in sorted(CODE):
        rows = [r for r in supported if r['kind_counts'].get(kind, 0)]
        policy('contains_' + kind, rows, 'At least one material of this kind; presence alone does not prove a suitable directed test host.')
    for name, kinds in [('contains_agent_check', AGENT), ('contains_any_code', CODE)]:
        rows = [r for r in supported if any(r['kind_counts'].get(k, 0) for k in kinds)]
        policy(name, rows, 'Keep a code carrier from these kinds; preserve all original attachments and constraints.')
    preferred = [r for r in supported if r['kind_counts'].get('temporary_probe' if r['case'] in no_av else 'agent_validation', 0)]
    policy('agent_test_else_probe_at_case_level', preferred,
           'Use agent_validation if any such material exists in this case inventory; otherwise temporary_probe. This is evaluated on the manually relevant inventory, not the full A/B candidate stream.')
    first_slot = []
    for row in preferred:
        sid = row['case']
        mids = set(row['material_ids'])
        anchor = 'temporary_probe' if sid in no_av else 'agent_validation'
        if any(any(set(option) <= mids and any(materials[sid][mid]['kind'] == anchor for mid in option)
                   for option in recipes[sid][rid]['slots'][0]['alternatives'])
               for rid in row['recipes'].split(',') if recipes[sid][rid]['qualification'] != 'incomplete'):
            first_slot.append(row)
    policy('preferred_kind_in_first_recipe_slot', first_slot,
           'Descriptive host warning screen using author slot order only, not a production criterion or proof that the source is a runnable host. Inspect excluded roles manually.')
    allowed = CODE | {'issue_or_documentation'}
    literal = [r for r in supported if set(r['kind_counts']) <= allowed]
    policy('literal_code_and_issue_only', literal,
           'Delete any recorded set with implementation, reasoning, fixture/snapshot or output. This tests literal recipe retention, not semantic impossibility.')
    attachment_review = json.loads((output / 'attachment_interpretations.json').read_text())
    lost = available_families - {(r['case'], r['gap']) for r in literal}
    assert {tuple(key.split('/')) for key in attachment_review} == lost
    for limit in [1, 2, 3, 4, 5]:
        rows = [r for r in supported if any(r['kind_counts'].get(k, 0) for k in AGENT) and len(r['code_units']) <= limit]
        policy(f'agent_check_at_most_{limit}_code_units', rows,
               'Require an Agent test/probe carrier and limit distinct code source units; do not constrain attachments. Source-unit count is not semantic-factor count.')

    projections = defaultdict(list)
    for row in supported:
        projections[row['case'], row['gap'], tuple(row['code_units'])].append(row)
    projection_rows = [{'case': key[0], 'gap': key[1], 'code_units': list(key[2]),
                        'original_group_ids': [r['group_id'] for r in rows],
                        'attachment_alternatives': [{'group_id': r['group_id'], 'materials': r['attachments'],
                                                     'recipes': r['recipes'], 'qualification': r['qualification']}
                                                    for r in rows]}
                       for key, rows in sorted(projections.items())]
    summary = {'source': str(source), 'cohort_cases': 88, 'supported_cases': 84,
               'supported_families': len(supported_families), 'families_with_materials': len(available_families),
               'supported_source_sets': len(supported),
               'cases_without_agent_validation_materials': sorted(no_av),
               'material_inventory_counts': dict(Counter(m['kind'] for ms in materials.values() for m in ms.values())),
               'targeted_attachment_review': {'additional_lost_families_reviewed': len(attachment_review),
                                              'categories': dict(Counter(row[0] for row in attachment_review.values())),
                                              'record': 'attachment_interpretations.json',
                                              'meaning': 'All 30 newly lost literal-recipe families were read at the recipe/material level; this is not another full-trajectory reading or generation validation.'},
               'policies': {name: {k: v for k, v in row.items() if k != 'retained_group_ids'} for name, row in policies.items()},
               'code_carrier_projection': {'groups': len(projections), 'with_code': sum(bool(key[2]) for key in projections),
                                           'meaning': 'Exact code-material-ID projection; all attachment alternatives and source-group memberships retained. This is not behavior equivalence or production search-cost measurement.'},
               'interpretation': 'Recorded source availability only. None of the retained sets is newly generated/executed here. At-least-one-kind counts do not by themselves establish a directed runnable host, and source-set reductions are not production candidate-search reductions.'}
    write_json(output / 'summary.json', summary)
    write_json(output / 'retained_groups.json', policies)
    with gzip.open(output / 'code_carrier_projection.json.gz', 'wt', encoding='utf-8') as stream:
        json.dump(projection_rows, stream, ensure_ascii=False, separators=(',', ':'))
    with gzip.open(output / 'source_sets.json.gz', 'wt', encoding='utf-8') as stream:
        json.dump(supported, stream, ensure_ascii=False, separators=(',', ':'))
    print(json.dumps({k: v for k, v in summary.items() if k != 'policies'}, ensure_ascii=False, indent=2))
    for name, row in policies.items():
        print(name, row['source_sets'], row['families'], row['cases'])


if __name__ == '__main__':
    main()
