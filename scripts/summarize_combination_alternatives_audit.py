#!/usr/bin/env python3
"""Summarize the reviewed source alternatives, keeping unfinished cases visible."""
import argparse
from collections import Counter
import csv
import gzip
import json
from pathlib import Path

from verify_combination_alternatives_audit import read, verify_case


def table(path, rows, fields):
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter='\t')
        writer.writeheader()
        writer.writerows(rows)


def case_text(review, entry, verification):
    kinds = {'agent_validation': 'Agent验证测试', 'temporary_probe': '临时脚本/操作探针',
             'repo_test': '仓库原有测试', 'implementation': '实现源码',
             'fixture_or_snapshot': '输入/fixture/快照', 'runtime_output': '运行结果',
             'reasoning': 'Agent推理', 'issue_or_documentation': '需求/文档'}
    qualification = {'direct': '直接重用', 'requires_transfer': '需要迁移/连接已有材料',
                     'requires_oracle_inference': '还需要推导正确预期', 'incomplete': '材料不足，不能算可用方案'}
    attempt = {'absent': '未见所需联合刺激的执行', 'weak_oracle': '已执行相关联合刺激，但检查不足或预期错误',
               'weakened': '正确检查后来被削弱', 'full_historical_witness': '历史中已有完整目标场景与正确预期',
               'constituent_missing': '所需组成部分尚缺', 'unknown': '当前记录无法确定'}
    by_id = {m['id']: m for m in review['materials']}
    lines = [f"{review['case_id']}  {entry['task']}",
             f"全文审读：{review['full_read']['steps']}步；原始引文核验{verification['checked_quotes']}条。",
             '材料组是人工分析的可组装方案；是否仍需推导预期、迁移API或补语义，在各方案中单列。', '']
    for gap in review['evaluation_families']:
        lines += [f"{gap['id']}  evaluation失败：", *['  ' + t for t in gap['failed_tests']],
                  '具体测试：' + gap['missing_joint_test'], '任务约定：' + gap['contract'],
                  '历史状态：' + attempt[gap['joint_attempt']],
                  'Verifier约定判断：' + gap['verifier_validity'], '']
        for recipe in (r for r in review['recipes'] if r['gap'] == gap['id']):
            lines.append(f"{recipe['id']}  {qualification[recipe['qualification']]}")
            for slot in recipe['slots']:
                options = []
                for option in slot['alternatives']:
                    options.append(' + '.join(f"{mid}〔{by_id[mid]['unit']}〕" for mid in option))
                lines.append('  需要 ' + slot['role'] + '：' + ' 或 '.join(options))
            lines.append('  如何连接：' + recipe['compatibility'])
            lines += ['  仍需补充：' + addition for addition in recipe['semantic_additions']]
            if recipe['forbidden_pairs']:
                lines.append('  不可同用的材料：' + json.dumps(recipe['forbidden_pairs']))
            lines.append('')
    lines += ['材料出处（精确引文和全部位置见同目录 manual_review.json）：']
    for material in review['materials']:
        locations = []
        for ref in material['refs']:
            location = ref['channel'] + ':' + (ref['path'] if ref['channel'] in {'repo', 'issue'} else str(ref['step']))
            if location not in locations:
                locations.append(location)
        lines.append(f"  {material['id']}  {kinds[material['kind']]}；{material['availability']}；"
                     f"{material['unit']}；出处 {'; '.join(locations)}")
    lines += ['', 'Agent实现过程：']
    for explanation in review['agent_process']['explanations']:
        lines.append(f"  [{explanation['support']}] {explanation['label']}：{explanation['interpretation']}")
    lines += ['', '对旧记录的更正：', *['  ' + text for text in review['prior_record_corrections']],
              '', '待确定事项：', *['  ' + text for text in review['uncertainties']]]
    return '\n'.join(lines) + '\n'


def summarize(run):
    index = read(run / 'case_index.json')
    cases = []
    gaps = []
    materials = []
    process_explanations = []
    patterns = Counter()
    pattern_cases = {}
    code_patterns = Counter()
    code_pattern_cases = {}
    qualifications = Counter()
    best_qualifications = Counter()
    classifications = Counter()
    origins = Counter()
    availability = Counter()
    kinds = Counter()
    used_kinds = Counter()
    all_qualifications = Counter()
    all_best_qualifications = Counter()
    source_routes = {}
    supported_packages = []
    source_groups = []
    group_numbers = Counter()
    code_kinds = {'temporary_probe', 'agent_validation', 'repo_test'}
    pending = []
    for entry in index:
        sid = entry['case']
        directory = run / 'cases' / sid
        if not (directory / 'manual_review.json').exists():
            pending.append(sid)
            continue
        verification = verify_case(directory)
        assert not verification['errors'], (sid, verification['errors'])
        review = read(directory / 'manual_review.json')
        (directory / 'case_review.txt').write_text(case_text(review, entry, verification))
        by_id = {m['id']: m for m in review['materials']}
        with gzip.open(directory / 'source_packages.json.gz', 'rt', encoding='utf-8') as stream:
            packages = json.load(stream)
        with gzip.open(directory / 'reviewed_source_packages.json.gz', 'rt', encoding='utf-8') as stream:
            reviewed_packages = json.load(stream)
        reviewed_qualified = [p for p in reviewed_packages if any(q != 'incomplete' for _, q in p['recipes'])]
        qualified = [p for p in packages if any(q != 'incomplete' for _, q in p['recipes'])]
        trace_only = [p for p in qualified if all(by_id[mid]['availability'] not in {'repo_unseen', 'unknown'}
                                                  for mid in p['materials'])]
        reviewed_trace_only = [p for p in reviewed_qualified
                               if all(by_id[mid]['availability'] not in {'repo_unseen', 'unknown'}
                                      for mid in p['materials'])]
        gap_by_id = {gap['id']: gap for gap in review['evaluation_families']}
        for package in reviewed_packages:
            qs = {q for _, q in package['recipes']}
            all_qualifications.update(qs)
            all_best_qualifications[next(q for q in ['direct', 'requires_transfer', 'requires_oracle_inference', 'incomplete']
                                         if q in qs)] += 1
        for package in reviewed_qualified:
            qs = {q for _, q in package['recipes']}
            best = next(q for q in ['direct', 'requires_transfer', 'requires_oracle_inference'] if q in qs)
            locations = {}
            for mid in package['materials']:
                locations[mid] = sorted({ref['channel'] + ':' +
                                         (ref['path'] if ref['channel'] in {'repo', 'issue'} else str(ref['step']))
                                         for ref in by_id[mid]['refs']})
            group_numbers[sid, package['gap']] += 1
            source_groups.append({'case': sid, 'gap': package['gap'],
                                  'group_id': f"{sid}-{package['gap']}-{group_numbers[sid, package['gap']]:04d}",
                                  'materials': ','.join(package['materials']),
                                  'recipes': ','.join(sorted({rid for rid, _ in package['recipes']})),
                                  'qualification': best, 'verifier_validity': gap_by_id[package['gap']]['verifier_validity'],
                                  'all_materials_in_trajectory': all(by_id[mid]['availability'] not in {'repo_unseen', 'unknown'}
                                                                     for mid in package['materials']),
                                  'source_kinds': json.dumps(package['source_kinds'], ensure_ascii=False),
                                  'source_locations': json.dumps(locations, ensure_ascii=False),
                                  'minimal_in_qualification': package['minimal_in_qualification']})
            counts = Counter(by_id[mid]['kind'] for mid in package['materials'])
            routes = []
            for left, right in [('agent_validation', 'agent_validation'),
                                ('temporary_probe', 'temporary_probe'),
                                ('temporary_probe', 'agent_validation'),
                                ('repo_test', 'agent_validation'),
                                ('repo_test', 'temporary_probe'), ('repo_test', 'repo_test')]:
                if (counts[left] >= 2 if left == right else counts[left] and counts[right]):
                    routes.append(left + ' + ' + right)
            for kind in ['implementation', 'fixture_or_snapshot', 'runtime_output', 'reasoning']:
                if counts[kind]:
                    routes.append('uses ' + kind)
            for route in routes:
                row = source_routes.setdefault(route, {'packages': 0, 'cases': set(), 'families': set(),
                                                       'supported_packages': 0, 'supported_cases': set()})
                row['packages'] += 1
                row['cases'].add(sid)
                row['families'].add((sid, package['gap']))
                if gap_by_id[package['gap']]['verifier_validity'] == 'supported':
                    row['supported_packages'] += 1
                    row['supported_cases'].add(sid)
            if gap_by_id[package['gap']]['verifier_validity'] == 'supported':
                supported_packages.append((sid, package['gap'],
                                           all(by_id[mid]['availability'] not in {'repo_unseen', 'unknown'}
                                               for mid in package['materials']),
                                           next(q for q in ['direct', 'requires_transfer', 'requires_oracle_inference']
                                                if q in {q for _, q in package['recipes']})))
        for package in packages:
            qs = {q for _, q in package['recipes']}
            for qualification in qs:
                qualifications[qualification] += 1
            best_qualifications[next(q for q in ['direct', 'requires_transfer', 'requires_oracle_inference', 'incomplete']
                                     if q in qs)] += 1
        for package in reviewed_qualified:
            pattern = ' + '.join(sorted(by_id[mid]['kind'] for mid in package['materials']))
            patterns[pattern] += 1
            pattern_cases.setdefault(pattern, set()).add(sid)
            code = ' + '.join(sorted(by_id[mid]['kind'] for mid in package['materials']
                                     if by_id[mid]['kind'] in code_kinds)) or '(no test/probe unit)'
            code_patterns[code] += 1
            code_pattern_cases.setdefault(code, set()).add(sid)
        used = {mid for package in reviewed_qualified for mid in package['materials']}
        for material in review['materials']:
            kinds[material['kind']] += 1
            if material['id'] in used:
                used_kinds[material['kind']] += 1
            origins[material['origin']] += 1
            availability[material['availability']] += 1
            materials.append({'case': sid, 'id': material['id'], 'kind': material['kind'],
                              'origin': material['origin'], 'availability': material['availability'],
                              'unit': material['unit'], 'supports': json.dumps(material['supports'], ensure_ascii=False),
                              'references': json.dumps(material['refs'], ensure_ascii=False)})
        for gap in review['evaluation_families']:
            gp = [p for p in qualified if p['gap'] == gap['id']]
            tp = [p for p in trace_only if p['gap'] == gap['id']]
            ap = [p for p in reviewed_qualified if p['gap'] == gap['id']]
            atp = [p for p in reviewed_trace_only if p['gap'] == gap['id']]
            classifications[gap['classification']] += 1
            gaps.append({'case': sid, 'gap': gap['id'], 'task': entry['task'],
                         'classification': gap['classification'], 'verifier_validity': gap['verifier_validity'],
                         'joint_attempt': gap['joint_attempt'],
                         'failed_tests': json.dumps(gap['failed_tests'], ensure_ascii=False),
                         'missing_joint_test': gap['missing_joint_test'], 'contract': gap['contract'],
                         'reviewed_source_packages': len(ap), 'reviewed_trace_only_packages': len(atp),
                         'source_packages': len(gp), 'trace_only_packages': len(tp),
                         'has_package_without_reasoning': any(all(by_id[mid]['kind'] != 'reasoning' for mid in p['materials'])
                                                              for p in ap),
                         'recipe_ids': ','.join(r['id'] for r in review['recipes'] if r['gap'] == gap['id'])})
        cases.append({'case': sid, 'task': entry['task'], 'failed_tests': entry['failed_tests'],
                      'families': len(review['evaluation_families']), 'materials': len(by_id),
                      'recipes': len(review['recipes']), 'source_packages': len(qualified),
                      'reviewed_source_packages': len(reviewed_qualified),
                      'reviewed_trace_only_packages': len(reviewed_trace_only),
                      'trace_only_packages': len(trace_only),
                      'joint_attempt': review['agent_process']['joint_attempt'],
                      'forgetting_assessment': review['agent_process']['forgetting_assessment']})
        for explanation in review['agent_process']['explanations']:
            process_explanations.append({'case': sid, 'label': explanation['label'],
                                         'support': explanation['support'],
                                         'interpretation': explanation['interpretation'],
                                         'references': json.dumps(explanation['refs'], ensure_ascii=False)})
    summary = {
        'cohort_cases': len(index), 'completed_cases': len(cases), 'pending_cases': pending,
        'cohort_failed_tests': sum(e['failed_tests'] for e in index),
        'reviewed_failed_tests': sum(c['failed_tests'] for c in cases),
        'evaluation_families': len(gaps), 'family_classifications': dict(classifications),
        'material_units': sum(kinds.values()), 'material_kinds': dict(kinds),
        'material_kinds_used_in_qualified_packages': dict(used_kinds),
        'material_origins': dict(origins), 'material_availability': dict(availability),
        'recipes': sum(c['recipes'] for c in cases),
        'source_packages_excluding_incomplete': sum(c['source_packages'] for c in cases),
        'reviewed_source_packages_excluding_incomplete': sum(c['reviewed_source_packages'] for c in cases),
        'reviewed_trace_only_source_packages_excluding_incomplete': sum(c['reviewed_trace_only_packages'] for c in cases),
        'trace_only_source_packages_excluding_incomplete': sum(c['trace_only_packages'] for c in cases),
        'packages_by_qualification': dict(qualifications),
        'packages_by_best_qualification': dict(best_qualifications),
        'reviewed_packages_by_qualification': dict(all_qualifications),
        'reviewed_packages_by_best_qualification': dict(all_best_qualifications),
        'strict_supported': {
            'families': sum(g['verifier_validity'] == 'supported' for g in gaps),
            'cases': len({g['case'] for g in gaps if g['verifier_validity'] == 'supported'}),
            'failed_test_records': len({(g['case'], name) for g in gaps if g['verifier_validity'] == 'supported'
                                       for name in json.loads(g['failed_tests'])}),
            'classifications': dict(Counter(g['classification'] for g in gaps if g['verifier_validity'] == 'supported')),
            'joint_attempts': dict(Counter(g['joint_attempt'] for g in gaps if g['verifier_validity'] == 'supported')),
            'reviewed_source_packages': len(supported_packages),
            'reviewed_trace_only_packages': sum(trace_only for _, _, trace_only, _ in supported_packages),
            'packages_by_best_qualification': dict(Counter(q for _, _, _, q in supported_packages)),
            'families_with_packages': len({(sid, gap) for sid, gap, _, _ in supported_packages}),
            'families_with_multiple_packages': sum(n > 1 for n in Counter((sid, gap) for sid, gap, _, _ in supported_packages).values()),
            'cases_with_packages': len({sid for sid, _, _, _ in supported_packages}),
            'cases_with_multiple_packages': sum(n > 1 for n in Counter(sid for sid, _, _, _ in supported_packages).values())},
        'verifier_validity': dict(Counter(g['verifier_validity'] for g in gaps)),
        'source_routes': {route: {'packages': row['packages'], 'cases': len(row['cases']),
                                  'case_ids': sorted(row['cases']), 'families': len(row['families']),
                                  'supported_packages': row['supported_packages'],
                                  'supported_cases': len(row['supported_cases'])}
                          for route, row in source_routes.items()},
        'families_by_classification': {
            classification: {'families': sum(g['classification'] == classification for g in gaps),
                             'cases': sorted({g['case'] for g in gaps if g['classification'] == classification}),
                             'source_packages': sum(g['source_packages'] for g in gaps if g['classification'] == classification),
                             'trace_only_packages': sum(g['trace_only_packages'] for g in gaps if g['classification'] == classification)}
            for classification in sorted(classifications)},
        'families_with_multiple_source_packages': sum(g['source_packages'] > 1 for g in gaps),
        'families_with_multiple_reviewed_source_packages': sum(g['reviewed_source_packages'] > 1 for g in gaps),
        'families_with_package_without_reasoning': sum(g['has_package_without_reasoning'] for g in gaps),
        'cases_with_multiple_source_packages': sum(c['source_packages'] > 1 for c in cases),
        'cases_with_multiple_reviewed_source_packages': sum(c['reviewed_source_packages'] > 1 for c in cases),
        'joint_attempts_by_case': dict(Counter(c['joint_attempt'] for c in cases)),
        'joint_attempts_by_family': dict(Counter(g['joint_attempt'] for g in gaps)),
        'forgetting_assessments': dict(Counter(c['forgetting_assessment'] for c in cases)),
        'interpretation': 'Source packages are manually reviewed material assemblies, not newly executed test results. '
                          'Qualification retains missing oracle inference or transfer. Trace-only excludes repo_unseen/unknown '
                          'materials. Reviewed packages retain every recorded source set, including routes starting from different '
                          'base tests. Minimal packages additionally remove proper supersets when a smaller set has all the same '
                          'qualifications. Both lists are retained; these are not all arbitrary generatable programs.'}
    (run / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    (run / 'source_patterns.json').write_text(json.dumps([
        {'pattern': pattern, 'packages': count, 'cases': sorted(pattern_cases[pattern])}
        for pattern, count in patterns.most_common()], ensure_ascii=False, indent=2) + '\n')
    (run / 'test_and_probe_patterns.json').write_text(json.dumps([
        {'test_and_probe_units': pattern, 'packages': count, 'cases': sorted(code_pattern_cases[pattern])}
        for pattern, count in code_patterns.most_common()], ensure_ascii=False, indent=2) + '\n')
    table(run / 'cases.tsv', cases, ['case', 'task', 'failed_tests', 'families', 'materials', 'recipes',
                                    'reviewed_source_packages', 'reviewed_trace_only_packages', 'source_packages', 'trace_only_packages', 'joint_attempt', 'forgetting_assessment'])
    table(run / 'gaps.tsv', gaps, ['case', 'gap', 'task', 'classification', 'verifier_validity', 'joint_attempt', 'failed_tests',
                                 'missing_joint_test', 'contract', 'reviewed_source_packages', 'reviewed_trace_only_packages', 'source_packages', 'trace_only_packages',
                                 'has_package_without_reasoning', 'recipe_ids'])
    table(run / 'materials.tsv', materials, ['case', 'id', 'kind', 'origin', 'availability', 'unit', 'supports', 'references'])
    table(run / 'process_explanations.tsv', process_explanations,
          ['case', 'label', 'support', 'interpretation', 'references'])
    table(run / 'source_groups.tsv', source_groups,
          ['case', 'gap', 'group_id', 'materials', 'recipes', 'qualification', 'verifier_validity',
           'all_materials_in_trajectory', 'source_kinds', 'source_locations', 'minimal_in_qualification'])
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(args.run), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
