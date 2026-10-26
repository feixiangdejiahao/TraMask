"""Read frozen evidence and render the offline missed-detection diagnosis.

No model calls, subject execution, label changes, or algorithm changes.
The classifications below are explicit static review judgments.
"""
from collections import Counter
from datetime import datetime, timezone
from html import escape
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'experiments/relation_distinction/results/pilot30_v3_detection_20261009_v1'
OUT = RUN / 'diagnosis_v1'
REPORT = ROOT / 'docs/archive/20261009_behavioral_gap_diagnosis_v03_n30.html'

CATEGORIES = {
    'selection': ('更相关的关系未进入模型候选', '程序已保留更相关的关系，但排序没有把它送入前 8 项。保留相关关系不等于已经完整表达目标。'),
    'context': ('关键关系或操作阶段没有连起来', '模型输入含相关函数或条件，但没有明确表示同一值、对象或状态如何跨操作影响结果。'),
    'values': ('选错输入类别或条件取值', '程序找到相关处理区域，但没有突出能区分正确与错误行为的具体输入。'),
    'requirement': ('模型错误解释了公开要求', '输入已展示关键的结果丢失。模型仍用不成立的需求解释排除了它。'),
}

# Target IDs refer to the existing offline reference set. They are not prompt rules.
NOTES = {
 'T01-R1': dict(category='context', subtype='temporal',
    mechanism='候选停在注册、完成、等待者清理等单次操作。它没有把同一批次中相同输入的身份，与首项结束后才运行重复项的调度顺序连起来。批内去重和在途请求合并因此没有形成行为对照。',
    model='模型解释了已完成请求的异步等待者为何能正确清理。其他候选也主要检查执行请求与等待共享结果的互斥分支。它没有分析受限并发下的批内调用次数。',
    fix='从 batch 测试中的重复值出发，连接逐项 invoke、完成后删除记录和下一次重复输入。比较重叠执行与顺序执行时的调用次数。'),
 'T06-R1': dict(category='context', subtype='temporal',
    mechanism='候选只表示一次 include 中当前覆盖值与路由值的优先级。它没有保留复制后值的来源，也没有把第二次 include 接到第一次解析后的路由对象。',
    model='模型用单层 include 的正确覆盖规则，以及对应的已有测试，排除了当前候选。这个理由没有涉及中间层 B 与外层 A 同时存在的情形。',
    fix='沿路由复制追踪值和来源标记。用相邻两次 include 的不同覆盖值，检查近层已确定的值是否继续保留。'),
 'T08-R1': dict(category='context', subtype='temporal',
    mechanism='程序把边界判断表示为布尔条件，却没有保留解析阶段。开始前找不到边界，与正文结束后缺少关闭边界，进入不同的错误路径。',
    model='模型检查的是开始扫描阶段耗尽输入。它正确指出若干边界谓词不能同时为真，却没有检查已经读取正文后的 EOF。',
    fix='把解析阶段和退出原因连起来。保留正常起始边界和正文，只移除最终关闭边界，再检查完整性错误。'),
 'T10-R1': dict(category='requirement', subtype='contract',
    mechanism='程序已经表示 warm-cache 的提前退出会跳过 output_results。公开要求也同时给出 JSON 输出字段。模型却把“不报告问题”解释为“不产生任何报告”。',
    model='模型认为输出调用属于必须跳过的报告路径。这把告警结果为空，与 stdout 为空混为一谈。候选又把预热与告警退出码配对，进一步偏离 JSON 输出目标。',
    fix='并列展示预热的空结果要求和所选 JSON 格式要求。把退出码、告警内容和输出格式分成不同的观察项。',
    caution='原两次查询均因返回多个 JSON 而失败。这会减少查阅机会，但不能使最终的需求解释成立。'),
 'T12-R1': dict(category='context', subtype='binding',
    mechanism='候选表示包查找和成员查找，却没有表示导入路径、文件内别名和文档限定符之间的绑定关系。查询“包是否存在”不能代替查询“此文件能否用这个名字引用它”。',
    model='模型检查内建标识符跳过包解析的分支。另一些候选检查空链接和成员类型。它没有检查别名 s 已建立时旧包名 strings 是否仍被接受。',
    fix='连接 import 的本地名称与链接解析器的名称表。对已改名的包，同时表示新名称应有效、旧限定符应无效。'),
 'T13-R1': dict(category='selection', subtype='identity',
    unselected=['joint_013873c0942a42c19978'],
    mechanism='完整候选中已有循环分配 ObjectPtr 的关系。它明确提出“不同输入项是否引用同一存储”和“复制后先写后读”。排序没有选择它，转而选择同一函数对象的副本缓存命中分支。',
    model='模型说明重复遇到同一个 CompiledFunction 时，seen[o] 可以保持共享。真实目标是两个不同函数共享同一个捕获单元。两种身份关系不同。',
    fix='保留共享存储的候选，并把两个不同闭包的写入与读回接到同一捕获单元。不要用重复函数引用的测试代替共享单元测试。'),
 'T15-R1': dict(category='values', subtype='lexical_value',
    mechanism='所选分类候选组合了 CIDR 解析成功与 SemVer 解析成功。这不是能激活目标的输入。真正需要区分的是 02 这类可解析为整数、但不符合版本分量约束的文本。',
    model='模型正确拒绝了同时属于 CIDR 和 SemVer 的不可行组合。它另行发现了超大数字预发布编号的错误，但没有发现前导零导致的错误分类。',
    fix='从 ParseUint 等有信息损失的转换回到输入文本。区分数值合法与版本语法合法，再观察类型分类如何改变混合排序。'),
 'T16-G1': dict(category='context', subtype='temporal',
    mechanism='类型约束保存在 Env 中，开关属于每次执行。候选只检查已有约束下的赋值失败，没有把两次执行和同一 Env 连起来。',
    model='模型认为类型不匹配时返回错误符合要求。这个解释只适用于本次仍启用类型约束的执行，没有检查第二次关闭选项。',
    fix='追踪写入持久约束的执行，以及后来读取约束的执行。保留 Env 身份，改变第二次执行的开关，并检查赋值结果。'),
 'T18-R1': dict(category='context', subtype='entry_path',
    mechanism='所选候选围绕 Truncate 的选项传递和 ASCII 分支。原测试也经过 Truncate，该路径会补回样式。候选没有表达直接 String 输出这条绕过截断的路径。',
    model='模型说明 ASCII 模式无需重开 ANSI 样式。这没有回答彩色输出在内部 reset 后是否保留 Bold。',
    fix='比较同一样式选项在 String 与 Truncate 两个公开入口的路径。检查 reset 后的字符是否重新获得外层样式。'),
 'T18-G1': dict(category='values', subtype='input_role',
    mechanism='程序找到剩余宽度和尾串截断代码，却没有区分 ANSI 来自主字符串，还是来自 Tail。它突出零宽度返回，目标则需要正的窄宽度与带色尾串。',
    model='模型只说明 maxWidth<=0 返回空字符串合理。它没有检查宽度为 1 时普通字符截断器是否切断 Tail 内的控制序列。',
    fix='追踪两个文本来源分别经过哪种截断器。将 ANSI 字符串放到 Tail，保留正的宽度预算，再检查控制序列完整性。'),
 'T19-G1': dict(category='selection', subtype='suppression_scope',
    unselected=['joint_d106b5042fba9596e66f','joint_0a4f84bc40dc7f9f53cd'],
    mechanism='完整候选保留了 checkDisjunction 中 containsNegation 的调用，以及带否定条件的分析关系。前 8 项没有保留这些焦点。剩余候选主要涉及通用遍历和报告。',
    model='模型检查 ctx.seen 递归保护，并指出不同 switch 分支不应组合。它没有检查后缀否定为何会抑制祖先分支已有的普通前缀冲突。',
    fix='保留抑制冲突报告的 containsNegation 路径。继续区分否定出现的位置与首 token 的来源，不能仅加入函数名。',
    caution='未选候选只提供更相关的入口。它仍未完整表达“普通前缀＋后缀否定”。不能把本项描述成“完整目标已提取，只差排序”。'),
 'T20-G1': dict(category='selection', subtype='cross_layer',
    unselected=['joint_d4460119495b00b4d6bf'],
    mechanism='程序已经连接 cookies.ttl 的配置正则、parseConsistentHashTTL 调用和输出 TTL。该候选没有进入前 8 项。模型实际分析的是运行时整数秒解析分支。',
    model='模型用整数秒和带单位时长的运行测试说明解析正确。它没有看到同一输入先经过配置正则时会被拒绝。',
    fix='保留同一字段跨配置校验和运行处理的关系。寻找两层接受范围的差异，并用 1.5s 这类输入检查整个入口。'),
 'T20-G2': dict(category='selection', subtype='cross_layer',
    unselected=['joint_d1fefa210ac566c75190','joint_e3d6dc58d2c81108695a'],
    mechanism='程序已经连接 queryParameters 的 list-map 声明和运行时去重。排序没有选择这些候选。模型只看到策略合并时是否存在输入。',
    model='模型说明两边都没有配置时不必合并。它没有检查重复 q 在到达“保留首项”的代码前，是否已被配置校验拒绝。',
    fix='把相同输入依次经过配置校验和去重的路径作为一个检查目标。用不同 terminal 值区分重复项，检查准入和保留首项两个结果。'),
 'T22-G1': dict(category='context', subtype='return_protocol',
    mechanism='该任务共只保留 8 个候选，全部已送入模型。异步根候选没有任何条件维度。分析没有连接 Recur 返回的 Promise，与同步 array 立即读取返回值的操作。此处不能主要归因于前 8 项筛选。',
    model='模型看到递归对象测试后认为委托结果已经检查。但实际提供的测试使用 objectAsync 和 arrayAsync。它把全异步路径的证据扩大到了同步内部容器。',
    fix='表达返回值是否需要等待，以及调用者是否等待。再用非空子树区分真正执行递归与仅构造类型。',
    caution='模型还查询了类型层面的 parse 限制。该查询进一步偏离运行时返回协议。'),
 'T24-G2': dict(category='context', subtype='branch_provenance',
    mechanism='候选位于最终条件表达式的拼接处。它没有保存 anyOf 已选分支的身份，也没有连接后续规则收集重新遍历全部分支的行为。',
    model='模型说明条件、名称和更新值的几个输出字段能够正常合并。它没有检查这些条件是否来自输入实际选中的分支。',
    fix='沿解析结果保存分支来源。把“选择 B”与“条件来自 A”并列展示，并追踪 savedAs 如何决定最终更新路径。'),
 'T25-R1': dict(category='values', subtype='enumeration_cap',
    mechanism='候选含 15 个条件。组合枚举只使用前 8 个。关键的 stack 属性、frames 分支及属性许可位于第 9 至第 15 个条件。最终 8 项建议主要围绕消息清理和 cause。',
    model='模型实际读到了 serializeError 的完整相关源码，但结论仍围绕消息清理、cause 和 off 模式。它没有检查 frames 模式同时允许复制原始 stack。',
    fix='按共同影响的输出属性选择条件。把普通属性复制与模式专属堆栈写入连接起来，优先比较同一输出中是否出现互斥表示。',
    caution='这是条件选择失败，不能仅称为源码缺失。当前候选甚至没有关联到任何原测试，说明测试关联也需要修正。'),
 'T27-R1': dict(category='context', subtype='producer_consumer',
    mechanism='候选连接异步完成、缓存与应用结果，但没有把返回项的内容接到默认本地过滤器。异步结果已经筛选过，与静态选项还需本地筛选，是两个不同输入来源。',
    model='模型说明过期请求应被丢弃、最新请求应被应用。这个生命周期判断没有检查被应用的列表是否又被错误删项。',
    fix='沿 resolver 返回列表追踪到显示列表。对照异步与同步入口的过滤步骤，检查服务端返回但不匹配本地查询词的合法项。'),
 'T27-G1': dict(category='context', subtype='temporal',
    mechanism='候选检查输入过短的入口分支，没有连接先前选择值与随后提交的返回值。完整候选有通用状态读写关系，但没有选出这条完整状态顺序。',
    model='模型讨论的是非异步实例为何不需清理异步状态。真正目标需要同一个异步实例先选中 A，再进入短输入状态，最后提交。',
    fix='连接 selectedValues 的建立、短输入时的列表清空和提交时的读取。原测试已经按 Enter，但没有检查返回值；补足的关键是观察项。',
    caution='另一项相关候选在追加调用后仍没有提交合法判断，属于叠加的调用问题。'),
 'T28-R1': dict(category='context', subtype='temporal',
    mechanism='候选重点检查 restore 当时的 data、error 和 status，或持久化器本次是否再次请求。它没有把 isInvalidated 的写入，接到后来观察者挂载触发的请求。',
    model='一项候选认为“有 error 时立即得到 error 状态”符合要求。较相关的恢复候选则仍未形成合法最终答复。两者都没有解决挂载后状态被新请求覆盖的问题。',
    fix='从恢复后的 isInvalidated 沿读取关系走到挂载请求条件。保留 error、已有 data、staleTime=Infinity 和未失效标记，再观察挂载后的状态及调用次数。',
    caution='该任务有 3 个候选最终仍为 unknown。因此不能把整条任务描述成模型已充分检查后判定无缺口。'),
 'T30-G1': dict(category='context', subtype='producer_consumer',
    mechanism='候选枚举单个 Track 的 fixed 与 minmax 分支。目标却要求两个层级的关系：子网格的 auto 内容宽度，应成为父网格 auto 列的测量输入。',
    model='模型正确指出一个 Track 不能同时是 fixed 和 minmax。但它随后接受了其他类别贡献 0 的局部实现，没有检查父网格如何使用这个 0。',
    fix='连接子网格的内容测量结果和父列宽度。分别标明父、子两个对象，避免把跨层级组合错写成同一 Track 的互斥类别。'),
 'T08-G1': dict(category='values', subtype='lexical_context',
    mechanism='输入有按分号切分和处理引号的相关代码。但条件只表示是否带引号、是否缺边界等布尔值，没有表示分号在引号内部。自动建议又主要选择空输入与错误类型。',
    model='主实验前两轮返回多个 JSON，末轮仍请求源码。追加调用也再次请求源码，因而没有合法的最终判断。不能把本项称为模型明确拒绝了引号内分号目标。',
    fix='保留引号范围和切分字符位置的关系，形成 boundary="a;b" 的合法输入类别。先修复调用协议，再检查模型能否利用该区别。',
    caution='内容缺陷和调用失败同时存在。本次不能证明修复输入表示就能检测成功。'),
 'T08-N1': dict(category='values', subtype='compound_predicate',
    mechanism='程序保留了头部结束和边界的相关语句，但把“未找到空行且已经 EOF”合成一个布尔条件。false 同时包含正常结束头部，以及尚未结束头部就先遇关闭边界。',
    model='主实验和追加调用均用完输出额度，未提交最终判断。前轮曾成功的更相关候选仍在完整候选中，本轮没有选中。',
    unselected=['joint_1073656804de870b6ea0'],
    fix='拆开“是否已有空行”和“为何退出头部扫描”。保留解析阶段，再区分 EOF、空行和边界三种退出原因。',
    caution='该目标仅属于扩展的第 24 项，不计入固定 23 项的分类分母。'),
}


def read(path):
    return json.loads(Path(path).read_text())


def rel(path):
    return str(Path(path).resolve().relative_to(ROOT))


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def link(path, label):
    import os
    return f'<a href="{escape(os.path.relpath(path, REPORT.parent), quote=True)}">{escape(label)}</a>'


def para(label, text):
    return f'<p><strong>{escape(label)}：</strong>{escape(text)}</p>' if text else ''


def historical_scope(t):
    rewritten = {
        'T08-G1':'原测试用引号包围简单边界值，也检查引号外的多个参数。它没有把分号放在引号内的边界值中。',
        'T16-G1':'原测试分别检查启用约束时拒绝错误类型，以及关闭约束时允许动态赋值。两组测试分别新建环境，没有复用同一个 Env。',
        'T18-G1':'原测试检查带 ANSI 样式的主字符串，以及普通省略号尾串。窄宽度测试中的尾串仍是普通文本。',
        'T19-G1':'原测试分别检查普通前缀冲突和纯否定分支。它没有把否定节点放在已经产生普通首 token 的前缀之后。',
        'T20-G1':'原运行测试检查 1h30m 和 3600 等时长。原配置正则检查也使用整数时长。它没有让小数时长依次经过两层处理。',
        'T20-G2':'原测试直接构造类型化配置，再调用运行时构造器。重复项的测试绕过了真实配置准入校验。',
        'T22-G1':'原测试运行了全同步和全异步递归。异步外层与同步内部容器的混合结构只有类型构造检查，没有运行非空子树。',
        'T24-G2':'原 anyOf 测试只有一个 map 分支。其他保存名测试也使用单一 map 树，没有检查两个分支的规则和保存名不同。',
        'T27-G1':'原核心测试检查短输入时的空列表和状态标记。另一个测试实际执行了 Enter，但没有检查提交返回值。',
        'T30-G1':'原自动列宽测试只放入普通文本。原嵌套网格测试使用固定宽度，没有观察子网格内容对父列自动宽度的影响。',
    }
    if t['id'] in rewritten:
        return rewritten[t['id']]
    s = t['source_record']
    if s.get('original_validation'):
        return s['original_validation']
    g = s.get('original_gap', {}).get('source_gap', {})
    keys = ('separate_coverage', 'original_tests_check_separately', 'existing_checks',
            'original_checks', 'existing_components')
    return next((g[k] for k in keys if g.get(k)), '请见原参照记录。')


def collect(t, review, combined):
    note = NOTES[t['id']]
    case, cid = t['case'], review['candidate']
    base = RUN / 'cases' / case / 'detector' / cid
    request_path = base / 'round1/request.json'
    request = read(request_path)
    e = json.loads(request['messages'][-1]['content'])['evidence']
    final = combined[(case, cid)]
    traces = []
    for stage, directory in [('primary', base), ('supplement', RUN/'decision_recovery_v1/cases'/case/cid)]:
        for folder in sorted(directory.glob('round*')):
            a, f = folder/'action.json', folder/'feedback.json'
            action = read(a) if a.exists() else None
            feedback = read(f) if f.exists() else None
            traces.append({'stage':stage, 'round':folder.name,
                           'directory':rel(folder), 'action':action,
                           'feedback_summary':{k:v for k,v in (feedback or {}).items()
                                               if k in ('status','error','path','start_line','end_line','truncated','total_tests','has_more')}})
    final_path = RUN/'decision_recovery_v1/cases'/case/cid/'result.json'
    if not final_path.exists():
        final_path = base/'result.json'
    pack_path = RUN/'evaluation/extraction'/f'{case}.json'
    pack = read(pack_path)
    unselected = []
    for key in note.get('unselected', []):
        c = next(c for c in pack if c['id']==key)
        assert not c['selected'], key
        unselected.append(c)
    record = {
        'id':t['id'], 'case':case, 'reference_set':t['set'], 'title':t['description'],
        'reference_record':t['source_record'], 'original_validation':historical_scope(t),
        'diagnosis':note, 'related_selected_candidate':cid,
        'candidate_family':e['analysis_candidate']['family'],
        'initial_conditions':e['behavioral_distinction']['conditions'],
        'proposed_targets':e['behavioral_distinction']['targets'],
        'initial_test_inventory':[{k:v for k,v in test.items() if k in ('id','name','origin','span','written_path','code_truncated')}
                                  for test in e['related_tests']],
        'initial_input_scope':e['input_scope'], 'history_chain':e['history_chain'],
        'primary_result':read(base/'result.json'), 'final_result':final,
        'unselected_related_candidates':unselected, 'interaction_trace':traces,
        'evidence':{'reference_set':rel(RUN/'evaluation/reference_targets.json'),
                    'retained_candidates':rel(pack_path), 'initial_request':rel(request_path),
                    'final_result':rel(final_path), 'request_sha256':sha(request_path),
                    'final_result_sha256':sha(final_path)},
        'reviewer':'Codex static evidence review; not independent human validation',
        'causal_limit':'Observed failure mechanism and a proposed diagnostic correction. No intervention or causal ablation was run.'}
    dump(OUT/'targets'/f"{t['id']}.json", record)
    return record


def main():
    refs = read(RUN/'evaluation/reference_targets.json')['targets']
    reviews = {x['id']:x for x in read(RUN/'evaluation/target_review.json')['targets']}
    inventory = read(RUN/'decision_recovery_v1/combined_inventory.json')
    combined = {(x['case'],x['candidate']):x for x in inventory}
    recovered = read(RUN/'decision_recovery_v1/summary.json')
    primary = read(RUN/'summary.json')
    positive_claims = [read(f) for directory in (RUN/'evaluation/claims',RUN/'decision_recovery_v1/evaluation/claims')
                       for f in sorted(directory.glob('*.json')) if read(f).get('verdict')=='correct']
    hit = {target for claim in positive_claims for target in claim.get('reference_targets', [])}
    assert hit == {'T17-R1','T24-R1'}, hit
    missed = [t for t in refs if t['id'] not in hit]
    assert set(NOTES) == {t['id'] for t in missed}
    records = [collect(t,reviews[t['id']],combined) for t in missed]
    main_records = [r for r in records if r['reference_set']=='primary23']
    counts = Counter(r['diagnosis']['category'] for r in main_records)
    assert counts == {'context':12,'selection':4,'values':4,'requirement':1}
    positive_tasks = {t['case'] for t in refs if t['set']=='primary23'}
    accepted = set(recovered['combined_correct_task_ids'])
    no_reference = sorted({f'T{i:02}' for i in range(1,31)}-positive_tasks)
    unknown = [v for v in inventory if v['decision']=='unknown']
    case_records = []
    for case in [f'T{i:02}' for i in range(1,31)]:
        task = {'case':case, 'fixed_targets':[t['id'] for t in refs if t['case']==case and t['set']=='primary23'],
                'missed_fixed_targets':[t['id'] for t in missed if t['case']==case and t['set']=='primary23'],
                'accepted_any_target':case in accepted,
                'final_decisions':[v for v in inventory if v['case']==case]}
        case_records.append(task)
    dump(OUT/'case_inventory.json',case_records)
    scope_examples = {}
    for r in records:
        scope_examples[r['id']] = r['initial_input_scope']
    summary = {
        'created_at':datetime.now(timezone.utc).isoformat(),
        'scope':'Final v3 detection-only decisions, including the separately reported uniform recovery.',
        'fixed_targets':23,'fixed_hits':len(hit),'fixed_misses':len(main_records),
        'expanded_targets':24,'expanded_misses':len(records),
        'fixed_positive_tasks':len(positive_tasks),
        'tasks_missing_at_least_one_fixed_target':len({r['case'] for r in main_records}),
        'known_positive_tasks_without_any_accepted_detection':sorted(positive_tasks-accepted),
        'tasks_without_eligible_fixed_reference':no_reference,
        'main_diagnostic_categories':{k:{'name':CATEGORIES[k][0],'count':v,
             'targets':[r['id'] for r in main_records if r['diagnosis']['category']==k]} for k,v in counts.items()},
        'content_classification_policy':'One dominant visible content bottleneck per target. Secondary causes remain explicit. These counts are not intervention-derived causal shares.',
        'related_candidate_final_decisions':dict(Counter(r['final_result']['decision'] for r in main_records)),
        'unknown_candidates':len(unknown),'unknown_errors':dict(Counter(v.get('error',v['stop_reason']) for v in unknown)),
        'unknown_by_case':dict(Counter(v['case'] for v in unknown)),
        'primary_selected_families':primary['selected_families'],
        'primary_queries':read(RUN/'evaluation/query_audit.json')['inspect_kinds'],
        'new_model_calls':0,'new_subject_executions':0,'algorithm_edits':0,'reference_label_edits':0,
        'review_mode':'Codex static evidence review, no independent human review and no causal ablation.',
        'evidence_sha256':{rel(f):sha(f) for f in (RUN/'protocol.json',RUN/'evaluation/reference_targets.json',
                            RUN/'decision_recovery_v1/combined_inventory.json',RUN/'decision_recovery_v1/summary.json')},
    }
    assert len(positive_tasks-accepted)==14 and len(no_reference)==12
    assert summary['tasks_missing_at_least_one_fixed_target']==17
    assert summary['related_candidate_final_decisions']=={'no_gap':19,'unknown':2}
    dump(OUT/'summary.json',summary)

    parts = ['''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>30 条任务：组合缺口漏检的分类诊断</title>
<style>
body{font-family:system-ui,"Noto Sans CJK SC",sans-serif;max-width:1120px;margin:38px auto;padding:0 22px;color:#172b3a;line-height:1.8;background:#fafcfd}
h1{font-size:1.85rem}h2{font-size:1.35rem;margin-top:2.2rem}h3{font-size:1.08rem}p{margin:.7rem 0}
table{border-collapse:collapse;width:100%;font-size:.93rem;margin:18px 0;background:white}th,td{border:1px solid #cdd8df;padding:10px;vertical-align:top}th{background:#edf3f6;text-align:left}
a{color:#075ba7}code{font-family:monospace;overflow-wrap:anywhere}details{background:white;border:1px solid #cdd8df;border-radius:6px;padding:14px 18px;margin:14px 0}summary{font-weight:650;cursor:pointer}.lead{border-left:5px solid #277ba3;background:#eef7fb;padding:14px 20px}.note{color:#4f5e6c;font-size:.92rem}.wrap{overflow-x:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f8;padding:12px;line-height:1.55;font-size:.87rem}.badge{color:#285e73}
@media print{body{max-width:none;background:white}details{break-inside:avoid}summary{list-style:none}}
</style><main>
<h1>30 条任务：组合缺口漏检的分类诊断</h1>
<p class="note">2026-10-09。对象：改进后的 v3 检测实验及统一追加判断。本文只诊断检测。没有生成测试，没有运行被测程序，也没有再次调用模型。</p>
<div class="lead"><p><strong>主要瓶颈是检查目标发生了偏移。</strong>程序经常把组合问题缩成局部布尔条件。模型随后解释这些局部分支为何合理。这样的答复可以成立，但没有检验同一输入、对象或状态经过多个操作后的结果。</p>
<p>另一些任务已经有更相关的程序关系，但排序没有选择它们。还有少数任务受到需求误读或无效模型答复的影响。不能把这些失败统一归为“模型能力不足”。</p></div>
<h2>1. 实验设置与统计范围</h2>
<p>实验使用原来的 30 条任务。方法读取原始补丁、公开要求、仓库代码和开发轨迹。程序保留 6,714 个候选，每条任务选 8 个，共 240 个。每个候选最多有两次只读查阅和一次最终判断。模型请求名为 DeepSeek-v4-flash，provider 返回名为 deepseek-flash。</p>
<p>主实验有 53 个候选因调用或输出问题未完成判断。实验对这 53 项统一追加一次最终调用。追加调用使用相同输入，只提高输出上限。本文诊断追加后的结果，并保留主实验的区别。</p>
<p>参照缺口必须满足既定静态标准：存在一个组合测试，原补丁不满足其断言，gold 补丁满足其断言；原验证没有有效检查该组合。固定集合含 23 项，分布于 18 条任务。前轮新增的 T08-N1 构成第 24 项扩展目标。R 表示由基准失败引导逆推的目标，G 表示保留的旧差分目标，N 表示前轮新增目标。字母不表示可信度等级。</p>
<p>这些参照用于事后评价。模型没有得到 gold、基准失败测试或参照标签。本轮沿用既有参照，没有重新扩大目标集合。多数目标依据静态语义。T08-N1 另有前轮保存的原补丁失败、gold 通过记录。</p>
<table><thead><tr><th>口径</th><th>结果</th><th>含义</th></tr></thead><tbody>
<tr><td>固定参照</td><td>检出 2/23，漏检 21/23</td><td>检出 T17-R1 和 T24-R1。漏检目标分布于 17 条任务。</td></tr>
<tr><td>扩展参照</td><td>检出 2/24，漏检 22/24</td><td>增加 T08-N1。该目标本轮未检出。</td></tr>
<tr><td>至少检出一个有效目标</td><td>4/30 条任务</td><td>T08、T15、T17、T24。T08 只确认资源关闭子目标；若排除这项部分正确的描述，保守口径为 3/30。</td></tr>
<tr><td>已知有参照，但未检出任何有效目标</td><td>14 条任务</td><td>T01、T06、T10、T12、T13、T16、T18、T19、T20、T22、T25、T27、T28、T30。</td></tr>
<tr><td>没有有效固定参照</td><td>12 条任务</td><td>不能把这些任务未报缺口直接计作漏报。T11 和 T23 的肯定报告经复核属于误报。</td></tr>
<tr><td>仍未完成判断</td><td>16/240 个候选</td><td>分布于 12 条任务。这是候选数，不是漏检任务数。</td></tr>
</tbody></table>
<p>T08 与 T15 找到了其他有效目标，仍漏掉原参照。T24 检出一个目标，漏掉另一个目标。本文按具体目标诊断，避免用“任务成功”掩盖剩余遗漏。</p>
<h2>2. 固定集合中 21 项漏检的分类</h2>
<p>下表为每个目标指定一个主要的内容问题。调用失败另行统计。一个目标可以同时受到多项因素影响。分类计数表示证据审读结果，不表示已经通过消融实验测得的因果比例。</p>
<table><thead><tr><th>主要问题</th><th>数量</th><th>目标</th><th>判定标准</th></tr></thead><tbody>''']
    for key in CATEGORIES:
        group=summary['main_diagnostic_categories'][key]
        anchors='、'.join(f'<a href="#{tid}">{tid}</a>' for tid in group['targets'])
        parts.append(f'<tr><td>{escape(group["name"])}</td><td>{group["count"]}</td><td>{anchors}</td><td>{escape(CATEGORIES[key][1])}</td></tr>')
    parts.append('''</tbody></table>
<p>第一类有 4 项。T13 的共享捕获单元关系、T20 的两项跨层关系已经存在，但没有送给模型。T19 也有更相关的否定抑制路径。不过，T19 仍需补充普通前缀与后缀否定的位置区别。</p>
<p>第二类有 12 项。其中 6 项需要区分先后阶段：T01、T06、T08-R1、T16、T27-G1、T28。其余 6 项需要保留名称绑定、入口差异、返回协议、分支来源或结果的后续使用：T12、T18-R1、T22、T24-G2、T27-R1、T30。</p>
<p>第三类有 4 项。T08-G1 缺少引号内部的分号。T15 缺少非法前导零。T18-G1 没有把 ANSI 放入尾串。T25 的条件截断排除了关键的模式与许可组合。这些问题主要涉及取值及输入角色，扩大关系链长度不能直接解决。</p>
<p>第四类有 1 项。T10 的材料已经说明提前退出会跳过输出。模型仍将“不报告告警”解释为“不输出 JSON”。程序表示也有不足，但模型的最终需求解释构成独立错误。</p>
<h2>3. 为什么这些问题反复出现</h2>
<h3>3.1 语法先后被当成需要共同检查的行为</h3>
<p>当前程序把带条件的退出语句，与同一函数中后面的调用、赋值或观察连接。它没有先排除互斥分支。因此，实际执行请求一方的异常退出，可被连接到等待共享结果一方的分支；同一个 Track 的 fixed 与 minmax 也可被组合。</p>
<p>这些关系标为“可能”，本身没有宣称存在缺陷。问题出在后续使用方式：它们获得较高排序，进入有限的模型候选。模型把查阅机会用于排除不可能的组合，真正的组合仍未进入判断范围。</p>
<p>因此，no_gap 只能解释为“这个候选未发现缺口”。它不能解释为整条任务没有缺口。本次模型多次正确拒绝局部候选，同时漏掉任务内已知的错误。</p>
<p>提示允许模型细化候选。但当前控制流程在收到合法判断后就结束该候选，不会因候选不可行而补选其他关系。这使错误的初始选择持续影响最终检出率。</p>
<h3>3.2 排序偏好局部退出，压低跨操作关系</h3>
<p>选出的 240 项中，152 项涉及提前退出，占 63.3%。共享复制关系和配置声明到运行处理的关系各为 0 项。程序并非完全不会提取它们；T13 保留了 17 项共享复制候选，T20 保留了 11 项声明到运行处理候选。</p>
<p>排序奖励修改语句、显式效果、少量具体条件和较小焦点。提前退出容易同时获得这些分数。共享身份和前后阶段属于抽象维度，不能同样获得“具体条件”加分。当前重复惩罚比较语句与条件的重合，仍可保留多个意义相近的退出候选。</p>
<p>上述实现和选择结果支持“排序偏向局部控制流”的诊断。但本轮没有重跑替代排序。因此，不能声称把某类候选放回前 8 项就必然检出对应目标。</p>
<h3>3.3 组合枚举受源码顺序影响</h3>
<p>程序只对前 8 个条件枚举，最多保留 40 个组合，再向模型突出最多 8 项。它按条件出现顺序展开。关键条件位于后部时，即使已经提取出来，也可能没有参与组合。</p>
<p>T25 给出直接证据。消息清理和 cause 位于前部。堆栈属性与 frames 位于后部。模型最后围绕前部组合推理。增加模型输出额度后，该目标仍未检出。</p>
<p>T08-N1 暴露另一种压缩损失。一个复合条件的 false 可以对应两种不同解析状态。程序保留布尔结果，却丢掉了造成 false 的原因。模型需要重新从源码恢复这个区别。</p>
<h3>3.4 原测试的范围没有围绕目标区别表达</h3>
<p>当前范围记录能区分单次调用，避免把两个独立调用直接拼成联合覆盖。但它仍依赖近似调用关系和布尔条件。它没有稳定表示对象身份、后续阶段、异步返回协议及具体断言究竟约束了哪个结果。</p>
<p>T22 的实际输入含全异步递归测试。模型将其当作委托行为已有充分检查，却没有区分同步 array。T28 的模型判断停在 restore 后立即观察 error 状态，缺口却在后来的挂载请求。T27-G1 原轨迹已经按 Enter，缺少的是提交值断言。</p>
<p>测试查询的路径问题已有改善。主实验的 18 次测试查询中，13 次返回匹配，4 次因末轮仍查询而未执行，1 次路径不在快照。审计未发现返回错误路径的测试。剩余问题主要是语义关联、范围压缩和观察阶段，不宜继续概括为“查询工具没找到测试”。</p>
<p>输入裁剪会加重这一问题。T28 的一个相关候选有 114 项关联测试、120 行范围记录，初始输入只保留 6 项测试和 1 行范围。这里的数量表示关联材料规模，不表示 114 项测试均能到达目标分支。另一个极端是 T25：相关序列化候选没有关联到任何原测试。</p>
<h3>3.5 轨迹没有充分转化成下一步检查方向</h3>
<p>输入已经提供历史步骤和最后修改后的验证概况。但它们主要说明读过、改过和运行过哪些内容。它们没有稳定地给出“测试依赖哪个前提，哪个后续结果尚未观察”。</p>
<p>主实验保存的有效动作中，源码查询有 251 次，测试查询有 18 次，没有显式的 history 或 scope 查询。初始输入已有部分轨迹，因此这不等于模型完全未使用轨迹。它说明后续查阅主要用于解释局部实现，没有主动扩大对原验证范围的核查。</p>
<p>原验证有三个重复模式：组件分别检查；联合场景只观察中间状态；样例恰好避开两种语义的差别。T20 分别检查配置与构造器。T28 只在恢复阶段观察。T01 用重叠执行，T25 用与模式一致的白名单。轨迹可帮助识别这些模式。</p>
<p>这些记录不能证明原 agent “遗忘”了逻辑，或“只追求覆盖率”。本文只报告可观察的测试选择、输入前提和检查范围。</p>
<h2>4. 调用失败是另一条诊断轴</h2>
<p>主实验有 53 个候选未完成判断。统一追加调用后，35 个转为 no_gap，2 个转为 gap，16 个仍为 unknown。新增肯定判断对应 T17 的固定目标，以及 T08 的资源关闭子目标。这个结果表明调用限制确实影响检测，但不能说明其余遗漏主要来自输出额度。</p>
<p>最后 16 项中，10 项没有提交合法最终判断，2 项引用了无效测试编号，4 项用完输出额度。固定漏检目标对应的主要相关候选中，T08-G1 和 T28-R1 仍为 unknown。扩展目标 T08-N1 也仍为 unknown。它们不能作为模型完成语义检查后拒绝目标的证据。</p>
<p>例如，T08-G1 在最终调用仍申请读取源码。T08-N1 在提高到 32,768 输出 token 后仍没有给出答案。后者的用量记录全部计为推理 token。单纯继续增加输出额度，没有得到本轮检测结果。</p>
<p>主实验多次因输出多个 JSON 触发解析失败。这类失败会消耗原本用于查阅的轮次。应单独评价“是否成功取得材料”和“是否形成正确语义判断”。不要把无效答复计成无缺口。</p>
<h2>5. 每个漏检目标的证据与原因</h2>
<p>下列条目包含原验证范围、应检查的组合、原补丁与 gold 的差别、实际候选和模型判断。链接保留原请求、逐轮反馈和最终答复。英文原始答复放在可展开的证据内，中文正文不要求读者理解内部候选名称。</p>''')
    for r in sorted(records,key=lambda r:r['id']):
        s=r['reference_record']; note=r['diagnosis']; tid=r['id']
        witness=s.get('distinguishing_check') or s.get('witness') or s.get('reason','')
        diff=s.get('semantic_difference') or s.get('paired_reason') or s.get('reason','')
        case_label='扩展目标' if r['reference_set']!='primary23' else '固定目标'
        final=r['final_result']; d={'no_gap':'未报告缺口','unknown':'未完成判断'}.get(final['decision'],final['decision'])
        parts.append(f'<details id="{tid}" open><summary>{tid} · {escape(r["title"])} <span class="badge">〔{case_label}；{escape(CATEGORIES[note["category"]][0])}〕</span></summary>')
        parts.extend([para('原验证',r['original_validation']),para('缺失组合及检查结果',witness),
                      para('原补丁与 gold',diff),para('提取与输入问题',note['mechanism']),
                      para('实际模型判断',note['model']),para('针对性修正',note['fix']),para('判断边界',note.get('caution',''))])
        links=[link(OUT/'targets'/f'{tid}.json','逐项审读记录'),
               link(ROOT/r['evidence']['initial_request'],'实际初始输入'),
               link(ROOT/r['evidence']['final_result'],'最终答复'),
               link(ROOT/r['evidence']['retained_candidates'],'完整候选摘要')]
        parts.append('<p class="note">'+' · '.join(links)+f'。该相关候选最终状态：{d}。</p>')
        reason=(final.get('assessment') or {}).get('reason')
        if reason:
            parts.append(f'<details><summary>原始英文判断</summary><pre>{escape(reason)}</pre></details>')
        parts.append('</details>')
    parts.append('''<h2>6. 仍需保留的边界</h2>
<p>T17 和 T24-R1 提供了成功对照。T24-R1 的输入明确表示“入口采用默认 put，但辅助函数收到原 options”。模型据此识别了下游跳过校验。T17 的程序表示仍有缺陷，但模型在查阅编译器后，通过追加判断恢复了目标。前者支持明确行为区别的价值，后者说明不完整表示不必然导致失败。</p>
<p>T11 的误报来自把已经执行且失败的组合当成未检查组合。T23 的误报来自沿用历史旧失败，没有核对最终补丁已经写回初始化返回值。这两项与漏检不同，但都说明轨迹必须结合代码版本解释。已有有效联合测试而未执行，应另记选测问题；已有执行失败，也不能改称组合验证缺口。</p>
<p>另外 12 条任务是 T02、T03、T04、T05、T07、T09、T11、T14、T21、T23、T26、T29。当前参照没有为它们确认有效组合目标。这不证明它们没有组合缺口，也不能解释成检测器的 12 次正确拒绝。</p>
<p>本文由 Codex 逐项静态审读。没有独立人工复核，没有新增原补丁与 gold 的成对执行，也没有测量 resolution rate。分类定位了可见断点。只有后续控制变量的对照，才能证明修正哪一项带来多少检测提升。</p>
<h2>7. 后续修正的优先级</h2>
<p><strong>先校正检查对象。</strong>围绕会影响外部结果的同一值、对象或状态组织关系。明确输入条件、关键操作和观察结果。不要把任意两个相邻布尔条件直接当成组合目标。</p>
<p><strong>再校正候选选择。</strong>在不改变提取器的对照中，把已有的共享捕获、跨层校验和否定抑制关系送入模型。另用轻量分支约束过滤明显互斥的候选。先判断排序究竟丢失了多少已有信息。</p>
<p><strong>随后校正取值与测试范围。</strong>按同一输出受哪些条件共同影响来选择组合。保留条件所指的对象、输入位置和前后阶段。用“原测试实际输入、经过的操作、断言结果”与目标逐项比较。</p>
<p><strong>把调用恢复单独评价。</strong>修复动作格式和最终判断流程，再用相同语义输入重试。只有这样，才能区分交互故障与算法表示不足。当前不需要继续生成测试来验证这些检测阶段的问题。</p>
<p>研究上的核心问题是：程序分析能否保留足以区分行为的上下文，同时排除无意义的组合。任务标签不能成为新增规则清单。后续应检验通用的状态传递、输入来源和消费关系能否覆盖这些遗漏。</p>
<h2>8. 可复核材料</h2><ul>''')
    for f,title in [(OUT/'summary.json','分类计数与审读边界'),(OUT/'case_inventory.json','全部 30 条任务及全部 240 项最终判断'),
                    (RUN/'evaluation/reference_targets.json','固定与扩展参照记录'),(RUN/'evaluation/query_audit.json','测试及源码查询审计'),
                    (RUN/'decision_recovery_v1/summary.json','统一追加判断结果'),
                    (ROOT/'src/augmentation/relations.py','关系提取实现'),(ROOT/'src/augmentation/ranking.py','候选排序实现'),
                    (ROOT/'src/augmentation/joint.py','条件组合枚举实现'),(ROOT/'src/augmentation/presentation.py','输入与原测试范围表示'),
                    (ROOT/'docs/archive/20261009_behavioral_gap_detection_v03_n30.html','完整实验报告')]:
        parts.append('<li>'+link(f,title)+'</li>')
    parts.append('</ul></main></html>')
    REPORT.write_text('\n'.join(parts))
    print(json.dumps({'report':rel(REPORT),'fixed_misses':len(main_records),'categories':dict(counts),'expanded_misses':len(records)},ensure_ascii=False))


if __name__=='__main__':
    main()
