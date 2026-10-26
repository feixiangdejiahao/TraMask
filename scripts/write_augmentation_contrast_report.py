"""Render the completed pilot and its explicit static adjudications as standalone HTML."""
from collections import Counter
from html import escape
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from scripts.run_augmentation_contrast_pilot import RUN, read

LABELS = {
    "A_direct": "A：旧候选，直接判断",
    "B_split": "B：旧候选，先发现再判断",
    "C_open": "C：开放模型发现",
    "D_static": "D：开放发现＋程序条件对比",
    "E_semantic": "E：模型选位置＋程序分析",
    "F_plan_only": "F：同一模型计划，不加程序反馈",
}
CASE_NAMES = {
    "T10": "Bandit：增量缓存与命令行行为",
    "T11": "etree：XML 差异、补丁与合并",
    "T13": "Tengo：闭包调用与实例隔离",
    "T17": "Tengo：解构赋值与默认值",
    "T20": "kgateway：一致性哈希策略",
    "T23": "Awilix：容器初始化与回滚",
    "T24": "DynamoDB Toolbox：条件必填字段",
    "T28": "TanStack Query：持久化状态恢复",
}


def link(path, label):
    p = Path(path)
    if p.is_absolute():
        p = p.relative_to(ROOT)
    return f'<a href="../{escape(str(p), quote=True)}">{escape(label)}</a>'


def table(headers, rows):
    return '<div class="scroll"><table><thead><tr>' + ''.join(f'<th>{h}</th>' for h in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in row) + '</tr>' for row in rows) + '</tbody></table></div>'


def main():
    s = read(RUN / "evaluation/summary.json")
    assert s["completed_runs"] == 96 and not s["unreviewed_affirmatives"]
    review = read(RUN / "evaluation/semantic_review.json")
    claims = read(RUN / "evaluation/adjudicated_claims.json")
    protocol = read(RUN / "protocol.json")
    refs = read(RUN / "evaluation/fixed_references.json")["targets"]
    paired_counts = Counter((p['E']['correct_task'], p['F']['correct_task']) for p in s['paired_E_F'])
    out = ['''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>八项任务 pilot：程序分析应如何帮助模型发现组合缺口</title>
<style>
:root{color-scheme:light}body{font-family:system-ui,"Noto Sans CJK SC",sans-serif;line-height:1.8;color:#182638;background:#f6f8fa;margin:0}main{max-width:1130px;margin:auto;background:white;padding:36px 42px}h1{font-size:1.85rem;line-height:1.4}h2{font-size:1.25rem;margin-top:2rem;border-top:1px solid #dce3eb;padding-top:1.2rem}p{margin:1em 0}.lead{background:#eaf2fa;padding:16px 20px;border-left:4px solid #24669a}.note{background:#f9f4e7;padding:12px 18px}table{border-collapse:collapse;width:100%;font-size:.94rem}th,td{border:1px solid #dce3eb;padding:9px 11px;vertical-align:top}th{background:#eef2f7;text-align:left}.scroll{overflow:auto}a{color:#145c95}code,pre{font-family:ui-monospace,monospace;font-size:.9em}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f9;padding:12px}summary{cursor:pointer;font-weight:600}details{border:1px solid #dce3eb;margin:12px 0;padding:10px 14px}.small{font-size:.88rem;color:#526273}.good{color:#176039}.bad{color:#983926}li{margin:.6em 0}@media(max-width:700px){main{padding:22px 16px}}
</style><main>
<h1>八项任务 pilot：程序分析应如何帮助模型发现组合缺口</h1>
<p class="small">2026-10-09。检测实验。请求模型为 DeepSeek-v4-flash。provider 返回的模型名称为 deepseek-flash。</p>
<p class="lead"><strong>96 次运行已完成。结果不支持把“LLM 提前参与程序分析”本身作为有效方法。</strong>开放模型发现在两次运行中分别正确检测 4/8、3/8 项任务。增加局部程序条件对比后，结果为 5/8、4/8。模型先选位置再接收程序反馈时，结果为 3/8、4/8。保留同一模型计划、删除程序反馈时，结果反而为 5/8、4/8。</p>
<p>程序条件对比有局部价值。但本次增益很小，样本也小。更明确的问题是：程序能定位代码，却还不能说明原测试是否区分了关键行为。当前实现不能据此声称形成了完整的学术贡献。</p>
<h2>问题和成功标准</h2>
<p>我们在 agent 提交 patch 前检查其验证测试。原测试可能分别检查了两个条件，却没有检查它们通过同一程序关系共同影响结果的情况。我们寻找这种遗漏，并提出后续补测目标。</p>
<p>本次只检测缺口。我们没有生成新测试，也没有执行被测项目。本次结果不能表示补测成功率或 resolution rate。</p>
<p>一个合格目标必须同时满足四点：公开需求支持预期结果；原验证没有有效检查该组合；静态语义分析支持原补丁违反该预期；gold patch 满足该预期。gold 和 benchmark 材料只供实验后复核。算法和 DeepSeek 均未读取这些材料。</p>
<p>我们不把覆盖不足直接当作实现错误。原轨迹已经执行并暴露的失败，也不算新组合缺口。已有有效联合测试但未运行的情况，应归为选测问题。</p>
<p>两版实现有时使用不同私有类、缓存文件或错误码。我们按相同逻辑条件和公开可观察结果比较。我们不声称模型文字可以直接变成一份能在两版执行的测试。若比较需要改变逻辑条件或主要预期，我们不计成功。</p>
<h2>本次检验的软工假设</h2>
<p><strong>原验证可能使几个不同的行为解释看起来都正确。</strong>例如，测试总把“存在错误”和“已失效”同时设为真。此时，“保留失效标记”和“有错误就强制失效”都会让断言通过。补测应拆开这两个条件。</p>
<p>同一现象也可能跨越多个操作。闭包复制测试只调用一个闭包，无法检查两个闭包是否仍共享同一个捕获变量。配置测试直接调用运行时构造函数，无法检查配置是否先被准入校验拒绝。组合搜索应追踪这种行为区别。</p>
<p>这个假设将搜索目标从“再覆盖几个函数”改为“找出原验证尚不能区分的行为”。它给出了软件工程依据。但它仍需算法和消融结果支持，不能仅靠一个新名称成立。</p>
<h2>实验设置</h2>
<p>我们选择此前诊断过的六项任务，并加入两项曾出现误报的任务。它们都是开发样本，不是独立保留集。T11、T23 不是已证明没有缺陷的负例。</p>''']
    out.append(table(["编号", "任务", "固定参照"], [
        [c, CASE_NAMES[c], '；'.join(escape(x['id'] + '：' + x['description']) for x in refs if x['case'] == c) or '无固定正目标。用于检查此前误报类型。']
        for c in protocol['cases']]))
    out += ['''<p>六项任务共有八个固定参照目标。我们在调用模型前冻结了这些目标。T20 和 T24 各有两项。它们来自前期原补丁、gold、benchmark 失败和原验证的静态对照。</p>
<p>每组处理同样八项任务，每项重复两次。每次最多保留两个缺口。温度为 0，启用 high reasoning。相同设置仍可能产生不同答复，所以我们分别报告两次结果，不取两次中的最佳结果。</p>
<p>每次包含三轮逻辑调用。每轮输出上限为 65,536 tokens。只有输出截断、JSON 格式或数量结构不合格时，程序才对同一输入重试一次。所有组使用相同恢复规则，不根据语义结果追加调用。</p>
<p>同一任务的各组、各轮使用完全相同的原始材料。材料包括公开需求、全部修改行附近的源码窗口、最多 45 段验证测试，以及按现有规则截取的轨迹命令和反馈。源码窗口保留修改行前后各 24 行。测试材料上限为 51,000 字符。轨迹材料上限为 22,000 字符。模型没有在中途自行查询仓库。</p>
<p>这些材料比前一版方法的局部候选包更广。因此，A 组也不是旧版实验的原样复跑。不能把本次 8 项的结果与旧版 30 项的结果直接相减。</p>''']
    out.append(table(["组别", "三轮处理方式", "主要比较目的"], [
        [LABELS['A_direct'], '旧前八候选注释＋公共材料；直接判断两轮；最后复核。允许纠正候选。', '本次材料和预算下的直接判断基线。'],
        [LABELS['B_split'], '相同旧候选注释；先提出具体场景；修订场景；最后复核。', '将发现与判断分开是否有用。'],
        [LABELS['C_open'], '不加旧候选注释；模型提出场景；修订；最后复核。', '模型自由发现的基线。'],
        [LABELS['D_static'], '在 C 的输入中加入自动提取的局部条件对比。', '程序提供具体条件是否有额外收益。'],
        [LABELS['E_semantic'], '模型先选需求相关的观察位置；程序返回局部分析；模型提出场景；最后复核。', '让模型指导程序分析的对象。'],
        [LABELS['F_plan_only'], '复用 E 的第一轮计划；第二轮只删除程序反馈；最后复核。', '把提前规划的作用与程序反馈的作用分开。'],
    ]))
    out += ['''<p>F 组在 E 的第一份计划返回前注册。它不读取 E 后两轮的判断。我们核对了 16 对第二轮请求。每对请求仅有程序反馈这一处内容差异。F 每次新增两轮调用；总费用只计算一次共享计划。</p>
<h2>程序实际做了什么</h2>
<p>D 组分析 Python、Go 和 TypeScript 的局部布尔表达式。一个表达式包含 2 至 6 个条件。程序枚举真假取值，找出“只改变一个条件就改变结果”的组合，也找出“改变这个条件但结果不变”的组合。它排除同一变量上一些直接矛盾的字面值约束。</p>
<p>E 组先让模型把公开需求对应到最多四个源码位置。程序核对位置和需求原文，收集局部赋值，并返回同一函数附近的条件对比。模型选择分析目标。程序计算局部事实。</p>
<p>本次程序提取了 68 个支持的布尔表达式，向 D 组选入 49 个。E 的两次运行共提出 45 个位置。程序定位了 44 个，其中 11 个位置获得了布尔对比。另一个位置属于 YAML，超出了当前语法分析范围。</p>
<p class="note">“定位成功”不等于“缺口提取正确”。当前测试联系仍来自名称出现位置。程序没有绑定测试输入与函数参数，没有证明对象身份、跨函数数据流、共享捕获变量或后续异步操作。局部赋值收集也不是完整的程序切片。</p>
<p>在八个固定目标中，当前局部算子明确表达了 T28 的关键真假组合。它没有自动表达 T13 的捕获单元共享、T17 的存在性判断、T20 的跨层准入限制或 T24 的默认参数传递。因此，其余成功主要说明模型从材料中找到了关系，不能自动归功于程序算子。</p>
<h2>结果与统计口径</h2>
<p>“正确任务”表示该次运行至少报告一个合格目标。目标可以来自固定参照，也可以是新的合格目标。“误报”表示模型肯定报告缺口，但该报告不满足本轮成功标准。“待定”不计成功，也不并入已确认误报。一项任务可同时有合格目标和误报。</p>
<p>“固定命中”和“固定漏检”以八个事先冻结的目标为分母。T28 的直接状态断言可揭示同一错误，但没有复现固定目标中的 React 挂载场景。我们把它计入正确任务，并另列“同一缺陷命中”，不悄悄改写固定场景。</p>
<p class="small">下表每格依次给出第一次／第二次结果。任务、固定目标均以 8 为分母。误报与待定按报告条目计数，不以任务为分母。</p>''']
    result_rows = []
    for arm in LABELS:
        a = [next(x for x in s['aggregates'] if x['arm'] == arm and x['repeat'] == rep) for rep in [1, 2]]
        pair = lambda fn: ' ／ '.join(str(fn(x)) for x in a)
        result_rows.append([LABELS[arm], pair(lambda x: f"{len(x['correct_tasks'])}/8"),
            pair(lambda x: f"{len(x['exact_reference_hits'])}/8"),
            pair(lambda x: len(x['exact_reference_misses'])),
            pair(lambda x: f"{len(x['same_defect_reference_hits'])}/8"),
            pair(lambda x: x['affirmative_claims'].get('rejected', 0)),
            pair(lambda x: x['affirmative_claims'].get('unresolved', 0))])
    out.append(table(['组别', '正确任务', '固定命中', '固定漏检', '同一缺陷命中', '误报条目', '待定条目'], result_rows))
    out += ['''<p>若将两次任务结果相加，C 为 7/16，D 为 9/16。它们对应同样八项任务的重复测量，不是 16 项独立任务。D 两次都多识别了 T28。但 C 的第一次发现阶段也提出了有效的 T28 状态组合，最后判断却以“正常错误状态总会失效”为由将其排除。因此，这个差距并不等于 C 无法提出该组合。</p>
<p>A 与 B 的正确任务数相同，都是 4/8、5/8。仅把发现与判断分开，没有在本次样本上带来稳定增益。两组发现的具体目标仍有差异。</p>
<p>E 为 7/16，F 为 9/16。16 对运行中，6 对都成功，6 对都未成功；只有 E 成功的有 1 对，只有 F 成功的有 3 对。这个配对结果没有支持当前程序反馈的正收益。</p>''']
    out.append(table(['配对差异', 'E：加入程序反馈', 'F：删除程序反馈', '解释'], [
        ['T11，第二次', '未得到合格目标。', '发现元素新增补丁反转后错误删除父节点。', '同一早期计划包含反转位置；增加反馈后，模型转向了其他目标。'],
        ['T20，第一次', '提出跨策略 disable 组合，最后判断未接受。', '保留该目标。gold 保留高优先级 header，原补丁会清空。', '差异发生在后续判断，不是 E 没有找到相关代码。'],
        ['T24，第一次', '要求 gold 为所选 anyOf 分支生成条件，gold 也不满足。', '要求不生成未选分支的额外条件，原错而 gold 对。', '相近位置仍可导出不同目标。位置相关不足以保证目标正确。'],
        ['T28，第二次', '发现 marker 恢复不应套用 bulk 的合并规则。', '只保留 gold 也不能满足的延后时间戳目标。', '加入反馈在这一对中得到有效新目标，但不能据此宣称总体有效。'],
    ]))
    out += ['''<p>以上结果没有统计显著性或泛化结论。八项任务来自既有诊断。两次输出存在波动。我们也没有在此次实验中实施完整的参数绑定、跨过程分析或可达性求解。因此，负结果只针对当前原型。</p>
<h2>误报、漏检与材料问题</h2>
<p>模型最终给出 127 条肯定报告。静态复核接受 69 条，拒绝 53 条，保留 5 条待定。它们包含不同组和重复运行对同一缺陷的重复报告，不能解释成 69 个独立缺陷。另外 40 条答复为 no_gap，24 条为 unknown。</p>''']
    out.append(table(['已拒绝条目的主要原因', '数量', '证据与含义'], [
        ['gold 不能满足所提目标', '39', '例如 T24 的数组遍历问题确实存在，但 gold 也不为 list 元素生成条件。它不符合本轮原错、gold 对的标准。'],
        ['轨迹已经执行并暴露同一失败', '10', 'T11 已执行节点重排后应用补丁。T23 的无返回值初始化测试已失败，随后 agent 修改测试使其返回实例。'],
        ['错误推断源代码行为', '3', 'T10 的 get_option 已支持点号分层查询。T11 的属性反转实际生成 /@x，模型误读成 /@/x。'],
        ['具体输入未建立所称行为差异', '1', 'T13 声称两个示例程序的 g 索引不同，示例却都先声明 g；gold 也没有按名称改写全局索引。'],
    ]))
    out += ['''<p>“gold 不能满足目标”不是模型推理错误的同义词。其中有原补丁的真实问题。我们按用户指定的修复相关标准将其排除，但不据此断言这些问题不存在。在线方法不能读取 gold，也不能据此加入针对 gold 的过滤规则。</p>
<p>五条待定报告中，四条依赖 gold 未明确支持的通配 key 配对。另一条正确指出嵌套删除应产生结构冲突，但模型要求一条冲突，gold 会按两个路径分别报告。我们保守地不把这项完整目标计为成功。</p>
<p>T10 的固定目标“缓存预热＋JSON 输出”和 T20 的固定目标“重复配置键＋准入及运行时顺序”在全部组中都未命中。T24 的省略默认 mode 目标只由 A 命中。各组仍会转向更显眼、但未必符合此次评价目标的风险。</p>
<p>截取源码和轨迹仍造成了具体损失。T10 的未修改辅助函数不在窗口中，模型猜错了它的语义。T11 的早期实际失败和 T23 的测试弱化不在当前轨迹片段中，模型把已知失败重新当作新缺口。扩大修改行窗口没有解决这些问题。</p>
<p>程序的局部对比也没有解决需求解释。T28 中，“普通运行通常生成某种状态”并不意味着公开恢复接口禁止其他状态。模型用运行惯例推翻了保留输入状态的明确要求。该错误发生在最后判断阶段。</p>
<h2>学术判断与下一步算法方向</h2>
<p><strong>当前贡献不能写成“先分析、再调用模型、最后判断”。</strong>这些调用顺序只是实现选择。本次 E/F 对照也表明，提前规划和程序反馈需要分别证明价值。</p>
<p>局部条件独立影响并不是新覆盖准则。相关基础可见 <a href="https://ntrs.nasa.gov/citations/20010057789">NASA 的 MC/DC 教程</a>。本次使用这类对比来检查 agent 验证中的条件混淆，其应用目的不同，但尚需证明该表示能稳定指导有效补测。</p>
<p>让 LLM 参与程序分析也已有先例。<a href="https://arxiv.org/abs/2405.17238">IRIS</a> 用模型推断污点规格并结合静态分析。<a href="https://arxiv.org/abs/2601.10865">SemTaint</a> 用模型补充调用边、来源、汇入点和库内传播信息。这不否定本问题的创新空间。它说明“LLM 不在最后”本身不是充分的新意。这里引用方法用途，不把预印本自动视为 SE 顶会发表结果。</p>
<p><strong>更有依据的研究目标是：从原验证中识别尚未被区分的行为，再搜索最小的区分组合。</strong>原 agent 可能让实现和测试共享同一个简化。方法应指出这个简化，并说明哪个输入或操作会使它失效。这样，轨迹、程序关系与测试补强服务于同一个问题抽象。</p>
<p>第一步，让模型从公开需求提出两个需要区分的解释。例如，“键不存在”和“键存在但值为 undefined”不同；“复制后与源实例隔离”和“复制体内部仍共享变量”也不同。模型只提出待核验假设，并标出有关输入、状态和观察位置。</p>
<p>第二步，让程序按这个假设追踪输入到观察结果的关系。它应绑定同一次测试中的对象和参数，展开相关辅助函数，并跟踪值经过调用、默认值补全、复制或序列化后的变化。遇到无法分析的库操作时，模型可以提出一个局部语义摘要。程序应保留该摘要的假设状态，不能把模型文字当作已证明事实。</p>
<p>第三步，用原测试是否能区分两个解释来指导搜索。若原测试在两个解释下结果相同，就寻找使两者结果不同的最小条件改变。先检查单个关系。只有当区别不能传到断言时，才沿调用、状态或后续操作扩展。这个规则按行为传播扩大范围，不按任务不断添加变异规则。</p>
<p>第四步，按候选关系查询完整轨迹。检索同一对象、操作和断言的生成、执行与修改记录。若原 agent 已看到同一失败，就输出失败反馈问题。若测试后来删除了关键条件，就输出测试弱化问题。只有没有有效联合检查时，才进入新测试补强。</p>
<p>最后判断应逐项指出哪条前提成立、哪条前提缺证。它不能用一般编程惯例直接否定显式需求。程序应帮助模型纠正条件和补齐证据，而不是只给模型一个更长的相关函数列表。</p>
<p>本次已实现的是局部对比和早期位置选择。上述输入绑定、跨操作行为对比和按候选检索轨迹，属于后续算法方向，尚未在本次 pilot 中实现或验证。我们不把它们写成已有实验成果。</p>
<h2>调用记录、复核边界与复现</h2>''']
    out.append(f'<p>正式实验实际发送 {s["actual_unique_calls"]} 次请求，记录 {s["actual_total_tokens"]:,} tokens。272 次为新增主调用，14 次为技术恢复。F 的第一轮计划与 E 共享，没有重复发送。286 份响应均返回 deepseek-flash。该名称是 provider 返回值，我们不能据此独立确认后端版本。</p>')
    cost_rows = []
    for arm in LABELS:
        c = s['cost'][arm]
        cost_rows.append([LABELS[arm], str(c['actual']['calls']), f"{c['actual']['tokens']:,}",
                          str(c['logical_including_shared_plan']['calls']), f"{c['logical_including_shared_plan']['tokens']:,}"])
    out.append(table(['组别', '新增请求', '新增 tokens', '含共享计划的逻辑请求', '含共享计划的逻辑 tokens'], cost_rows))
    out += ['''<p>10 次响应达到输出上限。另有格式或结构不合格的响应触发恢复。两处第一轮在恢复后仍无有效结构化结果，后续轮次仍完成：T17-B 第二次、T24-D 第一次。所有 96 次运行均有最终判断。无效响应的消耗已计入正式成本。</p>
<p>正式运行前另有一轮技术预检。预检存在输出截断和修改行材料被总量上限截掉的问题。我们在未按检测内容选参数前停止该轮，统一扩大输出上限，并保留全部修改行窗口。预检未形成可评价的完整三轮运行，不进入成绩。其 33 次已记录请求消耗至少 1,723,781 tokens；其中 12 次被中断时没有完整用量记录。</p>
<p>原型的六项本地测试已通过。它们检查条件遮蔽、矛盾字面值、未知调用、过多条件、Python 表达式，以及不可见源代码的排除。它们不验证被测项目，也不替代本次语义复核。</p>
<p>复核由当前 Codex 逐条完成，不是独立人工金标准。我们重建了八项任务的 gold 相关源码。原补丁反向应用和 gold 应用均成功。我们只阅读源码、已有测试和历史执行结果，没有新增动态测试。</p>''']
    out.append(f'<p>审计检查了 {s["audit"]["requests_checked"]} 份请求。各组原始材料一致，冻结的代码和输入哈希未改变。16 对 E/F 输入仅程序反馈不同。记录中的“无 gold 输入”还结合输入构造代码和请求内容核查，不仅依赖一个标志字段。</p>')
    artifact_links = [
        (RUN/'protocol.json','正式实验协议'), (RUN/'program_feedback_ablation_protocol.json','E/F 配对协议'),
        (RUN/'evaluation/summary.json','完整统计'), (RUN/'evaluation/semantic_review.json','逐项复核依据与映射'),
        (RUN/'evaluation/adjudicated_claims.json','原始报告与复核结论'), (RUN/'evaluation/input_audit.json','输入一致性审计'),
        (RUN/'evaluation/trajectory_counterevidence.json','原轨迹中的失败与测试修改'),
        ('src/augmentation/contrast_pilot.py','原型代码'), ('scripts/run_augmentation_contrast_pilot.py','正式运行脚本'),
        ('scripts/run_augmentation_contrast_ablation.py','配对对照脚本'), ('scripts/summarize_augmentation_contrast_pilot.py','统计脚本'),
    ]
    out.append('<p>' + ' · '.join(link(p, label) for p, label in artifact_links) + '</p>')
    out.append('<pre>.venv/bin/python scripts/summarize_augmentation_contrast_pilot.py\n.venv/bin/python scripts/write_augmentation_contrast_report.py</pre>')
    out.append('<p class="small">上述命令只从保存的数据生成统计和报告，不调用模型。</p>')
    out.append('<h2>附录：每条肯定报告的静态复核</h2><p>以下保留全部 127 条肯定报告，包括失败结果。同一语义问题可能在多个组出现。每项都给出原输入、模型目标和复核依据的链接。</p>')
    for case in protocol['cases']:
        selected = [x for x in claims if x['case'] == case and x['decision'] == 'gap']
        out.append(f'<details><summary>{escape(CASE_NAMES[case])}（{case}）：{len(selected)} 条肯定报告</summary>')
        rows = []
        for c in selected:
            v = c['adjudication']; verdict = {'accepted':'合格','rejected':'不合格','unresolved':'待定'}[v['verdict']]
            notes = review.get('claim_notes', {}).get(c['key'], '')
            rows.append([link(c['result_path'], c['key']), verdict,
                         escape(c['claim']['combination']), escape(v['rationale_zh'] + (' ' + notes if notes else ''))])
        out.append(table(['运行／条目', '复核', '模型提出的组合（原文）', '判断依据'], rows))
        out.append('</details>')
    out.append('</main></html>')
    target = ROOT / 'docs/20261009_program_guidance_pilot_n08.html'
    target.write_text('\n'.join(out), encoding='utf-8')
    print(str(target))


if __name__ == '__main__':
    main()
