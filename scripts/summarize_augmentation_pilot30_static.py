"""Build the pilot30 static differential audit from explicit source judgments.

Reads saved evidence only. Does not execute subjects, call models, adapt tests,
or modify the frozen original pilot and v2 labels.
"""
from collections import Counter
from html import escape
import hashlib
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "experiments/relation_distinction/results/pilot30_20261007_v1"
GOLD = RUN / "gold_comparison_v1"
OUT = RUN / "historical_relabel_v3"
REPORT = ROOT / "docs/archive/20261008_gap_static_screening_n30.html"
DECISIONS = {
    "qualifies": "符合：原补丁失败，gold 通过",
    "original_passes": "不纳入：原补丁已满足目标",
    "reference_fails": "不纳入：gold 也未满足该检查",
    "unresolved": "待定：尚缺有效共同判据",
}


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def receipt(path):
    path = Path(path)
    return {"path": str(path.relative_to(ROOT)), "sha256": digest(path)}


def verify(record):
    path = Path(record["path"])
    if not path.is_absolute():
        path = ROOT / path
    assert digest(path) == record["sha256"], str(path)


def link(path, label):
    return f'<a href="{escape(os.path.relpath(path, REPORT.parent), quote=True)}">{escape(label)}</a>'


def table(headers, rows):
    return '<div class="scroll"><table><thead><tr>' + ''.join(
        f'<th>{escape(h)}</th>' for h in headers
    ) + '</tr></thead><tbody>' + ''.join(
        '<tr>' + ''.join(f'<td>{v}</td>' for v in row) + '</tr>' for row in rows
    ) + '</tbody></table></div>'


def summarize():
    review = read(OUT / 'review.json')
    original = read(RUN / 'evaluation_truth.json')
    previous = read(RUN / 'summary.json')
    old_cases = {c['id']: c for c in previous['cases']}
    old_targets = {f'{c["id"]}-G{g["source_gap_index_1based"]}': (c, g)
                   for c in original for g in c['gaps'] if g['class'] in {'S', 'M'}}
    judgments = {r['id']: r for r in review['targets']}
    assert len(original) == len(old_cases) == 30
    assert len(judgments) == len(review['targets']) == len(old_targets) == 41
    assert judgments.keys() == old_targets.keys()

    protocol = read(GOLD / 'protocol.json')
    verify(protocol['previous_summary'])
    for rec in protocol['previous_reviews']:
        verify(rec)
    verify(read(RUN / 'protocol.json')['census'])
    gold_cases = {c['case']: c for c in protocol['cases']}
    for c in original:
        for rec in [c['primary_receipt'], c['cross_review_receipt'], *c['original_source_receipts'].values()]:
            verify(rec)
        for key in ['gold', 'gold_original', 'candidate_patch']:
            verify(gold_cases[c['id']][key])

    gold_summary = read(GOLD / 'summary.json')
    witness_sets = {key: gold_summary[key] for key in ['witnesses', 'prior_environment_witnesses']}
    for witnesses in witness_sets.values():
        for w in witnesses:
            pair = read(ROOT / w['comparison'])
            if 'gold_result' in pair:
                verify(pair['gold_result'])
            for test in w['matched_tests']:
                found = [t for t in pair['tests'] if t['id'] == test['id']]
                assert len(found) == 1
                assert found[0]['candidate'] == 'fail' and found[0]['reference'] == 'pass'
                assert found[0]['classification'] == 'differential_witness'

    records = []
    for tid, judgment in judgments.items():
        case, gap = old_targets[tid]
        cid = case['id']
        assert judgment['decision'] in DECISIONS
        positive = judgment['decision'] == 'qualifies'
        if positive:
            assert judgment['candidate_result'] == 'fail' and judgment['gold_result'] == 'pass'
        claims = read(RUN / f'evaluation/reviews/{cid}.json')['claims']
        old_matches = [c['candidate'] for c in claims
                       if gap['source_gap_index_1based'] in c['known_gap_indices']]
        # Previously reviewed tests match T24-G1. Other differential discoveries
        # remain separate from the pre-existing historical target denominator.
        generated = [w for w in witness_sets['witnesses'] if w['case'] == cid] if tid == 'T24-G1' else []
        records.append({
            **judgment, 'case': cid, 'trial': case['trial'], 'task': case['task'],
            'original_gap': gap, 'primary_positive': positive,
            'historical_match_candidates': old_matches,
            'method_detected': positive and bool(old_matches),
            'method_generated_fault_revealing_test': positive and bool(generated),
            'generated_witnesses': generated,
            'evidence': {
                'original_review': case['primary_receipt'],
                'original_cross_review': case['cross_review_receipt'],
                'original_sources': case['original_source_receipts'],
                'candidate_source_files': [receipt(RUN / f'cases/{cid}/repository' / f)
                                           for f in judgment['source_files']],
                'gold_patch': receipt(GOLD / f'cases/{cid}/gold.patch'),
                'method_review': receipt(RUN / f'evaluation/reviews/{cid}.json'),
            },
        })

    positives = [r for r in records if r['primary_positive']]
    detected = [r for r in positives if r['method_detected']]
    generated = [r for r in positives if r['method_generated_fault_revealing_test']]
    misses = [r for r in positives if not r['method_detected']]
    revoked = [r for r in records if r['historical_match_candidates'] and not r['primary_positive']]
    trials = []
    for c in original:
        cid = c['id']
        rows = [r for r in records if r['case'] == cid]
        old = old_cases[cid]
        trials.append({
            'case': cid, 'trial': c['trial'], 'task': c['task'], 'language': old['language'],
            'positive_targets': [r['id'] for r in rows if r['primary_positive']],
            'unresolved_targets': [r['id'] for r in rows if r['decision'] == 'unresolved'],
            'excluded_targets': [r['id'] for r in rows if r['decision'] in {'original_passes', 'reference_fails'}],
            'detected_targets': [r['id'] for r in rows if r['method_detected']],
            'generated_targets': [r['id'] for r in rows if r['method_generated_fault_revealing_test']],
            'method_test_packets': sum(old['native_status'].values()),
            'method_original_execution': old['native_status'],
            'miss_reason': old['miss_reason'],
            'other_differential_witness': cid in {'T04', 'T23'},
            'prior_environment_differential_witness': cid == 'T11',
            'task_is_bug_free': None,
        })
    positive_trials = sorted({r['case'] for r in positives})
    summary = {
        'version': review['version'], 'date': review['date'], 'scope_trials': 30,
        'historical_targets_reviewed': 41,
        'decisions': dict(Counter(r['decision'] for r in records)),
        'v2_pending_28_disposition': dict(Counter(r['decision'] for r in records if r['previous_v2_decision'] == 'pending')),
        'positive_targets': [r['id'] for r in positives], 'positive_trials': positive_trials,
        'unresolved_targets': [r['id'] for r in records if r['decision'] == 'unresolved'],
        'by_relation_class': {d: dict(Counter(r['original_gap']['class'] for r in records if r['decision'] == d)) for d in DECISIONS},
        'historical_target_metrics': {
            'eligible_target_count': len(positives), 'eligible_trial_count': len(positive_trials),
            'detected_targets': [r['id'] for r in detected], 'detected_target_count': len(detected),
            'target_recall': len(detected) / len(positives),
            'detected_trial_count': len({r['case'] for r in detected}),
            'trial_recall': len({r['case'] for r in detected}) / len(positive_trials),
            'generated_targets': [r['id'] for r in generated], 'generated_target_count': len(generated),
            'generated_trial_count': len({r['case'] for r in generated}),
            'false_negative_targets': [r['id'] for r in misses], 'false_negative_target_count': len(misses),
            'trials_without_historical_hit': sorted(set(positive_trials) - {r['case'] for r in detected}),
            'revoked_old_historical_hits': [r['id'] for r in revoked],
            'revoked_old_historical_hit_count': len(revoked),
            'all_proposal_false_positive_count': None, 'task_false_positive_rate': None,
            'all_proposal_precision': None,
            'scope_note': '只有历史目标匹配可给出完整分母。两个撤销旧命中不是全部 337 份建议的误报总数。',
        },
        'sensitivity_excluding_boundary_targets': {
            'excluded': ['T15-G1', 'T26-G1'], 'eligible_targets': len(positives) - 2,
            'eligible_trials': len(positive_trials) - 2, 'detected_targets': len(detected),
            'generated_targets': len(generated),
        },
        'generated_differential_evidence': {
            'historical_witness_proposals': sum(len(r['generated_witnesses']) for r in generated),
            'historical_witness_named_tests': sum(len(w['matched_tests']) for r in generated for w in r['generated_witnesses']),
            'original_artifact_trial_ids': sorted({w['case'] for w in witness_sets['witnesses']}),
            'original_artifact_proposals_with_a_witness': len(witness_sets['witnesses']),
            'original_artifact_named_tests': sum(len(w['matched_tests']) for w in witness_sets['witnesses']),
            'prior_environment_extra_trials': sorted({w['case'] for w in witness_sets['prior_environment_witnesses']}),
            'prior_environment_extra_named_tests': sum(len(w['matched_tests']) for w in witness_sets['prior_environment_witnesses']),
            'scope_note': '已核实的发现数量。不同目标不补入历史召回率分母。含有效测试不等于整份建议全部正确。',
        },
        'new_model_calls': 0, 'new_subject_executions': 0, 'new_repairs': 0,
        'measured_resolution_rate_after_repair': None, 'trials': trials,
        'limits': [review['negative_interpretation'], review['evaluation_caveat'], review['method_matching_scope'],
                   '只修订这 30 条。其他 181 条失败记录保持原状。',
                   '不纳入某历史目标不等于该任务没有其他错误。待定目标不是负例。',
                   '静态判断由 Codex 完成，尚无独立人类复核。'],
    }
    excluded = [{'case': c['id'], 'original_gap': g} for c in original for g in c['gaps'] if g['class'] == 'X']
    assert len(excluded) == 3
    assert [r['id'] for r in detected] == [r['id'] for r in generated] == ['T24-G1']
    labels = {'version': review['version'], 'positive_definition': review['positive_definition'],
              'review_input': receipt(OUT / 'review.json'), 'original_truth': receipt(RUN / 'evaluation_truth.json'),
              'targets': records, 'originally_excluded_candidates': excluded}
    write(OUT / 'labels.json', labels)
    write(OUT / 'summary.json', summary)
    return review, labels, summary, previous, witness_sets


def render(review, labels, summary, previous, witnesses):
    targets = labels['targets']
    counts = summary['decisions']
    m = summary['historical_target_metrics']
    parts = ["""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>30 个任务：静态差分筛选与方法结果</title>
<style>body{font:16px/1.8 system-ui,sans-serif;max-width:1160px;margin:36px auto;padding:0 22px;color:#192832;background:#fafbfd}h1{font-size:28px}h2{font-size:23px;margin-top:36px}h3{font-size:19px}a{color:#075fa6}p{max-width:1000px}.scroll{overflow-x:auto}table{border-collapse:collapse;background:white;width:100%;font-size:14px}th,td{padding:10px 12px;border:1px solid #dce3e8;text-align:left;vertical-align:top}th{background:#eaf1f5}.note{padding:14px 18px;background:#e9f3fb;border-left:4px solid #3280af}details{background:white;border:1px solid #dce3e8;margin:12px 0;padding:10px 18px}summary{cursor:pointer;font-weight:600}code{overflow-wrap:anywhere}.muted{color:#53626d}.links a{margin-right:16px}li{margin:6px 0}</style>
<h1>30 个任务：静态差分筛选与方法结果</h1>
<p class="muted">2026-10-08 · 旧 41 项目标的静态筛选附录 v3 · 只评价已有实验</p>"""]
    parts.append('<p class="note">当前主报告已按 benchmark 失败与补丁语义差异重新推导目标。请先看<a href="augmentation_pilot30_reverse_20261008.html">30 条任务的失败引导分析</a>。本附录只回答旧 41 项目标如何筛选，两个集合的分母不同。</p>')
    parts.append(f'<p class="note">{counts["qualifies"]} 个历史目标符合“原补丁失败、gold 通过”，分布在 {m["eligible_trial_count"]} 个任务。方法命中并生成错误检出测试的历史目标为 T24-G1。它漏掉其余 {m["false_negative_target_count"]} 个正目标。这里没有测量修复后的 resolution rate。</p>')
    parts.append('<p>一个任务可以有多个历史目标。因此，30 个任务对应 41 个待复核目标。另有 3 个原先未确认的候选。本次保留其原分类，不把它们加入分母。</p>')
    parts.append('<h2>实验材料与筛选规则</h2><p>原 pilot 从 211 条失败记录中选取了 30 个任务。Python、Go、TypeScript 各 10 个。它们按旧定义都存在验证缺口。原验证缺口只表示缺少联合检查，不保证原补丁有错误。</p>')
    parts.append('<p>方法先用程序分析提取测试、程序关系及相关开发步骤。模型判断是否需要补测，并生成测试。输入为待提交补丁、公开要求、原验证测试及 trajectory。gold 和历史标签只用于事后评价。</p>')
    parts.append('<p>原实验请求 DeepSeek-v4-flash。provider 返回模型名 deepseek-flash，并将其标为 DeepSeek-V4.1-Flash。原实验调用模型 1005 次，接受 337 份测试建议。一份建议可以包含多项测试。298 份在原补丁通过，33 份失败，6 份发生执行错误。这些数量都不是已确认错误的数量。</p>')
    parts.append('<p>本次逐项阅读公开要求、历史遗漏、原补丁、gold 和已有方法输出。筛选使用以下规则。</p><ol>' + ''.join(f'<li>{escape(x)}</li>' for x in review['positive_definition']) + '</ol>')
    parts.append('<p>本次没有调用模型，没有改写测试，也没有执行被测程序。文中的“静态通过”表示源码支持该断言。它不表示实际运行通过。T24 的生成测试另外具有已保存的运行证据。</p>')
    parts.append('<p>旧 v2 要求目标关联原 benchmark 已记录的失败。本次取消这个条件。一个符合公开要求的组合测试，只要能区分原补丁与 gold，就可纳入。该测试仍不保证修复后整个任务通过。</p>')
    parts.append('<h2>筛选结果</h2>')
    parts.append(table(['结论', '目标数', '解释'], [
        [DECISIONS['qualifies'], str(counts['qualifies']), '作为本次历史目标召回率的分母。'],
        [DECISIONS['original_passes'], str(counts['original_passes']), '原目标只能改善验证覆盖，未暴露当前原补丁错误。'],
        [DECISIONS['reference_fails'], str(counts['reference_fails']), '对应检查在 gold 也失败，不能用于本次差分正例。'],
        [DECISIONS['unresolved'], str(counts['unresolved']), '预期或合法共同入口仍不完整；不作为负例。'],
    ]))
    parts.append('<p>原先 28 个待定目标中，10 个转为正例，14 个不满足 gold 通过条件，4 个仍待定。旧 v2 的 7 个正例继续保留，6 个撤销项仍不纳入。</p>')
    parts.append('<p>“gold 也失败”不是“原补丁正确”。这 14 项仍可能指出真实错误。它们只是不满足当前以 gold 为通过参照的筛选规则。判断针对下文固定的检查，不声称穷尽目标范围内的所有输入。</p>')
    parts.append('<p>新增正例包括：带分号的引号边界、同一环境切换类型约束、彩色尾串的截断、普通前缀之后的否定节点、配置校验与运行时的接受范围、同步结构内的递归、anyOf 分支规则、过短输入后的旧选择，以及嵌套网格宽度。新增正例没有提高原方法的历史命中数量。</p>')
    parts.append('<h2>与方法实验结果对比</h2>')
    parts.append(table(['统计单位', '筛选后的分母', '正确检测', '生成错误检出测试', '漏检'], [
        ['历史目标', str(m['eligible_target_count']), f'{m["detected_target_count"]}（{m["target_recall"]:.2%}）', str(m['generated_target_count']), str(m['false_negative_target_count'])],
        ['含至少一个正目标的任务', str(m['eligible_trial_count']), f'{m["detected_trial_count"]}（{m["trial_recall"]:.2%}）', str(m['generated_trial_count']), str(len(m['trials_without_historical_hit']))],
    ]))
    parts.append('<p>这里的“正确检测”要求模型说明命中对应的历史错误目标。“生成错误检出测试”要求测试本身暴露同一错误。仅指出可补测，或生成原补丁能通过的测试，都不算错误检出。</p>')
    parts.append('<p>T24-G1 是唯一历史命中。两份模型说明直接指出省略 mode 会跳过条件检查。四份建议包含 7 项有效差分测试，但都暴露同一个根因，因此目标只计一次。其中一份建议还含 gold 也失败的其他测试，不能把整份建议称为全部正确。</p>')
    parts.append('<p>旧结果声称命中的另外两项是 T10-G1 和 T14-G2。它们分别检查缓存合并和 Retry-After 传递。测试已在原补丁通过，源码也支持正确行为。按新的错误检出定义，这两项是应撤销的历史误命中。它们不构成全部方法输出的误报总数。</p>')
    parts.append('<p>本次不能报告全体 337 份建议的误报率。原结果按验证覆盖判断，不按原补丁错误判断。尚未按新定义逐份穷尽核验全部建议，也没有任务级真实负例集合。不能把未纳入的历史目标所在任务直接作为负例。</p>')
    parts.append('<p>T15-G1 和 T26-G1 分别涉及版本格式边界和泛型接口。它们符合旧单关系定义，但组合新意较弱。若暂时移除这两项，仍有 15 个正目标、13 个任务。方法仍只命中 T24-G1，结论不变。</p>')
    parts.append('<h2>方法发现的其他错误</h2><p>历史标注不是全部错误的清单。方法还发现了不对应原历史目标的错误。它们应保留为方法的有效发现，但不补入本次历史召回率的分母。</p>')
    descriptions = {
        'T04': ('取消回调抛异常，后续回调仍须执行。', '历史目标检查旧 channel 误取消新消费者。'),
        'T23': ('子作用域初始化失败后，父作用域的已初始化实例仍须保留。', '历史目标检查间接初始化依赖和初始化期间的外部读取。'),
        'T24': ('默认 put 模式必须执行条件必填检查。', '对应历史目标 T24-G1。'),
        'T11': ('内容哈希身份模式与忽略空白共同生效。', '历史目标检查父节点删除与多个子节点新增。'),
    }
    rows = []
    for cid in ['T04', 'T23', 'T24', 'T11']:
        ws = [w for group in witnesses.values() for w in group if w['case'] == cid]
        rows.append([cid, escape(descriptions[cid][0]), str(sum(len(w['matched_tests']) for w in ws)),
                     escape(descriptions[cid][1]), '此前的环境对齐记录；单列' if cid == 'T11' else '原样测试的已保存对照'])
    parts.append(table(['任务', '有效组合检查', '具名测试数', '与历史目标的关系', '证据'], rows))
    parts.append('<p>原样测试中，已核实 3 个任务有有效差分测试：T04、T23、T24。共有 6 份建议包含 9 项有效测试。计入此前 T11 的环境对齐记录后，共 4 个任务、10 项有效测试。T11 使用文档要求的 diff 构建标签，并给两份实现补齐同一组原测试辅助文件；生成测试内容未变。</p>')
    parts.append('<p>上述 3/30 或含环境对齐的 4/30，表示已核实的错误检出任务数。它们不是 resolution rate。T04、T23、T11 不能因为未命中旧历史目标而被算作误报。</p>')
    parts.append('<h2>30 个任务逐项对比</h2><p>“其他发现”列只列已有差分证据。不纳入某历史目标，不代表该任务没有其他错误。详细组合与代码理由见下一部分。</p>')
    rows = []
    for c in summary['trials']:
        related = [r for r in targets if r['case'] == c['case']]
        items = '<br>'.join(f'<a href="#{r["id"]}">{r["id"]}</a>：{escape(DECISIONS[r["decision"]])}' for r in related)
        other = '有；不同于历史目标' if c['other_differential_witness'] else '有；此前环境对齐，单列' if c['prior_environment_differential_witness'] else '—'
        rows.append([f'{c["case"]}<br><span class="muted">{escape(c["task"])}</span>', items,
                     str(c['method_test_packets']), '<br>'.join(c['detected_targets']) or '0',
                     '<br>'.join(c['generated_targets']) or '0', other])
    parts.append(table(['任务', '历史目标筛选', '原方法测试建议数', '历史检测命中', '历史错误检出测试', '其他发现'], rows))
    parts.append('<h2>41 个目标的输入、结果与依据</h2><p>每项保留原编号。原验证内容来自已保存的 trajectory 审读。下面将其与本次具体输入和两份补丁的行为并列。</p>')
    for r in targets:
        sg = r['original_gap']['source_gap']
        parts.append(f'<details id="{r["id"]}" open><summary>{r["id"]} · {escape(r["target"])} · {escape(DECISIONS[r["decision"]])}</summary>')
        parts.append(f'<p><b>原验证：</b>{escape(sg.get("original_separate_checks", "见原始记录"))}</p>')
        parts.append(f'<p><b>组合检查：</b>{escape(r["witness"])}</p>')
        parts.append(f'<p><b>原补丁：</b>{escape(r["candidate_behavior"])}</p>')
        parts.append(f'<p><b>两份补丁的对照：</b>{escape(r["paired_reason"])}</p>')
        parts.append(f'<p><b>预期依据：</b>{escape(sg.get("oracle", "见公开需求及原审读"))}</p>')
        old = next(c for c in summary['trials'] if c['case'] == r['case'])
        method_note = '检测命中；生成测试也暴露此错误。' if r['method_detected'] else (
            '未命中。' + old['miss_reason'] if r['primary_positive'] else
            '不进入正目标召回率分母。' + ('旧历史命中在本次撤销。' if r['historical_match_candidates'] else ''))
        parts.append(f'<p><b>方法结果：</b>{escape(method_note)}</p>')
        if r.get('combination_boundary_note'):
            parts.append(f'<p>{escape(r["combination_boundary_note"])}</p>')
        evidence = r['evidence']
        evidence_links = [link(ROOT / evidence['gold_patch']['path'], 'gold 补丁'),
                          link(ROOT / evidence['method_review']['path'], '方法原审读'),
                          link(Path(evidence['original_review']['path']), '历史审读')]
        evidence_links += [link(ROOT / x['path'], '原源码：' + Path(x['path']).name) for x in evidence['candidate_source_files']]
        parts.append('<p class="links">' + ' '.join(evidence_links) + '</p>')
        if r.get('external_basis'):
            source = r['external_basis']
            parts.append(f'<p>配置约束的外部依据：<a href="{escape(source["url"])}">{escape(source["title"])}</a>。本项为结合该规范与两份 schema 的静态推导。</p>')
        parts.append('</details>')
    parts.append('<h2>仍待定的四项目标</h2>')
    parts.append(table(['目标', '缺少的依据'], [[r['id'], escape(r['paired_reason'])] for r in targets if r['decision'] == 'unresolved']))
    parts.append('<p>这四项不再因为“没有关联原 benchmark 失败”而待定。T03 和 T21 缺少明确的结果要求。T29 的两项还存在到达组合行为前的公开接口错误。按当前证据，强行分类会把不同问题混在一起。</p>')
    parts.append('<h2>结果能支持什么结论</h2><p>新规则可以筛掉仅增加覆盖的目标，也能保留与原 benchmark 失败不同的真实错误。它同时依赖 gold 的质量。gold 共享错误时，该规则会漏掉真实缺陷。因此，论文应把它称为差分错误检出评价，而不是全部缺陷的完备判定。</p>')
    parts.append('<p>目前方法对修复相关历史目标的召回率仍低。遗漏集中在跨操作状态、跨层约束和分支选择后的信息保留。仅生成更多能通过原补丁的组合测试，不能解决这一问题。</p>')
    parts.append('<p>若下一步继续优化，应先用这 17 个目标检查程序提取是否保留了决定差异的条件，再检查模型是否把条件落实到输入和断言。该诊断可分开定位提取遗漏与测试生成遗漏。本报告没有开展新实验。</p>')
    parts.append('<p>' + escape(review['reviewer']) + ' ' + escape(review['evaluation_caveat']) + '</p>')
    parts.append('<h2>数据与复核入口</h2><p class="links">' + ' '.join([
        link(OUT / 'review.json', '逐项目标判断'), link(OUT / 'labels.json', '标签与证据校验值'),
        link(OUT / 'summary.json', '统计结果'), link(OUT / 'verification.json', '完整性检查'),
        link(GOLD / 'summary.json', '已有差分测试明细'), link(RUN / 'summary.json', '冻结原实验结果'),
        link(ROOT / 'docs/archive/20261008_gap_relabeling_n30.html', '归档 v2 报告'),
    ]) + '</p><p>重新生成：<code>.venv/bin/python scripts/summarize_augmentation_pilot30_static.py</code></p></html>')
    REPORT.write_text('\n'.join(parts) + '\n')


def main():
    values = summarize()
    render(*values)
    review, labels, summary, _, _ = values
    references = []

    def collect(value):
        if isinstance(value, dict):
            if 'path' in value and 'sha256' in value:
                references.append(value)
                verify(value)
            for v in value.values():
                collect(v)
        elif isinstance(value, list):
            for v in value:
                collect(v)

    collect(labels)
    write(OUT / 'verification.json', {
        'version': review['version'], 'reference_receipts_verified': len(references),
        'distinct_reference_files_verified': len({r['path'] for r in references}),
        'all_30_trials_accounted_for': len(summary['trials']) == 30,
        'all_41_historical_targets_accounted_for': len(labels['targets']) == 41,
        'frozen_summary_and_original_review_hashes_verified': True,
        'new_subject_executions': 0, 'report': receipt(REPORT),
    })
    write(RUN / 'active_evaluation.json', {
        'version': review['version'], 'scope': 'Current 30 trials; static candidate-fail/gold-pass historical screening',
        'labels': receipt(OUT / 'labels.json'), 'review': receipt(OUT / 'review.json'),
        'summary': receipt(OUT / 'summary.json'), 'report': receipt(REPORT),
        'archived_v2_labels': receipt(RUN / 'historical_relabel_v2/labels.json'),
        'archived_validation_only_truth': receipt(RUN / 'evaluation_truth.json'),
        'archived_validation_only_summary': receipt(RUN / 'summary.json'),
        'rebuild_command': '.venv/bin/python scripts/summarize_augmentation_pilot30_static.py',
        'generation_use': 'Evaluation only; gold and revised labels were not inputs to original generation.',
    })
    print(json.dumps({'decisions': summary['decisions'], 'metrics': summary['historical_target_metrics'],
                      'report': str(REPORT)}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
