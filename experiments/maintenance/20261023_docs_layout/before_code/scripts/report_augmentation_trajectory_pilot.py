"""Render the completed trajectory detection pilot; no provider or subject calls."""
from collections import Counter, defaultdict
from html import escape
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/"src")]
from scripts.review_augmentation_trajectory_pilot import summarize
from scripts.run_augmentation_trajectory_pilot import RUN,OLD,ARMS,CASES,read

NAMES={"A_artifacts":"A：代码与测试片段","B_history":"B：加入开发过程","C_plan":"C：模型先建行为模型","D_computed":"D：再加入程序计算"}
CASELABELS={"T10":"Bandit：增量缓存与命令行","T11":"etree：XML 比较、补丁与合并","T13":"Tengo：闭包调用与实例复制","T17":"Tengo：解构与默认值","T20":"kgateway：配置校验与路由策略","T23":"Awilix：初始化与回滚","T24":"DynamoDB Toolbox：条件必填","T28":"TanStack Query：持久化状态恢复"}
GROUPLABELS={
"T10_limit":"重用缓存时修改容量上限","T10_bad_timestamp":"损坏时间戳与过期处理","T10_nested_config":"嵌套配置读取","T10_bad_issue":"损坏告警字段","T10_ignore_nosec":"扫描选项与缓存键",
"T11_swap":"节点交换后应用补丁","T11_sibling_merge":"删除与兄弟新增的合并","T11_nested_remove":"父子节点同时删除的冲突数","T11_duplicate_attrs":"重复属性与相等判断","T11_reverse_element":"反转元素新增补丁","T11_reverse_attribute":"反转属性补丁","T11_wildcard_tag_move":"通配 key 与跨标签移动","T11_position_replace":"位置替换后的节点顺序","T11_text_child_merge":"文本与子节点修改的合并",
"T13_transfer_shared":"复制或转移后的共享捕获","T13_return_shared":"返回闭包容器后的共享捕获","T13_different_global_layout":"不同全局变量布局的转移",
"T17_present_undefined":"存在的 undefined 与默认值",
"T20_fractional_duration":"小数时长经过配置准入","T20_inherited_disable":"优先级、合并与 disable","T20_empty_default_before_merge":"空配置的默认策略参与合并",
"T23_void_initializer":"无返回值初始化与随后 resolve","T23_indirect_dependency":"经过普通节点的初始化依赖","T23_indirect_cycle":"经过普通节点的依赖环","T23_scope_rollback":"子作用域回滚与父对象身份",
"T24_default_mode":"省略模式与条件必填","T24_inherited_name":"继承属性名称与兄弟字段校验","T24_require_selected_anyof":"所选分支的正向条件","T24_no_extra_anyof":"未选分支不得产生额外条件","T24_hidden_formatter":"隐藏字段与格式化检查","T24_hidden_formatted":"隐藏字段与格式化值 schema","T24_list_condition":"列表内字段与自动条件",
"T28_false_marker":"恢复错误状态与 false 标记","T28_lazy_timestamp":"延后恢复与较新错误时间","T28_null_error_counter":"空错误与错误计数","T28_marker_adopt_over_live":"自定义恢复状态与已有状态"}
VERDICTS={"accepted":"符合本轮规则","rejected":"不符合本轮规则","unresolved":"待定"}
GROUPLABELS.update({"T24_anyof_put_fallback":"anyOf 分支失败后的回退","T24_other_update_entry":"其他更新入口的自动条件","T10_summary_unique_paths":"缓存记录与不同路径的计数","T11_nested_remove_exactly_one":"嵌套删除要求恰好一项冲突"})
GROUPLABELS.update({"T11_same_add_merge":"两侧相同新增后的合并结果","T13_nested_capture_clone":"复制后直接与间接共享捕获","T13_layout_real_mismatch":"目的变量存在但索引不同","T13_arity_error_format":"Go 调用的参数错误格式","T28_marker_return_merged":"返回值与恢复后状态的一致性"})
GROUPLABELS.update({"T20_regex_only_unobserved":"未检查 regexRewrite 的测试建议","T17_overwritten_observation":"未单独观察早期绑定的测试建议"})
GROUPLABELS.update({"T20_empty_with_disable":"空配置、低优先级 disable 与最终策略","T28_default_refetch":"默认刷新后的恢复状态"})
GROUPLABELS.update({"T28_custom_hash_restore":"自定义查询标识与已有状态恢复"})

def table(headers,rows):
    return '<div class="table"><table><thead><tr>'+''.join('<th>'+escape(str(h))+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table></div>'

def link(path,label):
    path=Path(path)
    return '<a href="../'+escape(str(path.relative_to(ROOT)),quote=True)+'">'+escape(label)+'</a>'

def main():
    s=summarize()
    assert s['completed']==64, 'experiment_not_complete'
    assert not s['unreviewed_affirmatives'], 'claims_not_reviewed'
    assert not s['extraction_review']['unreviewed_models'], 'models_not_reviewed'
    assert len(s['paired_input_audit'])==16 and all(p['only_feedback_differs'] for p in s['paired_input_audit'])
    rows=read(RUN/'evaluation/adjudicated_claims.json')
    review=read(RUN/'evaluation/semantic_review.json')
    extraction=read(RUN/'evaluation/extraction_review.json')
    groups={**read(OLD/'evaluation/semantic_review.json')['groups'],**review['groups']}
    aggregates={(x['arm'],x['repeat']):x for x in s['aggregates']}
    def pair(arm,fn):return ' / '.join(str(fn(aggregates[arm,r])) for r in [1,2])
    metric_rows=[]
    for arm in ARMS:
        metric_rows.append([NAMES[arm],pair(arm,lambda x:len(x['correct_tasks'])),pair(arm,lambda x:len(x['exact_reference_hits'])),pair(arm,lambda x:len(x['exact_reference_misses'])),pair(arm,lambda x:x['affirmative_claims'].get('rejected',0)),pair(arm,lambda x:x['affirmative_claims'].get('unresolved',0))])
    case_rows=[]
    scores={(x['case'],x['arm'],x['repeat']):x for x in s['scores']}
    for case in CASES:
        case_rows.append([CASELABELS[case]]+[' / '.join('是' if scores[case,a,r]['correct_task'] else '否' for r in [1,2]) for a in ARMS])
    input_rows=[]
    for case in CASES:
        b=read(RUN/'inputs'/case/'base.json');h=read(RUN/'inputs'/case/'history.json');f=read(RUN/'inputs'/case/'facts.json')
        input_rows.append([case,len(b['source']),len(b['validation_tests']),h['counts']['events'],h['counts']['detailed'],len(f),len(b['literal_call_inventory'])])
    comparisons=[]
    for x in s['paired_outcomes']:
        c=x['outcomes'];comparisons.append([NAMES[x['left']]+' → '+NAMES[x['right']],c.get('both',0),c.get('left_only',0),c.get('right_only',0),c.get('neither',0)])
    ref_rows=[]
    ref_details=[]
    extra_reference_text={
        'T20-G1':('原验证使用整数时长，或直接调用 Go 构造函数。','令 ttl=1.5s，同时经过资源配置校验和运行时构造。原正则拒绝小数；gold 接受该输入并生成 1.5 秒的 TTL。'),
        'T20-G2':('原重复项测试直接调用构造函数，检查保留第一项。','令同名 q 的两个配置项分别取 terminal=true 和 false，先通过资源配置校验。原 list-map 唯一键限制先拒绝输入；gold 允许进入构造阶段并保留第一项。'),
        'T24-G2':('原 anyOf 探测只有一个 map；其他保存名检查也使用单一 map 树。','令 anyOf 的 A/B 两分支使用不同条件和保存名。输入只匹配 B，且不触发 B 的条件。原规则收集仍遍历 A，错误附加 A 的存在条件。gold 跳过该 anyOf，不附加条件。此目标不要求 gold 完整支持所选分支的正向条件。')}
    for ref in read(RUN/'evaluation/fixed_reference_digest.json')['targets']:
        hit=[];same=[]
        for a in ARMS:
            for r in [1,2]:
                if ref['id'] in aggregates[a,r]['exact_reference_hits']:hit.append(a[0]+str(r))
                elif ref['id'] in aggregates[a,r]['same_defect_reference_hits']:same.append(a[0]+str(r))
        description='未选 anyOf 分支不得附加额外条件' if ref['id']=='T24-G2' else ref['description']
        ref_rows.append([ref['id'],description,'、'.join(hit) or '未命中','、'.join(same) or '无'])
        if ref['id'] in extra_reference_text:
            original,distinction=extra_reference_text[ref['id']]
        else:
            original=ref['original_validation']
            distinction=ref['distinguishing_check']
        ref_details.append([ref['id'],original,distinction])
    case_cards=[]
    for case in CASES:
        grouped=defaultdict(list)
        for row in rows:
            if row['case']==case and row['decision']=='gap':grouped[row['semantic_group']].append(row)
        parts=[]
        for group,claims in grouped.items():
            g=groups[group];tag=GROUPLABELS.get(group,group)
            locations='、'.join(sorted({c['arm'][0]+str(c['repeat']) for c in claims}))
            parts.append('<p><strong>'+escape(tag)+'：</strong>'+escape(VERDICTS[g['verdict']])+'。出现于 '+escape(locations)+'。</p><p>'+escape(g['rationale_zh'])+'</p>')
        case_cards.append('<details><summary>'+escape(CASELABELS[case])+'</summary>'+''.join(parts)+'</details>')
    model_rows=[]
    for key,v in extraction['models'].items():
        model_rows.append([key,{'label_only':'整项问题的布尔标签','input_case_table':'输入类别与结果表','operational':'操作的条件表达式'}.get(v['encoding'],v['encoding']),v['rationale_zh']])
    reasoning=s['extraction_review']
    valid=s['affirmative_verdicts'].get('accepted',0);rejected=s['affirmative_verdicts'].get('rejected',0);unresolved=s['affirmative_verdicts'].get('unresolved',0)
    preflight=read(RUN.parent/'trajectory_contrast8_20261010_v1/preflight_closeout.json')
    binding_audit=read(RUN/'evaluation/binding_format_audit.json')
    binding_review=read(RUN/'evaluation/binding_format_review.json')
    technical_runs=[x for x in s['scores'] if x['technical_unknown_stages']]
    page='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Coding agent 组合缺口检测 pilot</title><style>
body{margin:0;background:#f6f8fa;color:#172334;font:17px/1.85 system-ui,"Noto Sans SC",sans-serif}main{max-width:1120px;margin:auto;padding:42px 24px 80px}h1{font-size:30px;line-height:1.4}h2{font-size:23px;margin-top:40px}h3{font-size:19px}p{max-width:1000px}a{color:#1259a7}code{background:#edf1f5;padding:2px 5px;overflow-wrap:anywhere}.table{overflow-x:auto}table{width:100%;border-collapse:collapse;background:white;font-size:15px}th,td{padding:11px 12px;border:1px solid #d7e0e8;text-align:left;vertical-align:top}th{background:#e8eef5}details{background:white;border:1px solid #d7e0e8;border-radius:8px;padding:14px 18px;margin:12px 0}summary{font-weight:650;cursor:pointer}.lead{background:#e8f1f8;border-left:5px solid #2a668c;padding:16px 22px}.small{font-size:14px;color:#4e6070}li{margin:8px 0}@media print{body{background:white}main{max-width:none;padding:0}.table{overflow:visible}details{break-inside:avoid}h2{break-after:avoid}}
</style></head><body><main><h1>Coding agent 的组合缺口检测：开发过程与程序计算对照</h1><p class="small">2026-10-10 · 8 项任务 · 4 组方法 · 每组重复 2 次 · 64 次检测运行</p>'''
    page+='<div class="lead"><p>已完成 64 次检测。四组在两次重复中的正确任务数分别为：'+ '；'.join(NAMES[a]+' '+pair(a,lambda x:len(x['correct_tasks'])) for a in ARMS)+'。每次的分母均为 8。本轮没有证据表明加入有限程序计算能提高检测效果。</p><p>研究场景是 coding agent 修改仓库后、提交补丁前的测试补强。正确结果必须给出具体组合：原补丁不能满足，gold patch 可以满足，且原验证没有已经暴露同一失败。我们只做静态语义核验。本轮没有生成或执行补测，也没有测量 issue resolution rate。</p></div>'
    page+='<h2>1. 问题与本轮算法</h2><p>一个 agent 可以分别验证多个局部行为，却没有检查它们在同一状态、同一对象或同一执行过程中的共同效果。例如，测试分别检查配置默认值和策略合并，却没有检查默认值是否在合并后保留。本文把这种遗漏称为组合缺口。</p><p>开发过程还有最终代码没有表达的信息。agent 可能只检查中间字段，绕过真实入口，或在失败后改变测试输入。这些记录可以缩小补测搜索范围，也可以证明某项失败已经出现。后者属于反馈处理问题。</p><p>原型先用程序收集修改代码、测试片段和开发事件。它保留完整命令时间线，并优先选取失败输出、相邻修改及相关测试。程序还解析测试调用中直接写出的值，例如 false、数字和字符串。下文称这些值为字面值。它不能据此证明测试实际执行，也不能解析任意变量、闭包共享或嵌入字符串中的程序语义。</p><p>模型随后提出最多两个行为区别。它可以提前选择需要查询的源码和历史步骤，也可以建立一个小模型：列出有限的输入取值，用两个表达式分别表示当前输出与要求输出。程序尝试从原测试绑定输入，再枚举原行为与要求行为不同的取值。模型最后形成并复核具体检测目标。</p><p>这里的两个表达式由模型提出。程序计算正确，不代表表达式忠实于源码或需求。实验因此单独核验表达式、测试绑定和最终目标，不把它们合成一个成功指标。</p>'
    page+='<h2>2. 实验设置与评价口径</h2><p>样本沿用上一轮的八项开发任务。它们来自已有失败记录，且此前已用于方法诊断。这不是未见样本评估，也不能代表全部 211 条记录。T11 和 T23 没有本轮固定参照目标，但仍可能存在其他有效目标。</p>'
    page+=table(['组别','输入与操作','检验目的'],[
        ['A','公开需求、修改代码窗口、相同测试片段和调用字面值；三次模型处理。','建立无时间线及执行反馈的对照。'],
        ['B','在 A 上加入自动提取的开发事件；三次模型处理。','观察开发过程信息的增量作用。'],
        ['C','使用 B 的材料；模型先提出行为模型和查询，再提出目标并复核。','观察把模型前移的作用。'],
        ['D','复用 C 的同一个首轮计划和查询结果；后两轮加入程序计算。','隔离有限计算反馈的增量作用。']])
    page+='<p>A 的测试片段也可能来自历史版本。因此 A/B 删除的是事件顺序和执行反馈，不是所有来自 trajectory 的材料。C/D 的 16 对第二轮请求除程序反馈外完全相同。后续生成内容仍可能不同。</p><p>每次运行最多保留两项报告。每组重复两次，分别列出结果，不取最好一次。两次重复仍是同八项任务。每次运行只在首轮后响应最多四项查询，内容限于源码或原始历史步骤。第二轮提出的新查询不再执行。</p><p>请求模型为 DeepSeek-v4-flash。正式响应记录的模型名为 '+escape('、'.join(s['response_models']))+'。每轮 temperature=0，启用高推理强度，输出额度为 65,536 tokens。技术性不完整或 JSON 错误最多原样重试一次；不因语义结果不好而重试。源码与实验材料发送到已授权的 .env provider。</p>'
    page+='<p><strong>正确任务数：</strong>该次运行至少发现一个符合上述规则的目标。目标可以是旧标签，也可以是新发现。</p><p><strong>固定目标命中与漏检：</strong>本轮有八个预先冻结的目标。严格命中须保留该目标的关键条件、操作和观察。漏检数等于八减去命中数。没有固定标签不代表任务没有错误。</p><p><strong>同缺陷的短反例：</strong>如果报告指出同一根本错误，但少了固定目标要求的后续操作，我们另列。例如，直接检查恢复后的错误标记，不等于已经检查 React 挂载后的刷新。有效短反例仍计入正确任务数。</p><p><strong>不合格报告：</strong>肯定报告不满足本轮差分规则。原因可能是 gold 也失败、原验证已经暴露失败，或源码推断错误。gold 也失败不等于原补丁正确。我们另列待定项，不把它们强行算成误报或正确结果。</p><p>全部肯定报告由本轮 Codex 逐条静态复核。复核读取原补丁、gold、公开需求和历史验证。它不是独立人工标注，也不是动态执行证明。gold 和 benchmark 信息仅用于评估，没有提供给被测方法。</p>'
    page+='<p>如果已有能揭示同一错误的联合测试，但 agent 没有运行，我们将它归为选测问题。如果 agent 已经看到失败，却没有修复，我们将它归为反馈处理问题。二者都不能计为新发现的测试组合缺口。测试可以更强，也不等于原补丁存在错误。</p>'
    page+='<h2>3. 检测结果</h2><p>每个单元格依次表示第一次 / 第二次重复。正确任务数的分母是 8；固定目标命中与漏检的分母也是 8，但二者统计对象不同。</p>'
    page+=table(['组别','正确任务','固定目标命中','固定目标漏检','不合格报告','审查待定'],metric_rows)
    page+=f'<p>全部运行共保留 {valid+rejected+unresolved} 条肯定报告：{valid} 条符合规则，{rejected} 条不符合，{unresolved} 条待定。条目包含跨组、跨重复的重复发现，不能当成同样数量的独立缺陷。</p>'
    page+=f'<p>“审查待定”只指肯定报告的离线审查状态。模型另有 {s["decision_counts"].get("unknown",0)} 项选择暂不判断，{s["decision_counts"].get("feedback_problem",0)} 项归为已有失败反馈，{s["decision_counts"].get("no_gap",0)} 项判断没有缺口。这些不是肯定报告，未计入上述 79 条。</p>'
    reasons={'gold_does_not_satisfy_proposed_target':'gold 也不满足所提完整预期','already_executed_failure':'同一失败已在原验证出现','no_current_patch_failure_established':'只提出加强测试，未推出原补丁错误'}
    page+=table(['不合格原因','报告数'],[(reasons.get(k,k),v) for k,v in s['rejection_reasons'].items()])
    page+='<p>这里的“不合格”按用户指定的原补丁失败、gold 通过规则判断。它不能直接解释为模型凭空编造了错误。例如，某项原错误确实存在，但 gold 使用另一种修复方式，仍可能不满足模型要求的具体输出。</p>'
    page+='<p>下表检查每项任务是否至少得到一个合格目标。“否”表示本次没有得到合格目标，不表示任务无缺陷。</p>'
    page+=table(['任务']+[a[0] for a in ARMS],case_rows)
    page+='<p>下表按相同任务和重复编号配对。它用于展示变化方向，不是对独立样本作统计显著性检验。</p>'
    page+=table(['比较','两组均正确','仅左组正确','仅右组正确','两组均未正确'],comparisons)
    page+='<h3>固定目标</h3><p>A1 表示 A 组第一次运行，以此类推。短反例列只列未严格命中、但指出同一缺陷的结果。</p>'+table(['目标','组合','严格命中的运行','同缺陷的短反例'],ref_rows)
    page+='<details><summary>八个目标：原验证检查了什么，还缺少什么组合</summary>'+table(['目标','原验证范围','需要补充的检查与两版差异'],ref_details)+'</details>'
    page+='<p>这些结果尚不能证明 resolution rate 上升。符合差分规则只说明目标有暴露原补丁问题的依据。实际修复和 benchmark 通过率需要后续实验。本轮样本也没有足够的无缺陷任务，因此不报告任务级误报率。</p>'
    page+='<h2>4. 程序提取与计算是否发挥作用</h2>'
    page+=f'<p>模型一共提交 {s["extraction_models"]} 个行为模型。程序能够计算其中 {s["computed_models"]} 个。只有 {s["fully_literal_bound_models"]} 个模型获得至少一行完整的原测试字面值绑定；总计 {reasoning["complete_rows"]} 行。计算覆盖率与语义正确率不能混用。</p>'
    page+=table(['表达方式','数量'],[({'label_only':'把整项问题编码成布尔标签','input_case_table':'直接列输入类别与结果','operational':'用条件表达式描述操作'}.get(k,k),v) for k,v in reasoning['encodings'].items()])
    page+='<p>字面值提取只覆盖很小一部分仓库测试。闭包共享、缓存所属容器、初始化后的状态，以及字符串中的 Tengo 程序都需要其他语义。模型提供的 suggested_values 没有参与原测试计算，因此不会被误计成程序提取成功。</p><p>部分绑定还使用了错误的结构：模型没有用因子名组织查询。程序拒绝这些绑定。格式正确也不一定代表语义正确，例如字段存在不能直接证明该字段处在 anyOf 内部。修正接口格式不足以解决行为表示问题。</p>'
    page+='<p>接口说明没有清楚展示“输入名称对应查询”的完整例子。这是本轮实现的问题。因此，零成功绑定不能用来证明程序分析本身没有价值。它也说明 D 组实际检验的是枚举模型提出的假设，尚未完成从源码和原测试推导区别的核心设计。</p>'
    page+=f'<p>我们另做了一项不调用模型的诊断。只对单输入模型修正查询的外层格式，保留查询路径、取值和表达式。{binding_audit["changed_models"]} 个模型适用此规则，{binding_audit["models_with_complete_row_after"]} 个得到形式上完整的绑定。逐项复核后，仅 {binding_review["correct_local_field_bindings"]} 个正确读取了模型所指字段，其余 {binding_review["semantic_or_context_mismatches"]} 个混淆了含义或上下文。这个诊断不改变正式成绩。</p>'
    page+='<p>例如，T28 的查询读出 refetchOnRestore=false，却把它用于“现有状态比保存状态更新”。前者控制后续刷新，后者需要比较两个对象的时间。T20 的查询读出 terminal=false，却把它用于“高优先级配置为空”。字段值相同，不代表程序含义相同。</p>'
    page+='<details><summary>每个行为模型的静态审阅</summary>'+table(['模型记录','表示','审阅依据'],model_rows)+'</details>'
    page+='<h3>自动输入的范围</h3><p>测试条数是片段数，包含历史版本。命令事件不等同于测试执行。程序从所有片段解析调用，再选择一部分调用展示给模型。相关材料可能仍被窗口或额度省略。</p>'
    page+=table(['任务','源码窗口','测试片段','命令事件','详细事件','调用记录','展示调用'],input_rows)
    page+='<p>我们另核对了六个诊断事件。它们都保留在详细输入中，包括 T11 的早期 round trip 失败、T13 的跨实例失败，以及 T23 的失败和紧随其后的测试修改。这是开发案例的局部核验，不能当成全部历史信息的提取召回率。</p>'
    page+='<h2>5. 逐任务复核</h2><p>下列条目说明每类肯定报告为何被接受、排除或保留为待定。完整输入、模型答复和逐条对应关系保存在报告末尾的数据中。</p>'+''.join(case_cards)
    page+='<h2>6. 研究解释与下一步</h2>'
    narrative=read(RUN/'evaluation/report_conclusions.json')
    for p in narrative['paragraphs_zh']:page+='<p>'+escape(p)+'</p>'
    page+='<h2>7. 可复核记录</h2>'
    page+=f'<p>正式实验实际记录 {s["actual_unique_calls"]} 次 provider 调用，共 {s["actual_total_tokens"]:,} tokens。C/D 共用首轮，因此实际调用数小于 64×3 加重试次数。调用状态为 '+escape(json.dumps(s['call_statuses'],ensure_ascii=False))+'。</p>'
    page+='<p>下列运行有处理阶段在原样重试后仍未得到完整结构化结果。后续阶段继续使用可用材料，最终结果保留在主统计中，没有删除失败运行。</p>'+table(['任务','组别','重复','未得到完整结果的阶段数'],[(x['case'],NAMES[x['arm']],x['repeat'],x['technical_unknown_stages']) for x in technical_runs])
    page+='<p>正式运行前，一版计划提示缺少 provider 要求的 JSON 字样。该预检已停止，全部组在同一修正后重新开始。预检保存了 14 次请求记录：3 次完成、2 次错误、9 次在途或中断。已记录用量下限为 305,288 tokens；中断调用可能另有计费。预检结果没有计入上述成绩。</p><p>正式调用期间，方法代码、provider 代码和输入保持冻结。报告生成时重新检查了哈希。输入准备阶段还修正了失败文本识别和相邻修改选择；这些修正在正式模型调用之前完成。原型的 17 项相关本地检查在正式运行前通过。它们检查实现，不证明检测目标正确。</p>'
    page+='<ul>'+''.join('<li>'+link(path,label)+'</li>' for path,label in [
        (RUN/'protocol.json','冻结协议与输入哈希'),(RUN/'evaluation/summary.json','完整统计与配对审计'),
        (RUN/'evaluation/adjudicated_claims.json','每条报告及其静态判定'),(RUN/'evaluation/semantic_review.json','本轮判定与新目标依据'),
        (RUN/'evaluation/extraction_review.json','行为模型与提取审阅'),(RUN/'evaluation/binding_format_audit.json','仅修正查询格式的离线诊断'),(RUN/'evaluation/binding_format_review.json','格式修正后的语义核验'),(RUN/'evaluation/history_evidence_audit.json','六个开发事件的输入核验'),
        (RUN/'evaluation/fixed_reference_digest.json','八个固定目标的定义'),(RUN/'evaluation/diagnosis.json','检测过程中丢失有效目标的例子'),(RUN/'evaluation/visibility_audit.json','T10 与 T24 关键源码的输入核验'),(RUN/'evaluation/evidence_receipts.json','离线评估材料哈希'),
        (ROOT/'src/augmentation/trajectory_contrast.py','原型实现'),(ROOT/'scripts/run_augmentation_trajectory_pilot.py','实验运行脚本')])+'</ul>'
    page+='</main></body></html>'
    target=ROOT/'docs/augmentation_trajectory_pilot_20261010.html'
    target.write_text(page)
    print(target, target.stat().st_size)

if __name__=='__main__':main()
