import json
from pathlib import Path

directory = Path(__file__).parent
case = json.loads((directory / 'case.json').read_text())
failures = json.loads((directory / 'evaluation_failures.json').read_text())['failed_tests']


def command(step, quote):
    return {'step': step, 'call': 0, 'channel': 'command', 'quote': quote}


def output(step, quote):
    return {'step': step, 'call': 0, 'channel': 'output', 'quote': quote}


def reasoning(step, quote):
    return {'step': step, 'channel': 'reasoning', 'quote': quote}


materials = []


def material(mid, kind, availability, unit, supports, refs, artifact='', symbol='', origin='agent_authored'):
    materials.append(dict(id=mid, kind=kind, origin=origin, availability=availability,
                          unit=unit, supports=supports, refs=refs, artifact=artifact, symbol=symbol))


material('F1', 'temporary_probe', 'executed_pass', 'Initial frames-mode roundtrip and matching annotation test, allows only stackFrames', ['G1:frames_mode_and_permission', 'G2:frames_permission'],
         [command(32, "it('frames mode serializes stackFrames',"), command(32, "sj.allowErrorProps('stackFrames');"), output(37, '34 passed')], 'src/error-stack.tmp.test.ts')
material('F2', 'agent_validation', 'executed_pass', 'Permanent frames roundtrip and annotation tests; stackFrames only', ['G1:frames_mode_and_permission', 'G2:frames_permission'],
         [command(53, "it('frames mode serializes stackFrames when allowed',"), command(53, "superJson.allowErrorProps('stackFrames');"), output(58, '112 passed')], 'src/error-stack.test.ts')
material('F3', 'temporary_probe', 'executed_pass', 'Frames plus direct-cause roundtrip; frames header and cause assertions', ['G1:frames_mode_and_permission', 'G2:frames_permission'],
         [command(45, "it('frames mode with cause',"), command(45, "sj.allowErrorProps('stackFrames');"), output(45, '2 passed')], 'src/error-stack.tmp3.test.ts')
material('F4', 'temporary_probe', 'executed_output', 'Built-output frames+basename script, actual stackFrames header and first frame printed', ['G1:frames_mode_and_permission', 'G2:frames_permission', 'G3:frames_processing_harness'],
         [command(51, "const sj2 = new SuperJSON({ errorStack: { mode: 'frames', redactPaths: 'basename' } });"), command(51, "sj2.allowErrorProps('stackFrames');"), output(51, 'frames[0]:')], '/tmp/e2e.mjs')
material('S1', 'temporary_probe', 'executed_pass', 'Initial string/max2 roundtrip, permits raw stack and checks positive processed result', ['G1:raw_stack_permission', 'G2:string_mode_harness', 'G3:string_integration_harness'],
         [command(32, "it('string mode processes stack',"), command(32, "sj.allowErrorProps('stack');"), output(37, '34 passed')], 'src/error-stack.tmp.test.ts')
material('S2', 'temporary_probe', 'executed_pass', 'Independent exact-output integration string roundtrip test', ['G1:raw_stack_permission', 'G2:string_mode_harness', 'G3:string_integration_harness'],
         [command(39, "it('string mode with allowErrorProps round trips',"), command(39, "sj.allowErrorProps('stack');"), output(43, '18 passed')], 'src/error-stack.tmp2.test.ts')
material('S3', 'agent_validation', 'executed_pass', 'Permanent string/max2 roundtrip and positive string annotation tests', ['G1:raw_stack_permission', 'G2:string_mode_harness', 'G3:string_integration_harness'],
         [command(53, "it('string mode processes stack when allowed',"), command(53, "superJson.allowErrorProps('stack');"), output(58, '112 passed')], 'src/error-stack.test.ts')
material('S4', 'temporary_probe', 'executed_pass', 'String+deep-cause annotation/deserialize test; permits stack', ['G1:raw_stack_permission', 'G2:string_mode_harness', 'G3:string_integration_harness'],
         [command(45, "it('nested causes under stack mode',"), command(45, "sj.allowErrorProps('stack');"), output(45, '2 passed')], 'src/error-stack.tmp3.test.ts')
material('S5', 'temporary_probe', 'executed_output', 'Built-output string/max2/direct/sanitize script; prints stack line count and cause', ['G1:raw_stack_permission', 'G2:string_mode_harness', 'G3:string_integration_harness'],
         [command(51, "mode: 'string', maxStackLines: 2, sanitizeMessage: true, includeCauses: 'direct'"), command(51, "sj.allowErrorProps('stack');"), output(51, 'stack lines: 2')], '/tmp/e2e.mjs')
material('O1', 'temporary_probe', 'executed_pass', 'Off-mode stack prohibition roundtrip; supplies permission and negative property matcher', ['G1:raw_stack_permission', 'G1:absence_matcher', 'G2:absence_matcher'],
         [command(32, "it('off mode never serializes stack even if allowed',"), command(32, 'expect(parsed.stack).toBeUndefined();'), output(37, '34 passed')], 'src/error-stack.tmp.test.ts')
material('O2', 'agent_validation', 'executed_pass', 'Permanent off-mode explicit absence test', ['G1:raw_stack_permission', 'G1:absence_matcher', 'G2:absence_matcher'],
         [command(53, "it('off mode never serializes stack even when allowed',"), command(53, 'expect(parsed.stack).toBeUndefined();'), output(58, '112 passed')], 'src/error-stack.test.ts')
material('P1', 'temporary_probe', 'executed_pass', 'Processor-removal test explicitly inspects res.json.stack absence; must remove callback to expose leakage', ['G1:plain_result_absence_observation', 'G2:plain_result_absence_observation'],
         [command(39, "it('processor can remove stack',"), command(39, 'delete serialized.stack;'), command(39, 'expect((res.json as any).stack).toBeUndefined();'), output(43, '18 passed')], 'src/error-stack.tmp2.test.ts')
material('P2', 'temporary_probe', 'executed_pass', 'String with no stack permission inspects serialized JSON stack absence and annotation', ['G1:plain_result_absence_observation', 'G2:plain_result_absence_observation'],
         [command(39, "it('mode string without allowErrorProps has no stack',"), command(39, 'expect((res.json as any).stack).toBeUndefined();'), output(43, '18 passed')], 'src/error-stack.tmp2.test.ts')
material('P3', 'agent_validation', 'executed_pass', 'Permanent processor-added extra test retains serialized JSON and roundtrip as two observation stages', ['G1:plain_result_observation', 'G2:plain_result_observation'],
         [command(53, "it('registerErrorStackProcessor runs after serialization steps',"), command(53, 'expect((serialized.json as any).extra).toBe(\'added\');'), output(58, '112 passed')], 'src/error-stack.test.ts')
material('R1', 'repo_test', 'executed_pass', 'Original regression108 observes absent stack under default and raw allowed stack after permission; read before design', ['G1:raw_stack_permission_and_negative_matcher', 'G2:legacy_observation_harness'],
         [output(13, "regression #108: Error#stack should not be included by default"), output(13, 'expect(thatShouldBeUndefined).toBeUndefined();'), output(13, "SuperJSON.allowErrorProps('stack');"), output(77, '112 passed')], 'src/index.test.ts', 'regression #108', 'repo_preexisting')
material('R2', 'repo_test', 'executed_pass', 'Original Error roundtrip table and optional nested cause fixture', ['G1:legacy_roundtrip_harness', 'G2:legacy_roundtrip_harness', 'G3:legacy_Error_harness'],
         [output(13, "'works for Errors':"), output(13, "'works for Error causes':"), output(77, '112 passed')], 'src/index.test.ts', 'works for Errors / Error causes', 'repo_preexisting')
material('N1', 'temporary_probe', 'executed_pass', 'String node-filter test shares concrete stack containing bare node:internal and normal user frames, checks internal removal', ['G3:internal_input_and_filter'],
         [command(32, "it('stripInternalFrames node',"), command(32, "at node:internal/modules/cjs/loader:5:6"), command(32, "expect(out).not.toContain('node:internal');"), output(37, '34 passed')], 'src/error-stack.tmp.test.ts')
material('N2', 'temporary_probe', 'executed_pass', 'String combined node+SuperJSON-filter test on same actual stack, both absence checks', ['G3:internal_input_and_filter'],
         [command(32, "it('stripInternalFrames node_and_superjson',"), command(32, "stripInternalFrames: 'node_and_superjson'"), output(37, '34 passed')], 'src/error-stack.tmp.test.ts')
material('N3', 'temporary_probe', 'executed_pass', 'Named string-order test combines limit2+node filtering but omits redactPaths and places internal after first two user frames', ['G3:internal_input_filter_and_limit'],
         [command(32, "it('string order: redact then limit then strip',"), command(32, "maxStackLines: 2, stripInternalFrames: 'node'"), output(37, '34 passed')], 'src/error-stack.tmp.test.ts')
material('N4', 'temporary_probe', 'executed_pass', 'Exact string limit4 then node-filter test, independently retained after correcting unrelated wrong limit oracle', ['G3:internal_input_filter_and_limit'],
         [command(39, "it('strip before limit in string mode is NOT done',"), command(39, "maxStackLines: 4, stripInternalFrames: 'node'"), output(43, '18 passed')], 'src/error-stack.tmp2.test.ts')
material('N5', 'agent_validation', 'executed_pass', 'Permanent string max3+node test; limit excludes internal line before filtering, so cannot observe filter effect', ['G3:internal_input_filter_and_limit'],
         [command(53, "it('processStackString strips internal frames after limiting',"), command(53, "stripInternalFrames: 'node'"), output(58, '112 passed')], 'src/error-stack.test.ts')
material('B1', 'temporary_probe', 'executed_pass', 'Initial string basename test processes same node+user+SuperJSON stack but asserts only two normal frames', ['G3:basename_and_internal_input'],
         [command(32, "it('redactPaths basename',"), command(32, "redactPaths: 'basename'"), output(37, '34 passed')], 'src/error-stack.tmp.test.ts')
material('B2', 'agent_validation', 'executed_pass', 'Permanent basename test similarly asserts only user filenames', ['G3:basename_and_internal_input'],
         [command(53, "it('processStackString redacts paths to basename',"), command(53, "redactPaths: 'basename'"), output(58, '112 passed')], 'src/error-stack.test.ts')
material('B3', 'temporary_probe', 'executed_pass', 'Frames basename test explicitly asserts that original node:internal becomes loader; initial contrary expectation fails39/42 then is deliberately corrected43', ['G3:basename_erases_internal_identity'],
         [command(39, "it('redact basename',"), output(42, 'at loader:5:6'), command(43, "expect(out[3]).toEqual({ raw: 'at loader:5:6' });"), output(43, '18 passed')], 'src/error-stack.tmp2.test.ts')
material('T1', 'implementation', 'read_only', 'Actual allowed-props loop only suppresses stack/stackFrames for off, then overrides selected representation; explicit transform read46', ['G1:raw_copy_connection', 'G2:undefined_field_copy_connection'],
         [output(46, "config?.mode === 'off' &&"), output(46, 'baseError[prop] = (v as any)[prop];')], 'src/transformer.ts', 'serializeError')
material('T2', 'implementation', 'read_only', 'Actual string pipeline redacts frame text before limit and text-based internal regex; frames strips before redaction', ['G3:producer_consumer_dependency'],
         [output(59, 'resultFrames = redactPaths(resultFrames, normalized.redactPaths);'), output(59, 'const NODE_INTERNAL_REGEX = /node:internal/;')], 'src/error-stack.ts', 'processStackString/processStackFrames')
material('Q1', 'reasoning', 'reasoning_only', 'Step47 expressly chooses frames raw stack permission as consistent with no explicit exclusivity in issue', ['G1:opposite_permission_scenario', 'G1:contract_dispute'],
         [reasoning(47, "The spec doesn't say frames mode suppresses stack. It only says off suppresses.")])
material('Q2', 'reasoning', 'reasoning_only', 'Step44 explicitly predicts string+allow(stackFrames) copies undefined and JSON null but dismisses as unlikely hidden edge', ['G2:opposite_permission_scenario', 'G2:plain_output_prediction'],
         [reasoning(44, "what if `allowedErrorProps` includes 'stackFrames' in string mode?"), reasoning(44, 'serialized as null.'), reasoning(44, 'Hidden tests unlikely.')])
material('Q3', 'reasoning', 'reasoning_only', 'Step43 explicitly accepts basename erasing node:internal; late50 and60 revisit this choice but never connect it to later string-mode filtering', ['G3:identity_erasure_clue'],
         [reasoning(43, 'redacting `node:internal/...` to `loader:5:6` is actually correct!'), reasoning(50, 'My implementation redacts `node:internal/modules/cjs/loader:5:6` to `loader:5:6`.')])
material('I1', 'issue_or_documentation', 'read_only', 'Original mode descriptions specify positive selected formats and off prohibition; do not explicitly require other allowed format to be absent', ['G1:mode_contract', 'G2:mode_contract'],
         [{'channel': 'issue', 'path': case['issue'], 'quote': '`off` never serializes stack data, even if `allowErrorProps` includes `stack`.'}, {'channel': 'issue', 'path': case['issue'], 'quote': '`frames` serializes `stackFrames` as an array of `{ raw: string }` objects when `stackFrames` is allowed.'}], 'instruction.md', origin='issue')
material('I2', 'issue_or_documentation', 'read_only', 'String pipeline order and unconditional node-internal removal requirement jointly supply expected semantics', ['G3:joint_pipeline_oracle'],
         [{'channel': 'issue', 'path': case['issue'], 'quote': '`normalizeNewlines -> trimLeadingWhitespace -> redactPaths -> maxStackLines -> stripInternalFrames`'}, {'channel': 'issue', 'path': case['issue'], 'quote': '`node` strips `node:internal` frames.'}], 'instruction.md', origin='issue')


def slot(role, alternatives):
    return {'role': role, 'alternatives': [[m] for m in alternatives]}


recipes = []


def recipe(rid, gap, slots, compatibility, additions, qualification='requires_oracle_inference'):
    recipes.append(dict(id=rid, gap=gap, qualification=qualification, slots=slots,
                        forbidden_pairs=[], compatibility=compatibility, semantic_additions=additions))


recipe('G1R1', 'G1', [slot('frames 基础测试', ['F1', 'F2', 'F3', 'F4']), slot('另一处允许 stack 的操作', ['S1', 'S2', 'S3', 'S4', 'S5', 'O1', 'O2', 'R1']), slot('序列化原始 JSON 观察', ['P1', 'P2', 'P3']), slot('模式合同', ['I1'])],
       '保留 frames 基础测试及其 frame/cause 观察，加上同一实例 allow(stack)，在 serialize 输出上检查 stack 缺席/非字符串。P1 的删除 stack 回调不能带入，否则主动掩盖错误。此候选符合官方测试，但互斥 oracle 不是 issue 明文要求。', ['新建模式互斥 oracle；额外 allow(stack)；明确观察 plain JSON。'])
recipe('G1R2', 'G1', [slot('有 stack 许可和缺席 matcher 的旧仓库测试', ['R1']), slot('frames 实例和 stackFrames 许可', ['F1', 'F2', 'F3', 'F4']), slot('原始 JSON 观察', ['P1', 'P2', 'P3']), slot('模式合同', ['I1'])],
       '从旧 regression108 保留 Error 与 stack 缺席 matcher，替换 static/default 实例为 frames 实例，保留双方许可，再先观察 plain serialize。原 default 缺席正确不证明 frames+allowboth 也必须缺席。', ['配置和观察阶段迁移；官方互斥语义需要额外解释。'])
recipe('G1R3', 'G1', [slot('任一历史 frames 基础执行', ['F1', 'F2', 'F3', 'F4']), slot('当前 reasoning 已完整提出另一许可场景', ['Q1']), slot('plain 观察', ['P1', 'P2', 'P3']), slot('模式合同', ['I1'])],
       'reasoning47 可以直接指导添加 allow(stack)，无需从唯一 string53 提取；仍须采用官方而非 Agent 明示的非互斥预期。', ['与 Agent 原解释相反的互斥 oracle。'])
recipe('G2R1', 'G2', [slot('string 基础测试', ['S1', 'S2', 'S3', 'S4', 'S5']), slot('其他测试中 stackFrames 许可', ['F1', 'F2', 'F3', 'F4']), slot('plain JSON 观察', ['P1', 'P2', 'P3']), slot('模式合同', ['I1'])],
       '在 string 实例额外允许 stackFrames，直接检查 json.stackFrames 不存在。原 Error 不含该字段时 raw loop 会写 undefined，walker 将其编码成 null；parse 后又还原 undefined，故只 roundtrip 无法复现官方 plain-json failure。', ['新增 plain 结果检查和对另一格式缺席的 oracle。'])
recipe('G2R2', 'G2', [slot('原有 string 执行', ['S1', 'S2', 'S3', 'S4', 'S5']), slot('当前 reasoning 已预测另一格式 null', ['Q2']), slot('plain JSON 观察', ['P1', 'P2', 'P3']), slot('模式合同', ['I1'])],
       '44 已写出允许另一属性会得到 serialized null 的整个条件与结果；可直接实体化到既有 string 测试，不能将该文字误记为实际执行。', ['将 reasoning 具体化；对 null 的合同判断另行推导。'])
recipe('G2R3', 'G2', [slot('旧仓库 Error 基础 fixture', ['R1', 'R2']), slot('string 配置及 stack 许可', ['S1', 'S2', 'S3', 'S4', 'S5']), slot('stackFrames 许可', ['F1', 'F2', 'F3', 'F4']), slot('plain 观察', ['P1', 'P2', 'P3']), slot('模式合同', ['I1'])],
       '旧 repo Error fixture 可以承载同样输入和 serialize 调用，但旧 annotations 与默认 roundtrip oracle 不能照搬。', ['切换实例配置；新增另一格式不应出现在 plain JSON 的 oracle。'])
recipe('G3R1', 'G3', [slot('已有内部 frame 的 string 过滤测试', ['N1', 'N2', 'N3', 'N4', 'N5']), slot('basename 处理条件', ['B1', 'B2', 'B3']), slot('联合 pipeline 合同', ['I2'])],
       '将 basename 加入原 string 过滤配置；N3/N5 的限制会在原 fixture 中提前排除内部 frame，须把已有 node frame 移到第一条（随后保留正常 frame），或移除 limit。保留过滤应去掉该输入 frame 的语义，不可仅检查文本 node:internal 已消失。N1/N2/N4 可直接联合并检查原被删行/行数。node_and_superjson 与 node 都暴露身份丢失。', ['对于 N3/N5 调整已有 frame 相对位置或取消 limit；加强 oracle 为该 frame 被删除而非原标记字符串消失。'])
recipe('G3R2', 'G3', [slot('basename 及真实内部输入', ['B1', 'B2', 'B3']), slot('node 过滤条件及原过滤观察', ['N1', 'N2', 'N4']), slot('联合 pipeline 合同', ['I2'])],
       '从 basename 测试出发添加 node 或 node_and_superjson，B3 为 frames 时切换为 string processor；已知其 loader 节点应随原内部帧删除。无需加入 max2 就能揭露同一缺陷；若按官方布局复现，再复用 N3 的 max2 并移动内部 frame 到首位。', ['frames→string 需要切换处理函数；新联合结果 oracle。'])
recipe('G3R3', 'G3', [slot('已有集成 string 测试或脚本', ['S1', 'S2', 'S3', 'S4', 'S5']), slot('basename fixture 和选项', ['B1', 'B2', 'B3']), slot('node 输入/过滤配置', ['N1', 'N2', 'N4']), slot('联合 pipeline 合同', ['I2'])],
       '将历史 synthetic stack 设为原 Error.stack，再把两项处理条件置于既有实例中，保留原 message/cause 检查并增加最终 stack 必须删除内部帧的检查。不必固定唯一 filepath 或官方 task_queues 字面值。', ['把 utility fixture 接到完整 Error serialize/parse 流；添加关系 oracle。'])
recipe('G3R4', 'G3', [slot('源码中明确读到的顺序与 regex', ['T2']), slot('已有 node-redaction 结果', ['B3']), slot('任一集成 string 测试', ['S1', 'S2', 'S3', 'S4', 'S5']), slot('联合 pipeline 合同', ['I2'])],
       '源码数据依赖和已执行 loader 输出提供独立发现路线：redaction 消费原路径并抹掉标识，后续 regex 消费已变化的文本；构造原有 Error/stack harness 并开启两项即可。', ['源码操作与测试结合；合成后过滤预期。'])

families = [
    dict(id='G1', failed_tests=[failures[0]['name']],
         contract='Official test expects frames mode to exclude string stack even if both props are allowed. Issue explicitly prohibits stacks in off mode, but frames/string descriptions state only positive production rules and do not explicitly revoke other generic allowed props.',
         missing_joint_test="frames mode + allowErrorProps('stack','stackFrames') + serialize(Error with real stack), inspect plain json.stack is not string.",
         classification='verifier_disputed', verifier_validity='disputed', joint_attempt='absent',
         required_components=['frames mode', 'both representation permissions', 'real Error.stack', 'plain-result opposite-format absence oracle'],
         patch_explanation='allowedErrorProps copies raw stack for every non-off mode, then frames branch adds stackFrames. This reproduces official failure, but exclusivity is an additional contract interpretation, explicitly rejected by Agent47.'),
    dict(id='G2', failed_tests=[failures[1]['name']],
         contract='Official test expects json.stackFrames undefined under string+allowboth. Raw undefined generic allowed props are encoded as null by the preexisting walker and restored on roundtrip; issue does not explicitly require omission of this other allowed field.',
         missing_joint_test="string mode + allowErrorProps('stack','stackFrames') + serialize(new Error); inspect json.stackFrames before deserialize, require undefined rather than encoded null.",
         classification='verifier_disputed', verifier_validity='disputed', joint_attempt='absent',
         required_components=['string mode', 'stackFrames allowed but absent on original Error', 'plain serialize result before undefined restoration', 'opposite-format omission oracle'],
         patch_explanation='Raw allowed-props copy creates stackFrames:undefined; walker encodes null with an undefined annotation. A parsed-output check is insufficient. Agent44 predicts the precise condition but accepts it as an unlikely edge; correctness of official exclusion is weaker than the actual failure observation.'),
    dict(id='G3', failed_tests=[failures[2]['name']],
         contract='Issue requires string redaction→limit→filter and node-mode removal of node:internal frames. Original frame identity must remain available when redaction changes the text that later filtering examines.',
         missing_joint_test="Use Error.stack with header, first internal frame, later normal frame; enable string/basename/max2/node; roundtrip expected header only. More generally basename+node on historical shared stack must remove redacted internal frame, independent of exact filename or limit2.",
         classification='untested_interaction', verifier_validity='supported', joint_attempt='absent',
         required_components=['string pipeline', 'actual node:internal input frame', 'basename erasing marker', 'subsequent node filter', 'oracle about removed frame rather than marker text alone'],
         patch_explanation='basename turns node:internal/.../loader into loader; isInternalFrame later tests only /node:internal/ on redacted text, so leaked loader/task_queues survives. max2 is needed for the exact heldout header-only witness, not for the underlying redaction/filter incompatibility.')]

review = dict(case_id='S070', reviewer='Codex /root',
              full_read=dict(line_ranges=[[1, 15608]], steps=80, unread=[], metadata_read=True,
                             note='All retained trajectory text read in order. Tool-truncated ranges3801–4250 and14851–15608 were reread completely in smaller ranges; original harness elisions remain such.'),
              evaluation_families=families, materials=materials, recipes=recipes,
              agent_process=dict(joint_attempt='absent', explanations=[
                  dict(label='explicit_contract_interpretation', support='direct',
                       interpretation='G1 opposite-format permission is actively considered47 and allowed because only off has an explicit prohibition; G2 copied null is predicted44 and dismissed as unlikely. These are conscious specification/priority decisions, not facts lost from long context.',
                       refs=[reasoning(47, "The spec doesn't say frames mode suppresses stack. It only says off suppresses."), reasoning(44, 'Hidden tests unlikely.')]),
                  dict(label='producer_consumer_effect_not_transferred', support='direct',
                       interpretation='G3 related tests are written together32/39;43 explicitly accepts basename erasing the node marker, while string-order checks separately verify limit/filter. The two effects are never traced through one shared input and result. Existing marker-absence matcher would itself miss a redacted-but-retained internal frame.',
                       refs=[command(32, "it('string order: redact then limit then strip',"), reasoning(43, 'redacting `node:internal/...` to `loader:5:6` is actually correct!'), reasoning(50, 'My implementation redacts `node:internal/modules/cjs/loader:5:6` to `loader:5:6`.')]),
                  dict(label='labelled_combination_not_actually_enabled', support='direct',
                       interpretation='The32 test is named redact then limit then strip but supplies only limit+strip; its internal frame is also beyond the retained prefix. The permanent53 test has the same observability limitation. A test name is not evidence that its advertised interaction was exercised.',
                       refs=[command(32, "it('string order: redact then limit then strip',"), command(32, "processStackString(stack, { ...base, maxStackLines: 2, stripInternalFrames: 'node' })"), command(53, "it('processStackString strips internal frames after limiting',")]),
                  dict(label='green_suite_as_completion_signal', support='direct',
                       interpretation='Final53 reorganizes tests and removes temporary files, but the missing interaction had never had a correct joint assertion. Repeated full checks112PASS and explicit item-by-item requirement review precede voluntary submit80. Metadata contains no step/cost/time cap; context length alone does not identify forgetting.',
                       refs=[output(77, '112 passed'), reasoning(80, 'Final review of requirements checklist')])],
                  forgetting_assessment='counterevidence'),
              prior_record_corrections=[
                  'Old focal G1 account treated format exclusivity as explicit issue requirement. This full review records the exact weaker wording and Agent47 contrary interpretation; a second independent Codex contract check agreed disputed.',
                  'All three real failed evaluations are represented, rather than only frames plain-stack leakage.',
                  'string32/39/45/51/53, frames32/45/51/53, old regression108 and several plain-result observers provide alternative routes. Repeated suite execution is linked as provenance rather than counted as a new material source.',
                  'G3 needs an oracle about internal-frame disappearance: checking not.toContain(node:internal) alone can PASS even when redaction merely removes the marker. It is not context-only repair with the original weak matcher.',
                  'The corrected39/43 unrelated expectations were not correct lost bug witnesses: limit-then-strip correction follows the stated order; loader basename correction makes that isolated test correct. The failure lies in their untested composition.'],
              uncertainties=['Newly assembled source routes were not executed this audit. G1/G2 are retained as reproducible official failures with disputed exclusivity semantics; G3 is supported by the stated filtering requirement.'])
(directory / 'manual_review.json').write_text(json.dumps(review, ensure_ascii=False, indent=2) + '\n')
(directory / 'reviewer_notes.txt').write_text('Full retained text15608lines/80steps plus metadata read.3failed names grouped3families. G1/G2 explicit format exclusivity not in issue; direct Agent47/44 counterevidence and independent Codex contract check, so disputed. G3 supported identity-erasure producer→consumer omission; existing marker matcher insufficient. Multiple utility/integration/repo/script/reasoning sources retained; no invented historical hard witness.\n')
