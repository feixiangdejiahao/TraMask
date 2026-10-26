"""Report diagnostic comparisons, input differences, and scoped conclusions."""
from collections import Counter
from html import escape
from pathlib import Path
import ast
import hashlib
import json
import os
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from scripts.run_augmentation_diagnostic6 import RUN,OLD,read,write,receipt,extract_facts,MATERIAL

REPORT=ROOT/'docs/augmentation_diagnostic6_20261008.html'
CASES=['T10','T13','T17','T20','T24','T28']
TITLES={'T10':'预热缓存与 JSON 输出','T13':'复制闭包与共享捕获变量','T17':'存在的 undefined 与默认值',
        'T20':'配置校验与运行时接受范围','T24':'默认模式与条件必填','T28':'恢复快照与后续框架挂载'}


def link(path,label):return f'<a href="{escape(os.path.relpath(path,REPORT.parent),quote=True)}">{escape(label)}</a>'
def table(headers,rows):
    return '<div class="scroll"><table><tr>'+''.join(f'<th>{escape(h)}</th>' for h in headers)+'</tr>'+''.join('<tr>'+''.join(f'<td>{x}</td>' for x in row)+'</tr>' for row in rows)+'</table></div>'


def collect(root,secondary=False):
    rows=[]
    for path in sorted(root.glob('cases/*/*/round*/result.json')):
        result=read(path);directory=path.parent;cid,arm,rn=result['case'],result['arm'],result['round']
        ap=directory/'assessment.json';assessment=read(ap) if ap.exists() else {}
        ep=directory/'execution/feedback.json';execution=read(ep) if ep.exists() else {}
        cp=directory/'execution/comparison.json';pair=read(cp) if cp.exists() else {}
        explicit=[];generated=[];basis='未命中本次参照目标。未据此将其他补测判为误报。'
        if cid=='T17' and ((arm=='B' and rn==2 and not secondary) or (arm=='N' and secondary and assessment.get('decision')=='gap')):
            explicit=generated=['T17-R1'];basis='说明和测试均区分存在的 undefined 与真正缺失。公开要求限定默认值仅用于缺失。'
        elif cid=='T24' and arm=='C':
            generated=['T24-R1'];basis='说明关注 savedAs 与 requiredIf；代码省略 mode，实际触发默认模式错误。不能将说明记为准确定位默认模式。'
        elif cid=='T24' and arm in ['D','N']:
            explicit=generated=['T24-R1'];basis='明确指出省略 mode 与显式 put 的差别，代码保留对应输入与拒绝断言。'
        elif cid=='T13' and arm=='N':
            explicit=generated=['T13-R1'];basis='两个不同闭包在同一转移对象中共享捕获变量。原补丁写入后读取仍为旧值。gold 按 ObjectPtr 缓存复制结果，Set 使用同一复制状态。此项按此前要求做 gold 静态语义判断，没有运行依赖原新增测试辅助函数的 gold 测试。'
        if not assessment:explicit=[];generated=[];basis='没有完整可解释的最终答复；单列技术失败，不能推断模型的缺口判断。'
        row={'case':cid,'arm':arm,'round':rn,'budget_recovery':secondary,
             'raw_status':result['status'],'decision':assessment.get('decision'),
             'explicit_target_ids':explicit,'generated_target_ids':generated,
             'candidate_status':execution.get('status'),
             'gold_status':pair.get('reference_run_status'),
             'dynamic_differential_named_tests':pair.get('counts',{}).get('differential_witness',0),
             'gold_static_support':cid=='T13' and arm=='N' and bool(generated),
             'transport_recovered':(directory/'transport_recovery.json').exists(),
             'reason':assessment.get('reason'),'distinction':assessment.get('distinction'),
             'review_basis':basis,'result':receipt(path),
             'assessment':receipt(ap) if ap.exists() else None,
             'execution':receipt(ep) if ep.exists() else None,
             'pair':receipt(cp) if cp.exists() else None}
        rows.append(row)
    return rows


def group_metrics(rows,arm):
    selected=[r for r in rows if r['arm']==arm or arm=='D' and r['arm']=='C' and r['round']==1]
    explicit={t for r in selected for t in r['explicit_target_ids']}
    generated={t for r in selected for t in r['generated_target_ids']}
    revealed={t for r in selected if r['candidate_status']=='fail' and (r['gold_status']=='pass' or r['gold_static_support']) for t in r['generated_target_ids']}
    return {'explicit_targets':sorted(explicit),'generated_targets':sorted(generated),'confirmed_revealing_targets':sorted(revealed),
            'explicit_trials':len({t.split('-')[0] for t in explicit}),
            'generated_trials':len({t.split('-')[0] for t in generated}),
            'revealing_trials':len({t.split('-')[0] for t in revealed}),
            'unreported_reference_targets':7-len(explicit),
            'new_gap_proposals':sum(r['decision']=='gap' for r in selected),
            'no_final_response_calls':sum(r['raw_status']=='provider_error' for r in selected)}


def validate():
    checks=[]
    for case in read(RUN/'cases.json'):
        cid=case['id'];d=RUN/'cases'/cid
        reqs={a:read(d/f'input_{a}.json') for a in ['A','B','C','N']}
        sent=read(d/'A/round1/request.json')
        original=read(next(x for x in read(RUN/'material_comparison.json') if x['case']==cid)['original_request']['path'])
        assert sent==original
        payloads={a:json.loads(q['prompt']) for a,q in reqs.items()}
        b=payloads['B'];c=payloads['C'];n=payloads['N']
        assert {k:v for k,v in c.items() if k!='program_extracted_conditions'}==b
        assert {k:v for k,v in n.items() if k!='analysis_candidate'}=={k:v for k,v in c.items() if k!='analysis_candidate'}
        for key in ['public_requirement','submitted_patch']:assert payloads['A'][key]==b[key]
        for key in ['family','scope','function_ids','relations','reason','contrast','evidence']:
            assert payloads['A']['analysis_candidate'][key]==b['analysis_candidate'][key]
        assert read(d/'conditions.json')==extract_facts(Path(case['repository']),MATERIAL[cid],case['language'])
        checks.append({'case':cid,'A_all_provider_payload_fields_equal_original':True,
                       'B_original_hypothesis_retained':True,'C_only_adds_extracted_conditions':True,
                       'N_only_changes_candidate_hypothesis':True,'conditions_reproducible_without_model':True})
    for d in read(RUN/'material_comparison.json'):
        for rec in d['material_receipts']:
            assert hashlib.sha256(Path(rec['path']).read_bytes()).hexdigest()==rec['sha256']
    return checks


CASE_NOTES={
 'T10':[
  '原候选只讨论 profile 到日志函数的数据传递。它没有关联到 CLI 测试。人工材料加入 CLI 测试、缓存测试和 JSON 格式化器，并保留 warm_cache 分支。',
  '原输入已有 main 与 manager 的完整代码，完整补丁也包含输出变更。因此，不能说模型完全没看到错误路径。三组首轮仍只否定 profile 日志关系。第二轮条件组转向 profile 内容是否影响缓存键，测试通过原补丁。候选表述补充组转向缓存命中后的输出，但没有组合 warm-cache。',
  '改进程序分析：识别传给断言辅助函数的可调用入口，例如 assertRaisesRegex(..., bandit.main)。然后建立提前退出对后续 output_results 的控制影响。把具体控制条件与输出联系起来，不能只把 main 内任意值传递当作相关候选。'],
 'T13':[
  '人工材料没有新增源码文件。它将 13 份文件收窄为 4 份，并减少同一隔离测试的历史版本。复制逻辑与单闭包验证原本就已进入自动请求。',
  '四组主对照都认为单闭包隔离测试已足够。仅改变候选问题后，模型明确提出两个不同闭包共享捕获变量。生成测试在转移后的写闭包执行后读取，得到 1 而非 2。',
  '改进候选表示：保留共享对象身份及复制前后的共享关系。结果已断言只能排除“完全未观察”，不能排除“共享结构发生变化”。此处需要改候选问题；增加源码检索不是首要修改。'],
 'T17':[
  '人工材料补入 vm.go、objects.go 和当前 destructuring_test.go。它把编译默认值、索引读取、缺失值转换和原测试放在同一范围。原候选主要是 emit 返回位置传给 changeOperand。',
  '人工材料组第二轮识别存在的 undefined，生成测试在原补丁失败、gold 通过。条件组提取了 70 项事实，但第二轮仍只测试普通值和缺失值；该测试通过原补丁。',
  '改进程序分析：沿默认值判断的输入反查来源，连接“查找是否成功”“返回的值”“默认值分支”。保留上游不同状态被转换为同一个值的情况。不要用分支数量替代这条联系。'],
 'T20':[
  '人工材料加入配置 YAML，并保留运行时转换及原测试。原自动源码列表没有 YAML，但原完整补丁已包含配置约束。条件组进一步提取 schema 路径与 pattern。',
  '主对照仍集中于 sourceIP 的默认 terminal 值。补充组改查 header regexRewrite 与 cookie 字段传递。补测都通过原补丁。它们没有让小数时长或重复配置先经过实际配置校验，因此两个参照目标仍未命中。',
  '改进程序分析：用序列化字段路径连接 schema 约束与运行时读取，例如 consistentHash.cookies.ttl。形成“同一输入先校验、后解析”的候选。分别列出正则和 ParseDuration 调用，仍不足以建立该组合。'],
 'T24':[
  '人工材料把大量通用 Zod 测试收窄到 item/map 解析器及 requiredIf 测试。条件组列出了调用方的默认 mode 和下游 mode 判断。',
  '原输入组与人工材料组都生成 savedAs 联合测试，并显式传 put，所以原补丁通过。条件组的说明仍讨论 savedAs，但代码省略 mode，测试在原补丁失败、gold 通过。反馈组读取失败后明确定位默认值没有传给下游，保留正确断言并去掉部分无关重命名。',
  '改进程序分析：连接上游默认化结果与下游实际读取的对象。为候选区分“省略选项”和“显式传默认值”。反馈的已观察作用是帮助定位失败原因；本例没有显示反馈新增了另一个错误检出任务。'],
 'T28':[
  '人工材料将 35 份文件缩至 5 份，并加入 queryObserver、createPersister 和 React 的 fine-grained persister 测试。原输入已有部分其他适配器测试，不能称其完全缺少框架代码。',
  '主对照都停在 defaultQueryOptions 到 fetch 的交接，认为核心恢复状态断言已覆盖后果。它们没有继续检查同一查询进入挂载和刷新阶段后的公开结果。',
  '改进程序分析：从恢复的状态写入追踪到同一 query key 的后续观察者操作。连接恢复、挂载、刷新与最终状态。普通向下调用展开不能完整恢复事件顺序；应在共享状态上补充消费者与回调关系。'],
}


def render(rows,extra,summary):
    p=['''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>六条任务诊断对照：材料、条件与执行反馈</title><style>body{font:16px/1.8 system-ui,sans-serif;max-width:1160px;margin:32px auto;padding:0 22px;color:#172c38;background:#fbfcfe}h1{font-size:27px}h2{font-size:22px;margin-top:32px}a{color:#08669e;overflow-wrap:anywhere}table{border-collapse:collapse;width:100%;background:white;font-size:14px}td,th{border:1px solid #d9e1e7;padding:10px;text-align:left;vertical-align:top}th{background:#edf3f8}.scroll{overflow:auto}.note{background:#e9f3fc;border-left:4px solid #3488b8;padding:14px}details{padding:14px;background:white;border:1px solid #d9e1e7;margin:12px 0}summary{font-weight:600}code{overflow-wrap:anywhere}.muted{color:#526575}li{margin:9px 0}</style>
<h1>六条任务诊断对照：材料、条件与执行反馈</h1>
<p class="muted">2026-10-08 · DeepSeek-v4-flash · 实际答复标识 deepseek-flash · 所有实验材料按授权发送到 .env 配置的 provider</p>
<p class="note">相关材料有帮助，但本轮没有观察到稳定的逐组提升。T17 受益于材料选择。T13 需要改变候选问题。T24 的执行反馈帮助模型从测试失败定位到默认模式错误。仅列出更多分支和状态表达式，仍没有解决 T10、T20、T28 的关键组合定位。</p>''']
    p.append('<h2>实验设置</h2><p>选择 T10、T13、T17、T20、T24、T28 六条原失败任务。评价使用此前确认的 7 个参照目标：T20 有两个目标，其余各一个。T24 的 anyOf 目标只作额外观察，不进入这次分母。gold 与 benchmark 信息仅用于离线评价。</p>')
    p.append(table(['组别','输入与流程'],[
      ['A：原自动输入','每条任务选一个与诊断范围相关的原候选。首轮 provider 请求与其原始请求逐字段相同。第二轮只做自查，不提供执行结果。'],
      ['B：人工材料','保留 A 的候选原因、关系、判断问题和系统提示。替换相关源码、原测试和历史步骤。第二轮仍不提供执行结果。'],
      ['C：增加程序条件','在 B 上加入程序提取的分支、默认值、状态赋值和 YAML 约束。其余输入不变。第二轮只做自查。'],
      ['D：加入执行反馈','共用 C 的首轮答复。第二轮提供该答复生成测试在原补丁上的结果。没有生成测试时，明确说明没有运行证据。']]))
    p.append('<p>每组每任务有两次调用预算。单次上限为 32768 个输出 token，temperature 为 0，reasoning_effort 为 high。C/D 共用首轮，主对照共实际调用 42 次。该共用设计使第二轮反馈比较从同一份测试开始。</p>')
    p.append('<p>C 首轮只在 T20、T24 生成测试。因此，D 只有这两条任务获得实际运行反馈。其余四条只有“没有生成测试”的状态说明。本轮不能据此判断执行反馈对那四个遗漏目标是否有效。</p>')
    p.append('<p>材料由本次 Codex 助手按前次诊断手选。程序随后在选定文件内选取最近 12 次相关命令及最后 3 次验证命令，并保留原反馈。条件提取也仅作用于手选区域。因此，B/C 是定位与表示能力的诊断，不是已经实现的自动算法成绩。没有独立人类审阅。</p>')
    p.append('<p>A 也不是重跑所有自动候选。六条任务的原完整运行共有 295 次调用，并命中 T24。当前 A 是每任务一个已选候选的匹配对照；其两次调用没有复现原 T24 命中。虽然请求字段相同，仍出现答复差异。本轮只有一次配对运行，不能据此估计稳定提升幅度。</p>')
    p.append('<h2>主对照结果</h2><p>“准确说明”要求答复中的原因或补测目标明确指出参照条件。“正确补测”要求测试包含必要条件，并用需求支持的断言揭示原补丁错误。说明可能没有准确定位原因，但测试仍可能触发错误。C 的 T24 就属于这种情况。</p>')
    p.append('<p>“准确说明”是本轮额外检查的解释质量，不替代前次按实际错误揭示评价的成功数。各组在两次预算内任一次成功即可计入；这里没有把首轮和次轮相同目标重复计数。</p>')
    p.append(table(['组别','准确说明目标的任务','正确补测揭示错误的任务','未准确报告的参照目标','没有最终答复的调用'],[
        [a,f'{summary["arms"][a]["explicit_trials"]}/6',f'{summary["arms"][a]["revealing_trials"]}/6',
         f'{summary["arms"][a]["unreported_reference_targets"]}/7',str(summary['arms'][a]['no_final_response_calls'])] for a in ['A','B','C','D']]))
    p.append('<p>未报告数量包含技术失败，不全是模型判无缺口。未命中参照目标也不自动构成误报。这里没有负例样本，不能估计任务级误报率；测试通过原补丁也不自动说明补测无效。</p>')
    def result_cell(cid,arm):
        rs=[r for r in rows if r['case']==cid and (r['arm']==arm or arm=='D' and r['arm']=='C' and r['round']==1)]
        explicit=any(r['explicit_target_ids'] for r in rs);gen=any(r['generated_target_ids'] for r in rs)
        if explicit and gen:return '准确说明；正确补测'
        if gen:return '说明未定位原因；测试命中'
        if any(r['raw_status']=='provider_error' for r in rs):return '未命中；一次调用未完成'
        return '未命中'
    p.append(table(['任务','参照目标','A','B','C','D'],[[cid,TITLES[cid],*[result_cell(cid,a) for a in ['A','B','C','D']]] for cid in CASES]))
    p.append('<p>T17-B 的检查在原补丁失败、gold 通过。T24-C 的两轮测试及 T24-D 的最终测试也完成同样的动态对照。T24 的 A/B 测试显式传 put，两版都通过。结果支持“没有激活错误条件”的判断。</p>')
    p.append('<h2>原自动输入与人工材料有什么不同</h2><p>下表给出发送文本的 UTF-8 字节数，使用十进制 KB。它不是 token 数。A/B 保留同一完整补丁和公开要求，因此新增局部文件不一定表示模型此前完全看不到相关代码。</p>')
    comps=read(RUN/'material_comparison.json')
    p.append(table(['任务','A → B 输入大小','文件数','显式相关测试数','手选材料的主要变化'],[
        [d['case'],f'{d["request_bytes"]["A"]/1000:.0f} → {d["request_bytes"]["B"]/1000:.0f} KB',
         f'{len(d["original_files"])} → {len(d["manual_regions"])}',f'{d["original_test_count"]} → {d["manual_test_count"]}',
         escape({'T10':'补入 CLI 测试与 JSON 输出；保留预热分支。','T13':'没有新增文件；收窄复制逻辑，减少历史版本。',
                 'T17':'补入索引读取、缺失值转换与当前解构测试。','T20':'补入 YAML 约束，与运行时转换放在一起。',
                 'T24':'聚焦 item/map、默认选项与 requiredIf。','T28':'补入观察者、持久化恢复与 React 挂载测试。'}[d['case']])] for d in comps]))
    p.append('<p>源码列表之外还有完整补丁和历史步骤。完整差异清单分别记录文件是否原本在源码列表、是否出现在补丁，以及手选片段能否在原请求内容中找到。'+link(RUN/'material_comparison.json','查看逐项材料差异')+'。</p>')
    p.append('<h2>补充检查：候选问题是否限制了模型</h2><p>主对照首轮显示，模型即使拿到相关材料，仍可能只回答原先狭窄的问题。因此增加一个单独的检查：保持 C 的全部材料和条件不变，仅把原特定关系假设改为“检查本区域的条件与最终行为是否被联合验证”。六条任务各调用一次，上限仍为 32768。此组记为 N，不混入四组主结果。</p>')
    n=summary['neutral_followup']
    p.append(f'<p>N 在固定预算内准确说明并正确补测 {n["revealing_trials"]}/6 条任务：T13、T24。T13 在原补丁执行失败，gold 的指针复制映射提供静态支持；按此前对新增辅助代码的要求，本项未运行 gold。T24 完成动态 gold 对照。T10、T20 的测试仍未触及参照目标。T17、T28 的调用耗尽输出额度，没有最终答复。</p>')
    p.append('<p>T13 是本轮最清楚的候选表示证据：C/N 的材料和程序事实相同。C 继续判断“Clone 结果已有断言”，N 则识别“两个不同闭包仍须共享同一捕获变量”。这支持优先修改候选问题。但一次对照尚不能给出平均收益或泛化结论。</p>')
    p.append('<h2>技术补跑与格式问题</h2><p>三次未完成请求单独用 65536 输出上限补跑。模型、输入文本及其他请求字段保持一致。此结果回答技术额度是否阻止输出，不能作为固定预算主对照的提升。</p>')
    extra_rows=[]
    for r in extra:
        text='无最终答复' if not r['decision'] else ('未命中' if not r['generated_target_ids'] else '正确目标；原补丁'+('失败' if r['candidate_status']=='fail' else str(r['candidate_status'] or '等待执行'))+'；gold '+('通过' if r['gold_status']=='pass' else '未运行'))
        extra_rows.append([r['case']+'-'+r['arm'],escape(text),link(Path(r['result']['path']),'补跑记录')])
    p.append(table(['调用','结果','依据'],extra_rows))
    p.append('<p>补跑后，T17-N 生成了存在的 undefined 测试，并在原补丁失败、gold 通过。T17-D 仍判无缺口。T28-N 仍把核心恢复断言视为充分验证，没有生成挂载后的检查。该补跑说明 T28 的问题不限于输出额度。</p>')
    p.append('<p>固定预算的 48 次调用中，有 5 份答复被原输出校验拒绝。提高上限补跑后另有 1 份同类问题。我们统一修正 JSON 末尾多余逗号，或移除无效的可选测试编号。我们保留全部测试代码字节。修正记录与原拒绝状态都已保存。只有 N-T10 因此恢复了可执行测试，其结果通过原补丁，没有改变参照命中数。</p>')
    p.append('<h2>逐项解释与程序分析修改</h2>')
    for cid in CASES:
        p.append(f'<details open id="{cid}"><summary>{cid}：{TITLES[cid]}</summary>')
        for label,note in zip(['材料差异','观察结果','算法修改'],CASE_NOTES[cid]):p.append(f'<p><b>{label}：</b>{escape(note)}</p>')
        p.append('<p>'+link(RUN/'cases'/cid/'conditions.json','程序提取条件')+' · '+link(RUN/'cases'/cid/'input_B.json','人工材料输入')+'</p></details>')
    p.append('<h2>下一版算法应先改什么</h2><ol><li><b>让候选表达条件对结果的影响。</b>用“输入或状态条件—相关操作—最终观察”组织候选。程序应连接提前退出、值转换、复制和后续消费者。不要把“某函数有结果”“某条边存在”直接变成缺口问题。</li><li><b>把原测试当作具体行为证据。</b>记录当前候选需要的输入状态、共享对象及操作顺序即可。辅助函数调用、回调参数和公开入口都可保留为潜在测试联系。已有一次成功断言不能排除其他条件。</li><li><b>用程序事实构建候选，不只把事实附在末尾。</b>保留缺失与取值、复制与共享、默认化与原选项、配置校验与后续解析之间的联系。当前语法事实列表仍缺少这些联系。</li><li><b>让反馈回到条件与原因。</b>T24 说明原补丁失败反馈能帮助定位原因。对通过测试，应继续检查条件是否实际触发。本轮 D 只提供执行结果，没有完整的分支与状态激活记录；下一步应补这一点。</li></ol>')
    p.append('<p>实现上应先修改 '+link(ROOT/'src/augmentation/search.py','候选构造')+'，再修改 '+link(ROOT/'src/augmentation/program.py','测试入口与消费者关系')+' 和 '+link(ROOT/'src/augmentation/history.py','验证历史连接')+'。本轮没有把这些建议写回原方法；已实现的是独立诊断脚本和程序条件提取原型。</p>')
    p.append('<h2>原样测试、运行结果与复核依据</h2><p>每一行是一份模型答复，可包含多个测试。D 首轮复用 C，不重复列出。检测命中与测试命中分别记录。代码文件与运行输出可从以下链接复核。</p>')
    def row_link(r):
        directory=Path(r['result']['path']).parent
        links=[link(directory/'completion.txt','原答复')] if (directory/'completion.txt').exists() else []
        if r['assessment']:links.append(link(Path(r['assessment']['path']),'测试与判断'))
        if r['execution']:links.append(link(Path(r['execution']['path']),'原补丁执行'))
        if r['pair']:links.append(link(Path(r['pair']['path']),'gold 对照'))
        return ' · '.join(links)
    p.append(table(['任务/组/轮','答复','准确说明目标','测试命中目标','原补丁 / gold','依据'],[
        [f'{r["case"]}/{r["arm"]}/{r["round"]}',escape(r['decision'] or r['raw_status']),
         escape(', '.join(r['explicit_target_ids']) or '—'),escape(', '.join(r['generated_target_ids']) or '—'),
         escape(str(r['candidate_status'] or '未运行')+' / '+str(r['gold_status'] or ('静态支持' if r['gold_static_support'] else '未运行'))),row_link(r)] for r in rows]))
    p.append('<p>'+ ' · '.join([link(RUN/'protocol.json','主对照设置'),link(RUN/'neutral_candidate_amendment.json','候选问题补充检查设置'),
         link(RUN/'review.json','逐答复复核'),link(RUN/'summary.json','统计数据'),link(RUN/'input_audit.json','输入与源码核验'),
         link(ROOT/'scripts/run_augmentation_diagnostic6.py','诊断与条件提取实现')])+'</p>')
    p.append('<p>这六条任务经过既有结果指导下的选择。结果只用于定位方法缺陷。这里没有估计独立测试集表现，没有测量修复后的 resolution rate，也没有声称某一修改已经获得稳定因果收益。</p></html>')
    REPORT.write_text('\n'.join(p)+'\n')


def main():
    rows=collect(RUN);extra=collect(RUN/'budget_recovery',True)
    assert len(rows)==48
    audit=validate();write(RUN/'input_audit.json',{'cases':audit,'subject_sources_unchanged':True})
    summary={'unique_fixed_budget_calls':len(rows),'primary_four_arm_calls':42,'neutral_followup_calls':6,
        'budget_recovery_calls':len(extra),'raw_status':dict(Counter(r['raw_status'] for r in rows)),
        'all_new_model_calls':len(rows)+len(extra),
        'transport_recovered':sum(r['transport_recovered'] for r in rows),
        'reference_tasks':6,'reference_targets':7,'arms':{a:group_metrics(rows,a) for a in ['A','B','C','D']},
        'neutral_followup':group_metrics(rows,'N'),
        'unique_test_proposals':sum(r['decision']=='gap' for r in rows),
        'budget_recovery_test_proposals':sum(r['decision']=='gap' for r in extra),
        'candidate_execution_status':dict(Counter(r['candidate_status'] for r in rows if r['decision']=='gap')),
        'no_new_reference_labels':True,'independent_human_review':False,'resolution_rate_measured':False,
        'counts_are_not_false_positive_rate':True}
    write(RUN/'review.json',{'reviewer':'Codex source/log inspection; no independent human review',
         'explicit_detection_rule':'reason/distinction must explicitly identify the reference trigger, not merely a broad feature',
         'generated_rule':'test must instantiate the missing condition and a public-contract-supported discriminating assertion',
         'main_and_neutral_rows':rows,'budget_recovery_rows':extra})
    write(RUN/'summary.json',summary)
    render(rows,extra,summary)
    ast.parse(Path(__file__).read_text())
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
