"""Post-hoc evaluator; target labels are consumed here, never by retrieval."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

KS = (1, 5, 10, 20, 50, 100)


def evaluate(result, target):
    anchors = {a['id']: a for a in result['anchors']}
    def target_test(row):
        return row['path'] == target['path'] and row['name'] == target['name']
    metrics = {}
    for method, ids in result['rankings'].items():
        test_rank, assertion_rank = None, None
        seen = set()
        for rank, aid in enumerate(ids, 1):
            row = anchors[aid]
            if row['test_id'] not in seen:
                seen.add(row['test_id'])
                if target_test(row) and test_rank is None:
                    test_rank = len(seen)
            if target_test(row) and row['line'] in target['assertion_lines'] and assertion_rank is None:
                assertion_rank = rank
        metrics[method] = {'test_rank': test_rank, 'assertion_rank': assertion_rank,
                           'ranked_tests': len(seen), 'ranked_assertions': len(ids)}
    matches = [a for a in result['anchors'] if target_test(a) and a['line'] in target['assertion_lines']]
    return {'methods': metrics, 'target_assertions_in_inventory': len(matches),
            'target_evidence': matches, 'oracle_scope': target['oracle_scope']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--targets', type=Path, default=Path('configs/anchor_targets.json'))
    args = parser.parse_args()
    labels = json.loads(args.targets.read_text())
    cases, rows = {}, []
    for cid, target in labels['cases'].items():
        path = args.results / f'{cid}.json'
        if not path.exists():
            continue
        result = json.loads(path.read_text())
        case = evaluate(result, target)
        case['counts'], case['timing_seconds'] = result['counts'], result['timing_seconds']
        cases[cid] = case
        for method, metrics in case['methods'].items():
            rows.append({'case': cid, 'method': method, **metrics})
    summary = {}
    for method in ('full', 'no_input_gaps', 'no_diversity', 'legacy_keywords'):
        summary[method] = {}
        for unit in ('test', 'assertion'):
            ranks = [c['methods'][method][unit + '_rank'] for c in cases.values()]
            n = len(ranks)
            summary[method][unit] = {
                'cases': n,
                'mrr': sum(1 / r for r in ranks if r is not None) / n if n else 0,
                'hit_at': {str(k): {'hits': sum(r is not None and r <= k for r in ranks),
                                    'rate': sum(r is not None and r <= k for r in ranks) / n if n else 0}
                           for k in KS}}
    report = {'target_labels_sha256': hashlib.sha256(args.targets.read_bytes()).hexdigest(),
              'scope': 'Seven manually audited discovery pilots, four issue families. Retrieval only, not oracle validity or bug detection.',
              'summary': summary, 'cases': cases}
    (args.results / 'evaluation.json').write_text(json.dumps(report, indent=2, ensure_ascii=True))
    with (args.results / 'ranks.csv').open('w') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ['case'])
        writer.writeheader()
        writer.writerows(rows)
    lines = ['**本地 target-test 检索实验**', '',
             '排名越小越好；— 表示未进入结果。断言排名与去重后的测试函数排名分别计算。', '',
             '| Case | 测试定义数 | 受影响断言数 | full 测试 / 断言排名 | 关键词基线测试 / 断言排名 | 秒 |',
             '|---|---:|---:|---|---|---:|']
    for cid, case in cases.items():
        fmt = lambda method: ' / '.join(str(case['methods'][method][key]) if case['methods'][method][key] is not None else '—' for key in ('test_rank', 'assertion_rank'))
        lines.append(f"| {cid} | {case['counts']['test_units']} | {case['counts']['affected_assertions']} | {fmt('full')} | {fmt('legacy_keywords')} | {case['timing_seconds']['total']:.2f} |")
    lines.extend(['', '| 方法 | Test Hit@10 | Assertion Hit@10 | Test MRR |', '|---|---:|---:|---:|'])
    for method, metrics in summary.items():
        lines.append(f"| {method} | {metrics['test']['hit_at']['10']['hits']}/{metrics['test']['cases']} | {metrics['assertion']['hit_at']['10']['hits']}/{metrics['assertion']['cases']} | {metrics['test']['mrr']:.4f} |")
    lines.extend(['', '目标由前一轮人工审查固定。检索器不读取标注、handbook、隐藏 verifier 或参考补丁。',
                  'P6/P7 只评价原测试入口的检索，命中不能证明目标组合已有可继承 oracle。',
                  '未标注其他候选是否相关，因此不把它们都当作 false positive，也不报告伪造的 precision。',
                  '统计包含最终仓库及解析出的 trajectory 脚本；没有重放历史脚本或执行被测仓库。'])
    (args.results / 'report.md').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines), flush=True)


if __name__ == '__main__':
    main()
