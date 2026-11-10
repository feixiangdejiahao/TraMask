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


def material(mid, kind, availability, unit, supports, refs, origin='agent_authored', artifact='', symbol=''):
    materials.append({'id': mid, 'kind': kind, 'origin': origin, 'availability': availability,
                      'unit': unit, 'supports': supports, 'artifact': artifact, 'symbol': symbol, 'refs': refs})


material('E1', 'agent_validation', 'executed_pass', 'String-mode direct roundtrip: one outer Error and one inner Error, asserts inner type/message only', ['G1:direct_mode_roundtrip'],
         [command(35, "it('round-trips causes with includeCauses direct',"), command(35, "errorStack: { mode: 'string', includeCauses: 'direct' }"), output(36, '(29 tests)'), output(69, '133 passed')], artifact='src/error-stack.test.ts', symbol='round-trips causes with includeCauses direct')
material('E2', 'agent_validation', 'executed_pass', 'Off-mode direct roundtrip: independent test with outer+inner and retained immediate message', ['G1:direct_mode_roundtrip'],
         [command(47, "it('off mode still honors includeCauses',"), command(47, "errorStack: { mode: 'off', includeCauses: 'direct' }"), output(47, '47 passed'), output(69, '133 passed')], artifact='src/error-stack.test.ts', symbol='off mode still honors includeCauses')
material('E3', 'agent_validation', 'executed_pass', 'Direct mode plus sanitization roundtrip: inner email message checked, still only one cause', ['G1:direct_mode_roundtrip'],
         [command(64, "it('sanitizes direct cause messages',"), command(64, "includeCauses: 'direct',"), command(64, "expect(out.cause.message).toBe('email [redacted]');"), output(64, '51 passed'), output(69, '133 passed')], artifact='src/error-stack.test.ts', symbol='sanitizes direct cause messages')
material('E4', 'agent_validation', 'executed_pass', 'Deep-mode maxDepth2 test: outer1→inner2→inner3→nonError; explicit third-cause absence check', ['G1:nested_error_input', 'G1:boundary_assertion_pattern'],
         [command(35, "it('includeCauses deep respects maxCauseDepth and drops non-Error causes',"), command(35, "const inner2 = new Error('2', { cause: inner3 });"), command(35, 'expect(out.cause.cause.cause).toBeUndefined();'), output(36, '29 passed'), output(69, '133 passed')], artifact='src/error-stack.test.ts', symbol='includeCauses deep respects maxCauseDepth and drops non-Error causes')
material('E5', 'agent_validation', 'executed_pass', 'Deep default16 test: loop creates sixteen Error causes; dynamic traversal counts exact retained depth', ['G1:nested_error_input', 'G1:depth_observation_pattern'],
         [command(40, "it('deep defaults to maxCauseDepth 16',"), command(40, "cause = new Error('cause-' + (15 - i), { cause });"), command(40, 'expect(depth).toBe(16);'), output(40, '42 passed'), output(69, '133 passed')], artifact='src/error-stack.test.ts', symbol='deep defaults to maxCauseDepth 16')
material('E6', 'repo_test', 'executed_pass', 'Original works for Error causes: original cause constructor, roundtrip table and type/message checks; read before feature design', ['G1:legacy_roundtrip_harness'],
         [output(11, "'works for Error causes': {"), output(11, "cause: new Error('catastrophic failure'),"), output(11, "expect(e.cause?.message).toBe('catastrophic failure');"), output(16, '82 passed'), output(69, '133 passed')], origin='repo_preexisting', artifact='src/index.test.ts', symbol='works for Error causes')
material('E7', 'agent_validation', 'executed_pass', 'Normalization test includes depth5 as a valid explicit limit and checks deep mode normalization', ['G1:explicit_limit_value'],
         [command(35, 'maxCauseDepth: 5'), command(35, "expect(normalizeErrorStackOptions({ includeCauses: 'deep', maxCauseDepth: 5 })!.maxCauseDepth).toBe(5);"), output(36, '29 passed')], artifact='src/error-stack.test.ts', symbol='defaults maxCauseDepth to 16 for deep')
material('E8', 'agent_validation', 'executed_pass', 'Non-Error direct cause test supplies precise cause-absence matcher but does not test depth of Error chains', ['G1:absence_matcher'],
         [command(40, "it('drops non-Error direct causes',"), command(40, 'expect(out.cause).toBeUndefined();'), output(40, '42 passed')], artifact='src/error-stack.test.ts', symbol='drops non-Error direct causes')
material('E9', 'agent_validation', 'executed_pass', 'Explicit option default cause-drop test with real inner Error; absence matcher on parsed result', ['G1:absence_matcher'],
         [command(40, "it('provided errorStack with default includeCauses drops cause',"), command(40, "const input = new Error('outer', { cause: new Error('inner') });"), command(40, 'expect(out.cause).toBeUndefined();'), output(40, '42 passed')], artifact='src/error-stack.test.ts', symbol='provided errorStack with default includeCauses drops cause')
material('E10', 'implementation', 'read_only', 'Actual direct branch retains raw v.cause; recursively visited under unchanged instance settings. This is the cause of grandcause leakage', ['G1:direct_configuration_and_dataflow'],
         [command(24, "if (errorStack.includeCauses === 'direct') {\n      if (v.cause instanceof Error) {\n        baseError.cause = v.cause;"), output(49, "if (errorStack.includeCauses === 'direct') {"), output(49, 'baseError.cause = v.cause;')], artifact='src/transformer.ts', symbol='transformError')
material('E11', 'implementation', 'read_only', 'Actual deep helper clones bounded Error chains and strips the terminal cause; offers construct/strip patterns but is not an independent expected-result source', ['G1:nested_error_constructor_pattern', 'G1:terminal_edge_pattern'],
         [command(24, 'function truncateCauseChain(error: Error, maxDepth: number): Error | undefined {'), command(24, 'delete clone.cause;'), command(24, 'result = cloneError(chain[i], result);')], artifact='src/transformer.ts', symbol='cloneError/truncateCauseChain')
material('E12', 'implementation', 'read_only', 'Original walker recursively serializes transformed cause under the same SuperJSON instance; exact execution connection read at9', ['G1:recursive_consumer_connection'],
         [output(9, 'const recursiveResult = walker(\n      value,\n      identities,\n      superJson,'), output(9, 'const transformed = transformationResult?.value ?? object;')], origin='repo_preexisting', artifact='src/plainer.ts', symbol='walker')
material('E13', 'reasoning', 'reasoning_only', 'Early design restates direct immediate versus deep recursive and plans actual-Error cause values to retain annotations', ['G1:mode_contract_and_recursive_connection'],
         [reasoning(16, "`direct` keeps the immediate cause. `deep` keeps causes recursively up to `maxCauseDepth`"), reasoning(16, "If we simply include `cause = v.cause`, the walker will recurse infinitely until it detects circular references")])
material('E14', 'reasoning', 'reasoning_only', 'Late step62 explicitly notices SAME config re-applies while walker transforms cause, but checks and resolves only deep-mode re-cloning', ['G1:recursive_connection'],
         [reasoning(62, "The cause's rule selection depends on the cause's name and the SAME errorStack config."), reasoning(62, "the `Error` rule's transform (default) when errorStack present: includeCauses handling applies again!")])
material('E15', 'issue_or_documentation', 'read_only', 'Issue supplies direct=one immediate cause versus deep=recursive contract; deriving grandcause absence is necessary for every corrected direct test', ['G1:correct_direct_depth_oracle'],
         [{'channel': 'issue', 'path': case['issue'], 'quote': '`direct` keeps the immediate cause.'}], origin='issue', artifact='instruction.md', symbol='includeCauses requirement')
material('E16', 'reasoning', 'reasoning_only', 'Late step64 again checks off immediate-cause requirement, then tests only direct-message sanitization', ['G1:correct_mode_contract'],
         [reasoning(64, 'direct immediate cause; deep recursive up to maxCauseDepth default 16'), reasoning(64, 'In direct mode, the immediate cause is included as an actual Error in baseError.cause. The walker transforms it')])

recipes = [
    {'id': 'R1', 'gap': 'G1', 'qualification': 'requires_oracle_inference',
     'slots': [{'role': '原有 direct roundtrip 基础测试', 'alternatives': [['E1'], ['E2'], ['E3']]},
               {'role': '现成的多层 Error 输入', 'alternatives': [['E4'], ['E5']]},
               {'role': 'direct 深度1的正确预期', 'alternatives': [['E15'], ['E13'], ['E16']]}],
     'forbidden_pairs': [],
     'compatibility': '保留任一 direct 基础测试的 mode、roundtrip 和即时 cause 断言，换成已有多层 Error 链；从 direct 仅保留立即 cause 推导 out.cause.cause 必须为空。off 与 string 是同一 includeCauses 实现路径；sanitize 版本保留原消息预期。E4 非 Error 尾节点可保留，E5 更长链也可直接使用。',
     'semantic_additions': ['新增 grandcause-absence 断言；深度2/16的旧 oracle 不能原样复制到 direct。显式 maxCauseDepth=5 并非揭错所必需，若要逐字重现 heldout 可用 E7 配置值。']},
    {'id': 'R2', 'gap': 'G1', 'qualification': 'requires_oracle_inference',
     'slots': [{'role': '仓库原有 Error cause roundtrip', 'alternatives': [['E6']]},
               {'role': 'direct 实例配置', 'alternatives': [['E1'], ['E2'], ['E3']]},
               {'role': '已有深链输入', 'alternatives': [['E4'], ['E5']]},
               {'role': '正确 direct 边界约定', 'alternatives': [['E15'], ['E13'], ['E16']]}],
     'forbidden_pairs': [],
     'compatibility': '原仓库 cause 表格本来验证默认无限 cause 行为；必须改为当前 direct 实例调用，保留原消息/type 检查后使用已有深链和新的深度1缺席检查。材料组明确包含被改写的旧测试，不能将默认语义测试原样视为 direct 证据。',
     'semantic_additions': ['将原 static/default harness 改为 direct 配置实例；新增 grandcause 缺席关系。']},
    {'id': 'R3', 'gap': 'G1', 'qualification': 'requires_oracle_inference',
     'slots': [{'role': '深链与深度观察均已存在的测试', 'alternatives': [['E4'], ['E5']]},
               {'role': '已有 direct 模式语义', 'alternatives': [['E15'], ['E13'], ['E16']]}],
     'forbidden_pairs': [],
     'compatibility': '直接从深链测试出发，把 includeCauses deep 变为 direct；E4 保留即时 cause 检查，将原更深节点检查变为第二条 cause 不存在；E5 保留遍历算法，把期望深度16改为1。这一构造不需要额外依赖某一 direct35 测试。',
     'semantic_additions': ['切换模式并推导对应的新边界/深度1 oracle；不把旧 deep 成功当作 direct 正确性的证据。']},
    {'id': 'R4', 'gap': 'G1', 'qualification': 'requires_oracle_inference',
     'slots': [{'role': '原 direct 测试及构造器', 'alternatives': [['E1'], ['E2'], ['E3']]},
               {'role': '已有原因链构造/截断操作', 'alternatives': [['E11']]},
               {'role': '正确 direct 边界约定', 'alternatives': [['E15'], ['E13'], ['E16']]}],
     'forbidden_pairs': [],
     'compatibility': '实现中已读到 Error cause 链和 terminal cause 删除模式，可据同一对象类型在原 inner Error 上构造第二条 cause；必须新增输入 Error 和独立边界断言，不能调用错误的 direct 分支来给自己的输出充当正确预期。',
     'semantic_additions': ['从实现链条结构构造多层输入，新增 direct 边界断言；属于源码操作加测试的材料路线。']},
]

review = {
    'case_id': 'S072', 'reviewer': 'Codex /root',
    'full_read': {'line_ranges': [[1, 13049]], 'steps': 70, 'unread': [], 'metadata_read': True,
                  'note': 'All retained trajectory text read before consulting old adjudication. Original harness omissions remain omitted; truncated root reads were reread in smaller ranges.'},
    'evaluation_families': [{'id': 'G1', 'failed_tests': [x['name'] for x in failures],
       'contract': 'Issue explicitly distinguishes direct immediate-only versus deep recursive causes. direct must retain level2 and drop level3 independently of a valid positive maxCauseDepth.',
       'missing_joint_test': "SuperJSON({errorStack:{mode:'string',includeCauses:'direct',maxCauseDepth:5}}) roundtrips level1→level2→level3; assert immediate cause retained and out.cause.cause undefined. Any historical deeper chain and off-mode direct also test the same defect.",
       'classification': 'untested_interaction', 'verifier_validity': 'supported', 'joint_attempt': 'absent',
       'required_components': ['direct instance mode', 'immediate Error that itself has an Error cause', 'roundtrip', 'immediate retention plus grandcause absence check'],
       'patch_explanation': 'transformError forwards raw v.cause for direct; walker recursively visits every cause with the unchanged direct instance. Unlike deep, direct never removes the retained child’s cause. maxCauseDepth5 is incidental, not a necessary interacting factor.'}],
    'materials': materials, 'recipes': recipes,
    'agent_process': {'joint_attempt': 'absent', 'explanations': [
       {'label': 'feature_checklist_independent_fixtures', 'support': 'direct',
        'interpretation': 'Direct and multi-level deep fixtures were authored in the very same step35 test file; direct checked only one-level input. Subsequent additions test modes, sanitizer, nonError and defaults separately, without the nested direct boundary.',
        'refs': [command(35, "it('round-trips causes with includeCauses direct',"), command(35, "it('includeCauses deep respects maxCauseDepth and drops non-Error causes',"), command(40, "it('deep defaults to maxCauseDepth 16',"), command(64, "it('sanitizes direct cause messages',")]},
       {'label': 'recursive_effect_applied_only_to_deep_reasoning', 'support': 'direct',
        'interpretation': 'Agent explicitly noticed repeated transform under the SAME configuration in late step62, but reasoned only through deep cloning and concluded it correct. It failed to apply its own recursion observation to the raw direct branch; this is a local reasoning/validation omission despite the relevant facts remaining in current attention.',
        'refs': [reasoning(62, "includeCauses handling applies again!"), reasoning(62, 'The total depth is still N'), reasoning(64, 'direct immediate cause; deep recursive up to maxCauseDepth default 16')]},
       {'label': 'green_suite_as_completion_signal', 'support': 'direct',
        'interpretation': 'The suite grows from29 to51 new tests and131→133 total passes. Agent repeatedly checks all requirement bullets, then submits voluntarily; metadata has no step/cost/time limit. Long trajectory length alone does not establish memory loss.',
        'refs': [output(69, '133 passed'), reasoning(70, 'All done. The working tree is clean, all tests pass')]}],
       'forgetting_assessment': 'counterevidence'},
    'prior_record_corrections': ['Old direct35 + deep35 is a valid route but not unique: off47/direct-sanitize64, default16 chain40, the original repository cause test, source clone helpers and explicit late reasoning supply alternative starting material.', 'Do not call this context-only repair: adding a deeper cause while retaining only the original immediate-cause assertions still passes; a new boundary assertion is required.', 'maxCauseDepth5 is one heldout configuration, not a necessary ingredient for exposing direct recursion leakage.'],
    'uncertainties': ['Material routes are manually reconstructed; this audit did not execute newly assembled tests. No evidence that Agent ever ran nested direct input with the correct boundary check.']
}
(directory / 'manual_review.json').write_text(json.dumps(review, ensure_ascii=False, indent=2) + '\n')
(directory / 'reviewer_notes.txt').write_text('Read all 13049 retained lines /70 steps and metadata. One failed family, supported by explicit direct-vs-deep contract. All meaningful direct/nested input/oracle/provider alternatives recorded; repeated exact reprints are linked as refs, not new sources. Direct plus nested never jointly executed. Step35 writes both constituents together; late62/64 reason about recursive propagation explicitly. Correct absence oracle still requires derivation.\n')
