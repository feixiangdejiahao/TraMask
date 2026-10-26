"""Render the completed pilot and its separately recorded query recovery."""
from collections import Counter
from html import escape as h
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/"experiments/validation_context/results/pilot6_20261016_v1"
OUT=ROOT/"docs/validation_context_pilot_20261016.html"


def read(path):
    return json.loads(path.read_text())


def link(path,label):
    return f'<a href="../{h(str(path.relative_to(ROOT)))}">{h(label)}</a>'


NAMES={"A_source":"A：源码与测试", "B_history":"B：再加开发历史",
       "C_validation":"C：按原验证范围搜索", "D_no_feedback":"D：C 的无执行反馈对照"}


def result_table(summary):
    rows=[]
    for x in summary["aggregates"]:
        values=[NAMES[x["arm"]],str(x["repeat"]),f'{len(x["correct_detection_tasks"])}/6',
                f'{len(x["correct_generated_tasks"])}/6',str(len(x["false_positive_tasks"])),
                f'{len(x["fixed_misses"])}/5',str(len(x["unknown_tasks"]))]
        rows.append('<tr>'+''.join(f'<td>{h(v)}</td>' for v in values)+'</tr>')
    return '<div class="wide"><table><thead><tr>'+''.join(f'<th>{v}</th>' for v in
        ['组别','重复','正确检测','正确补测','不合格肯定报告','固定目标漏检','未完成或待定'])+'</tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>'


def main():
    original=read(RUN/"evaluation/summary.json")
    recovered=read(RUN/"query_recovery/evaluation/summary.json")
    recovery_protocol=read(RUN/"query_recovery/protocol.json")
    analysis=read(RUN/"evaluation/report_analysis.json")
    for summary in [original,recovered]:
        assert summary["completed"]==48 and not summary["unreviewed"]
        assert summary["audit"]["all_request_checks_pass"] and not summary["audit"]["source_mismatches"]
        assert len(summary["paired_input_audit"])==12 and all(x["only_runtime_feedback_differs"] for x in summary["paired_input_audit"])
    text=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
          '<title>新 pilot：从原验证范围搜索组合缺口</title>',
          '<style>body{font:17px/1.75 system-ui,sans-serif;color:#202b38;background:#fafbfd;margin:auto;max-width:1120px;padding:30px 24px}h1{font-size:30px;line-height:1.4}p{max-width:1000px}table{border-collapse:collapse;width:100%;background:white;font-size:15px}td,th{border:1px solid #ccd5df;padding:9px 12px;vertical-align:top}th{background:#eaf0f6;text-align:left}.wide{overflow-x:auto;margin:20px 0}a{color:#115cb2}code{font-size:.92em;background:#edf1f5;padding:2px 4px}details{margin:15px 0;background:white;padding:14px;border:1px solid #ccd5df}summary{cursor:pointer;font-weight:600}.lead{border-left:4px solid #2675bd;padding:6px 18px;background:#edf5fc}.small{font-size:14px;color:#4d5b69}</style>',
          '<h1>新 pilot：从原验证范围搜索组合缺口</h1><p class="small">2026-10-16。六项任务，四组设置，每组重复两次。研究原型，不是完整 benchmark 评估。</p>']
    text.append('<div class="lead">'+''.join('<p>'+h(p)+'</p>' for p in analysis['lead'])+'</div>')
    text.append('''<p><strong>本轮检验的问题。</strong>coding agent 已经生成补丁和验证测试。我们在提交前检查这些验证是否遗漏了相关条件的组合。我们检验三个假设：开发历史是否增加有效线索；按原验证范围搜索是否优于开放搜索；原补丁的执行反馈是否帮助实现补测。</p>
<p><strong>软件工程问题抽象。</strong>一项验证只在具体输入、状态、入口和观察方式下成立。代码调用过某个函数，不能证明相关条件已经在同一次执行中成立。我们尝试保留原验证所检查的行为，再寻找一个合法上下文，使原来未被区分的行为产生可观察差异。</p>
<p>例如，两个函数分别可调用，不等于它们在复制后仍共享同一变量。恢复后的数据正确，也不等于后续读取使用了同一个缓存对象。我们搜索这些具体差别，不预定所有目标都必须由两个源码位置组成。</p>
<p><strong>实验材料。</strong>本轮从已分析的 30 项任务中选择 6 项。它们都是方法开发任务。T13、T17、T24、T28 含有已复核的固定目标。T11、T23 用于检查已有验证、错误断言和其他目标；它们不是无缺陷负例。</p>
<p>实验使用保存的最终补丁状态。轨迹用于提取材料。任务选择和调用预算与此前 30 任务实验不同，因此两轮比例不能直接作为同条件的提升幅度。</p>
<div class="wide"><table><tr><th>任务</th><th>软件与需求</th><th>本轮固定目标</th></tr>
<tr><td>T11</td><td>etree：XML 差分与三方合并。</td><td>无。仍检查模型提出的新目标。</td></tr>
<tr><td>T13</td><td>Tengo：从 Go 调用、复制和传递闭包。</td><td>不同闭包共享变量，复制或传递后先写后读。</td></tr>
<tr><td>T17</td><td>Tengo：解构赋值与默认值。</td><td>字段实际存在且值为 undefined 时，不执行默认值。</td></tr>
<tr><td>T23</td><td>Awilix：按依赖异步初始化服务。</td><td>无。仍检查模型提出的新目标。</td></tr>
<tr><td>T24</td><td>DynamoDB Toolbox：条件必填规则。</td><td>省略解析模式时仍检查规则；不同 anyOf 分支的规则用于更新。</td></tr>
<tr><td>T28</td><td>TanStack Query：恢复完整查询状态。</td><td>恢复错误快照后挂载消费者，不因错误本身触发额外刷新。</td></tr></table></div>
<p><strong>四组设置。</strong>各组使用同一模型、调用上限和测试上限。实际输入长度和消耗可以不同。表中的“历史”指代码阅读、修改、测试执行、反馈及相关推理。</p>
<div class="wide"><table><tr><th>组别</th><th>可用信息与操作</th><th>比较目的</th></tr>
<tr><td>A：源码与测试</td><td>公开需求、补丁源码片段、原测试代码。模型自行选择目标并请求源码查询。</td><td>开放搜索对照。</td></tr>
<tr><td>B：再加开发历史</td><td>A 的全部材料，加上自动整理的历史事件。搜索提示保持开放。</td><td>检验历史事件的增量作用。</td></tr>
<tr><td>C：按原验证范围搜索</td><td>与 B 相同。模型先指出一项原验证及其限制，再搜索仍应满足同一需求的新上下文。</td><td>检验信息使用方式。</td></tr>
<tr><td>D：无执行反馈对照</td><td>与 C 共享完全相同的调查、查询结果和测试草稿。最后一轮只自行审阅，不接收执行结果。</td><td>隔离执行反馈的作用。</td></tr></table></div>
<p>A 组仍含从 trajectory 恢复的历史测试代码。我们只去掉事件顺序、推理与执行记录。因此，A 与 B 比较的是历史事件的增量作用，不是“全部 trajectory 信息有无”的比较。</p>
<p><strong>本轮实际实现。</strong>程序按补丁修改行收集源码。程序按修改文件、测试来源和需求词匹配选择原测试。程序再按路径、测试名和时间位置索引历史步骤。模型可以读取源码、搜索文本、查看原测试、查询历史，或查找有共同调用的测试。共同调用仅用于检索，不证明数据流或对象共享。</p>
<ol><li>模型提出至多两个假设，并请求至多六项查询。</li><li>模型根据查询结果选一个目标。模型生成至多两个文件、三个命名测试。程序在原补丁上执行草稿。</li><li>模型获得一次修正机会。A、B、C 收到原补丁反馈。D 只自行审阅。程序执行最终测试。</li></ol>
<p>LLM 因此参与假设形成、材料选择、源码解释、测试编写和修正。它不再只做最后判断。程序提供可核对的源码与执行事实。本轮尚未实现自动证明组合条件的分析器。</p>
<p><strong>模型与执行环境。</strong>请求模型为 DeepSeek-v4-flash。provider 返回的模型标识为 deepseek-flash。实验保存了两者。温度为 0，启用高强度推理，每次输出上限为 65,536 token。格式错误或截断最多进行一次同输入重试。</p>
<p>六项任务的原生测试环境均先通过最小测试。生成测试在隔离容器中运行。在线阶段只接收原补丁的结果。gold 是 benchmark 的参考补丁，只用于离线评价。模型没有收到 gold、benchmark 失败测试或人工目标标签。</p>
<p><strong>四项效果指标。</strong>正确检测要求模型指出一个原验证遗漏的合法组合，并有依据说明原补丁会违反公开要求，而 gold 可以满足该要求。缺少组合本身不等于补丁存在错误。已经运行过的联合验证，后来没有重跑，应记为重新选测问题。</p>
<p>正确补测要求至少一个原样生成的完整测试实现该目标，并在原补丁失败、gold 通过。我们还检查输入是否合法、关键条件是否成立、预期是否有需求依据。不能删掉错误断言后，把原输出计为成功。</p>
<p>统计以按协议交付的最终输出为准。中间草稿不替代最终输出。若草稿已提出正确方向，但最终输出格式失败，我们单列交付失败，不将其解释为语义判断错误。</p>
<p>“不合格肯定报告”对应本轮标准下的误报任务数。它包括错误预期、把旧验证当新缺口，以及不满足原失败、gold 通过的报告。最后一种可能仍指出真实软件缺陷。报告会说明原因，不把它与错误断言混为一类。</p>
<p>漏检按实验前固定的五个目标统计，不按六项任务统计。T24 有两个目标。历史目标之外的有效补测可以计入正确检测，但不能抵消固定目标漏检。未形成最终决定的调用单列为未完成或待定，仍保留在六项任务的分母中。</p>
<p>T28 的自定义查询身份目标也满足原失败、gold 通过，因此与修复相关。它没有命中预定挂载场景，不表示它没有修复价值。当前实验没有测量这些补测是否提高最终解决率。</p>
<p>一份输出可能既有正确测试，又有错误附加测试。此时，正确补测与不合格报告两列都计数。两列不互斥。两次重复也不是十二项独立任务。</p>
<p>此表报告误报任务数，不估计无缺口任务上的总体误报率。当前原型仍会产生不合格报告，尚未达到零误报目标。</p>
<p><strong>冻结版本结果。</strong>以下结果保留最初实现，包括随后发现的目录查询缺陷。</p>''')
    text.append(result_table(original))
    n=len(recovery_protocol['affected'])
    text.append(f'<p><strong>目录查询修复后的复测。</strong>原查询接口误把目录当文件读取。模型的合法目录搜索因此失败。我们统一修复了这一接口，对全部 {n} 个受影响调查重新运行后两步。C 对应的 D 同时重跑。我们复用原调查计划，保持语义提示和目标预算不变。未受影响的输出保持原结果。</p>')
    text.append('<p>下表展示复测结果与未受影响结果合并后的完整视图。它不替换上表。复测重新调用了模型，因此前后差异也可能包含生成波动，不能全部归因于接口修复。</p>')
    text.append(result_table(recovered))
    for title,paragraphs in analysis['sections']:
        for i,p in enumerate(paragraphs):
            text.append('<p>'+(f'<strong>{h(title)}。</strong>' if i==0 else '')+h(p)+'</p>')
    text.append('<p><strong>逐项复核。</strong>以下记录保留每份最终输出的判断依据。复核由 Codex 完成，结合源码、原测试、trajectory 和执行结果。没有独立人员盲审。</p>')
    for name,summary in [('冻结版本',original),('目录查询修复后的完整视图',recovered)]:
        text.append(f'<details><summary>{name}：48 份输出的逐项结论</summary>')
        for score in summary['scores']:
            review=score['review'];key=score['key']
            label='正确检测' if review.get('detection')=='repair_relevant_gap' else '待定' if review.get('detection')=='unknown' else '未符合检测标准'
            generation='正确补测' if review.get('generation')=='correct_repair_relevant_test' else '未生成合格补测'
            display=f'{score["case"]}，{NAMES[score["arm"]]}，第 {score["repeat"]} 次'
            text.append(f'<p><strong>{h(display)}：{label}；{generation}。</strong>{h(review.get("reason",""))}</p>')
        text.append('</details>')
    text.append(f'<p><strong>调用与检查记录。</strong>冻结版本实际调用 {original["physical_model_calls"]} 次，使用 {original["actual_total_tokens"]:,} token。目录修复另调用 {recovered["additional_recovery_calls"]} 次，使用 {recovered["additional_recovery_tokens"]:,} token。token 数包含缓存输入，不代表按此数量直接计费。共享的 C、D 前两步只计一次实际调用。</p>')
    text.append(f'<p>结束时，{original["audit"]["source_files_checked"]:,} 个源码文件的摘要均与冻结记录一致。十二对 C、D 最后一轮输入只在执行反馈上不同。程序原型的九项本地检查通过。</p>')
    text.append('<p>T11 的 gold 把公开差分 API 放在 diff 构建标签下。离线比较因此对原补丁与 gold 同时启用该标签。测试源码保持原样，最初的构建结果也保留。我们没有把构建配置差异记成模型发现的缺陷。</p>')
    text.append('<p>冻结版本的一份 T28 输出把测试放在两个独立 JS 子包。原运行器拒绝一次执行两个子包。评价阶段按现有包分别执行，测试源码保持原样。两项目标仍在 gold 失败。此项运行修正没有产生新的成功记录。</p>')
    text.append('<p>目录修复后，对应输出又调用了原补丁独有的 Query.restore 方法。我们按用户要求只做静态语义判断，没有把 gold 缺少该方法当作行为失败。公开恢复入口的目标同样受到 gold 清零错误计数的语义影响。</p>')
    text.append('<p><strong>解释边界。</strong>本轮样本小，而且已经用于方法开发。我们只运行补测，没有让 agent 继续修复，也没有测 resolution rate。原补丁失败、gold 通过只是与修复相关的证据。它不等于解决率已经提高。</p>')
    links=[(RUN/'protocol.json','冻结方案'),(RUN/'evaluation/summary.json','冻结版统计'),
           (RUN/'evaluation/review.json','冻结版逐项复核'),(RUN/'query_recovery/protocol.json','统一目录修复方案'),
           (RUN/'query_recovery/evaluation/summary.json','修复后统计'),(RUN/'query_recovery/evaluation/audit.json','输入与查询检查'),
           (ROOT/'src/augmentation/validation_context_pilot.py','原型实现'),(ROOT/'src/augmentation/context_query_recovery.py','目录查询修复'),
           (ROOT/'scripts/run_validation_context_pilot.py','实验运行脚本')]
    text.append('<p>'+ ' · '.join(link(p,l) for p,l in links)+'</p></html>')
    OUT.write_text('\n'.join(text))
    print(OUT)


if __name__=='__main__':main()
