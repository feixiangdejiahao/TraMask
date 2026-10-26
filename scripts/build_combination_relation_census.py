"""Build the 2026-10-07 relation census from explicit, evidence-bound coding.

No subject code, trajectory command, or model request is executed.
"""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
import hashlib
import html
import json
from pathlib import Path
import re
import os
from urllib.parse import quote

from result_paths import canonical_path

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / 'research/deepswe_failure_manual_20261006'
BASE = ROOT / 'research/combination_relation_census_20261007'
OUT = ROOT / 'docs/archive/20261007_combination_relation_census_n211.html'


def read(path):
    return json.loads(path.read_text())


def receipt(path):
    return {'path': str(path.relative_to(ROOT)),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def category(classes):
    if classes == {'S', 'M'}:
        return 'both'
    if classes == {'S'}:
        return 'single_only'
    if classes == {'M'}:
        return 'multi_only'
    assert not classes, classes
    return 'no_confirmed'


def link(path, label):
    relative = quote(os.path.relpath(canonical_path(path), OUT.parent), safe='/@:+')
    return f'<a href="{html.escape(relative, quote=True)}">{html.escape(label)}</a>'


def table(headers, rows):
    return ('<div class="table"><table><thead><tr>' + ''.join(f'<th>{html.escape(str(x))}</th>' for x in headers)
            + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f'<td>{html.escape(str(x))}</td>' for x in row)
              + '</tr>' for row in rows) + '</tbody></table></div>')


def main():
    protocol = read(BASE / 'protocol.json')
    manifest = read(BASE / 'source_index.json')
    files = sorted((OLD / 'trials').glob('*.json'))
    assert len(files) == len(manifest) == 211
    with (BASE / 'coding.tsv').open() as f:
        coding = list(csv.DictReader(f, delimiter='\t'))
    annotations = {}
    for row in coding:
        key = int(row['record']), int(row['gap'])
        assert key not in annotations, key
        assert row['class'] in {'S', 'M', 'X'}
        assert all(row[k] for k in ('shape', 'screen', 'basis'))
        annotations[key] = row
    records, used = [], set()
    tasks = defaultdict(lambda: {'classes': set(), 'trials': []})
    screens, gap_classes, shape_sizes = Counter(), Counter(), Counter()
    record_screens = defaultdict(set)
    for ordinal, (path, frozen) in enumerate(zip(files, manifest), 1):
        source = read(path)
        cross_path = OLD / 'cross_review/trials' / path.name
        cross = read(cross_path)
        assert source['trial'] == frozen['trial'] == path.stem
        assert receipt(path) == frozen['primary']
        assert receipt(cross_path) == frozen['cross_review']
        assert cross['status'].startswith('accepted'), (path, cross['status'])
        assert cross['primary_report_receipt']['sha256'] == frozen['primary']['sha256']
        gap_rows, classes = [], set()
        for index, gap in enumerate(source['combination_gaps'], 1):
            key = ordinal, index
            row = annotations[key]
            used.add(key)
            cls = row['class']
            tags = [] if cls == 'X' else row['screen'].split(',')
            assert set(tags) <= set(protocol['screen_labels'])
            assert len(tags) == len(set(tags))
            nodes = re.split('[→←]', row['shape'])
            if cls == 'S':
                assert len(nodes) == 2, key
            elif cls == 'M':
                assert len(nodes) >= 3, key
                shape_sizes[len(nodes)] += 1
            if cls != 'X':
                classes.add(cls)
                screens.update(tags)
                for tag in tags:
                    record_screens[tag].add(source['trial'])
            gap_classes[cls] += 1
            gap_rows.append({
                'source_gap_index_1based': index,
                'source_gap_id': gap.get('id'),
                'class': cls,
                'class_label': protocol['class_labels'][cls],
                'relation_shape': row['shape'],
                'representation_node_count': len(nodes) if cls != 'X' else None,
                'minimal_input_interaction_order': None,
                'reason': row['basis'],
                'screen_features': tags,
                'source_gap': gap,
            })
        if source['verdict'] in {'no_confirmed_combination_gap', 'selection_problem'}:
            assert not classes, source['trial']
        else:
            assert classes, source['trial']
        records.append({
            'ordinal': ordinal, 'trial': source['trial'], 'task': source['task'],
            'original_verdict': source['verdict'], 'original_verdict_reason': source['verdict_reason'],
            'category': category(classes), 'classes': sorted(classes), 'gaps': gap_rows,
            'primary_receipt': frozen['primary'], 'cross_review_receipt': frozen['cross_review'],
            'original_source_receipts': source['source_receipts'],
        })
        tasks[source['task']]['classes'].update(classes)
        tasks[source['task']]['trials'].append(source['trial'])
    assert used == set(annotations)
    assert len(used) == 286
    task_rows = [{'task': task, 'classes': sorted(v['classes']), 'category': category(v['classes']),
                  'trials': v['trials']} for task, v in sorted(tasks.items())]
    summary = {
        'records': len(records), 'tasks': len(task_rows), 'source_gap_entries': len(used),
        'confirmed_gap_entries': gap_classes['S'] + gap_classes['M'],
        'gap_classes': dict(gap_classes), 'record_categories': dict(Counter(r['category'] for r in records)),
        'task_categories': dict(Counter(r['category'] for r in task_rows)),
        'original_verdicts': dict(Counter(r['original_verdict'] for r in records)),
        'multi_relation_representation_nodes': dict(sorted(shape_sizes.items())),
        'screen_gap_entries': dict(screens),
        'screen_records': {k: len(v) for k, v in record_screens.items()},
        'automated_detection_performance': None,
        'minimal_interaction_order_measured': False,
    }
    result = {'protocol': protocol, 'summary': summary, 'records': records, 'tasks': task_rows,
              'input_receipts': [receipt(BASE / n) for n in ('protocol.json', 'coding.tsv', 'source_index.json')]}
    result_path = BASE / 'census.json'
    # The 2026-10-07 scientific record is frozen. Regenerate only its reader.
    assert read(result_path)['summary'] == json.loads(json.dumps(summary)), 'Frozen census differs; create a separate revision.'

    e = html.escape
    category_labels = {'single_only': '仅报告单关系缺口', 'multi_only': '仅报告多关系缺口',
                       'both': '两类均有', 'no_confirmed': '未确认组合缺口或仅有选测问题'}
    counts = summary['record_categories']
    task_counts = summary['task_categories']
    confirmed = summary['confirmed_gap_entries']
    overview = table(['缺口结构', '条目数', '占已确认条目'], [
        ('单关系', gap_classes['S'], f'{gap_classes["S"]/confirmed:.1%}'),
        ('多关系', gap_classes['M'], f'{gap_classes["M"]/confirmed:.1%}'),
        ('合计', confirmed, '100%'),
    ])
    cohort = table(['记录或任务中的缺口类型', '失败记录（共211）', '去重任务（共90）'],
                   [(category_labels[k], counts[k], task_counts[k])
                    for k in ('single_only', 'multi_only', 'both', 'no_confirmed')])
    features = table(['线索', '涉及缺口条目', '程序分析可以检查什么', '典型材料'], [
        ('联系未对应验证', screens['F'], '比较生产者与消费者的字段、返回值、对象绑定和实际入口；检查测试是否连接同一来源。',
         'Igel：别名列选择与按原列名编码各自通过；Testem：mock增加了真实结果没有的字段。'),
        ('输入不激活或不判别', screens['A'], '检查前置分支、读写字段交集、空集合、恒等值、单元素、同序数据，以及不同条件是否始终同真同假。',
         'SQLite：UPDATE改name，规则却只看COUNT；TOC：区域内标题已被层级条件排除。'),
        ('状态与时序不足', screens['T'], '在同一对象上比较状态写入与后继操作；找仅新建对象、错误后无后继、清空后同键重用及延迟事件。',
         'Anko：开关模式各用新Env；LangChain：旧执行未完成时清空并重用同key。'),
        ('观察不足', screens['O'], '追踪相关字段或状态是否到达断言；检查丢弃返回值、只看数量或成功、错误捕获范围和观察时点。',
         'Pest：空白组合已执行，只断言is_ok；HTTPX：完整收集无法检查首项提前产出。'),
    ])
    cards = []
    for rec in records:
        rec_links = ' · '.join([
            link(rec['primary_receipt']['path'], '原主审记录'),
            link(rec['cross_review_receipt']['path'], '原复核记录'),
            link(f'results/deepswe_failure_manual_20261006/trials/{rec["trial"]}/trajectory.json', '原trajectory'),
            link(f'results/deepswe_failure_manual_20261006/trials/{rec["trial"]}/model.patch', '提交patch'),
            link(f'results/deepswe_failure_manual_20261006/trials/{rec["trial"]}/instruction.md', '公开任务'),
        ])
        gap_html = []
        for g in rec['gaps']:
            tags = '；'.join(protocol['screen_labels'][t] for t in g['screen_features'])
            gap_html.append(f'<div class="gap"><p><b>原条目 {g["source_gap_index_1based"]}：{e(g["class_label"])}</b></p>'
                            f'<p class="shape">{e(g["relation_shape"])}</p><p>{e(g["reason"])}</p>'
                            + (f'<p class="muted">筛选线索：{e(tags)}</p>' if tags else '') + '</div>')
        if not gap_html:
            gap_html = ['<p>原报告未列入确认缺口。本轮不把已有失败反馈、错误期望或选测问题改算为新的组合缺口。</p>']
        search = e(' '.join([rec['trial'], rec['original_verdict_reason']] +
                           [g['relation_shape'] + g['reason'] for g in rec['gaps']]).lower(), quote=True)
        cards.append(f'<details class="record" id="r{rec["ordinal"]:03}" data-category="{rec["category"]}" data-search="{search}">'
                     f'<summary>{rec["ordinal"]:03} · {e(rec["trial"])} · {category_labels[rec["category"]]}</summary>'
                     f'<p>{e(rec["original_verdict_reason"])}</p>{"".join(gap_html)}<p class="links">{rec_links}</p></details>')
    rules = ''.join(f'<li>{e(rule)}</li>' for rule in protocol['coding_rules'][1:])
    report = f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>组合缺口的关系结构与程序筛选：211条记录复核</title>
<style>
body{{font:17px/1.8 system-ui,sans-serif;color:#202c3b;max-width:1120px;margin:auto;padding:30px 22px;background:#fafbfc}}
h1{{font-size:1.8rem;line-height:1.4}}h2{{font-size:1.35rem;margin-top:2.2rem}}p{{margin:.8em 0}}a{{color:#1859a4}}
.lead,.box{{background:#edf4ff;border-left:4px solid #2868b2;padding:14px 20px}}.muted{{color:#566578;font-size:.94em}}
.table{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;background:white}}th,td{{text-align:left;vertical-align:top;border:1px solid #d5dde6;padding:10px 13px}}th{{background:#eef2f7}}
.record{{background:white;border:1px solid #d5dde6;border-radius:6px;padding:12px 16px;margin:12px 0}}summary{{cursor:pointer;overflow-wrap:anywhere}}
.gap{{border-left:3px solid #ccd8e8;padding-left:14px;margin:15px 0}}.shape{{font-weight:600}}.links{{font-size:.9em}}input,select{{font:inherit;max-width:100%;padding:8px;margin:4px}}
.controls{{background:#eef2f7;padding:14px;margin-top:20px}}li{{margin:.5em 0}}[hidden]{{display:none!important}}
@media print{{.controls{{display:none}}body{{max-width:none;background:white}}.record{{break-inside:avoid}}}}
</style></head><body>
<h1>组合缺口的关系结构与程序筛选</h1>
<aside class="box" id="counterfactual-revision"><strong>2026-10-21 口径更新：</strong>本页的 264 条是历史“验证覆盖缺口”条目，不是与实际 evaluation 失败相关的组合缺口数。全部 211 个 trial 已按“补有效联合检查是否可能指导修复并改善 F2P/P2P”重新手动审查。请先看<a href="deepswe_failure_manual_20261006.html">当前逐 trial 报告</a>及<a href="../research/deepswe_counterfactual_review_20261021/summary.json">新统计</a>。本页的单/多关系编码与原实验数据保留，不自动转换为新标签；下文“确认”均指旧覆盖口径。</aside>
<p class="muted">2026-10-07 · 211条失败记录 · 90个不同任务 · 在既有完整审读上进行关系重编码</p>
<p class="lead">本次纳入264个已确认验证缺口条目。200个可用单条关系定位，64个需要保留多条相连关系。后续原型应同时检查单关系和短关系链，并用输入、状态和断言特征提前筛选。</p>
<p>这是一份方法设计依据。它没有运行新的补测，也没有测量新算法的检测率。验证缺口不等于patch存在错误。</p>
<h2>统计对象与做法</h2>
<p>数据来自DeepSWE v1.1中原模型为deepseek-v4-flash、结果为fail的全部211次尝试。它们属于90个任务和75个项目。原研究已完成211份主审和211份另一位AI助手的复核。</p>
<p>本轮逐条读取主审结论、全部286个缺口或候选条目，以及对应复核分类。对边界条目追加检查程序关系及复核证据。另核对4个代表任务的公开需求，并检查现有提取器。逐条分类由当前AI助手完成，未做独立复标。本轮没有第三次全文审读所有原始trajectory。</p>
<p>保留原报告的条目粒度。其中21项仍是未确认候选，另1项已有原始运行反证覆盖，因此排除22项。剩余264项用于结构统计。一个条目可能含多个例子或观察；它不是一个独立bug，也不代表所有可能缺口已经穷尽。</p>
<p>未确认patch缺陷不会导致已确认验证缺口被排除。两个Kgateway条目就是例子：原复核支持跨层验证缺失，只把API接收请求时的实际校验后果保留为候选。本次将它们计入。</p>
<h2>怎样区分单关系与多关系</h2>
<p><b>单关系</b>连接两个相关端点。例如，UPDATE写入的字段影响规则读取的值。补测需要使这条影响实际发生，并检查其结果。</p>
<p><b>多关系</b>保留一个短链、汇合、嵌套或跨阶段生命周期。例如，上游初始化经过无初始化器的服务，再影响下游初始化。又如，旧执行仍活动，clear清空状态，新执行重用同key，旧执行随后返回。</p>
<p>关系数量不等于输入因素数量。返回值从产生操作传到使用操作，可以经过多个函数。一个三节点简图也可能只需改变两个输入因素。以下计数是固定解释粒度下的描述性编码，不是最小二维或高维交互阶数的证明。</p>
<details><summary>查看完整归类规则与边界</summary><ul>{rules}</ul></details>
<h2>逐条统计结果</h2>
{overview}
<p>“单关系”包括端点未连接、联合输入不敏感、观察不足三种情形。“多关系”也包括已有完整操作序列却没有正确观察的情形。因此，不能把264项都写成“缺少联合输入”。</p>
{cohort}
<p>181条记录有至少一个原报告确认的缺口。其中154条包含单关系缺口，59条包含多关系缺口，二者交集为32条。剩余30条为29条未确认缺口及1条纯选测或保留问题。</p>
<p>去重后，86个任务至少有一次失败尝试报告了缺口。81个任务含单关系缺口，34个任务含多关系缺口。去重统计只取各次尝试的并集，不能推断同任务的每次尝试都遗漏同一关系。</p>
<p>64个多关系条目中，60个在本次简图中有3个节点，4个有4个节点。4节点项涉及Kombu旧新channel复用、Koota不重叠成分历史、LangChain旧新执行交错，以及Quill创建者与活动者分离的延迟事件。这些是表示大小，不是最小测试长度或检测成功率。</p>
<h2>程序分析可以提前筛选什么</h2>
<p>现有数据支持四类可检查线索。它们针对测试的验证能力，不针对各项目编写独立变异规则。各类可以重叠；下表数量不能相加。</p>
{features}
<p>这些数量来自本轮语义编码，尚未用程序提取器验证。尤其是字段含义、合法输入及期望结果，仍可能需要任务语义。不能把175项“联系线索”直接报告为175项自动检出。</p>
<p>程序分析可以直接识别部分强信号。例如，返回值被丢弃；不同测试每次创建新对象；错误之后没有后继操作；检查结构之前必先因校验和不匹配返回；原测试只有空集合、单元素或相同值。数据流与控制流可把这些信号绑定到patch相关关系。</p>
<p>对于不敏感输入，程序应检查目标关系是否有机会改变结果。例如，UPDATE只写name，而测试规则只读取COUNT。这里应标记该测试不能验证“更新触发规则拒绝”。不能因为本例读写不相交，就把UPDATE与规则的整个候选关系删除。</p>
<p>对于观察不足，程序应从断言反向查找所读的字段与状态。没有数据或控制依赖，是可疑线索。存在依赖则仍不保证断言正确。快照断言和期望常量是否符合公开需求，仍需语义判断。</p>
<h2>补充后的简化算法</h2>
<p><b>第一步：按程序关系定位小范围。</b> 从patch相关操作出发，收集数据传递、共享状态、控制依赖和对象归属。关联原测试，并取得相关trajectory中的阅读、修改和执行反馈。</p>
<p><b>第二步：先由程序检查验证结构。</b> 对每个关系候选检查三件事：原测试是否连接相关端点；输入是否激活目标条件；断言是否观察相关结果。程序用上表四类线索选择候选。发给模型的是关系、缺少的连接或观察线索，以及对应原测试。</p>
<p><b>第三步：只沿相连关系扩展。</b> 同时搜索单条关系和共享端点的两条关系。中间状态涉及聚合、身份、作用域、递归返回或生命周期时，保留这段结构。看到清空后同键重用等明确线索，再扩到三条关系。不要组合互不相关的功能，也不要等单关系测试失败后才扩展；两段分别通过正是多关系缺口的一种来源。</p>
<p><b>第四步：让模型做局部语义判断并补测。</b> 模型读取公开需求、关系结构、原测试和相关trajectory。它判断该联系是否应受验证。若有缺口，它直接改输入、连接操作或增强断言。无需先生成完整检查规范。运行结果分别说明是否增加有效验证，以及是否揭示patch错误。</p>
<p>已有有效联合测试但未运行或被删除，应恢复、选择并复核该测试。已有明确失败应沿原反馈处理。两者不计为新生成组合的收益。</p>
<p>当前提取器已能提供调用、赋值通道和历史关联线索。它的部分使用关系仍是词法匹配，历史关联也主要依赖路径和名称。上面的关系筛选及扩展尚未实现。下一轮pilot应先检查程序能否重建这些简图和触发这些筛选线索，再检查模型能否据此完成有效补测。</p>
<h2>对问题抽象和新意的影响</h2>
<p>问题可以表述为：已有验证覆盖了一些操作和局部结果，但没有充分验证它们之间的影响。方法应寻找程序中存在、而验证中未连接、未激活或未观察的关系。多关系时，还需保持中间的身份、作用域或状态。</p>
<p>可检验的方法贡献是：用程序关系及验证能力的差异定位补测目标，再让模型完成局部语义判断和生成。只画调用图、检索历史或调用模型补测试，本身不足以体现这项贡献。当前统计支持这一研究假设，还未证明算法有效或完成对新意的文献验证。</p>
<h2>逐条依据</h2>
<p>每条记录保留原结论、每个条目的关系简图、归类理由和可回查材料。没有缺口的记录也保留。数据文件：{link('research/combination_relation_census_20261007/census.json', '完整JSON')} · {link('research/combination_relation_census_20261007/coding.tsv', '逐条编码')} · {link('research/combination_relation_census_20261007/protocol.json', '统计口径')}。</p>
<div class="controls"><label>搜索任务或内容 <input id="search" type="search" placeholder="例如：awilix、共享、断言"></label>
<label>记录类型 <select id="category"><option value="">全部</option>{''.join(f'<option value="{k}">{v}</option>' for k,v in category_labels.items())}</select></label>
<span id="shown" aria-live="polite">显示211条</span></div>
{''.join(cards)}
<script>
const search=document.getElementById('search'), category=document.getElementById('category');
const records=Array.from(document.querySelectorAll('.record'));
function filterRecords(){{const q=search.value.trim().toLowerCase(),c=category.value;let shown=0;
for(const r of records){{const ok=(!q||r.dataset.search.includes(q))&&(!c||r.dataset.category===c);r.hidden=!ok;if(ok)shown++;}}
document.getElementById('shown').textContent=`显示${{shown}}条`;}}
search.addEventListener('input',filterRecords);category.addEventListener('change',filterRecords);
</script></body></html>'''
    OUT.write_text(report)
    # Preserve the historical audit, including its original report receipt.
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
