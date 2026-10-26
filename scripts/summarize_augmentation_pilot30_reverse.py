"""Report failure-guided semantic differences for all 30 saved pilot trials.

No model calls or subject execution. Judgments are explicit in review.json.
"""
from collections import Counter
from html import escape
from pathlib import Path
import json
import os

import summarize_augmentation_pilot30_static as historical


ROOT = historical.ROOT
RUN = historical.RUN
GOLD = historical.GOLD
OUT = RUN / 'benchmark_reverse_v4'
REPORT = ROOT / 'docs/archive/20261008_benchmark_guided_gap_targets_n30.html'
read, write, receipt, verify = historical.read, historical.write, historical.receipt, historical.verify
table = historical.table
CATEGORIES = {
    'combination_gap': '确认组合缺口',
    'existing_wrong_oracle': '已有联合测试，但预期与需求或验收要求相反',
    'basic_error': '非组合差异：接口、格式或基础规则',
    'revalidation_gap': '已有联合检查未在最终版本复验',
    'unresolved': '当前证据不足以确定',
}


def link(path, text):
    return f'<a href="{escape(os.path.relpath(path, REPORT.parent), quote=True)}">{escape(text)}</a>'


def build():
    # The historical pool is a separate appendix, not the reverse-analysis denominator.
    old_values = historical.summarize()
    historical.render(*old_values)
    old_review, old_labels, old_summary, original_summary, _ = old_values
    review = read(OUT / 'review.json')
    cases = {c['id']: c for c in read(RUN / 'cases.json')}
    previous = {c['id']: c for c in original_summary['cases']}
    targets = review['targets']
    assert len(targets) == len(cases) == 30
    assert {r['case'] for r in targets} == cases.keys()
    assert len({r['id'] for r in targets}) == 30
    records = []
    for r in targets:
        cid = r['case']
        assert r['category'] in CATEGORIES
        original_dir = GOLD / f'cases/{cid}/original_benchmark'
        evidence = {
            'public_requirement': receipt(cases[cid]['issue']),
            'original_patch': receipt(cases[cid]['candidate_patch']),
            'trajectory': receipt(cases[cid]['trajectory']),
            'historical_review': receipt(ROOT / r['historical_review']),
            'gold_patch': receipt(GOLD / f'cases/{cid}/gold.patch'),
            'benchmark_tests': receipt(GOLD / f'cases/{cid}/benchmark_test.patch'),
            'benchmark_results': receipt(original_dir / 'ctrf.json'),
            'candidate_sources': [receipt(RUN / f'cases/{cid}/repository' / p) for p in r['candidate_source_files']],
            'original_method_review': receipt(RUN / f'evaluation/reviews/{cid}.json'),
            'saved_model_assessments': [receipt(p) for p in sorted(
                (RUN / f'cases/{cid}/generation').glob('*/assessment.json'))],
        }
        if (original_dir / 'test-stdout.txt').exists():
            evidence['raw_benchmark_output'] = receipt(original_dir / 'test-stdout.txt')
        records.append({**r, 'primary_positive': r['category'] == 'combination_gap', 'evidence': evidence,
                        'original_method_test_packets': sum(previous[cid]['native_status'].values()),
                        'original_method_run_status': previous[cid]['native_status']})

    positive = [r for r in records if r['primary_positive']]
    detected = [r for r in positive if r['method_detected']]
    generated = [r for r in positive if r['method_generated_fault_revealing_test']]
    assert [r['case'] for r in detected] == [r['case'] for r in generated] == ['T24']
    combined = [{
        'id': r['id'], 'case': r['case'], 'source': 'benchmark_reverse',
        'description': r['title'], 'method_detected': r['method_detected'],
        'method_generated_fault_revealing_test': r['method_generated_fault_revealing_test'],
        'historical_aliases': [tid for tid, mapping in review['same_root_mapping'].items()
                               if mapping['benchmark_target'] == r['id']],
    } for r in positive]
    for r in old_labels['targets']:
        if not r['primary_positive'] or r['id'] in review['same_root_mapping']:
            continue
        if r['id'] in review['non_combination_historical_boundary']:
            continue
        combined.append({
            'id': r['id'], 'case': r['case'], 'source': 'historical_static',
            'description': r['target'], 'method_detected': r['method_detected'],
            'method_generated_fault_revealing_test': r['method_generated_fault_revealing_test'],
            'historical_aliases': [],
        })
    assert len(combined) == 23 and len({r['case'] for r in combined}) == 18
    combined_metrics = {
        'unit': 'distinct reviewed combination error target after explicit same-root merging',
        'eligible_targets': len(combined), 'eligible_trials': len({r['case'] for r in combined}),
        'positive_trials': sorted({r['case'] for r in combined}),
        'detected_targets': [r['id'] for r in combined if r['method_detected']],
        'generated_targets': [r['id'] for r in combined if r['method_generated_fault_revealing_test']],
        'false_negative_targets': [r['id'] for r in combined if not r['method_detected']],
        'detected_target_count': sum(r['method_detected'] for r in combined),
        'generated_target_count': sum(r['method_generated_fault_revealing_test'] for r in combined),
        'false_negative_target_count': sum(not r['method_detected'] for r in combined),
        'target_recall': sum(r['method_detected'] for r in combined) / len(combined),
        'benchmark_related_targets': len(positive),
        'additional_historical_targets': len(combined) - len(positive),
        'merged_duplicate_historical_targets': list(review['same_root_mapping']),
        'non_combination_historical_boundary': review['non_combination_historical_boundary'],
        'boundary_sensitivity': {'excluded': 'T15-R1', 'targets': 22, 'trials': 17,
                                 'detected_targets': 1, 'generated_targets': 1},
        'scope': 'Selected reference targets, not an exhaustive list of all errors or method discoveries.',
    }
    summary = {
        'version': review['version'], 'date': review['date'], 'trials_reviewed': len(records),
        'representative_mechanisms_reviewed': len(records),
        'classification_counts': dict(Counter(r['category'] for r in records)),
        'confirmed_combination_trials': combined_metrics['positive_trials'],
        'benchmark_combination_trials': [r['case'] for r in positive],
        'combined_static_screening': combined_metrics,
        'primary_metrics': combined_metrics,
        'benchmark_subset_metrics': {
            'unit': 'one confirmed benchmark-related representative combination target per eligible trial',
            'eligible_trials': len(positive), 'eligible_targets': len(positive),
            'detected_trials': len(detected), 'generated_fault_revealing_trials': len(generated),
            'detected_targets': [r['id'] for r in detected],
            'generated_targets': [r['id'] for r in generated],
            'false_negative_count': len(positive) - len(detected),
            'false_negative_targets': [r['id'] for r in positive if not r['method_detected']],
            'target_recall': len(detected) / len(positive),
            'all_method_proposal_false_positive_count': None,
            'task_false_positive_rate': None,
            'false_positive_limit': '未按新定义独立穷尽判定 337 份建议；非正类任务不是无错误任务，不能直接作为负例。',
        },
        'boundary_sensitivity': {'excluded_target': 'T15-R1', 'eligible_targets': len(positive) - 1,
                                 'detected_targets': len(detected), 'generated_targets': len(generated)},
        'historical_v3_comparison': {
            'old_targets_reviewed': 41, 'decisions': old_summary['decisions'],
            'v2_pending_28_disposition': old_summary['v2_pending_28_disposition'],
            'historical_recall': old_summary['historical_target_metrics']['target_recall'],
            'historical_positive_trials': len(old_summary['positive_trials']),
            'detected_historical_targets': ['T24-G1'],
            'definition_difference': review['relation_to_v3'],
        },
        'known_other_differential_discoveries': ['T04', 'T23', 'T11 (prior environment adjustment)'],
        'new_model_calls': 0, 'new_subject_executions': 0, 'new_patch_repairs': 0,
        'measured_resolution_rate_after_repair': None,
        'scope_limit': review['scope'], 'evidence_limit': review['evidence_limit'],
    }
    labels = {'version': review['version'],
              'scope': 'One representative benchmark failure per trial; primary_positive applies to that selected mechanism only.',
              'protocol': review['protocol'],
              'review_receipt': receipt(OUT / 'review.json'), 'targets': records}
    write(OUT / 'labels.json', labels)
    write(OUT / 'summary.json', summary)
    write(OUT / 'combined_targets.json', {
        'definition': review['primary_definition'], 'review': receipt(OUT / 'review.json'),
        'historical_labels': receipt(historical.OUT / 'labels.json'),
        'benchmark_labels': receipt(OUT / 'labels.json'), 'targets': combined,
        'same_root_mapping': review['same_root_mapping'],
        'excluded_non_combination_boundary': review['non_combination_historical_boundary'],
        'summary': combined_metrics,
    })
    render(review, records, summary, combined)

    refs = []
    def collect(v):
        if isinstance(v, dict):
            if 'path' in v and 'sha256' in v:
                verify(v)
                refs.append(v)
            for value in v.values():
                collect(value)
        elif isinstance(v, list):
            for value in v:
                collect(value)
    collect(labels)
    write(OUT / 'verification.json', {
        'version': review['version'], 'all_30_trials_accounted_for': True,
        'unique_mechanism_ids': len({r['id'] for r in records}),
        'combined_distinct_targets': len(combined),
        'combined_positive_trials': len({r['case'] for r in combined}),
        'evidence_receipts_verified': len(refs), 'distinct_evidence_files_verified': len({r['path'] for r in refs}),
        'frozen_original_summary_and_reviews_verified_by_historical_builder': True,
        'new_subject_executions': 0, 'report': receipt(REPORT),
    })
    write(RUN / 'active_evaluation.json', {
        'version': review['version'], 'scope': review['scope'],
        'labels': receipt(OUT / 'combined_targets.json'), 'review': receipt(OUT / 'review.json'),
        'benchmark_failure_labels': receipt(OUT / 'labels.json'),
        'summary': receipt(OUT / 'summary.json'), 'report': receipt(REPORT),
        'combined_static_targets': receipt(OUT / 'combined_targets.json'),
        'historical_target_appendix': receipt(historical.OUT / 'labels.json'),
        'historical_target_report': receipt(historical.REPORT),
        'archived_v2_labels': receipt(RUN / 'historical_relabel_v2/labels.json'),
        'archived_validation_only_truth': receipt(RUN / 'evaluation_truth.json'),
        'archived_validation_only_summary': receipt(RUN / 'summary.json'),
        'rebuild_command': '.venv/bin/python scripts/summarize_augmentation_pilot30_reverse.py',
        'generation_use': 'Evaluation only. Gold and benchmark failures were not inputs to original method generation.',
    })
    print(json.dumps({'counts': summary['classification_counts'], 'metrics': combined_metrics,
                      'report': str(REPORT)}, ensure_ascii=False, indent=2))


def render(review, records, summary, combined):
    m = summary['benchmark_subset_metrics']
    cm = summary['combined_static_screening']
    parts = ['''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>30 条任务：从 benchmark 失败与补丁差异推导组合缺口</title>
<style>body{font:16px/1.8 system-ui,sans-serif;max-width:1180px;margin:35px auto;padding:0 20px;background:#fafbfd;color:#192832}h1{font-size:29px}h2{font-size:23px;margin-top:35px}a{color:#076098}table{border-collapse:collapse;background:white;width:100%;font-size:14px}td,th{padding:10px 12px;border:1px solid #dce3e8;vertical-align:top;text-align:left}th{background:#e9f1f6}.scroll{overflow:auto}.note{background:#e9f3fb;border-left:4px solid #3280af;padding:14px 18px}details{border:1px solid #dce3e8;background:white;margin:12px 0;padding:12px 18px}summary{font-weight:600;cursor:pointer}.muted{color:#52616b}code{overflow-wrap:anywhere}p{max-width:1030px}.links a{margin-right:14px}li{margin:7px 0}</style>
<h1>30 条任务：从失败测试与补丁差异推导组合缺口</h1>
<p class="muted">2026-10-08 · 当前分析 v4 · 30 个 trial · 静态复核与已有运行证据</p>''']
    parts.append(f'<p class="note">按静态差分规则，30 条任务中有 {cm["eligible_trials"]} 条至少包含一个已确认的组合错误目标。合并重复根因后，共 {cm["eligible_targets"]} 项。原方法检测、生成各命中 1 项，即 T24 的默认模式与条件必填；漏检 {cm["false_negative_target_count"]} 项。其中 {m["eligible_targets"]} 项与本轮选定的 benchmark 失败直接相关。</p>')
    parts.append('<p>本轮先读 benchmark 失败，再比较原补丁与 gold 的行为，最后回查原验证。原历史标签用于对照。仅有源码不同、测试失败或测试数量少，都不足以证明存在组合缺口。</p>')
    parts.append('<h2>材料与分析步骤</h2><p>原 pilot 选取 30 个不同任务。Python、Go、TypeScript 各 10 个。它们来自 211 条失败记录。方法用程序分析提取测试、程序关系及相关 trajectory，再让模型判断缺口并生成测试。</p>')
    parts.append('<p>原实验请求 DeepSeek-v4-flash。provider 返回 deepseek-flash，并标为 DeepSeek-V4.1-Flash。原实验共有 1005 次模型调用、337 份可执行测试建议。一份建议可含多项测试。原补丁上有 298 份通过、33 份失败、6 份执行错误。这些结果不能直接等同于真实错误数量。</p>')
    parts.append('<p>本轮没有新模型调用，也没有执行、适配或改写测试。多数 gold 通过结论来自逐项源码推导。T24 另有已保存的逐测试运行对照。分析由 Codex 完成，尚无独立人类复核。新目标在实验后构建，不能称为事先固定的独立金标准。</p>')
    parts.append('<ol>' + ''.join(f'<li>{escape(s)}</li>' for s in review['protocol']) + '</ol>')
    parts.append('<p>每项推导都需要一条完整解释：失败断言 → 原补丁与 gold 的语义差异 → 触发条件 → 共同结果 → 原验证遗漏。已有联合测试但未运行，应优先补跑。已有错误断言，应修订预期。二者均不计为新组合输入缺口。</p>')
    parts.append('<p>分析围绕每个任务的关键失败展开。本报告不声称穷尽所有失败根因。没有纳入的任务仍可能存在其他组合错误。gold 和 benchmark 的结果也需要公开要求支持。</p>')
    parts.append('<h2>按用户规则筛选后的合并结果</h2><p>benchmark 只帮助定位错误，不是额外准入条件。我们保留旧目标中符合静态差分规则的组合缺口。新旧目标指向同一根因时，只计一次。</p>')
    parts.append(table(['参照目标来源', '去重目标数', '正确检测', '生成错误检出测试', '漏检'], [
        ['从 benchmark 失败逆向推导', '13', '1', '1', '12'],
        ['旧记录中另有静态差分依据的组合', '10', '0', '0', '10'],
        ['合计', '23', '1（4.35%）', '1', '22'],
    ]))
    parts.append('<p>这 23 项分布在 18 条任务。方法在其中 1 条命中参照目标，另外 17 条没有命中。任务比例为 1/18。目标比例为 1/23。两者仅表示这份参照集合的召回，不表示全部错误的发现率。</p>')
    parts.append('<p>合并过程为：13 项新目标，加上 17 项旧差分目标，合并 6 项同根因目标，再单列 1 项接口问题 T26-G1。后者在单个函数的泛型调用处已失败，不需要 over/as 组合。因此严格组合集合为 23 项。T15 仍是较弱的分类与排序组合；若也排除它，则为 22 项、17 条任务，检测和生成仍各命中 1 项。</p>')
    parts.append(table(['另外保留的目标', '组合检查', '方法结果'], [
        [f'<a href="{historical.REPORT.name}#{r["id"]}">{r["id"]}</a>', escape(r['description']), '未命中']
        for r in combined if r['source'] == 'historical_static'
    ]))
    parts.append('<p>上述十项不因缺少当前 benchmark 失败关联而被撤销。其具体输入、两份补丁行为和原测试见旧目标附录。T19、T22、T30 等任务的代表性 benchmark 失败属于基本问题，但它们仍有其他有效组合目标。</p>')
    parts.append('<h2>各任务的代表性 benchmark 失败分类</h2><p>下表分类的是本轮选定的失败原因，不是整个任务是否存在任何组合错误。</p>')
    counts = summary['classification_counts']
    parts.append(table(['分类', '任务数', '处理'], [
        [CATEGORIES['combination_gap'], str(counts['combination_gap']), '计入本次检测和生成召回率。'],
        [CATEGORIES['existing_wrong_oracle'], str(counts['existing_wrong_oracle']), '修订断言或先处理接口；不称为缺少组合。'],
        [CATEGORIES['basic_error'], str(counts['basic_error']), '直接检查接口或基本规则；不作为组合召回目标。'],
        [CATEGORIES['revalidation_gap'], str(counts['revalidation_gap']), '重放已出现的联合检查。'],
        [CATEGORIES['unresolved'], str(counts['unresolved']), '保留不确定性；不当作负例。'],
    ]))
    parts.append('<h2>确认的 13 项组合缺口</h2><p>下表给出从语义差异逆向得到的必要条件。它不只是给测试附加更多选项。</p>')
    positives = [r for r in records if r['primary_positive']]
    parts.append(table(['任务', '缺少的组合', '原补丁与 gold 的语义差异', '方法结果'], [
        [f'<a href="#{r["id"]}">{r["case"]}</a>', escape(r['title']), escape(r['semantic_difference']),
         '检测、生成均成功' if r['method_detected'] else '未完整命中；无错误检出测试'] for r in positives
    ]))
    parts.append('<p>T06 的模型说明接近嵌套配置继承，但没有实例化连续两次 include 的不同覆盖值。本次不把宽泛相关性计为完整命中。T27 的光标补测设置 filter:()=>true，主动避开了实际会出错的默认过滤路径。</p>')
    parts.append('<h2>benchmark 相关子集与原方法结果对比</h2>')
    parts.append(table(['指标', '结果', '单位'], [
        ['筛选出的代表性组合目标', str(m['eligible_targets']), '13 条任务，各 1 项。'],
        ['正确检测', '1 / 13（7.69%）', 'T24-R1。'],
        ['生成正确的错误检出测试', '1 / 13（7.69%）', '仍为 T24-R1。'],
        ['漏检', str(m['false_negative_count']), '其余 12 项已确认目标。'],
        ['全部输出的误报数／误报率', '尚不能确定', '本轮未按新规则穷尽重判全部 337 份建议。'],
    ]))
    parts.append('<p>一个检测命中需要指出决定行为差异的具体条件。一个生成命中需要测试真正揭示原补丁错误。T24 的 2 份说明直接命中该条件。4 份建议包含 7 项有效差分测试，但根因相同，故只计 1 个目标。</p>')
    parts.append('<p>不能把另外 17 条任务作为真实负例来计算误报率。部分任务有其他真实组合错误，部分任务的预期仍待定。旧历史命中的 T10-G1 和 T14-G2 已撤销，因为对应测试在原补丁通过。它们是两个旧目标的误命中，不是全部建议的误报总数。</p>')
    parts.append('<p>T15 是较弱的“分类结果影响排序”组合。若不把此类基础边界计入，主集合变为 12 项。检测和生成仍各为 1 项，漏检 11 项，结论不变。T26 的泛型错误在进入 over/as 链前已经发生，本轮将它列为接口错误。</p>')
    parts.append('<p>原样生成测试另在 T04、T23 揭示其他真实错误。此前 T11 的环境对齐记录也有一项。它们与本轮选定的 benchmark 失败原因不同，因此不进入此处的召回分母，也不能被算作误报。连同 T24，已有记录确认 3 个任务有原样差分测试；计入 T11 后为 4 个任务。</p>')
    parts.append('<h2>值得修正的原判断</h2><p>T02 已测试死信路由与历史头，但将新目的地写成了历史来源的预期。T23 已测试子作用域先初始化，却要求父单例一并启动。继续生成相同组合，且沿用原断言，不能改善这两项结果。</p>')
    parts.append('<p>T11 的独立文本修改与节点新增脚本已经在开发早期运行。后续改动重新破坏该行为。需要检查测试执行的代码版本，并重放已有脚本。这是复验问题。</p>')
    parts.append('<p>T20 的实际差异是额外的 google_re2:{} 字段。保存的比较没有证明头部重写行为错误。不能因为整份配置快照不同，就反向编造组合缺口。</p>')
    parts.append('<p>T09 的两份补丁都拒绝显式同名别名。失败源于 ValueError 与 ProviderNotFoundError 的类型差异。原测试已经包含同名别名输入。不能把这个失败写成“gold 接受同名别名”或“原测试缺少该组合”。</p>')
    parts.append('<h2>逐任务的完整推导</h2>')
    for r in records:
        parts.append(f'<details id="{r["id"]}" open><summary>{r["case"]} · {escape(r["title"])} · {escape(CATEGORIES[r["category"]])}</summary>')
        parts.append(f'<p class="muted">{escape(r["task"])}</p>')
        seeds = r['matched_benchmark_failure_names'] + r.get('additional_raw_failure_names', [])
        if seeds:
            parts.append('<p><b>失败入口：</b>' + '<br>'.join(escape(s) for s in seeds) + '</p>')
        else:
            parts.append('<p><b>失败入口：</b>' + escape('；'.join(r['benchmark_seed_patterns'])) + '。具体条目见原记录。</p>')
        if r.get('requirement_basis'):
            parts.append('<p><b>预期依据：</b>' + escape(r['requirement_basis']) + '</p>')
        for title, key in [('语义差异', 'semantic_difference'), ('触发条件', 'activating_conditions'),
                           ('区分检查', 'distinguishing_check'), ('原验证', 'original_validation'),
                           ('分类依据', 'classification_reason'), ('方法对照', 'method_comparison_note')]:
            parts.append(f'<p><b>{title}：</b>{escape(r[key])}</p>')
        e = r['evidence']
        links = [link(ROOT / e[k]['path'], name) for k, name in [
            ('public_requirement', '公开要求'), ('original_patch', '原补丁'), ('gold_patch', 'gold 补丁'),
            ('benchmark_tests', 'benchmark 测试'), ('benchmark_results', '原失败结果'),
            ('historical_review', 'trajectory 审读'), ('original_method_review', '方法原记录')]]
        if 'raw_benchmark_output' in e:
            links.append(link(ROOT / e['raw_benchmark_output']['path'], '原始构建／运行日志'))
        if e['saved_model_assessments']:
            links.append(link(RUN / f'cases/{r["case"]}/generation', '原模型说明与测试'))
        links += [link(ROOT / x['path'], Path(x['path']).name) for x in e['candidate_sources']]
        parts.append('<p class="links">' + ' '.join(links) + '</p></details>')
    parts.append('<h2>旧 41 项历史目标如何处理</h2><p>此前按用户的静态差分规则，已逐项筛选 41 个旧目标：17 项在原补丁失败而 gold 通过，6 项原补丁已经满足，14 项对应检查在 gold 也失败，4 项仍待定。17 项分布于 15 条任务。方法只命中 T24-G1，历史目标召回为 1/17。</p>')
    parts.append('<p>原先 28 个待定目标中，10 个转为正例，14 个因 gold 也失败而不纳入，4 个仍待定。这里没有再要求它们对应原 benchmark 的失败。</p>')
    parts.append('<p>本报告的 13 项不是上述 17 项的简单子集。13 项从 benchmark 失败和补丁差异重新推导。它包含原标注未收录的缓存预热、连续路由覆盖等目标。两个原始集合不能直接相加。前文的 23 项结果使用明确的同根因合并表，并将 T26 的接口边界单列。</p>')
    parts.append('<p>' + link(historical.REPORT, '查看旧 41 项静态筛选完整附录') + '。附录保留每个组合输入、两份补丁行为及原编号。</p>')
    parts.append('<h2>对方法改进的直接含义</h2><p>提取阶段应关注三类条件：状态从一个操作流入另一个操作；模式开关与既有处理路径同时生效；默认值或来源信息在包装、复制和输出时保留。候选必须附带最终公开观察点。</p>')
    parts.append('<p>原模型多次正确否定无关候选，却没有收到关键关系。例如，T13 的说明用单个闭包的复制隔离测试排除补测需求，没有区分两个闭包共享同一捕获单元。T28 的说明列举恢复状态测试，却未追踪恢复后的框架挂载。现有输出支持“候选范围与后续行为不足”这一解释；本轮没有阶段对照实验，不能把全部漏检归给某一个模块。</p>')
    parts.append('<p>模型应区分“没有测试输入”“断言检查错”“测试只在旧版本运行”。T02、T23 需要修订预期；T11 需要重放。统一要求模型再生成一个测试，会掩盖真实问题。</p>')
    parts.append('<p>benchmark 和 gold 在本轮只用于离线归因及评价。实际方法仍须从公开需求、原补丁和 trajectory 提取线索。不能把本轮失败测试喂给生成方法后，继续把结果称为原 pilot 的检测能力。</p>')
    parts.append('<p>这些目标能够揭示与修复相关的错误，但还没有完成补丁修复和全套验收。因此，本报告不报告 resolution rate 提升。</p>')
    parts.append('<h2>可复核数据</h2><p class="links">' + ' '.join([
        link(OUT / 'review.json', '30 条逐项判断'), link(OUT / 'labels.json', '判断与证据校验值'),
        link(OUT / 'combined_targets.json', '合并后的 23 项组合目标'),
        link(OUT / 'summary.json', '统计结果'), link(OUT / 'verification.json', '完整性检查'),
        link(GOLD / 'summary.json', '已有差分测试结果'), link(RUN / 'active_evaluation.json', '当前数据入口')]) + '</p>')
    parts.append('<p>重建报告：<code>.venv/bin/python scripts/summarize_augmentation_pilot30_reverse.py</code></p></html>')
    REPORT.write_text('\n'.join(parts) + '\n')


if __name__ == '__main__':
    build()
