"""Explain saved pilot failures. Does not call models or execute subjects."""
from collections import Counter
from html import escape
from pathlib import Path
import ast
import hashlib
import json
import os


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'experiments/relation_distinction/results/pilot30_20261007_v1'
OUT = RUN / 'diagnosis_v5'
REPORT = ROOT / 'docs/augmentation_pilot30_diagnosis_20261008.html'


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def receipt(path):
    path = Path(path)
    return {'path': str(path.relative_to(ROOT)),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def link(path, label):
    return f'<a href="{escape(os.path.relpath(path, REPORT.parent), quote=True)}">{escape(label)}</a>'


def table(headers, rows):
    return '<div class="scroll"><table><tr>' + ''.join(f'<th>{escape(h)}</th>' for h in headers) + '</tr>' + ''.join(
        '<tr>' + ''.join(f'<td>{c}</td>' for c in row) + '</tr>' for row in rows) + '</table></div>'


def build():
    review = read(OUT / 'review.json')
    inventory = read(OUT / 'inventory.json')
    combined = read(RUN / 'benchmark_reverse_v4/combined_targets.json')
    original = read(RUN / 'summary.json')
    cases = {c['id']: c for c in original['cases']}
    inventories = {c['case']: c for c in inventory['cases']}
    positive_cases = sorted({t['case'] for t in combined['targets']})
    assert len(combined['targets']) == 23 and len(positive_cases) == 18
    assert {r['case'] for r in review['cases']} == set(positive_cases)

    evidence, all_decisions, model_status, positive_decisions = [], Counter(), Counter(), Counter()
    for case in cases:
        directory = RUN / f'cases/{case}'
        if (directory / 'generation_plan.json').exists():
            plan = read(directory / 'generation_plan.json')
            for rec in [plan['prepared'], *plan['source']]:
                assert hashlib.sha256(Path(rec['path']).read_bytes()).hexdigest() == rec['sha256']
            evidence.append(receipt(directory / 'generation_plan.json'))
        decisions = Counter()
        for path in sorted((directory / 'generation').glob('*/result.json')):
            model_status[read(path)['status']] += 1
            apath = path.with_name('assessment.json')
            if apath.exists():
                decisions[read(apath)['decision']] += 1
        all_decisions.update(decisions)
        if case in positive_cases:
            positive_decisions.update(decisions)
        inventories[case]['valid_model_decisions'] = dict(decisions)

    for r in review['cases']:
        cid = r['case']
        for candidate in r['evidence_candidates']:
            directory = RUN / f'cases/{cid}/generation/{candidate}'
            for filename in ['request.json', 'result.json', 'assessment.json']:
                path = directory / filename
                if path.exists():
                    evidence.append(receipt(path))
        evidence.append(receipt(RUN / f'cases/{cid}/extraction.json'))
    for path in [OUT / 'review.json', OUT / 'inventory.json', RUN / 'active_evaluation.json',
                 RUN / 'benchmark_reverse_v4/combined_targets.json', RUN / 'gold_comparison_v1/summary.json',
                 ROOT / 'src/augmentation/search.py', ROOT / 'src/augmentation/pipeline.py',
                 ROOT / 'src/augmentation/history.py', ROOT / 'src/augmentation/program.py',
                 ROOT / 'scripts/run_augmentation_pilot30_model.py']:
        evidence.append(receipt(path))
    summary = {
        'version': review['version'], 'reviewed_original_runs': 30,
        'reference_targets': 23, 'reference_positive_trials': 18,
        'reference_hit_targets': 1, 'reference_hit_trials': 1,
        'reference_missed_targets': 22, 'reference_trials_without_hit': 17,
        'original_all_model_calls': sum(c['model_calls'] for c in cases.values()),
        'original_all_decoded_decisions': dict(all_decisions),
        'original_model_status': dict(model_status),
        'reference_trials_model_calls': sum(cases[c]['model_calls'] for c in positive_cases),
        'reference_trials_test_proposals': sum(sum(cases[c]['native_status'].values()) for c in positive_cases),
        'reference_trials_decisions': dict(positive_decisions),
        'reference_trial_with_no_extraction': ['T01'],
        'reference_trials_only_no_gap_among_decoded_responses': [
            c for c in positive_cases if inventories[c]['valid_model_decisions']
            and set(inventories[c]['valid_model_decisions']) == {'no_gap'}],
        'other_confirmed_differential_trials': ['T04', 'T23'],
        'prior_environment_adjustment_trial': 'T11',
        'source_matches_original_generation': all(inventory['source_matches_recorded_generation'].values()),
        'new_model_calls': 0, 'new_subject_executions': 0,
        'causal_limit': review['classification_note'],
    }
    assert summary['original_all_model_calls'] == 1005
    assert all_decisions == {'gap': 337, 'no_gap': 570}
    assert summary['reference_trials_model_calls'] == 418
    assert summary['reference_trials_test_proposals'] == 162
    write(OUT / 'summary.json', summary)
    write(OUT / 'evidence.json', {'records': evidence, 'purpose': 'Source and saved-run evidence, not proof of causal attribution.'})
    render(review, summary, cases, inventories, combined)
    ast.parse(Path(__file__).read_text())
    write(OUT / 'verification.json', {
        'all_reference_targets_accounted_for': len(combined['targets']),
        'all_reference_positive_trials_accounted_for': len(review['cases']),
        'source_and_prepared_inputs_match_original_generation': True,
        'evidence_files': len({r['path'] for r in evidence}),
        'report': receipt(REPORT), 'new_subject_executions': 0, 'new_model_calls': 0,
    })
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def render(review, summary, cases, inventories, combined):
    p = ['''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>30 条任务 pilot：为什么漏检，以及如何改进</title>
<style>body{font:16px/1.8 system-ui,sans-serif;max-width:1160px;margin:36px auto;padding:0 22px;background:#fafbfd;color:#192832}h1{font-size:28px}h2{font-size:23px;margin-top:34px}a{color:#076098;overflow-wrap:anywhere}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;background:white;font-size:14px}td,th{border:1px solid #dce3e8;padding:10px;vertical-align:top;text-align:left}th{background:#eaf1f6}details{background:white;border:1px solid #dce3e8;padding:14px;margin:12px 0}summary{font-weight:600;cursor:pointer}.note{background:#e9f3fb;border-left:4px solid #3280af;padding:14px 18px}.muted{color:#52616b}p{max-width:1030px}li{margin:8px 0}code{overflow-wrap:anywhere}</style>
<h1>30 条任务 pilot：为什么漏检，以及如何改进</h1>
<p class="muted">2026-10-08 · 已保存候选、模型请求、答复和测试的逐项诊断 · 没有新模型调用或被测程序执行</p>
<p class="note">主要问题是候选的语义范围不准确。程序常找到函数之间的联系，却没有保留使最终结果不同的条件。模型随后用局部测试判定整个方向已验证，或生成没有触发错误条件的测试。原流程也没有用补测反馈修正下一步探索。</p>''']
    p.append('<h2>“只有 1 个任务成功”的范围</h2><p>这里的 1 个任务，是命中本轮 23 项参照目标的任务数。23 项分布在 18 条任务。T24 命中 1 项并生成有效补测，另外 22 项漏检；17 条任务没有命中任何参照目标。T24 的另一个 anyOf 目标也漏掉了。</p>')
    p.append('<p>这个数字不表示方法在全部 30 条任务中只发现一个错误。原样生成测试还在 T04、T23 发现其他真实错误；此前 T11 的环境对齐记录另有一项。这些发现不属于本轮参照目标，但不能算误报。</p>')
    p.append('<p>本报告检查全部 18 条参照任务的候选和模型输出，并逐项解释 22 个遗漏目标。其余 12 条任务没有进入该参照集合，不能一律判作漏检或真实负例。目标筛选及静态依据见' + link(ROOT / 'docs/augmentation_pilot30_reverse_20261008.html', '30 条任务的补丁差异报告') + '。</p>')
    p.append('<h2>本轮检查了什么</h2><p>我们读取原程序提取结果、实际发送的模型请求、答复、生成代码和已有执行记录。8 个原型源码文件与原调用计划的校验值全部一致。诊断对应实际运行版本。</p>')
    p.append('<p>原实验先用程序分析找出可能未被联合验证的调用、状态读写、条件及返回结果。每个候选触发一次模型调用。请求包含公开任务、原补丁、相关源码、测试和历史步骤。模型判断是否存在缺口，并在判断为有缺口时生成测试。程序随后在原补丁上尝试执行测试。gold 与 benchmark 失败信息仅用于事后评价。</p>')
    p.append('<p>原实验请求 DeepSeek-v4-flash。provider 返回的模型标识为 deepseek-flash，其模型目录名称为 DeepSeek-V4.1-Flash。本次只分析原记录，没有重新请求模型。</p>')
    p.append(table(['范围', '模型调用', '生成并执行的测试建议', '说明'], [
        ['全部 30 条任务', '1005', '337', '907 次答复通过输出校验：337 次提出补测，570 次判无缺口；其余为 76 次输出校验失败、22 次未完整返回或调用失败。'],
        ['18 条参照任务', '418', '162', 'T01 提取超时。其余 17 条进入模型阶段。'],
    ]))
    p.append('<p>一份测试建议可以包含多个测试。已保存的执行结果说明建议是否运行成功，不能单独证明检测了真实错误。298 份原建议通过原补丁，也不能据此全部判为误报。</p>')
    p.append('<p>“检测命中 1 项”和“补测命中 1 项”不是两个独立能力分数。原流程先检测，再为自身发现的目标生成测试。它没有逐项获得 23 个正确目标作为输入。因此，当前结果不能证明模型在明确获知其他目标后仍无法生成正确测试。T06、T17 等记录则能直接说明：即使方向接近，生成仍可能漏掉必要条件。</p>')
    p.append('<p>本轮依据记录定位了实际丢失的条件，并检查相应实现。我们没有做输入替换或模块消融。因此，各原因可以同时存在，不能把 22 项强行分配成互斥的因果百分比。分析由 Codex 完成，尚无独立人类复核。</p>')
    p.append('<h2>根本问题一：搜索目标仍偏向验证覆盖</h2><p>原方法寻找缺少的程序关系检查。原模型提示允许“补充一个原补丁能够通过的正确测试”。当前评价则要求测试暴露原补丁已有错误。两者的成功标准不同。</p>')
    p.append('<p>例如，T30 四份补测都围绕 gap 与 span。它们可以补齐验证，但没有检查真正出错的子网格宽度向父网格传播。继续生成同类通过测试，不会自动接近该错误。</p>')
    p.append('<p>应保留覆盖补强的价值，同时为错误检出设单独目标：根据公开要求和原补丁，提出一个可能违反要求的行为，再寻找能够区分该行为的组合。不能以强行制造失败作为目标。</p>')
    p.append('<h2>根本问题二：函数关系丢失了关键上下文</h2><p>当前候选主要表达调用、传递字段的差异、状态读写和返回值观察。函数联系存在，不能说明具体哪组输入、哪个对象、哪次调用会产生不同结果。</p>')
    p.append(table(['遗漏的信息', '记录中的表现', '相关目标'], [
        ['一次操作与再次操作的区别', '状态搜索要求不同函数。相同函数的多次调用、不同层级或不同配置没有充分表达。', 'T06 连续 include；T16 同一 Env 切换模式；T30 父子布局。'],
        ['控制流对末端观察的影响', '候选未保留提前退出跳过输出，以及成功前缀之后的异常终止。', 'T10 预热后 JSON；T08 关闭边界。'],
        ['值、存在性和对象身份的区别', '已有值相同，仍可能来自不同存在状态；复制后的多个闭包也可能需要共享一个捕获单元。', 'T17 undefined；T13 共享捕获；T12 导入绑定。'],
        ['声明约束与运行时代码的联系', '源码加载仅支持 Python、Go、TypeScript。配置约束没有进入程序关系图。', 'T20 小数 TTL、重复配置项。'],
        ['构造结果与后续执行的区别', '返回对象字段已被断言，就缺少继续追踪实际解析、挂载或输出的候选。', 'T22 递归执行；T28 挂载；T18 普通 String。'],
    ]))
    p.append('<p>代码中存在两个具体限制。条件筛选要求至少一个测试输入能静态求值；全部未知时不输出该条件。状态组合还跳过相同函数的读写组合。这会削弱配置间接传入、重复调用及阶段切换的表达能力。</p>')
    p.append('<p>' + link(ROOT / 'src/augmentation/search.py', '查看候选筛选与状态组合实现') + '。这些限制能解释候选表示的不足，但本轮没有删除限制后重跑，尚不能声称每个遗漏都由某一条限制单独造成。</p>')
    p.append('<p>T10 最能说明“数量不等于相关性”。229 个候选中，131 个检查多个缓存状态操作，93 个检查缓存读写，只有 4 个涉及 CLI main。模型的 229 份保存结果均未提出 warm-cache 与 JSON 输出的组合。</p>')
    p.append('<h2>根本问题三：模型把局部覆盖判断扩大了</h2><p>部分候选已经接近正确代码。模型拒绝“函数结果完全无人检查”这个过强假设，本身可能合理。但它没有继续判断原测试是否只覆盖了某一种输入状态。</p>')
    p.append(table(['任务', '模型用来判定已覆盖的证据', '证据没有覆盖的条件'], [
        ['T08', '普通带引号的边界已经送入解码器。', '引号内部同时含分号。'],
        ['T13', '一个闭包在源实例和副本中返回不同值。', '同一副本中的两个闭包仍共享捕获变量。'],
        ['T16', '开启和关闭类型模式分别有测试。', '两次执行使用同一 Env，旧约束仍然存在。'],
        ['T18', 'PreserveResets 后经过 Truncate 的输出正确。', '直接调用普通 String，不再经过 Truncate。'],
        ['T24 的 anyOf 目标', '普通 map 的条件更新与 savedAs 已测试。', '多个分支包含不同规则，只应作用于所选分支。'],
        ['T28', '恢复后核心缓存状态已检查。', '同一快照在框架挂载后仍保持错误状态。'],
    ]))
    p.append('<p>改进应限制“已覆盖”结论的作用范围。一次成功断言只能支持相应输入、状态和观察阶段。无需给每项测试建立复杂规范；保留与当前候选有关的条件即可。</p>')
    p.append('<p>程序没有把所有已有结构证据直接删除。它会把这些候选交给模型核查执行情况。T24 的成功候选就来自这条路径。因此，不能把漏检全部归因于程序提前过滤了已有测试。</p>')
    p.append('<h2>根本问题四：补测没有落实决定性的条件</h2><p>T06 和 T17 已出现接近目标的模型说明，但测试没有构造真正使原补丁出错的输入。检测和生成同时低分，不能据此认定两阶段是同一种失败。</p>')
    p.append(table(['任务', '生成代码实际做了什么', '缺少或绕过的条件'], [
        ['T06', '给不同层路由设置不同默认值。', '连续两次 include 显式传入不同覆盖值。'],
        ['T17', '比较存在的普通值与缺失值，并观察默认值副作用。', '键或位置存在，但值为 undefined。'],
        ['T27', '设置 filter:()=>true 后检查异步光标。', '默认过滤器再次处理异步结果的错误路径。'],
        ['T27 的旧选择目标', '异步结果正常到达后提交。', '已有选择后输入过短，再提交。'],
    ]))
    p.append('<p>生成后应核查测试是否到达目标分支、使用同一状态对象，并观察目标发生之后的结果。测试通过时，先区分“没有触发候选条件”和“条件已触发但实现正确”。原方法没有进行这个区分。</p>')
    p.append('<h2>根本问题五：trajectory 没有成为完整的验证记录</h2><p>当前历史检索按源码路径和函数名匹配。它把命中的步骤整体加入请求，没有稳定连接测试编写、实际执行、反馈和后续修改。纯 go test ./... 这类不含具体路径的命令可能被漏掉。</p>')
    p.append('<p>例如，T17 最后的 step_id=221 包含 go test ./...，但没有进入任何候选的历史步骤集合。这个事实说明检索存在遗漏，不能单独证明它导致了 undefined 目标漏检。</p>')
    p.append('<p>相反，大量资料已经进入请求。T28 的材料包含部分框架测试，T20 的完整补丁包含配置 schema。问题不是一律少给资料，而是没有围绕具体状态变化组织资料。</p>')
    p.append('<p>应为当前候选收集短的验证过程：原测试如何构造条件、如何观察结果、最后一次运行发生在哪次相关修改之后。程序负责连接记录；模型判断是否仍遗漏条件。不能从测试数量推断 agent 的动机或遗忘。</p>')
    p.append('<h2>根本问题六：补测结果没有指导下一轮</h2><p>原 runner 对每个候选只发起一次独立模型调用。它随后执行生成测试，但没有把执行结果传回模型，也没有根据结果更新其他候选的优先级。原型是一次生成与事后评价流程。</p>')
    p.append('<p>因此，相似候选可以重复生成同一个已正确实现的组合。T30 的四份 gap/span 补测，以及 T10 大量缓存状态补测，都没有推动搜索转向尚未解释的行为。</p>')
    p.append('<p>' + link(ROOT / 'scripts/run_augmentation_pilot30_model.py', '原生成流程') + '与' + link(ROOT / 'scripts/execute_augmentation_pilot30.py', '独立执行流程') + '提供该事实的直接依据。不能把“没有反馈迭代”进一步说成模型无法利用反馈；后者尚未实验。</p>')
    p.append('<h2>为什么 T24 能成功</h2><p>T24 的区别集中在相邻代码：调用方把省略 mode 解释为 put；下游检查却直接读取原 options。模型明确指出了两者不同，并注意到原测试只显式传 put。</p>')
    p.append('<p>随后生成测试省略 mode，让控制字段命中规则，并省略依赖字段。断言检查解析应拒绝该值。已有差分记录证明同一检查在原补丁失败、gold 通过。</p>')
    p.append('<p>该成功说明：当关键区别清楚、相关代码和测试集中、触发条件可直接构造时，当前模型能够完成检测与补测。它不能证明所有多关系问题都需要更强模型。</p>')
    p.append('<h2>改进后的核心算法</h2><p>建议把候选定义为“条件、短操作序列、末端观察”。程序关系用于连接这三个部分。模型只需说明哪项条件仍未验证，以及需求要求观察什么。</p>')
    p.append('<ol><li><b>程序定位行为范围。</b>从变更的判定、状态写入或转换出发，向前寻找输入来源，向后寻找公开观察。包含提前退出、异常和返回对象的后续执行。保留同一函数的多次调用与共享对象。先实现短序列，不扩成任意全程序搜索。</li><li><b>程序提取可能被混淆的状态。</b>利用代码里的默认化、字段存在检查、复制、筛选及边界条件，保留决定结果的输入区别。对已有测试，只记录它实际使用的相关条件。静态未知保留为未知。</li><li><b>模型判断缺失的行为区别。</b>输入公开需求、局部代码、原测试和相关验证过程。模型可以否定候选，但结论仅覆盖当前条件。输出一条短假设和测试，不要求额外生成复杂规则文档。</li><li><b>程序核查触发，模型按反馈补测。</b>运行时记录少量关键分支或读写事件，核对输入是否触发目标。若没有触发，只修改该输入条件。若触发且通过，将该假设记为已验证；若触发且失败，再核查预期。反馈可以指导一次后续尝试，不通过改写预期强行制造失败。</li></ol>')
    p.append('<p>单关系目标检查条件变化如何影响一个后续结果。多关系目标从同一对象或值继续扩展操作序列，直到结果可观察。两者使用同一表示。函数数量和测试数量不再决定组合阶数。</p>')
    p.append('<p>程序提供可操作的条件，模型负责解释需求。例如，程序能指出“存在性与取值分开”“省略值经过默认化”“两次操作共享状态”。它不需要为每个项目新增一套手写变异规则。</p>')
    p.append('<p>这是设计假设。学术贡献应围绕“结合程序关系与原验证上下文，构造能够区分潜在错误的测试”，并用对照证明效果。仅增加提示词、模型调用或候选种类，不足以证明该贡献。</p>')
    p.append('<h2>建议先做的诊断 pilot</h2><p>先用 T10、T13、T17、T20、T24、T28 六条任务。它们覆盖控制流、共享身份、存在性、声明约束、已成功案例和跨阶段状态。该组用于定位模块作用，不用于宣称对新任务的泛化。</p>')
    p.append(table(['对照', '只改变什么', '回答的问题'], [
        ['原自动流程', '保留原候选及输入。', '得到参照结果。'],
        ['相关材料对照', '人工选出相关公开代码、原验证与历史步骤；不提供 gold 或 benchmark 测试。', '自动定位是否是主要瓶颈。'],
        ['条件表达对照', '在相关材料上加入从原源码提取的关键状态与操作顺序。', '模型是否需要更具体的条件指导。'],
        ['执行反馈对照', '加入关键条件是否触发及断言结果；给相同预算的后续尝试。', '反馈能否修正未触发或观察过早的测试。'],
    ]))
    p.append('<p>每组使用相同模型、调用预算和执行环境。分别报告目标检测、条件实际触发、测试可执行、原补丁错误检出及错误断言数。人工选材可以利用本次诊断来定位材料，因此只是能力上限与模块诊断，不能当作自动方法的成绩。</p>')
    p.append('<p>gold 与 benchmark 只用于离线复核。若人工选材仍不能检出，应改进模型的条件推理或预期判断；若人工选材有效而自动流程无效，应优先改程序定位；若目标正确但条件未触发，应改生成与执行反馈。</p>')
    p.append('<h2>18 条任务的逐项原因与改动</h2><p>下文的短编号标识一份已保存的模型答复。每条任务末尾提供对应依据和测试代码。一份建议可以包含多个测试；执行失败也不直接等于发现真实错误。</p>')
    for r in review['cases']:
        cid = r['case']
        targets = [t for t in combined['targets'] if t['case'] == cid]
        p.append(f'<details open id="{cid}"><summary>{cid} · {escape(r["title"])}</summary>')
        p.append(f'<p class="muted">{escape(cases[cid]["task"])}</p>')
        p.append('<p><b>本轮目标：</b>' + '；'.join(escape(t['description']) + ('（已命中）' if t['method_detected'] else '（漏检）') for t in targets) + '</p>')
        d = inventories[cid]['valid_model_decisions']
        execution = cases[cid]['native_status']
        execution_text = '，'.join(f'{name} {execution.get(key, 0)} 份' for key, name in [('pass', '运行通过'), ('fail', '运行失败'), ('error', '无可用结果')])
        p.append(f'<p><b>原方法结果：</b>{cases[cid]["model_calls"]} 次调用；有效答复中 {d.get("gap", 0)} 次提出补测，{d.get("no_gap", 0)} 次判无缺口。测试建议的执行情况：{execution_text}。</p>')
        for key, name in [('observed_mechanism','原因'),('concrete_evidence','直接依据'),('proposed_change','改进'),('uncertainty','判断边界')]:
            p.append(f'<p><b>{name}：</b>{escape(r[key])}</p>')
        links = [link(RUN / f'cases/{cid}/extraction.json', '提取结果')]
        if (RUN / f'cases/{cid}/prepared.json').exists():
            links.append(link(RUN / f'cases/{cid}/prepared.json', '原候选及材料'))
        for index, candidate in enumerate(r['evidence_candidates'], 1):
            directory = RUN / f'cases/{cid}/generation/{candidate}'
            file = directory / 'assessment.json'
            if not file.exists(): file = directory / 'result.json'
            links.append(link(file, f'说明与测试 {index}'))
        p.append('<p>' + ' · '.join(links) + '</p></details>')
    p.append('<h2>可复核材料</h2><p>' + ' · '.join([
        link(OUT / 'review.json', '逐项诊断'), link(OUT / 'inventory.json', '原候选与输出清单'),
        link(OUT / 'summary.json', '范围及统计'), link(OUT / 'evidence.json', '证据文件校验值'),
        link(OUT / 'verification.json', '完整性检查')]) + '</p>')
    p.append('<p>本报告没有修改方法源码、原标签或实验结果。建议尚未实现和验证。这里不报告 resolution rate 提升，也不把未命中参照目标自动计为误报。</p></html>')
    REPORT.write_text('\n'.join(p) + '\n')


if __name__ == '__main__':
    build()
