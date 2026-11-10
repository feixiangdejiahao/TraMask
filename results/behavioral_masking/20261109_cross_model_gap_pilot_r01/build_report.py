"""Assemble the manually reviewed, bounded cross-model case study."""
import collections
import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parent
selection = json.loads((ROOT / 'selection.json').read_text())
baseline = json.loads((ROOT / 'baseline_compare.json').read_text())
cohort = json.loads(Path(selection['source_cohort']).read_text())['cases']
cohort_by_task = {c['task']: c for c in cohort}
downloads = json.loads((ROOT / 'download_manifest.json').read_text())
TASK_COMMIT = '0b9fabbb63b9104d678fe965e1632f2dd9eaa2ea'

# The order and members were frozen in selection.json before manual inspection.
NOTES = {
 'abs-stepped-slices__TAfgXAm': {
  'classification': 'earlier_failing_witness_removed',
  'classification_zh': '已执行失败场景，随后重写测试时丢失该例；不是从未联合执行',
  'strict_unexecuted_combination_supported': False,
  'final_commit_prefix': '915d3ff',
  'target_behavior': 's="abc"; s[-1]="Z" 应得到 abZ；本次最终 patch 报 index out of range: -1。',
  'agent_validation': 'step 45 已运行 s="hello"; s[-1]="O"，日志明确出现负索引错误。该测试当时的 expected="hello" 本身也不符合 held-out 的尾字符替换约定。step 47 删除三组新增 evaluator 测试；step 48 为修正 Unicode 编码重新写入测试时省掉负索引赋值。step 49 和 step 80 的其余 evaluator/parser/AST 测试通过。',
  'chronology': ['step 45: 新测试已经到达负索引字符串赋值，并观察到错误。', 'steps 47-48: 为处理 mojibake 删除后重建测试块，负索引赋值未被重建。', 'step 77: 全测试仍有 util.TestUpdateAvailable 失败，不能说全仓测试全绿；step 80 专项测试通过。', 'step 79 commit 915d3ff；step 80 在该提交后验证，step 81 提交完成。'],
  'missing_joint_conditions': [],
  'oracle_or_history_gap': '现有执行历史已包含失败刺激，最终验证集合没有保留它；需要从历史取回该刺激并明确正确输出关系。',
  'contract_caveat': 'issue 明确字符串支持单索引写入，但未逐字规定负单索引写入的归一化；要求保留已有 single-index 行为。将负索引写入视为正确尾字符替换，是 held-out 的具体契约，不把这条据为纯组合缺失证据。',
  'evidence_steps': [25, 27, 45, 47, 48, 49, 77, 79, 80, 81],
  'comparison': '与 DeepSeek S001 是同一具名失败和相同最终错误。DeepSeek 的旧复核也记录负索引写入被执行；本次 GLM 的具体历史路径是失败例在测试重写中消失，不能推断是遗忘。',
 },
 'abs-stepped-slices__EJT9ZBd': {
  'classification': 'joint_executed_oracle_incompatible',
  'classification_zh': '联合执行已覆盖，但自建 oracle 接受与 held-out 相反的行为',
  'strict_unexecuted_combination_supported': False,
  'final_commit_prefix': '390fdbc',
  'target_behavior': '负单索引 × 字符串赋值 × 一字符替换：held-out 要求 abZ，最终 patch 报 index out of range: -1。',
  'agent_validation': 'step 51 添加 TestStringAssignment，其中 s="hello"; s[-1]="y"; s 的 expected 明确是 "index out of range: -1"。step 74 运行此测试并 PASS，最终 model.patch 保留此错误预期。',
  'chronology': ['step 51: 将负单索引赋值错误写成预期输出。', 'steps 52-53: 修订另外两个切片测试的预期，不涉及该负索引条目。', 'step 74: TestStringAssignment 与切片测试一起通过。', 'step 76 commit 390fdbc；step 81 再跑回归；step 82 声称所有要求已验证。'],
  'missing_joint_conditions': [],
  'oracle_or_history_gap': '刺激已经联合并被执行；缺的是将负索引正确对应到最后一个 rune 的结果 oracle。',
  'contract_caveat': '同 GLM abs 案，负单索引写入的预期是 held-out 的具体语义，issue 对此并非显式示例。将其保留为 oracle/契约解释案例，不算未执行组合正例。',
  'evidence_steps': [33, 39, 51, 52, 53, 74, 76, 81, 82],
  'comparison': '与 DeepSeek S001 同名失败、同错误；两者均有已经执行目标刺激但接受错误结果的证据。与配对 GLM 相比，Qwen 最终测试仍保留明确错误的 expected。',
 },
 'arktype-json-schema-refs-depende__ZpEqkDe': {
  'classification': 'specific_nested_fixture_missing',
  'classification_zh': '广义递归与 anyOf 已联合覆盖，缺的是递归边内部的 nullable union 形状',
  'strict_unexecuted_combination_supported': False,
  'fine_grained_missing_joint_fixture_supported': True,
  'final_commit_prefix': 'f8123116',
  'target_behavior': 'Node.next=anyOf[$ref(Node),null] 的递归链，以及 Tree.children.items=anyOf[$ref(Tree),null] 再联合 Meta 引用；最终两个具名测试均栈溢出。',
  'agent_validation': 'step 74 的 ref.test.ts 包含递归 object.next=$ref、递归 def 自身是 anyOf[primitive,object(children array of ref)]、相互递归等测试。step 133 还在已提交实现上执行 root anyOf[$ref(recursiveNode),string]。step 135 82 个 JSON Schema 测试通过。不能说 recursion×anyOf 从未联合。',
  'chronology': ['steps 60/67: 探索递归及 anyOf，曾遇执行/导入问题并修复。', 'step 74: 添加真实断言的递归及 anyOf 测试。', 'step 116: 另行探查递归 ref 在组合中的情况。', 'step 128: 1731 个全仓测试通过；step 132 commit f8123116。', 'steps 133/135: 提交后补做 root anyOf + recursiveNode 实验，82 包测试再通过；未发现 nullable union 在递归 property/item 位置的完整 witness。'],
  'missing_joint_conditions': ['递归 $ref 直接作为 next property 的 anyOf 分支，并以 null 终止，而不是把整个 def 定义为 anyOf。', '更深测试还组合 children array 的 items nullable recursive union 与独立 Meta property $ref。'],
  'oracle_or_history_gap': '已有广义联合及显式 true/false oracle；缺少上述位置敏感的具体结构。仅在该细粒度下称为组合 fixture 缺口。',
  'contract_caveat': 'issue 明说递归 $ref inside anyOf，但 agent 的验证已覆盖其若干形状。测试名中 "dependent $ref" 是 suite 前缀，不能据此前缀声称失败一定由 dependentSchemas 触发。',
  'evidence_steps': [60, 67, 74, 83, 99, 116, 128, 132, 133, 135, 137],
  'comparison': '与 DeepSeek S004/S005 共享 deep recursive $defs 测试；GLM 还在较浅的 nullable linked-list 测试失败。DeepSeek S004 是 false!==true、S005 是解析错误，本次 GLM 是 RangeError，不能宣称实现内部机制完全相同。',
 },
 'arktype-json-schema-refs-depende__ARyinMQ': {
  'classification': 'specific_nested_fixture_missing',
  'classification_zh': '广义递归与 anyOf 已联合覆盖，缺的是递归边内部的 nullable union 形状',
  'strict_unexecuted_combination_supported': False,
  'fine_grained_missing_joint_fixture_supported': True,
  'final_commit_prefix': 'cf529f0d',
  'target_behavior': '与配对 GLM 相同的 nullable recursive property/item 布局；两个 held-out 正例均 false!==true。',
  'agent_validation': 'step 79 运行递归 expr def 内 anyOf[number,object(left/ref,right/ref)]。steps 84-98 对递归、anyOf、数组、additionalProperties 做过真正调试，修复 append 展开 array 和 seen-guard 问题。step 115 正式 tests 包含 recursive $ref in anyOf，且含 null 分支的 JSON-value union。77 个包测试和 1726 全仓测试通过。广义联合已存在。',
  'chronology': ['steps 84-98: 主动针对 issue 的 anyOf+recursion 提示做实验；先发现错误再修源代码，并补 boolean/null 分支。', 'step 115: 添加带 true/false 断言的 recursive union 测试。', 'step 119: 修正 conditional 测试中错误的 else 预期，不是删除本次 nullable recursive witness。', 'steps 125-145: 继续测试 refs 的组合，修 seen guard 的重复访问问题。', 'step 160: 77 包测试通过并 commit cf529f0d；step 161 1726 全仓测试再次通过。'],
  'missing_joint_conditions': ['recursive $ref 直接位于 object.next 的 anyOf[$ref,null] 或 children.items 的 anyOf[$ref,null]；已有 JSON union 的结构方向不同。'],
  'oracle_or_history_gap': '精确递归边位置的 fixture 未出现；已存在广义联合执行和正确的 true/false oracle，不能把该例算作完全不测 recursion×anyOf。',
  'contract_caveat': '未重跑原仓库，不从历史日志推断内部引擎根因；这里只确立最终 acceptance failure 与 fixture 位置差异。',
  'evidence_steps': [79, 84, 87, 94, 96, 97, 98, 115, 119, 125, 144, 145, 160, 161, 162],
  'comparison': '与 DeepSeek S004 在 deep recursive 正例有相同 false!==true 表象；Qwen 还在较浅 nullable linked-list 失败。S005 是 parse-time 错误，与本次 acceptance failure 不同。',
 },
 'awilix-async-container-initializ__AAMdX4D': {
  'classification': 'joint_executed_oracle_incompatible',
  'classification_zh': '已联合执行 child-first 场景，但把父 singleton 的额外初始化当作正确',
  'strict_unexecuted_combination_supported': False,
  'final_commit_prefix': '211f343',
  'target_behavior': 'parent 未 initialize、child 有无依赖的 scoped 注册时，仅执行 child initializer；held-out 预期 [scoped]，得到 [parentSingleton,scoped]。',
  'agent_validation': 'step 20 的独立 scope 测试先 initialize parent，因此单独不能揭示问题。step 45 进一步 child-first，但 child 依赖 db。关键 step 82 添加 makes singletons initialized by a scope visible to the root：parent 尚未初始化、child 不声明依赖，却断言 scope.initialize 后 parent singleton 已 initialized=true。完整目标上下文并未缺席，测试预期与 held-out 的独立 scope 契约相反。',
  'chronology': ['step 20: parent-first scope 测试。', 'step 45: child-first 且依赖 parent db 的测试。', 'step 82: 无依赖的 child-first/未初始化 parent 场景，明确接受额外初始化。', 'step 97: 最终修改只确保 active run 注销，29 feature tests 通过。', 'steps 99-101: 全测试 187 tests 通过但 1 suite failed/15 passed；agent 归因 build artifact。最终 commit 211f343，工作树 clean。'],
  'missing_joint_conditions': [],
  'oracle_or_history_gap': '需要校正 scope 独立性的 expected side effect；仅重组既有刺激或提醒模型记住已测场景不够。',
  'contract_caveat': 'issue 说 scoped independently、parent singletons not reinitialized；agent 将从未初始化的 inherited singleton 首次初始化视为允许。以 held-out 解释为准时是错误 oracle，同时保留这种契约解读差异。',
  'evidence_steps': [20, 45, 82, 93, 94, 96, 97, 99, 100, 101, 102],
  'comparison': 'DeepSeek S006 唯一失败是默认 concurrency 导致两个独立服务串行；本次 GLM 是 scope/parent ownership。虽然同 task，失败条件不同，不作为同一机制复现。',
 },
 'awilix-async-container-initializ__7okkvQL': {
  'classification': 'joint_executed_oracle_incompatible',
  'classification_zh': '已联合执行 child-first 场景，但测试明确要求父 singleton 一起初始化',
  'strict_unexecuted_combination_supported': False,
  'final_commit_prefix': '3fbf177',
  'target_behavior': '与配对 GLM 同一 held-out scope-first failure：额外执行 parentSingleton。',
  'agent_validation': 'step 35 写入 initializes inherited parent registrations when the parent is not initialized。root 注册 database、child 注册不依赖 database 的 logger；scope.initialize 后断言 dbInitCount==1 且 metrics 为 [database,logger]，再测 parent.initialize 不重跑。step 74 全 199 tests 通过，最终 patch 保留该测试。',
  'chronology': ['step 35: 将 parent 未初始化时 scope 初始化 inherited 注册作为正当行为写入测试。', 'steps 37-38: 修正另一项依赖图测试的参数命名。', 'steps 50-52: 修订另一项 undeclared dependency 测试，未改变上述 parent 初始化预期。', 'step 70: build + 199 tests 通过。', 'step 73 commit 3fbf177；step 74 对已提交状态再测 199 tests 通过。'],
  'missing_joint_conditions': [],
  'oracle_or_history_gap': '刺激覆盖完整；本地 oracle 所采用的 inherited singleton 策略与 held-out 的 scope-independent 策略不符。',
  'contract_caveat': '同 GLM awilix，保留 issue 的 parent singletons not reinitialized 与首次初始化之间的解释空间；不能称其从未考虑这个组合。',
  'evidence_steps': [35, 37, 38, 50, 51, 52, 65, 67, 70, 73, 74, 75],
  'comparison': '与配对 GLM 是相同 failure/oracle disagreement；与 DeepSeek S006 的 default-concurrency failure 不同。',
 },
 'bandit-incremental-cache-control__fwSsPW7': {
  'classification': 'joint_scenario_not_executed',
  'classification_zh': '未测 scan formatter 生命周期 × cache-stats 的联合调用',
  'strict_unexecuted_combination_supported': True,
  'final_commit_prefix': 'a8b314f',
  'target_behavior': '已有缓存时执行 --cache-stats --cache-dir DIR issue.py；默认 screen formatter 扫描并输出后关闭 stdout，后续 _report_cache print(stats) 崩溃。',
  'agent_validation': 'step 29 单独调用 --cache-stats，无 positional target。step 43 的真实 subprocess test_cache_stats 先 incremental scan，再单独无 target stats，并 json.loads+assert cache_file_size_bytes。step 86 的最终要求核查也只无 target stats。正常扫描独立经过 screen/text/json 验证；未找到 stats 与扫描同一次 CLI 进程执行。',
  'chronology': ['step 29: 手工维护模式 stats 成功。', 'step 43: 添加 subprocess 断言，但 stats 仍是独立无 target 进程。', 'step 86: 最终核查仍将 scan 与 stats 拆开。', 'step 98: 344 pytest tests 通过；step 100 commit a8b314f。', 'steps 103-104: stestr 新测试 28/28、全套 343 passed；最终未补带 target stats。'],
  'missing_joint_conditions': ['同一进程先用默认 screen formatter 扫描一个实际 target。', '在该 formatter 已完成/关闭输出后，再执行 cache stats 的 print；standalone maintenance 不经过此前置生命周期。'],
  'oracle_or_history_gap': 'stats schema 与数值 oracle 已存在且有效，但输入上下文没有把它置于 scanner/formatter 之后。',
  'contract_caveat': '这里依据原 held-out 的实际带 target 调用，不声称所有 formatter 都触发；JSON 单独 stats 成功不等于默认 screen 与 stats 联合成功。',
  'evidence_steps': [24, 27, 29, 30, 43, 50, 81, 86, 98, 100, 103, 104, 105, 106],
  'comparison': 'DeepSeek S007 的失败是 warm-cache + JSON 得到空 stdout；本次 GLM 已能 warm-cache 输出 results=[]，失败在另一种 formatter 生命周期与 stats 组合。不能把同 task 归成同一病因。',
 },
 'bandit-incremental-cache-control__NJPeLmy': {
  'classification': 'joint_scenario_not_executed',
  'classification_zh': 'summary 无 target 与 warm-cache 请求 JSON 的两种联合模式未验证',
  'strict_unexecuted_combination_supported': True,
  'final_commit_prefix': 'b563930',
  'target_behavior': '--cache-summary --cache-dir DIR 不带 target 应 exit0 并输出文件数；--warm-cache -f json issue.py 应输出可解析 JSON 且 results=[]。最终前者 usage/exit2，后者 stdout 为空。',
  'agent_validation': 'steps 36-43 真的发现并修复过带 target summary 的 stdout-closed 问题，后续 summary 验证总带 target。step 44 的 R10 用 -r src ... --cache-summary -f txt。R16 对 warm-cache 不带 -f json，直接把 stdout 为空当验收；后续普通 incremental 另起进程验证 JSON hits。step 93 30 checks PASS，仍沿用同一刺激。',
  'chronology': ['steps 36-43: 针对有 target summary 观察异常、迭代修 stdout，具有主动调试证据。', 'step 44: R10 summary 总带 src；R16 warm-cache 要求空 stdout；R22 stats 无 target。', 'steps 55-58: 为避免测试 capture 被 formatter 关闭，自建 scan tests 改用 -o，这会避开 stdout 路径。', 'step 88: 更正 corrupted-cache 测试的 exit code oracle；未修 summary 无 target 或 warm-cache JSON。', 'steps 91-93: 317 tests 通过，commit b563930，30/30 自检通过。'],
  'missing_joint_conditions': ['cache-summary maintenance flag × 不提供 positional scan targets。', 'warm-cache mode × JSON formatter（同一次调用），保留格式外壳并令 results=[]。'],
  'oracle_or_history_gap': 'summary 的计数 oracle 和普通 scan 的 JSON decode/results oracle 已有；最终未置于相应 mode。warm-cache 的本地验收把无格式参数时空 stdout 当 empty results，不能据此断定显式请求 JSON 的约定也已验证。',
  'contract_caveat': 'issue 对 summary 仅要求打印计数，未显式举无 target 例；held-out 将其视为维护命令。warm-cache 与 -f json 的输出契约来自 existing formatter 语义及 held-out。故同时记录契约解释因素，不归因模型能力。',
  'evidence_steps': [26, 27, 36, 38, 39, 40, 41, 43, 44, 55, 58, 83, 88, 91, 92, 93, 94, 95],
  'comparison': 'warm-cache JSON 与 DeepSeek S007 是同一具名失败、同样空 stdout。但 DeepSeek 旧证据显示自己真的以 -f json 执行并 expected bytes empty，属于 oracle 错误；本次 Qwen 没发现显式 -f json 联合，属于输入组合缺口。summary 另两条失败在 S007 不存在。',
 },
 'bandit-structured-nosec-directiv__AYrR8Wh': {
  'classification': 'specific_layout_missing_with_joint_coverage',
  'classification_zh': 'region×multiline 已覆盖，inline begin 落在语句尾部的特定布局未覆盖',
  'strict_unexecuted_combination_supported': False,
  'fine_grained_missing_joint_fixture_supported': True,
  'final_commit_prefix': '2828009',
  'target_behavior': 'multiline Popen 的 shell=True 参数行附 nosec-begin B602；下一物理行只有 )，其后显式 nosec-end。held-out 要求整条 statement 被抑制，最终仍报告 B602。',
  'agent_validation': 'step 21 已运行 region 在 statement 之前开始、nosec-end 位于 statement 内部的 multiline 场景，也运行 next-line multiline。step 26 测试单行 Popen 尾部 inline begin，与 inline nosec 合并。step 30 添加 statement-wide 单元测试；steps 31-36 调试 unit helper，35 test_nosec tests 通过。缺的是 inline begin × 多行语句尾部仅余 closing paren 的交叉布局。',
  'chronology': ['step 21: 真正执行 multiline + region/end-inside，并展示下一独立语句仍被报告。', 'step 26: 执行 inline begin 但其 Popen 单行已结束。', 'steps 30-36: 修测试 helper 的 comments 提取并验证 whole-statement；没有删除本次 held-out exact layout 的证据。', 'step 68: 315 tests passed/0 failed；step 69 commit 2828009。', 'steps 70-75: 继续验证相邻 next-lines、compound statements、stdin；final message 明述 statement extents 与合并语义。'],
  'missing_joint_conditions': ['begin directive 出现在已开始的 multiline statement 最后参数行。', 'begin 下一行仅有 grouping close )，显式 end 再下一行；需要把该后续物理行的抑制关联回完整 statement。'],
  'oracle_or_history_gap': '已有 region 和 statement-wide 的组合测试以及 inline begin 的非 retroactive 检查；只在上述位置/次序粒度下缺完整 witness。不存在完全没考虑 statement-wide 的证据。',
  'contract_caveat': 'Verifier 在此有 issue 支持：自动 dedent 结束的条件是 region 未被 explicitly ended；058 后面有匹配 end，因此 closing-only 的下一物理行仍应由 region 覆盖，再经 statement-wide 规则抑制整条调用。最终 nosec.py 在看到更小缩进时无条件过滤 region，没有判断后续显式匹配 end。该根因是源码推断，未新重放。',
  'evidence_steps': [13, 17, 21, 26, 30, 31, 32, 33, 35, 36, 68, 69, 70, 72, 75, 77],
  'comparison': '与 DeepSeek S009/S010/S011 同一唯一具名 p2p058 failure，所有69个f2p通过；S008另有 selector metrics failures。本次充分的 statement-wide 验证反驳“模型完全没想到这个概念”，但精确 inline-begin closing-only 布局仍缺。',
 },
 'bandit-structured-nosec-directiv__9pg3LbC': {
  'classification': 'specific_layout_missing_with_joint_coverage',
  'classification_zh': 'region×multiline 已覆盖，inline begin 落在语句尾部的特定布局未覆盖',
  'strict_unexecuted_combination_supported': False,
  'fine_grained_missing_joint_fixture_supported': True,
  'final_commit_prefix': 'b8527a8',
  'target_behavior': '与配对 GLM 同一 p2p058 closing-only layout failure。',
  'agent_validation': 'steps 35/38 自检包含 multiline statement suppressed despite end inside it、inline begin on one-line statement。steps 45/48/51 做了 tabs/CRLF/encoding、inline begin+dedent、nested begin/end、next-line compound 等真实实例。steps 66-69 又修复 multiline string/f-string token 深度。step 80 自建 assertions 全过，原275 tests通过。没有找到目标的 late-inline-begin multiline close-only 完整 witness。',
  'chronology': ['steps 35-44: 修正自检 leading newline、invalid semicolon、metrics/profile 预期与少量实现，最终自检通过。', 'step 48: 明确测试 trailing-comment begin，但代码是单行 x=1 后另一个 statement。', 'step 51: 继续实测 multiline/compound 边界。', 'steps 66-69: 识别并修 multiline string/f-string 对 dedent 的影响，显示规则并未单纯遗忘。', 'step 80: ALL TESTS PASSED，275 unittest tests 通过；steps 82-83 commit b8527a8 后再通过。'],
  'missing_joint_conditions': ['inline begin 要与已经进行中的 multiline call 组合，且下一行只含 closing grouping token。'],
  'oracle_or_history_gap': '覆盖很多相关交互、存在正常断言；仍缺 precise placement/termination fixture。不能从最终失败反推所有相关测试都没写，亦不能证明是检索/记忆遗忘导致。',
  'contract_caveat': 'Verifier 的具体布局有 issue 支持：dedent 自动结束仅适用于未被 explicitly ended 的 region；058 后续有匹配 end。最终 manager.py 的 region_stack 在较小缩进 line_start_tokens 行无条件 pop，没有保留将被显式 end 配对的 region。该根因是源码推断，未新重放。正例仅指具体布局缺口，广义 region×multiline 验证已存在。',
  'evidence_steps': [25, 26, 35, 38, 43, 45, 48, 49, 51, 66, 67, 68, 69, 70, 76, 80, 82, 83, 84],
  'comparison': '与 DeepSeek S009/S010/S011 和配对 GLM 是相同具名058失败/同一具体布局。相关交互的测试非常多，不能由共同失败断言三个模型均没有 statement-wide 推理。',
 },
}


def receipt(path):
    body = path.read_bytes()
    return {'path': str(path), 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()}


cases = []
for case_number, row in enumerate(selection['selected'], 1):
    trial = row['trial_name']
    directory = ROOT / 'trials' / trial
    trajectory = json.loads((directory / 'trajectory.json').read_text())
    ctrf = json.loads((directory / 'ctrf.json').read_text())
    reward = json.loads((directory / 'reward.json').read_text())
    commands = [json.loads(line) for line in (directory / 'commands.jsonl').read_text().splitlines()]
    note = NOTES[trial]
    original = cohort_by_task[row['task_name']]
    task_root = Path(original['task_directory'])
    task_capture = ROOT / 'tasks' / row['task_name']
    task_capture.mkdir(parents=True, exist_ok=True)
    for relative in ['instruction.md', 'task.toml', 'tests/test.patch', 'tests/config.json', 'tests/test.sh', 'tests/grader.py']:
        destination = task_capture / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(task_root / relative, destination)
    issue = (task_capture / 'instruction.md').read_text()
    prompt = trajectory['steps'][1]['message']
    all_observed = '\n'.join(c['output'] for c in commands)
    failed = [test for test in ctrf['results']['tests'] if test['status'] == 'failed']
    assert row['outcome'] == 'fail' and row['reward'] == 0 and reward['reward'] == 0
    assert failed
    assert issue.strip() in prompt
    assert original['base_commit'][:7] in all_observed
    assert note['final_commit_prefix'] in all_observed
    selected_evidence = [c for c in commands if c['step_id'] in note['evidence_steps']]
    (directory / 'reviewed_evidence.json').write_text(json.dumps(selected_evidence, ensure_ascii=False, indent=2) + '\n')
    all_messages = [{'trajectory_step_index':i, 'step_id':step['step_id'], 'message':step['message']}
                    for i, step in enumerate(trajectory['steps']) if step['source'] == 'agent' and step['message']]
    (directory / 'reviewed_agent_messages.json').write_text(json.dumps(all_messages, ensure_ascii=False, indent=2) + '\n')
    truncated = []
    for i, step in enumerate(trajectory['steps']):
        for j, observation in enumerate(step.get('observation', {}).get('results', [])):
            data = json.loads(observation['content'])
            if 'output_head' in data:
                truncated.append({'trajectory_step_index':i, 'step_id':step['step_id'], 'call_index':j,
                                  'elided_chars':data['elided_chars']})
    task_baselines = [b for b in baseline if b['task'] == row['task_name']]
    case = {
        'case_id':f'XM{case_number:02d}',
        'trial_name':trial,
        'task':row['task_name'],
        'benchmark':'DeepSWE v1.1',
        'runtime_identity': {
            'public_metadata_model':row['model'], 'public_metadata_provider':row['provider'],
            'trajectory_model_name':trajectory['agent']['model_name'],
            'agent_name':trajectory['agent']['name'], 'agent_version':trajectory['agent']['version'],
            'config':row['config'], 'reasoning_effort':row['reasoning_effort'],
            'started_at':row['started_at'], 'finished_at':row['finished_at'],
            'agent_execution_seconds':row['agent_duration_seconds'],
            'sampling_parameters':'Not present in published trajectory/summary; do not substitute model-card benchmark settings.',
            'backend_weight_digest':'Not published; cloud service identity is publisher-labeled, not a local checkpoint attestation.',
        },
        'task_alignment': {
            'repository':original['repository'], 'base_commit':original['base_commit'],
            'base_commit_prefix_observed_in_git_output':True,
            'canonical_instruction_exact_substring_in_agent_prompt':True,
            'canonical_task_repository_commit':TASK_COMMIT,
            'official_issue_url':f'https://github.com/datacurve-ai/deep-swe/blob/{TASK_COMMIT}/tasks/{row["task_name"]}/instruction.md',
            'captured_instruction':receipt(task_capture / 'instruction.md'),
            'captured_verifier_test_patch':receipt(task_capture / 'tests/test.patch'),
            'external_reference_solution_read':False,
        },
        'final_evaluation':{
            'kind':'Published historical evaluation of this trial final submitted model.patch; no new Docker replay.',
            'reward':reward,
            'failed_named_tests':failed,
            'all_test_status_counts':dict(collections.Counter(t['status'] for t in ctrf['results']['tests'])),
            'patch':receipt(directory / 'model.patch'),
            'ctrf':receipt(directory / 'ctrf.json'),
            'stdout':receipt(directory / 'test-stdout.txt'),
            'ownership_basis':'All five raw artifacts use the same official release/trial_name prefix; metadata, model alias, task prompt and observed base commit agree.',
        },
        'review_scope': {
            'all_published_agent_messages_read':True,
            'all_commands_and_observations_indexed':True,
            'all_command_timeline_search':'Full commands+observations scanned for target-specific constructs; manual review covered matching validation/revision contents and final-state checks, with all published agent messages read in chronological order.',
            'unrelated_tool_output_read_word_for_word':False,
            'manual_evidence_step_ids':note['evidence_steps'],
            'reviewed_evidence_file':str(directory / 'reviewed_evidence.json'),
            'reviewed_agent_messages_file':str(directory / 'reviewed_agent_messages.json'),
            'original_observation_elisions':truncated,
            'absence_claim_limit':'No full witness was found in the preserved trajectory after timeline search and targeted review; missing text inside original output elisions cannot be recovered here.',
            'unpublished_reasoning':'No inference about unavailable internal reasoning; published short messages and tool evidence only.',
        },
        'analysis':note,
        'same_task_deepseek_comparison': {
            'case_ids':[b['case_id'] for b in task_baselines],
            'matching_failed_test_names':sorted({f['name'] for b in task_baselines for f in b['evaluation_failures']}
                                                & {f['name'] for f in failed}),
            'baseline_evidence':'baseline_compare.json',
            'conclusion':note['comparison'],
            'caution':'Same task and failure name establish semantic alignment, not identical source bug, causal mechanism or model-only attribution.',
        },
        'artifact_sources':[d for d in downloads if d['trial_name'] == trial],
    }
    cases.append(case)
    (directory / 'analysis.json').write_text(json.dumps(case, ensure_ascii=False, indent=2) + '\n')

(ROOT / 'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
counts = dict(collections.Counter(c['analysis']['classification'] for c in cases))
discovery = {
 'schema_version':'eviweave-cross-model-gap-pilot-v1',
 'date':'2026-11-09',
 'objective':'Actual bounded analysis of published target-model SWE trajectories on tasks shared with the frozen DeepSeek cohort; no inference from benchmark aggregate scores.',
 'result':'Both requested model families have complete public DeepSWE v1.1 failure artifacts; no new model budget or user-supplied trajectories were needed.',
 'models':[
  {'requested':'GLM-5.3-Flash','metadata_model':'glm-5-3-flash','observed_runtime_alias':'anthropic/glm-5.3-flash-stable','provider_field':'anthropic','interpretation':'Provider/protocol label is not the actor model family; original ATIF agent model name and metadata both identify GLM. No backend checkpoint hash is published.','official_model_card':'https://huggingface.co/zai-org/GLM-5.3-Flash','snapshot_rows':448,'advertised_complete_artifact_rows':448},
  {'requested':'Qwen3.8-Max / open weights Qwen3.8-2.4T-A95B','metadata_model':'qwen3-8-max','observed_runtime_alias':'qwen/qwen3.8-max','provider_field':'openrouter','interpretation':'These are genuine Max service trajectories. The official card says the managed Max service is based on released Qwen3.8-2.4T-A95B weights with extra features. Do not relabel the run as local checkpoint inference or attest identical weights.','official_model_card':'https://huggingface.co/Qwen/Qwen3.8-2.4T-A95B','snapshot_rows':452,'advertised_complete_artifact_rows':448},
 ],
 'selection':{
  'file':'selection.json','policy':selection['policy'],
  'eligible_failed_trial_counts':selection['eligible_counts'],
  'eligible_failed_task_counts':selection['eligible_task_counts'],
  'common_eligible_task_count':selection['common_eligible_task_count'],
  'selected_tasks':selection['selected_tasks'],'selected_trials':10,
  'replacements_after_reading_content':0,'download_exclusions':[],
  'scope':'Five paired tasks, one failed run per target model/task. The sample conditions on common failures and original DeepSeek case order; it is not a random model failure sample.',
 },
 'evidence_capture':{
  'metadata_snapshot':selection['source_snapshot'],'metadata_sha256':selection['source_sha256'],
  'metadata_public_url':'https://deepswe.datacurve.ai/artifacts/v1.1/trials.json',
  'current_release_metadata_url':'https://deepswe.datacurve.ai/artifacts/v1.1/release.json',
  'current_artifact_base_url':json.loads((ROOT / 'sources' / 'deepswe_current_release.json').read_text())['artifact_base_url'],
  'download_manifest':'download_manifest.json','raw_artifact_files':len(downloads),
  'download_bytes':sum(d['bytes'] for d in downloads),'http_failures':0,
  'canonical_task_commit':TASK_COMMIT,'all_10_instruction_and_base_checks_passed':True,
  'agent':'mini-swe-agent 2.4.6','no_model_calls':True,'no_new_docker_execution':True,
 },
 'classification_counts_in_this_selected_sample':counts,
 'interpretation':{
  'clear_mode_or_format_combination_not_executed':[c['case_id'] for c in cases if c['analysis']['strict_unexecuted_combination_supported']],
  'fine_grained_fixture_gap_after_broad_joint_tests':[c['case_id'] for c in cases if c['analysis'].get('fine_grained_missing_joint_fixture_supported')],
  'joint_executed_wrong_oracle':[c['case_id'] for c in cases if c['analysis']['classification']=='joint_executed_oracle_incompatible'],
  'earlier_failure_then_witness_removed':[c['case_id'] for c in cases if c['analysis']['classification']=='earlier_failing_witness_removed'],
  'basic_missing_feature_without_history_diagnosis':[],
  'warning':'Do not add these categories into a headline model gap rate. Finer fixture gaps depend on factor granularity; wrong-oracle cases are counterexamples to the claim that combinations were never exercised.',
 },
 'search_and_alternatives':[
  {'source':'Official target model cards','finding':'Confirmed actual names, managed/open-weight distinction and evaluation harness footnotes, not trajectory-level gap evidence.','captured':['sources/glm53_card.md','sources/qwen38_card.md']},
  {'source':'Local original DeepSWE trials snapshot','finding':'31,617 rows include target aliases and full artifact flags. This directly supplied the paired same-benchmark sample; the public current release gives the artifact host.'},
  {'source':'https://huggingface.co/datasets/kaitchup/DeepSWE1.1-trajectories-Qwen3.8-27B','finding':'Verified genuine evaluation outputs (791 task records/trajectories, Qwen3.8-27B in several harnesses plus separate Muse/Qwen3.6 baselines). Not used as target Max evidence; run indexes captured only.','revision':'e58b83310346104971fd17c42f9955e7cd5e3b25'},
  {'source':'https://huggingface.co/datasets/ZhuofengLi/Harbor-SWE-Trajectory','finding':'Dataset card distinguishes actual Qwen3/3.5, SWE-Lego and Sonnet models, and retains verifier archives. Alternative only; no training dataset relabeled as Qwen runtime evidence.'},
  {'source':'SWE-bench/experiments GLM-5 mini-v2.0.0 submission','finding':'Public submission directory located. A guessed results child URL returned HTTP404; no evaluation claim made from it. Target DeepSWE artifacts rendered fallback unnecessary.'},
  {'source':'Read-only local /data3/jhx research directories','finding':'SWE-EVO Qwen3-Coder/OpenHands and other benchmark data discovered, not used because target-model same-task DeepSWE evidence was available. Initial unrestricted filename search was too large; further search bounded to known directories.'},
 ],
 'limitations':[
  'Public metadata identifies endpoint aliases and run configurations; backend weight digests/sampling settings were not published in the trial artifacts.',
  'No new patch replay was performed; final failure evidence is the original published per-trial verifier outcome, not an experiment newly rerun today.',
  'All published agent messages were read. Tool timelines were indexed in full and manually inspected around each target, validation, test revision and final commit; unrelated large output was not read word for word.',
  'Original tool observations sometimes elide middle output. Elisions and their locations are preserved per case; absence claims are bounded to the retained evidence.',
  'Selection deliberately uses original DeepSeek tasks and paired failures. Scores, prevalence, significance, and model capability comparisons cannot be inferred.',
  'No new composed test was run, so this pilot establishes historical validation gaps/oracle disagreements, not a causal benefit for EviWeave or a memory explanation.',
 ],
 'deliverables':{'cases':'cases.json','per_trial':'trials/<trial>/analysis.json','baseline':'baseline_compare.json','report':'report.txt','reproduction':'fetch_pilot.py; index_trajectories.py; build_report.py'},
}
(ROOT / 'discovery.json').write_text(json.dumps(discovery, ensure_ascii=False, indent=2) + '\n')

lines = [
 'GLM-5.3-Flash / Qwen3.8-Max：同任务公开轨迹小范围复核（2026-11-09）',
 '',
 '两个目标型号的真实轨迹均已找到。本轮固定抽取原 DeepSeek 58 个任务中两模型共同失败的前5个任务，各1条，10条均取得 trajectory、最终 model.patch、CTRF、reward 与原始 verifier stdout，7,933,761 bytes，无替换/下载排除。来源、完整候选顺序见 discovery.json、selection.json。',
 '',
 '运行身份：GLM=anthropic/glm-5.3-flash-stable（2026-08-26），Qwen=qwen/qwen3.8-max（2026-08-03），mini-swe-agent 2.4.6。anthropic 在此是供应/协议字段；Qwen 是Max服务运行，不应假称本地2.4T权重运行。10条prompt都含相同canonical instruction，Git输出base前缀都对应原88样本。',
 '',
 '事实分类（只描述所选10条，不是发生率）：',
 '  明确未执行mode/format联合场景：2条（XM07/XM08，bandit incremental）。',
 '  已有广义联合测试但遗漏更细位置/布局fixture：4条（XM03/XM04 arktype；XM09/XM10 nosec）。',
 '  场景已联合执行但oracle与held-out相反：3条（XM02 abs；XM05/XM06 awilix）。',
 '  已见失败刺激，重写测试时未保留：1条（XM01 abs）。',
 '',
 '最清楚的mode组合例：GLM独立执行无target cache-stats并检查JSON字段，但带target时screen formatter先关闭stdout，随后的stats print崩溃；Qwen验证summary时总给target，最终summary无target exit2，同时warm-cache未与-f json同进程验证，最终stdout为空。',
 '',
 '不能全称为“组合没测”：两个模型awilix都实际执行parent未初始化的child-first场景，却写了要求parent也初始化的oracle；Qwen abs明确把负索引写入错误当expected；GLM abs早已观察负索引写入错误，随后重写测试块时该例消失。arktype和nosec都包含真实广义交互验证，缺口只能在具体结构/布局粒度陈述。',
 '',
 '与DeepSeek对照：abs同失败语义；arktype共享deep-recursive测试但报错阶段不同；awilix的DeepSeek失败在默认并发，本次失败在scope ownership；cache的DeepSeek和Qwen都在warm-cache JSON失败，但DeepSeek曾联合执行且oracle错误，Qwen本轮未找到该联合；nosec两模型与S009-S011在同一058布局失败。详见baseline_compare.json和每例comparison。',
 '',
 '逐例记录：',
]
for case in cases:
    n = case['analysis']
    lines.extend([
      '', f"{case['case_id']} {case['runtime_identity']['public_metadata_model']} {case['trial_name']}",
      n['classification_zh'], n['target_behavior'], n['agent_validation'],
      '历史变化：' + '；'.join(n['chronology']),
      '结论边界：' + n['oracle_or_history_gap'] + ' ' + n['contract_caveat'],
      'DeepSeek对照：' + n['comparison'],
      f"证据：trials/{case['trial_name']}/analysis.json 与 reviewed_evidence.json；原轨迹、patch、CTRF均保留。",
    ])
lines.extend([
 '',
 '检查范围：已读全部公开agent messages；全量索引/检索tool时间线，并人工核对目标、validation、测试修订和最终commit；未逐字阅读无关大型输出。原轨迹中output elision已逐例记录。没有新的模型调用、Docker replay、外发人工标签；当前公开数据足够，无需追加预算。',
 '这些数据支持“未测输入上下文/更细fixture缺口”和“错误oracle/历史证据丢失”都存在于目标模型运行；不支持模型优劣、全体发生率、遗忘因果解释或EviWeave增益结论。',
])
(ROOT / 'report.txt').write_text('\n'.join(lines) + '\n')
print(json.dumps({'cases':len(cases), 'counts':counts, 'source_alignment_checks':10,
                  'downloaded_files':len(downloads),'raw_bytes':sum(d['bytes'] for d in downloads)}, indent=2))
