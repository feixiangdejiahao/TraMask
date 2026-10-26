"""Render the completed, reviewed detection-only pilot as a self-contained report."""
from collections import Counter
from html import escape
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.summarize_augmentation_detection30_v3 import RUN, main as summarize
from scripts.summarize_augmentation_detection30_v3_recovery import main as summarize_recovery


def read(p):
    return json.loads(Path(p).read_text())


def table(headers,rows):
    return '<table><thead><tr>'+''.join('<th>'+escape(str(v))+'</th>' for v in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in r)+'</tr>' for r in rows)+'</tbody></table>'


def main():
    summarize()
    summarize_recovery()
    s=read(RUN/'summary.json')
    recovery=read(RUN/'decision_recovery_v1/summary.json')
    assert s['status']=='complete', 'Do not publish incomplete experiment as final'
    assert recovery['status']=='complete'
    assert not s['implementation_hash_mismatches']
    assert not recovery['request_changes_other_than_max_tokens'] and not recovery['primary_result_changes']
    cases=read(RUN/'cases.json')
    target_review=read(RUN/'evaluation/target_review.json')
    targets=target_review['targets']
    claims=[read(p) for p in sorted((RUN/'evaluation/claims').glob('*.json'))]
    recovery_claims=[read(p) for p in sorted((RUN/'decision_recovery_v1/evaluation/claims').glob('*.json'))]
    all_claims=claims+recovery_claims
    final_inventory=read(RUN/'decision_recovery_v1/combined_inventory.json')
    final_found={t for v in all_claims if v['verdict']=='correct' for t in v.get('reference_targets',[])}
    decisions=read(RUN/'evaluation/inventory.json')
    audit=read(RUN/'evaluation/query_audit.json')
    tp=s['claim_review'].get('correct',0)
    fp=s['claim_review'].get('false_positive',0)
    unknown=s['model_decisions'].get('unknown',0)
    rejected=Counter()
    for key,n in audit['action_errors'].items():
        rejected['multiple_json_or_json_format' if key.startswith(('Extra data','Expecting','Unterminated','Invalid')) else key]+=n
    primary_explicit=sum(v['set']=='primary23' and v['selected_representation']=='explicit' for v in targets)
    prefix='../experiments/relation_distinction/results/pilot30_v3_detection_20261009_v1/'
    sections=[]
    def p(text): sections.append('<p>'+text+'</p>')
    def h(text): sections.append('<h2>'+text+'</h2>')
    p(f'2026-10-09。本次重新处理原来的 30 个任务。程序重新提取候选。DeepSeek 只判断组合缺口，不生成测试，也不运行被测程序。原始预算下正确检测 {len(s["correct_task_ids"])} 个任务。对全部技术性未知项统一补一次结论调用后，正确检测 {len(recovery["combined_correct_task_ids"])} 个任务，误报涉及 {len(recovery["combined_false_positive_task_ids"])} 个任务。固定 23 个目标最终命中 {recovery["primary_detected"]} 个，漏检 {recovery["primary_missed"]} 个。')
    p('本轮识别了 T24 的默认值传递问题和 T17 的存在性判断问题，并在 T15 与 T08 发现新目标。T08 只确认异常后的资源关闭；不确认流已读完。候选排序仍偏向普通退出分支，多个跨阶段关系仍未明确表达。这些结果只支持有限进展。')
    h('实验如何进行')
    p('输入来自此前相同的 30 份开发轨迹。每份输入包含公开需求、原补丁、对应代码快照，以及 agent 阅读代码、修改代码和运行验证的记录。模型看不到 gold patch、benchmark 失败测试或评估标签。')
    p('程序使用当前 v3 算法。它提取条件、具体操作、可能的结果影响和原测试范围。每个任务最多保留 400 个候选，再按当前排序选择 8 个。关系搜索深度上限为 6，关系组合阶数上限为 3。该阶数不等于候选中条件表达式的数量。')
    p('每个候选还会列出最多 8 组条件取值，供模型判断。这与“每个任务选择 8 个候选”是两项不同限制。候选被选中后，关键取值仍可能没有进入这 8 组组合。')
    p('每个候选最多使用 3 次模型调用。前两次可查询材料，最后一次必须给出结论。每个任务的总 token 预算为 100 万。每次输出上限为 16,384 token。请求模型为 DeepSeek-v4-flash，provider 返回的模型标识为 deepseek-flash。')
    p('本次新建了只读检测入口。它只允许查询材料和给出判断。判断分为发现缺口、未发现该候选缺口、选测问题和未知。测试生成与执行接口没有进入本轮流程。上一轮加入的追加位置说明、执行修正机会和生成后条件检查，本轮均未接受效果评估。')
    p('我在模型调用前冻结了算法、提示和预算。6 个任务首次提取时触发旧兼容处理错误。恢复脚本将该处理限定到历史测试信息，并重新提取这 6 项。恢复过程没有使用参考答案。全部原始失败与恢复记录均已保存。最终算法散列与冻结记录一致。')
    h('怎样判定正确、误报和漏报')
    p('正确检测必须说明具体的联合条件、原验证遗漏的观察，以及原补丁中的错误行为。公开需求必须支持所需结果。静态比较还必须支持：原补丁不满足该结果，而 gold patch 满足该结果。缺少覆盖本身不满足这一标准。')
    p('若已有联合检查并且已经观察到失败，我不把它计为新组合缺口。若已有有效检查但未在最终版本运行，应单列选测或复验问题。若模型引用旧版本的失败，而最终补丁已经修复，我将该主张计为误报。')
    p('主参照集合包含 23 个目标，分布于 18 个任务。这些目标来自此前对 benchmark 失败、原补丁与 gold 差异的复核。扩展集合另加入上一轮确认的 T08-N1，共 24 个目标。它们用于离线评估，不进入模型输入。其余任务不等于已确认无缺口。')
    p('新发现与固定目标使用相同的正确性标准。区别仅在于它是否已经进入参照集合。两者都必须暴露原补丁中的错误。目标编号用于对应任务和证据，表格逐项解释其含义。')
    p('我逐项检查模型报告的缺口，并对固定目标核对遗漏。核验方式是 Codex 静态语义审阅。它不是独立人工标注。本轮没有新增动态验证。因此，报告中的成功指检测判断成立，不表示已生成可执行测试，也不表示 resolution rate 已提高。')
    h('原始预算下的检测结果')
    sections.append(table(['指标','结果','含义'],[
      ['完成提取和检测','30 / 30','每个任务处理 8 个候选'],
      ['正确检测任务',f'{len(s["correct_task_ids"])} / 30',', '.join(s['correct_task_ids']) or '无'],
      ['固定目标的任务召回',f'{len({v["case"] for v in targets if v["set"]=="primary23" and v["target_detected"]})} / 18','任务至少命中一个固定目标；不包含本轮另找出的新目标'],
      ['固定目标命中 / 漏检',f'{s["primary_detected"]} / {s["primary_missed"]}','分母为 23 个目标'],
      ['扩展目标命中 / 漏检',f'{s["expanded_detected"]} / {s["expanded_missed"]}','分母为 24 个目标，包含 T08-N1'],
      ['另行确认的新目标',len(s['new_discoveries']),', '.join(v['id'] for v in s['new_discoveries']) or '无'],
      ['误报主张',fp,', '.join(s['false_positive_task_ids']) or '无'],
      ['报告缺口的精确率',f'{tp} / {tp+fp} = {100*tp/(tp+fp):.1f}%' if tp+fp else '无可用分母','正确主张占已判定缺口主张的比例'],
      ['无有效结论的候选',f'{unknown} / 240','不计为无缺口或正确否定'],
      ['新增组合测试','未生成','不能计算补测成功率']]))
    p('这里不报告整体准确率或传统误报率。当前标签没有穷尽所有真实缺口，也没有可靠的负例分母。“模型未发现缺口”只表示该次判断没有提出成立的缺口，不能证明补丁正确。')
    labels={'gap':'报告组合缺口','no_gap':'未发现该候选缺口','unknown':'未知','selection_problem':'选测问题',
            'model_decided':'模型给出有效结论','action_error':'动作格式或参数错误','provider_incomplete':'回复不完整'}
    sections.append(table(['模型最终输出','候选数'],[(labels.get(k,k),v) for k,v in s['model_decisions'].items()]))
    p(f'全部任务共保留 {s["retained_candidates"]:,} 个候选，选择 240 个。实际使用 {s["external_model_calls"]:,} 次外部模型调用，provider 记录 {s["charged_tokens"]:,} token。生成测试和执行补测的调用数均为 0。')
    h('逐项核验模型报告的缺口')
    sections.append(table(['任务','判定','依据'],[(v['case'],'正确' if v['verdict']=='correct' else '误报' if v['verdict']=='false_positive' else '待定',v['reason']) for v in claims]))
    p('T24 的有效区别是：省略 mode 时，入口使用默认 put；辅助函数继续读取未补默认值的 options.mode。原补丁因此跳过条件必填检查。原验证显式传入 put 或 update，没有检查省略参数与触发必填条件的组合。Gold 会拒绝缺少依赖字段的输入。这里确认解析是否拒绝，不依赖模型给出的具体错误类型或声明写法。')
    p('T15 的新目标将“大数字预发布编号”和“版本分类后的排序”连接起来。输入标签为 1.0.0-18446744073709551616 与 1.0.0。原补丁因 64 位整数解析溢出，把前者归为普通字符串，排在正式版之后。Gold 保留其版本类型，并在这一输入对上将预发布版排在正式版之前。')
    p('该预发布编号符合数字标识符语法。同核心的预发布版应先于正式版。依据是 <a href="https://semver.org/#spec-item-9">SemVer 2.0.0 第 9 项</a>与<a href="https://semver.org/#spec-item-11">第 11 项</a>。我仅在离线审阅时查阅规范。本轮模型没有收到该补充材料。T15-N1 不计入冻结的 23/24 个目标分母。')
    h('统一补充结论后的结果')
    p('原始结果中，53 个候选因格式、参数或回复长度问题而未知。我按这一机械条件选取全部 53 项，没有按是否接近参考答案挑选。每项额外调用一次模型，输出上限从 16,384 增至 32,768 token。系统提示和用户输入与原最后一次调用完全相同，没有新增源码查询、执行反馈或标签。')
    p('这组结果同时包含重复调用和增加输出额度两个变化。它不能单独测量输出额度的因果效果。原始记录和成绩保持不变。')
    sections.append(table(['指标','原始预算','加入统一补充调用'],[
      ['正确检测任务',f'{len(s["correct_task_ids"])} / 30',f'{len(recovery["combined_correct_task_ids"])} / 30'],
      ['固定 23 目标命中 / 漏检',f'{s["primary_detected"]} / {s["primary_missed"]}',f'{recovery["primary_detected"]} / {recovery["primary_missed"]}'],
      ['扩展 24 目标命中 / 漏检',f'{s["expanded_detected"]} / {s["expanded_missed"]}',f'{recovery["expanded_detected"]} / {recovery["expanded_missed"]}'],
      ['另行确认的新目标',', '.join(v['id'] for v in s['new_discoveries']),', '.join(v['id'] for v in recovery['new_discoveries'])],
      ['误报主张',fp,recovery['combined_claim_review'].get('false_positive',0)],
      ['成立的核心缺口主张 / 全部缺口主张',f'{tp} / {tp+fp}',f'{recovery["combined_claim_review"].get("correct",0)} / {recovery["combined_model_decisions"].get("gap",0)}'],
      ['无有效结论的候选',unknown,recovery['combined_model_decisions'].get('unknown',0)],
      ['外部模型调用',s['external_model_calls'],s['external_model_calls']+recovery['external_model_calls']],
      ['provider 记录的 token',f'{s["charged_tokens"]:,}',f'{s["charged_tokens"]+recovery["charged_tokens"]:,}']]))
    p(f'补充调用得到 {recovery["supplement_decisions"].get("no_gap",0)} 项未发现该候选缺口、{recovery["supplement_decisions"].get("gap",0)} 项缺口主张，以及 {recovery["supplement_decisions"].get("unknown",0)} 项未知。原来的 T08-N1 仍因输出不完整而未知。T25 得到否定结论，但模型继续讨论消息清理和 off 模式，未检查 frames 模式与允许 stack 属性的组合。')
    sections.append(table(['任务','补充调用后的核验','依据'],[(v['case'],'核心目标成立' if v['verdict']=='correct' else v['verdict'],v['reason']) for v in recovery_claims]))
    p('T17 的正确目标是“字段存在，值为 undefined，同时有默认表达式”。原补丁把该值误当作字段缺失，执行默认表达式。Gold 先检查键是否存在。模型使用原调用已经查到的编译代码，修正了初始候选对程序层次的理解。')
    p('T08-N2 的正确目标是“流式响应遇到无效 multipart 元数据后仍关闭资源”。原补丁在关闭之前抛错。Gold 的 finally 会关闭响应和底层流。模型还写到流被消费；这部分不受 gold 支持。本报告只计它明确提出的关闭状态检查。若不接受仅部分观察成立的报告，可将 T08 单列，保守成功数为 3/30。')
    p('T08-N2 与此前 T08-N1 不同。N1 检查头部尚未结束便遇到结束边界时是否拒绝消息；N2 检查元数据错误后的资源关闭。两个新目标不加入本轮冻结分母，也不被解释为已提高 benchmark 的 resolution rate。')
    h('提取的正确性')
    p('“提取到相关文件”“保留关键关系”与“给出能够区分行为的取值组合”是三项不同结果。我对 24 个已知目标检查了所选候选中的条件、主要操作和自动列出的组合。关系与组合取值都明确支持关键区别时，才记为“明确”。仅有相关源码或条件名称，仍记为“不完整”。这项审阅不是全部程序关系的精确率，也不是源码检索召回率。')
    p(f'24 个目标中，{s["direct_relationships_retained"]} 个保留了直接相关的条件关系：T24-R1、T25-R1 和 T08-N1。继续检查组合取值后，只有 {s["selected_representation_review"].get("explicit",0)} 个明确表达了关键区别，即 T24-R1。其余 {s["selected_representation_review"].get("incomplete",0)} 个仍需模型补充输入类别、对象关系、状态阶段或具体取值。')
    p('T25 的条件表包含输出模式与属性许可，但前 8 项自动组合没有选择它们。T08 把“未遇空行”与“到达文件末尾”合成一个布尔条件。该条件为 false 时，程序无法直接区分“正常结束头部”与“头部未结束但先遇边界”。模型仍可从源码推导答案，但这部分工作尚未由程序分析完成。')
    p(f'测试查询的路径处理已经工作。本轮 {s["tests_query_count"]} 次测试查询均指定了路径。成功返回的测试来自所请求文件，或来自写入该文件的历史测试记录。没有发现忽略路径而返回其他文件的情况。查询失败或没有匹配项不证明缺少测试；路径匹配正确也不代表测试在语义上相关。')
    p('18 次查询中，13 次返回匹配测试，4 次因调用协议错误未执行，1 次查询的路径不在快照中。因此，不能把 18 次请求全部计为有效取证。')
    p('原测试范围仍有过度关联。T24 的首轮输入把一个 list schema 测试关联到 item parser。该测试调用公共分发函数，但实际使用 list 分支。程序保留了分支未知信息，却仍提供了这条可能调用路径。模型不能据此认定 item 行为已被检查。')
    sections.append(table(['目标','需要检查的组合','所选表示','提取判断','原预算命中','补充后命中'],[
        [v['id'],v['description'],'明确' if v['selected_representation']=='explicit' else '不完整',v['extraction_review'],'是' if v['target_detected'] else '否','是' if v['id'] in final_found else '否'] for v in targets]))
    h('为什么仍然漏检')
    p(f'第一，排序偏向语法上明显的退出条件。240 个所选候选中，{s["selected_families"].get("blocked_continuation",0)} 个围绕提前返回或异常。T13 保留了 17 个共享复制候选，最终没有选择任何一个。T20 保留了 11 个声明校验与运行处理候选，最终也没有选择。现有排序中的条件数量和操作影响信号，不能替代任务所需的关系。')
    p('第二，程序经常提取单个条件，却没有明确取值来源和操作阶段。T17 提取的是编译器内部语法数组的下标是否存在，目标却是用户程序中的字段存在且值为 undefined。T28 提取了恢复和过期判断，却没有形成恢复错误状态、挂载观察者及禁止再次请求之间的完整联系。')
    p('第三，模型可能把合理的局部行为扩大为整个组合的正确性。T10 已选中预热后提前退出与输出调用。模型却把“不报告告警”理解为“不必输出 JSON”。T13 的模型说明了复用同一个函数对象为何合理，却没有检查两个不同闭包共享同一捕获位置时是否仍共享。')
    p('第四，历史记录没有形成可靠的版本约束。T11 的原轨迹已运行同一组合并观察到失败。T23 的历史调试失败则已被最终补丁修复。模型都把它们当成新缺口。需要先确定检查针对哪个代码版本，以及之后的修改是否改变了相关行为。')
    p('第五，交互失败限制了结论。部分回复包含多个 JSON 动作，部分在最后一次调用仍要求继续查询，部分输出达到长度上限。流程没有得到可接受的最终判断。这些情况记为未知。它们不能作为算法成功排除误报的证据。')
    sections.append(table(['停止原因','候选数'],[(labels.get(k,k),v) for k,v in s['stop_reasons'].items()]))
    h('与上一轮比较')
    sections.append(table(['指标','上一轮 v2','本轮原预算','本轮含补充调用'],[
      ['正确检测任务','1 / 30',f'{len(s["correct_task_ids"])} / 30',f'{len(recovery["combined_correct_task_ids"])} / 30'],
      ['固定 23 目标命中 / 漏检','0 / 23',f'{s["primary_detected"]} / {s["primary_missed"]}',f'{recovery["primary_detected"]} / {recovery["primary_missed"]}'],
      ['扩展 24 目标命中 / 漏检','1 / 23',f'{s["expanded_detected"]} / {s["expanded_missed"]}',f'{recovery["expanded_detected"]} / {recovery["expanded_missed"]}'],
      ['错误检出标准不成立的报告','77 份最终测试建议',f'{fp} 个缺口主张',f'{recovery["combined_claim_review"].get("false_positive",0)} 个缺口主张'],
      ['测试生成与执行','包含','不包含','不包含']]))
    p('这不是受控消融。上一轮通过生成测试和执行反馈形成最终建议；本轮直接要求说明原实现的具体错误。输出上限和交互流程也不同。因此，任务成功数增加和报告主张减少，不能单独归因于程序分析改进。固定目标最终仍只命中 2 项，尚不能支持稳定提高召回的结论。')
    h('下一步应检验什么')
    p('先把候选表示收敛为一个可核验的行为区别：哪些条件同时成立，值从哪里来，经过哪些操作，最后哪个结果发生变化。程序应保留对象身份、默认值来源和前后状态。模型应解释需求与该结果的关系。不要只增加更多条件规则。')
    p('候选选择应保留不同的行为机制。共享复制、配置校验和后续状态消费不应被大量普通退出分支挤掉。可以先在同一批固定候选上比较当前排序与按不同数据流、状态阶段保留候选的排序，再检查遗漏关系是否进入模型输入。')
    p('测试范围应说明同一次调用真正支持的条件。若分支无法确认，应明确说“可能到达”，不能把它等同于已有联合检查。历史验证还应关联到其执行时的代码版本，并记录后续修改是否涉及同一行为。')
    p('交互格式与输出长度应单独修正和复测。补充调用必须保存原成绩，并使用相同输入。这样可以区分“模型未识别行为区别”和“流程没有接收模型结论”。本报告分别保留原始预算结果和补充调用结果。')
    h('30 个任务明细：包含统一补充调用')
    case_rows=[]
    for c in cases:
        cid=c['id']; ds=Counter(v['decision'] for v in final_inventory if v['case']==cid); refs=[v for v in targets if v['case']==cid]
        owned=[v for v in all_claims if v['case']==cid]
        case_rows.append([cid,c['task'],len(refs),sum(v['id'] in final_found for v in refs),
                          sum(v['verdict']=='correct' for v in owned),sum(v['verdict']=='false_positive' for v in owned),
                          ds.get('no_gap',0),ds.get('unknown',0)])
    sections.append(table(['任务','项目任务','参照目标数（扩展）','命中目标','正确主张','误报主张','未发现候选缺口','未知候选'],case_rows))
    h('数据与复核入口')
    p('以下文件保留完整设置、输入散列、模型交互和逐项审阅。评估文件与模型输入分开保存。')
    links=[('protocol.json','冻结协议'),('summary.json','总统计'),('evaluation/target_review.json','24 项提取与命中审阅'),
           ('evaluation/inventory.json','240 项原始模型判断'),('evaluation/query_audit.json','查询审计'),('evaluation/condition_assignment_review.json','组合取值审阅'),('evaluation/selection_comparison.json','新旧候选选择对照'),('evaluation/claims/','原始主张核验'),
           ('decision_recovery_v1/protocol.json','统一补充调用协议'),('decision_recovery_v1/summary.json','补充后统计'),('decision_recovery_v1/evaluation/claims/','补充主张核验')]
    p(' · '.join(f'<a href="{prefix}{path}">{label}</a>' for path,label in links))
    p('<a href="../scripts/run_augmentation_detection30_v3.py">实验脚本</a> · <a href="../src/augmentation/detection.py">只读检测流程</a> · <a href="../scripts/summarize_augmentation_detection30_v3.py">离线汇总脚本</a> · <a href="augmentation_pilot30_v2_20261008.html">上一轮报告</a>')
    p('本地 82 项回归检查通过。它们验证查询、检测入口和原算法接口，不代表模型检测效果。报告中的未知项和误报均保留，没有据此修改本轮冻结算法或成绩。')
    p('这 30 个任务已用于方法诊断。它们属于开发集。本报告不能替代独立数据上的评估。')
    html='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>30 个任务：改进后的组合缺口提取与检测</title><style>body{font:16px/1.8 system-ui,sans-serif;max-width:1160px;margin:32px auto;padding:0 22px;color:#192832;background:#fafbfd}h1{font-size:28px}h2{font-size:22px;margin-top:32px}table{border-collapse:collapse;width:100%;background:white;margin:16px 0}td,th{border:1px solid #dce3e8;padding:9px;text-align:left;vertical-align:top;overflow-wrap:anywhere}th{background:#eaf1f6}a{color:#08628e}code{overflow-wrap:anywhere}@media(max-width:760px){table{display:block;overflow:auto}td{min-width:95px}}</style></head><body><h1>30 个任务：改进后的组合缺口提取与检测</h1>'''+''.join(sections)+'</body></html>\n'
    out=ROOT/'docs/augmentation_detection30_v3_20261009.html'
    out.write_text(html)
    print(out)


if __name__=='__main__':
    main()
