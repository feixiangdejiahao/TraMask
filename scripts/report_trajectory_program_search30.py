"""Render a retrospective report from explicit static-review annotations.

This script copies local evidence. It does not infer labels, call models, or run
subject tests. Reasoning excerpts are original dataset records, not new output.
"""
from __future__ import annotations

import hashlib
from html import escape
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.analyze_trajectory_program_search30 import OUT, read, write, commands
from scripts.read_deepswe_trajectory import observations, display_text

REPORT = ROOT / 'docs/20261010_trajectory_program_analysis_n30.html'

# These are manually selected source ranges, not results of an automatic slicer.
SOURCES = {
 'T01': [('libs/core/tests/unit_tests/runnables/test_coalesce.py',112,145)],
 'T02': [('t/unit/transport/virtual/test_dlx_ttl.py',232,251)],
 'T03': [('tests/unit/core/test_nosec.py',303,312)],
 'T04': [('t/unit/transport/virtual/test_single_active_consumer.py',164,175)],
 'T05': [('tests/test_monitor.py',369,419)],
 'T06': [('tests/test_deprecation_headers.py',90,133)],
 'T07': [('skrub/tests/test_duration_encoder.py',305,322)],
 'T08': [],  # The decisive test was a /tmp script in trajectory step 36.
 'T09': [('tests/unit/morphing/facade/provider/test_name_mapping_aliases.py',76,86)],
 'T10': [('tests/unit/cli/test_main.py',405,419)],
 'T11': [('diff_more_test.go',67,121)],
 'T12': [('checkers/testdata/brokenDocLink/negative_tests.go',1,43)],
 'T13': [('compiled_function_call_test.go',389,461), ('objects.go',647,680)],
 'T14': [('internal/http/retry_test.go',128,163)],
 'T15': [('promql/sort_test.go',39,51)],
 'T16': [('vm/vmTypedBindings_test.go',113,122)],
 'T17': [('destructuring_test.go',29,53), ('compiler.go',916,945)],
 'T18': [('ansi/ansi_test.go',98,110)],
 'T19': [('analyze_test.go',146,159)],
 'T20': [('pkg/kgateway/extensions2/plugins/trafficpolicy/consistent_hash_test.go',78,111),
         ('pkg/kgateway/extensions2/plugins/trafficpolicy/consistent_hash_test.go',301,318)],
 'T21': [('packages/core/tests/aspect.test.ts',94,107),('packages/core/tests/aspect.test.ts',260,271)],
 'T22': [('library/src/schemas/recursive/recursiveAsync.test.ts',16,35)],
 'T23': [('src/__tests__/initialize.test.ts',204,231),('src/__tests__/initialize.test.ts',310,338)],
 'T24': [('src/schema/actions/requiredIf.unit.test.ts',137,153),
         ('src/schema/actions/zodSchemer/parser/item.ts',34,60),
         ('src/schema/actions/zodSchemer/parser/utils.ts',131,144)],
 'T25': [('src/error-stack.test.ts',176,221)],
 'T26': [('test/typings/test-d/grouped-aggregation-window-frames.test-d.ts',54,92)],
 'T27': [('packages/prompts/test/autocomplete.test.ts',581,597),
         ('packages/core/test/prompts/autocomplete-async.test.ts',125,154),
         ('packages/core/test/prompts/autocomplete-async.test.ts',283,326)],
 'T28': [('packages/query-persist-client-core/src/__tests__/persisterRestoreResult.test.ts',155,205),
         ('packages/query-core/src/queryCache.ts',112,126)],
 'T29': [('packages/core/tests/predicate.test.ts',88,97),('packages/core/tests/predicate.test.ts',151,172)],
 'T30': [('test/grid.tsx',31,40),('test/grid.tsx',267,279),('src/grid.ts',496,522)],
}

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def link(path, label):
    return f'<a href="../{escape(str(path), quote=True)}">{escape(label)}</a>'

def p(text):
    return '<p>' + escape(text) + '</p>'

def table(headers, rows):
    return ('<div class="table-wrap"><table><thead><tr>' +
        ''.join('<th>'+escape(x)+'</th>' for x in headers) +
        '</tr></thead><tbody>' + ''.join('<tr>'+''.join('<td>'+x+'</td>' for x in row)+'</tr>' for row in rows) +
        '</tbody></table></div>')

def make_evidence(review):
    active = read(ROOT/'experiments/relation_distinction/results/pilot30_20261007_v1/active_evaluation.json')
    current_targets = read(ROOT/active['labels']['path'])['targets']
    benchmark = {t['case']:t for t in read(ROOT/active['benchmark_failure_labels']['path'])['targets']}
    result = []
    for c in review['cases']:
        name = c['case']
        ctx = read(OUT/'inputs'/name/'context.json')
        original = ctx['case']
        trajectory_path = Path(original['trajectory'])
        trajectory = read(trajectory_path)
        steps = {s['step_id']:s for s in trajectory['steps']}
        records = []
        for n in c['steps']:
            st = steps[n]
            records.append({'step': n,
                'original_reasoning': display_text(st.get('reasoning_content') or ''),
                'commands': commands(st),
                'outputs': [{'returncode':rc,'text':display_text(t)} for rc,t in observations(st)]})
        source_records = []
        for filename, start, end in SOURCES[name]:
            path = Path(original['repository'])/filename
            lines = path.read_text().splitlines()
            assert 1 <= start <= end <= len(lines), (name, filename)
            source_records.append({'path':str(path.relative_to(ROOT)),
                'sha256':digest(path),'start_line':start,'end_line':end,
                'text':'\n'.join(f'{i+1}: {lines[i]}' for i in range(start-1,end))})
        ev = {'case':name,'task':original['task'],
            'trajectory_path':str(trajectory_path.relative_to(ROOT)),
            'trajectory_sha256':digest(trajectory_path),
            'selection':'Manually selected review evidence; not automatic retrieval output.',
            'steps':records,'sources':source_records,
            'fixed_target_ids':[x['id'] for x in current_targets if x['case']==name],
            'benchmark_representative':{k:v for k,v in benchmark[name].items() if k not in {'evidence','classification_revision'}}}
        outpath = OUT/'evidence'/f'{name}.json'
        write(outpath,ev)
        result.append(ev)
    return result

def main():
    review = read(OUT/'review.json')
    manifest = read(OUT/'manifest.json')
    assert [c['case'] for c in review['cases']] == [f'T{i:02}' for i in range(1,31)]
    evidence = make_evidence(review)
    counts = {'cases':len(evidence),
        'indexed_steps':sum(c['steps'] for c in manifest['cases']),
        'steps_with_reasoning':sum(c['steps_with_reasoning'] for c in manifest['cases']),
        'initial_saved_neighborhood_steps':sum(len(c['saved_neighborhood_steps']) for c in manifest['cases']),
        'steps_linked_to_case_annotations':sum(len(c['steps']) for c in evidence),
        'source_ranges':sum(len(c['sources']) for c in evidence),
        'new_external_model_calls':0,'new_subject_executions':0}
    write(OUT/'summary.json',{'counts':counts,
        'scope_note':'All trajectories indexed; targeted retrospective reading. No automatic detection, causal-effect or resolution-rate estimate.',
        'important_classification_findings':[
            {'case':'T08','target':'T08-R1','finding':'Same missing-closing input was exercised with an acceptance assertion. Current evaluation v5 classifies it as an oracle issue and excludes it from the 22 combination targets; original v4 statistics remain archived.'},
            {'case':'T27','target':'T27-G1','finding':'Original test executed Enter and awaited the result, but did not assert it. This is an observation gap, not an absent operation sequence.'},
            {'case':'T11','finding':'An earlier joint script predates later implementation edits. Route to replay assessment, not new-input generation.'}],
        'annotation_sha256':digest(OUT/'review.json')})

    html = ['''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>30 项任务：从开发过程与程序关系搜索组合缺口</title>
<style>
:root{color-scheme:light;--ink:#1f2937;--muted:#586579;--line:#d8e0e9;--accent:#155e75}
body{margin:0;background:#f5f7fa;color:var(--ink);font:16px/1.85 system-ui,-apple-system,"Noto Sans CJK SC",sans-serif}
main{max-width:1130px;margin:auto;padding:32px 24px 80px;background:white}h1{font-size:29px;line-height:1.45}h2{font-size:23px;margin-top:38px;border-bottom:1px solid var(--line);padding-bottom:8px}h3{font-size:18px}
p{margin:12px 0}a{color:var(--accent)}.meta{color:var(--muted);font-size:14px}.lead{padding:16px 22px;background:#eef7fa;border-left:4px solid var(--accent)}.note{padding:12px 18px;background:#fff8e7}.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;margin:18px 0;font-size:14px}th,td{border:1px solid var(--line);padding:10px 12px;text-align:left;vertical-align:top}th{background:#eef2f6}td:first-child{min-width:90px}code{background:#f0f3f6;padding:1px 4px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f8;font:13px/1.65 ui-monospace,monospace;padding:16px}details{border:1px solid var(--line);border-radius:6px;padding:12px 16px;margin:14px 0}summary{cursor:pointer;font-weight:650}details details{background:#fbfcfd}.case-label{font-weight:650;color:#24445b}input{box-sizing:border-box;width:100%;padding:11px 14px;border:1px solid #a5b4c5;font:inherit}.steps{color:var(--muted);font-size:14px}.flow{display:flex;gap:10px;align-items:stretch;flex-wrap:wrap}.flow div{flex:1;min-width:175px;background:#eef7fa;border-top:3px solid var(--accent);padding:12px}
@media print{body,main{background:white;padding:0}input,.controls{display:none}details{break-inside:avoid}a{color:inherit}}
</style></head><body><main>
<h1>30 项任务：从开发过程与程序关系搜索组合缺口</h1>
<p class="meta">2026-10-10 · 原始 coding-agent issue-resolution 轨迹 · 回顾性静态审读</p>
<div class="lead"><p><strong>主要发现：不少遗漏发生在 agent 已经考虑过的交互附近。原测试固定了某个条件，绕开了后续处理，或没有观察最终结果。</strong>因此，搜索应从“原验证为什么无法区分两种行为”出发。trajectory 提供待核查的假设，程序关系提供具体检查位置。</p></div>
<p>这里的 trajectory 指 agent 阅读代码、修改补丁、编写测试和执行命令的过程记录。本报告以原 agent 的验证测试为主。它也复核了两份已有补测，说明哪些条件被保留，哪些条件被绕过。</p>
<p>本文使用短句、主动语态和明确用词。ASD-STE100 面向受控英语；这份中文报告采用其清晰表达原则，不声称通过英文规范认证。</p>
<nav><a href="#scope">分析范围</a> · <a href="#observations">轨迹规律</a> · <a href="#program">测试间关系</a> · <a href="#examples">具体对照</a> · <a href="#search">联合搜索</a> · <a href="#cases">全部 30 项</a></nav>
<h2 id="scope">分析范围与判断口径</h2>''']
    html.append(p(f"本轮索引了全部 30 条轨迹的 {counts['indexed_steps']:,} 个步骤。其中 {counts['steps_with_reasoning']:,} 步含原始推理记录。最初按历史审读定位并保存了 {counts['initial_saved_neighborhood_steps']} 个邻近步骤。最终逐项说明关联 {counts['steps_linked_to_case_annotations']} 个步骤和 {counts['source_ranges']} 处测试或程序片段。"))
    html.append(p('这些数字描述材料规模。它们不代表逐行阅读全部 4,542 步，也不代表自动提取召回率。本轮先用历史缺口定位，再回查原始记录。步骤编号来自各自 trajectory，不能跨任务比较先后。'))
    html.append(p('本轮没有调用外部模型，没有执行被测项目，也没有测量 resolution rate。结论由当前 Codex 静态审读得出，不是独立人工复核结果。30 项来自既有失败样本，不能用它们估计全部 coding-agent 任务的发生率。'))
    html.append(p('初始固定参照包含 23 个目标。按用户要求修订 T08-R1 后，当前参照包含 22 个目标，仍分布于 18 个任务。其他任务仍能提供验证设计线索。本报告不会把所有候选都称为补丁缺陷。gold 补丁和 benchmark 只用于离线解释既有判断，不应进入将来检测方法的输入。'))
    html.append(table(['情况','本报告如何处理'],[
      ['缺少关键输入或状态组合','搜索补充输入，但仍须确认公开契约及修复相关性。'],
      ['操作组合已执行，断言未区分结果','补足观察。T27 的提交返回值属于此类。'],
      ['同一输入已有测试，但期望错误','重新核查预期。T08 的缺结束分隔符属于此类。'],
      ['已有联合测试，后续代码修改后未复验','优先选择并重跑已有测试。T11 提供这类证据。'],
      ['原补丁已正确，或 gold 也不满足','保留验证线索；不计为原补丁失败、gold 通过的修复相关缺口。']]))
    html.append('''<div class="note"><p><strong>已修订的历史解释：</strong>T08-R1 的输入并未遗漏。第 36 步已有 <code>test_missing_closing_delimiter</code>，第 37 步输出通过，断言接受不完整消息。当前统计已把它转入预期判断问题。T08 的引号内分号目标仍是另一项输入缺口。各轮重算见<a href="augmentation_t08_statistics_revision_20261010.html">T08 统计修订报告</a>。</p></div>
<h2 id="observations">轨迹中可以利用的规律</h2>
<h3>1. agent 已提出交互，但只处理了其中一部分</h3>
<p>T18 第 42 步已指出带 ANSI 的尾部被截断时可能出错。第 72 步只修复尾部可以完整放下的情况。T19 第 75 步直接写出普通前缀与否定后缀的组合，却把局部例外扩展到了整个结构。</p>
<p>这类记录可以直接缩小搜索范围。需要提取的是具体条件、相关代码和未验证的分支。不能只把“edge case”这样的词当成缺陷证据。</p>
<h3>2. 测试调整会去掉原先暴露行为的条件</h3>
<p>T01 增加 sleep，使批量重复请求发生重叠。T18 交换 Bold 与 Truncate 的顺序。T28 为避免挂载触发 fetch，换用另一种 observer 调用。这些修改解释了测试最后为何通过，也说明通过结论适用的范围。</p>
<p>测试调整本身不证明错误。T01 移除错误的串行化锁、T12 修正 receiver 声明，都是合理修正。方法应检查修改是否取消了公开需求允许的情形，或只消除了无效夹具。</p>
<h3>3. 实现与测试可能共享同一个错误假设</h3>
<p>T28 认为 queryCache.build 会先应用客户端默认选项，再计算 hash。实际代码先计算 hash，后应用默认选项。T19 的实现和测试都沿用了对例外范围的同一解释。T08 则明确为缺结束分隔符写了接受预期。</p>
<p>因此，原推理和原测试都不能自动充当正确答案。轨迹的价值是暴露假设，程序和公开需求的价值是核查假设。</p>
<h3>4. 测试名称和执行通过会夸大验证范围</h3>
<p>T18 的 styled tail 测试实际把样式放在正文，Tail 仍是普通字符串。T12 希望覆盖全部诊断分支，但输入先在“类型不存在”处结束。T02 的跳数测试没有可达下游，无法用空队列证明上限生效。</p>
<p>程序分析应先回答三个问题：条件是否成立，目标操作是否到达，断言是否依赖该操作。测试名称只能辅助检索。</p>
<h3>5. 历史验证会随着代码和测试整理失效</h3>
<p>T11 的联合脚本早于后续分类逻辑修改。T25 的临时 max=4 夹具能区分两种操作顺序，整理后的 max=3 夹具不能。只看最终测试集，会失去这些具体的复验依据。</p>
<p>这些证据不支持“agent 只追求 coverage”或“agent 普遍遗忘需求”的结论。许多轨迹包含细致推理，并通过执行修复过真实错误。更有依据的解释是：局部验证结论被扩展到了尚未验证的上下文。</p>
<h2 id="program">测试之间应连接哪些程序信息</h2>''')
    html.append(table(['可利用的关系','具体证据','如何限制搜索'],[
      ['同一对象的连续使用','T16：同一 Env 的两次 Execute。T29：同一个 predicate 查询的建立和增量维护。','保留实际对象身份。两个测试分别 NewEnv，不构成状态组合。'],
      ['不同引用共享同一资源','T13：两个不同闭包共享一个捕获单元。T21：两个字段属于同一个 trait。','追踪共同指向的资源及读写操作，不能只连接相同函数名。'],
      ['生产者输出与消费者输入','T05：快照到 diff。T20：schema 准入到运行时。T30：子宽度到父布局。','要求同一个值或结构能沿真实调用路径传递。'],
      ['条件来源与判断范围','T17：存在性与 undefined。T19：后缀否定影响祖先判断。T24：局部默认值与原 options。','保留来源及语义角色，避免提前压成一个布尔标签。'],
      ['集合规模和对应关系','T11：一个父删除关联多个子修改。T21：逐字段更新对应按 trait 通知。','检查一对多或多对一关系是否被单一元素的测试隐藏。'],
      ['程序执行顺序','T14：发送响应头之前设置 header。T22：同步消费者收到 Promise。T28：hash 与默认化先后。','以真实调用顺序筛掉不可能或未发生的组合。'],
      ['结果到断言的数据依赖','T09：异常类型与缺失字段集合。T27：列表与提交值。T25：回调时点与最终输出。','把断言放在能够观察区别的字段、对象和时刻。'],
      ['测试与代码版本关系','T11 的已运行联合脚本，T25 整理前后的具体参数。','已有有效输入优先复用；后续相关修改触发复验。']]))
    html.append(p('这些关系不是八套领域专用变异规则。它们都用于核查一条较短的行为链：某个条件，经若干操作，影响一个可观察结果。普通调用图只能给出连接可能性；对象身份、取值和断言依赖决定这条连接是否有用。'))
    html.append('''<h2 id="examples">具体测试对照</h2>
<p>下面的简写用于解释组合目标，不是本轮生成并执行的可运行测试。完整原测试片段见每项任务的证据展开区。</p>
<h3>T13：两个已测事实没有跨过同一边界</h3>
<pre>原测试 A：inc 与 get 共享 n；在原实例中 inc 后，get 能看到变化。
原测试 B：[inc, {inc: inc}] 跨实例传递；两个引用仍累加同一个 n。
缺少组合：把 [inc, get] 跨实例传递；副本中 inc 后，副本的 get 仍看到变化。
另需保留：源实例的 n 不变化。</pre>
<p>第 104 步说明 agent 理解“副本内部应共享”。问题出在用同一函数的两个引用代表了两个函数共享变量。程序应暴露共同捕获单元，LLM 再把已有读、写闭包带入传递场景。</p>
<h3>T17：原测试无法区分两种输入状态</h3>
<pre>已测：[] 配默认值 → 采用默认值。
已测：[2] 配默认值 → 保留 2。
未测：[undefined] 配默认值 → 元素实际存在，不能仅凭值触发默认分支。</pre>
<p>原程序用 IndexGet 返回值判断是否缺项。缺项和值为 undefined 得到相同表示。这里需要补的是存在性信息。多放几个函数名或更多默认值例子，都无法表达这个区别。</p>
<h3>T27：已有操作组合，需要增加结果观察</h3>
<pre>原流程：初次加载 → 输入不足最小长度 → 检查提示 → Enter → await result。
缺少断言：这次提交不能返回之前的旧选择。
所需联系：候选列表清空 → 选择状态同步 → 提交返回值。</pre>
<p>这项不需要再发明更长操作序列。程序应发现原测试已经走到返回点，但没有观察返回值。对于另一个异步过滤目标，原数据又常恰好符合本地过滤条件，需要改变返回选项与搜索词的关系。</p>
<h3>T28：轨迹假设可以变成程序查询</h3>
<pre>轨迹假设：build 使用客户端默认 hash 函数计算键。
实际顺序：读取传入 options 算 hash → 查缓存 → 创建 Query 时才应用默认选项。
搜索输入：客户端自定义 hash + 已有查询 + 恢复同一持久化快照。
观察结果：仍更新同一查询，而非新增默认 hash 下的查询。</pre>
<p>这里适合让模型在程序分析前提出问题：“计算 hash 前是否合并默认选项？”程序可返回带位置的调用顺序。模型不需要自行创建完整行为模型，再把无依据的真假值交给程序枚举。</p>
<h3>已有补测也会重复原验证的限制</h3>
<p>T27 的 candidate_6e2ef 光标补测设置了 <code>filter: () =&gt; true</code>。这有助于单独测试光标，但它绕过了要检测的默认过滤行为。因此，该测试不能证明异步过滤缺口已补足。</p>
<p>T24 的 candidate_006c69 包含 <code>new ZodSchemer(schema).parser()</code>，并保留 requiredIf 的触发值和缺失 dependent 字段。它改变了默认调用上下文，同时保留了错误触发条件。这是已有实验中有效目标的具体形式。该文件还包含需另审的 update-mode 调用，不能据其中一段有效就认可整个文件。</p>
<h2 id="search">如何联动 trajectory 与程序来搜索</h2>
<p>建议将研究问题抽象为：<strong>恢复原 agent 的验证限制，再搜索一个合法上下文，使被该限制隐藏的行为区别变得可观察。</strong>验证限制指测试固定的输入、对象、配置、执行阶段或观察位置。它必须能对应到具体代码，不能只是一句抽象主题。</p>
<div class="flow"><div>① 找到具体假设或限制<br>阅读、修改、测试、反馈</div><div>② 绑定程序事实<br>条件、对象、操作、断言</div><div>③ 搜索最小有效变化<br>连接上下文或补足观察</div><div>④ 检查目标是否保留<br>公开预期与原测试对照</div></div>
<h3>第一步：从验证过程提出少量可查证的问题</h3>
<p>程序先把测试创建、修改、执行结果与相关补丁修改连起来。模型读取这些局部记录，提出具体问题。例如，“这次 helper 替换是否绕过挂载？”或“复制是否保留共同捕获单元？”模型可以在此处参与，不必只在最后作判断。</p>
<p>搜索优先级可由三个信号支持：轨迹明确提出过风险；测试在失败后改变了相关条件；最终代码仍含对应分支。只有测试名相似或函数共同出现时，证据较弱。该排序目前是待验证设计，不是本轮测得的最佳策略。</p>
<h3>第二步：让程序返回足够小的行为事实</h3>
<p>每个候选只需表达四项信息：原测试固定什么，哪个操作可能受影响，哪个对象或值连接它们，断言实际观察什么。程序给出代码位置和能确认的关系。对别名、回调和框架行为无法确认时，保留未知，不将模型猜测写成程序事实。</p>
<p>例如，T24 可表示为“测试显式 mode=put；调用者仅局部默认化；helper 读取原 options；断言检查是否抛错”。T13 可表示为“inc 和 get 读写同一捕获单元；原传递测试只搬运同一函数的重复引用”。这种表达比纯关系名称更直接，也比全仓库形式模型更容易核查。</p>
<h3>第三步：沿关系搜索，而非任意交叉功能</h3>
<p>优先复用原测试的合法输入和断言。只改变隐藏区别的那一处条件。可改变输入取值，复用同一对象连接两个阶段，或把断言延伸到后续消费者。T24 删除显式 mode，T16 复用 Env，T27 检查 result，分别说明这三种方式。</p>
<p>搜索可以从一个局部关系开始。若结果需要经过另一操作才可见，就沿相同对象或值继续。T13 需要共享、传递、读写三个联系；T30 需要子宽度、父列宽和兄弟偏移。关系数量由行为传播需要决定，不由固定的二元或三元输入枚举决定。</p>
<h3>第四步：防止生成过程再次消除目标条件</h3>
<p>模型生成候选后，程序核对关键条件是否仍在。例如，T27 保留默认过滤器，T22 保留非空 children，T13 保留两个不同函数共享单元。这里先核对目标结构，不要求模型额外发明一整套精确检查规范。</p>
<p>模型再依据公开需求解释预期。原实现、原测试和原 agent 的推理只能提供线索。若同一联合测试已存在，则选择补断言、修正预期或重跑；不把它包装为新输入缺口。</p>
<h3>可以形成的研究贡献</h3>
<p>核心候选贡献是把 coding agent 的验证决策变成程序搜索约束，并恢复原测试无法区分的行为。trajectory 提供“为何只验证这一范围”，程序提供“这个范围之外是否存在相连行为”，补测提供可观察的区分实例。</p>
<p>这一设计利用了仓库级 issue resolution 的特性：agent 同时修改实现与测试，测试期望可能与补丁共享假设，验证结果又依赖代码版本。静态切片、组合测试或 LLM 推理都是可用组件。论文的新意应由它们在这个问题上的具体抽象、搜索机制和实证收益支撑。</p>
<p>本轮观察还没有证明新算法有效。前次八任务 pilot 中，加入历史文本没有稳定超过原组，31 个行为模型也没有获得完整的原测试输入绑定。两项结果并不矛盾：轨迹确实包含有用线索，但现有表示还没有把线索可靠地接到程序和原测试上。</p>
<p>下一次小 pilot 应先检验这条连接：能否从轨迹提出具体问题，能否绑定真实程序位置，能否保留原测试条件并产生有区别的候选。可固定相同代码材料，对照有无相关轨迹，并加入无关轨迹作为对照。历史失败测试和 gold 继续只用于离线评估。</p>
<h2 id="cases">全部 30 项逐项记录</h2>
<p>每项分别列出原验证、候选组合、程序关系和结论边界。“候选”不表示本轮已生成或已动态验证。原始证据包保存了所引用步骤的推理、命令、输出以及源码片段和哈希。</p>
<div class="controls"><label for="case-filter">筛选任务、程序关系或关键词</label><input id="case-filter" placeholder="例如 T13、默认值、同一对象、已观察失败"></div>''')
    labels = [('trajectory','轨迹中的逻辑'),('original_tests','原测试检查什么'),
        ('candidate','缺少什么或需要补强什么'),('program_relation','可利用的程序关系'),
        ('search','搜索方式'),('evidence_kind','证据强度'),('boundary','判断边界')]
    for c, ev in zip(review['cases'], evidence):
        html.append(f'<details class="case" id="{c["case"]}"><summary>{c["case"]} · {escape(c["title"])} <span class="meta">{escape(ev["task"])}</span></summary>')
        html.append('<p class="steps">关联步骤：'+', '.join(map(str,c['steps']))+'。历史固定目标：'+escape('、'.join(ev['fixed_target_ids']) or '无')+'。</p>')
        for key,label in labels:
            html.append(f'<p><span class="case-label">{label}：</span>{escape(c[key])}</p>')
        html.append('<p>'+link(Path('research/trajectory_program_search30_20261010/evidence')/f'{c["case"]}.json','本项完整证据包')+' · '+link(ev['trajectory_path'],'原始 trajectory')+'</p>')
        for src in ev['sources']:
            html.append('<details><summary>源码片段：'+escape(src['path'].split('/repository/')[-1])+f'，第 {src["start_line"]}–{src["end_line"]} 行</summary><pre>'+escape(src['text'])+'</pre><p>'+link(src['path'],'查看源码')+'</p></details>')
        html.append('</details>')
    html.append('''<h2>数据与可复核性</h2>''')
    html.append('<p>'+link(OUT.relative_to(ROOT)/'review.json','30 项静态审读记录')+' · '+link(OUT.relative_to(ROOT)/'summary.json','范围与分类发现')+' · '+link(OUT.relative_to(ROOT)/'manifest.json','30 条原始轨迹及哈希')+'</p>')
    html.append('<p>'+link('experiments/relation_distinction/results/pilot30_20261007_v1/cases/T27/generation/candidate_6e2efdeaf11987b8d714/completion.txt','T27 已有光标补测')+' · '+link('experiments/relation_distinction/results/pilot30_20261007_v1/cases/T24/generation/candidate_006c69613fad2e886580/completion.txt','T24 已有默认模式补测')+'</p>')
    html.append('<p>较早结论可见 <a href="augmentation_trajectory_pilot_20261010.html">八任务轨迹对照实验</a>、<a href="augmentation_pilot30_reverse_20261008.html">原补丁与 gold 的初始反向分析</a>。原始输出保持不变。当前修订统计见 <a href="augmentation_t08_statistics_revision_20261010.html">T08 统计修订</a>；各轮 active_evaluation.json 指向更新后的评价。</p>')
    html.append('''<script>document.getElementById('case-filter').addEventListener('input',function(){const q=this.value.trim().toLowerCase();document.querySelectorAll('details.case').forEach(x=>{x.hidden=q!==''&&!x.textContent.toLowerCase().includes(q)});});</script></main></body></html>''')
    REPORT.write_text('\n'.join(html))
    print(json.dumps({'report':str(REPORT.relative_to(ROOT)),**counts},ensure_ascii=False))

if __name__ == '__main__':
    main()
