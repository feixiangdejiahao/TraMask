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


material('E1', 'agent_validation', 'executed_pass', 'Legacy integration uses fresh new SuperJSON() and raw-stack roundtrip without errorStack', ['G1:default_receiver'],
         [command(29, "it('keeps existing behavior when errorStack is omitted',"), command(29, 'const sj = new SuperJSON();'), output(31, '36 passed'), output(67, '131 passed')], artifact='src/error-stack.test.ts', symbol='keeps existing behavior when errorStack is omitted')
material('E2', 'agent_validation', 'executed_pass', 'Configured string-mode processor checks sanitized message and returns extra; restored extra checked after roundtrip', ['G1:registration_and_hook_observation', 'G2:processor_harness'],
         [command(29, "it('runs registerErrorStackProcessor after all serialization steps',"), command(30, "expect(serialized.stack).toContain('Error: visit https://example.com');"), command(29, "expect(out.extra).toBe('added');"), output(31, '36 passed')], artifact='src/error-stack.test.ts', symbol='runs registerErrorStackProcessor after all serialization steps')
material('E3', 'agent_validation', 'executed_pass', 'Configured deep processor test counts hook calls and asserts one top-level invocation', ['G1:registration_and_call_observation'],
         [command(52, "it('runs the processor once for the top-level error, not for causes',"), command(52, 'expect(calls).toBe(1);'), output(52, '126 passed'), output(67, '131 passed')], artifact='src/error-stack.test.ts', symbol='runs the processor once for the top-level error, not for causes')
material('E4', 'agent_validation', 'executed_pass', 'Nonmatching-class processor negative control registers Error callback with TypeError-only filter and asserts zero calls', ['G1:registration_and_call_observation', 'G3:class_filter_setup'],
         [command(29, "it('does not run the processor for non-matching classes',"), command(29, "errorStack: { mode: 'string', classFilter: ['TypeError'] }"), command(29, 'expect(calls).toBe(0);'), output(31, '36 passed')], artifact='src/error-stack.test.ts', symbol='does not run the processor for non-matching classes')
material('E5', 'agent_validation', 'executed_pass', 'Frames container test registers processor, inserts Date and checks Date after roundtrip', ['G1:registration_and_output_observation', 'G2:frames_consumer'],
         [command(29, "it('round-trips container types inside stackFrames',"), command(29, "expect(out.stackFrames[0].date).toBeInstanceOf(Date);"), output(31, '36 passed')], artifact='src/error-stack.test.ts', symbol='round-trips container types inside stackFrames')
material('E6', 'repo_test', 'executed_pass', 'Original works for Errors table: bare Error, default serialization and explicit name/message checks', ['G1:legacy_error_harness'],
         [output(10, "'works for Errors': {"), output(10, "e: new Error('epic fail'),"), output(10, "expect(e.message).toBe('epic fail');"), output(25, '82 passed'), output(67, '131 passed')], origin='repo_preexisting', artifact='src/index.test.ts', symbol='works for Errors')
material('E7', 'repo_test', 'executed_pass', 'Original works for Error causes table: cause constructor and retained inner name/message', ['G1:legacy_error_harness', 'G3:cause_constructor'],
         [output(10, "'works for Error causes': {"), output(10, "cause: new Error('catastrophic failure'),"), output(10, "expect(e.cause?.message).toBe('catastrophic failure');"), output(25, '82 passed')], origin='repo_preexisting', artifact='src/index.test.ts', symbol='works for Error causes')
material('E8', 'repo_test', 'executed_pass', 'Original regression108 default roundtrip distinguishes absent versus explicitly allowed raw stack', ['G1:legacy_error_harness'],
         [output(10, "test('regression #108: Error#stack should not be included by default',"), output(10, 'expect(thatShouldExist).toEqual(input.stack);'), output(25, '82 passed')], origin='repo_preexisting', artifact='src/index.test.ts', symbol='regression #108')
material('E9', 'agent_validation', 'executed_pass', 'Standalone string basename test uses five parenthesized path frames; exact basename expected for each', ['G2:redaction_input_and_oracle'],
         [command(29, "it('redacts paths to basenames',"), command(29, "'at alpha (alpha.ts:1:1)\\n'"), output(31, '36 passed')], artifact='src/error-stack.test.ts', symbol='redacts paths to basenames')
material('E10', 'temporary_probe', 'executed_output', 'Built /tmp/e2e.mjs all-options run includes basename, max3, strip, deep and sanitizer; actual parenthesized paths redacted successfully', ['G2:redaction_and_hook_input', 'G3:sanitized_cause_harness'],
         [command(55, "redactPaths: 'basename',"), command(55, "cause: new Error('inner cause'),"), output(56, 'at foo (foo.ts:1:1)'), output(56, 'cause: inner cause')], artifact='/tmp/e2e.mjs', symbol='sj.serialize({e})')
material('E11', 'agent_validation', 'executed_pass', 'Original processing fixture: alpha/beta/gamma/delta parenthesized paths, string+frames trimming and order tests', ['G2:path_fixture', 'G2:mode_limit_strip_context'],
         [command(29, "'    at alpha (/app/src/alpha.ts:1:1)\\r\\n'"), command(29, "it('frames mode applies stripInternalFrames before maxStackLines',"), command(29, "it('string mode applies maxStackLines before stripInternalFrames',"), output(31, '36 passed')], artifact='src/error-stack.test.ts', symbol='error-stack processing fixture and order tests')
material('E12', 'agent_validation', 'executed_pass', 'String roundtrip with trim=false and max2, exact whitespace preserved in output; no redaction configured', ['G2:untrimmed_roundtrip_context'],
         [command(29, "it('string mode serializes and restores a processed stack',"), command(29, 'trimLeadingWhitespace: false,'), output(31, '36 passed')], artifact='src/error-stack.test.ts', symbol='string mode serializes and restores a processed stack')
material('E13', 'agent_validation', 'executed_pass', 'Frames roundtrip has two parenthesized paths and exact raw entries; no redaction configured', ['G2:frames_roundtrip_context'],
         [command(29, "it('frames mode serializes and restores stackFrames',"), command(29, "{ raw: 'at b (/app/b.ts:2:2)' }"), output(31, '36 passed')], artifact='src/error-stack.test.ts', symbol='frames mode serializes and restores stackFrames')
material('E14', 'agent_validation', 'executed_pass', 'Raw options processing test supplies string and frames max2 and exact shortened path-bearing output', ['G2:mode_limit_context'],
         [command(45, "it('accepts raw (non-normalized) options',"), command(45, "const rawFrames = { mode: 'frames', maxStackLines: 2 }"), output(46, '43 passed')], artifact='src/error-stack.test.ts', symbol='accepts raw (non-normalized) options')
material('E15', 'agent_validation', 'executed_pass', 'classFilter test constructs both Error and TypeError and checks standalone processing selection; no cause or sanitizer', ['G3:class_filter_and_error_names'],
         [command(29, "it('classFilter restricts processing to matching error names',"), command(29, "const plain: any = new Error('plain');"), command(29, "const type: any = new TypeError('type');"), command(29, "expect(out.plain.stack).toBeUndefined();"), output(31, '36 passed')], artifact='src/error-stack.test.ts', symbol='classFilter restricts processing to matching error names')
material('E16', 'agent_validation', 'executed_pass', 'Sanitize+deep cause test checks outer URL and inner email both redacted; no classFilter', ['G3:sanitizer_cause_input_and_harness'],
         [command(29, "it('sanitizes the error message and every kept cause message',"), command(29, "expect(out.cause.message).toBe('mail [redacted]');"), output(31, '36 passed')], artifact='src/error-stack.test.ts', symbol='sanitizes the error message and every kept cause message')
material('E17', 'agent_validation', 'executed_pass', 'Direct cause test constructs outer→inner, verifies Error instance, immediate message, and no deeper cause', ['G3:direct_cause_harness'],
         [command(29, "it('includeCauses direct keeps the immediate cause',"), command(29, "expect('cause' in out.cause).toBe(false);"), output(31, '36 passed')], artifact='src/error-stack.test.ts', symbol='includeCauses direct keeps the immediate cause')
material('E18', 'agent_validation', 'executed_pass', 'Standalone sanitizer test supplies inner-reusable URL plus exact redaction expected string', ['G3:sensitive_message_input_and_oracle'],
         [command(29, "sanitizeMessage('see https://example.com/path?q=1 and http://a.b')"), command(29, ").toBe('see [redacted] and [redacted]');"), output(31, '36 passed')], artifact='src/error-stack.test.ts', symbol='sanitizeMessage/redacts URLs, emails, and IPv4 addresses')
material('E19', 'reasoning', 'reasoning_only', 'Step51 explicitly notices basename leaves unparenthesized path frame unchanged and calls that Good; supplies alternative frame-layout information', ['G2:unparenthesized_frame_layout'],
         [reasoning(51, "**`processStackString` with `redactPaths: 'basename'` on a frame with no parentheses**: unchanged. Good.")])
material('E20', 'implementation', 'read_only', 'basename regex matches only parenthesized paths, shared by both string and frames routes', ['G2:format_boundary'],
         [command(18, r"return line.replace(/\(([^()]*?)([^/\\()]+)\)/g, '($2)');"), output(42, 'Replace "path/to/file.ts:1:2" with "file.ts:1:2" inside parentheses.')], artifact='src/error-stack.ts', symbol='redactPath')
material('E21', 'implementation', 'read_only', 'Top-level selection has matchesClassFilter; manually serialized cause leaf sanitizes unconditionally and bypasses this selection', ['G3:producer_consumer_bypass'],
         [command(20, 'return options.classFilter.includes(error.name);'), command(20, 'result.message = sanitizeMessage(result.message);'), output(48, 'return serializeErrorLeaf(cause, options);'), command(51, 'const result = serializeErrorLeaf(cause, options);')], artifact='src/transformer.ts', symbol='matchesClassFilter/serializeErrorCause/serializeErrorLeaf')
material('E22', 'reasoning', 'reasoning_only', 'Step14 explicitly chooses to run hook only in processing rules, excluding default Error path; repeated in26', ['G1:explicit_scope_assumption'],
         [reasoning(14, "The spec ties it to error stack processing, so I'll only run it in the processing rules."), reasoning(26, "The hook receives baseError before plainer walks. Good.")])
material('E23', 'reasoning', 'reasoning_only', 'Step57 correctly discusses nonmatching AggregateError.errors messages remaining unsanitized via recursive walker; does not transfer this rule to plain cause serializer', ['G3:correct_per_error_filter_relation'],
         [reasoning(57, 'If a non-matching error in errors, default rule used, not sanitized. That\'s consistent with classFilter restricting sanitization.')])
material('E24', 'issue_or_documentation', 'read_only', 'Issue specifies classFilter per error.name, basename without parentheses restriction, and a registered post-serialization hook by class name', ['G1:hook_contract', 'G2:basename_contract', 'G3:filter_contract'],
         [{'channel': 'issue', 'path': case['issue'], 'quote': '`classFilter` restricts stack processing and sanitization to errors with matching `.name`'},
          {'channel': 'issue', 'path': case['issue'], 'quote': '`basename` keeps only the filename'},
          {'channel': 'issue', 'path': case['issue'], 'quote': 'registers a post-serialization hook by error class name'}], origin='issue', artifact='instruction.md')

def recipe(rid, gap, qualification, slots, compatibility, additions):
    return {'id': rid, 'gap': gap, 'qualification': qualification,
            'slots': [{'role': role, 'alternatives': alternatives} for role, alternatives in slots],
            'forbidden_pairs': [], 'compatibility': compatibility, 'semantic_additions': additions}


recipes = [
    recipe('R1', 'G1', 'requires_oracle_inference',
           [('无errorStack的原有实例/默认测试', [['E1'], ['E6'], ['E7'], ['E8']]),
            ('现成注册hook与观察方式', [['E2'], ['E3'], ['E4'], ['E5']]),
            ('注册即生效的任务约定', [['E24']])],
           '将注册和回调观察转移到已有默认配置Error序列化。回调设置called或递增计数并检查至少调用一次；E2的sanitize预期、E5的frames返回值预期不能照搬到默认配置。若用E7/3的cause链，也不能盲目保留总计数等于1。',
           ['需要推导默认路径也运行已注册hook的正向预期；使用回调是否发生的观察，不把其他模式下特定输出原样当oracle。']),
    recipe('R2', 'G2', 'requires_transfer',
           [('可复用basename输入和正确预期', [['E9'], ['E10']]),
            ('历史中的无括号格式提示', [['E19']])],
           '保持相同绝对路径、filename和basename预期，把命名函数括号形式at f(/path/file.ts:1:1)换成历史推理提到的无括号格式at /path/file.ts:1:1。单string模式已揭同一缺陷，无需额外开关才会失败。',
           ['无括号布局只在reasoning明确出现，没有找到同格式成功/失败的历史输入执行；需要据提示改写fixture。']),
    recipe('R3', 'G2', 'requires_transfer',
           [('具体调用context', [['E2'], ['E5'], ['E11'], ['E12'], ['E13'], ['E14']]),
            ('已有basename配置与预期', [['E9'], ['E10']]),
            ('历史无括号布局提示', [['E19']])],
           '在相应hook、trim=false、string/frames、max2或strip+max harness中移入basename配置及无括号绝对路径；保留原模式约定，检查目录消失而basename保留。各额外设置分别对应7个heldout变体，但都在同一basename匹配边界失败。',
           ['无括号输入需从自然语言布局提示具体化；不能把7个相同底层redaction失败都宣称为7种独立feature交互。']),
    recipe('R4', 'G3', 'requires_oracle_inference',
           [('带敏感消息的原因链或可复用原因链', [['E16'], ['E10'], ['E17', 'E18'], ['E7', 'E18']]),
            ('Error/TypeError与classFilter选择', [['E15'], ['E4']]),
            ('逐个Error适用的正确filter关系', [['E24'], ['E23']])],
           '让外层TypeError匹配TypeError-only filter，内层Error不匹配；保留敏感URL/email，开启sanitize和direct/deep。外层消息变redacted，内层消息保持原值。E16中两层都redact的旧预期只适用于无filter，不能复制。E10探针缺硬断言，可借其序列化/反序列化调用。',
           ['新增按对象.name分别判断适用性的oracle；历史已执行filter和sanitize+cause，但未联合执行混合cause名称加filter。']),
]

redact_names = [x['name'] for x in failures if 'redactPaths' in x['name'] or 'already-redacted' in x['name']]
families = [
    {'id': 'G1', 'failed_tests': [x['name'] for x in failures if 'fires even when no' in x['name']],
     'contract': 'New instance hook is registered by error class name; the issue does not make registration depend on setting errorStack. Explicitly opting into the new hook can affect a legacy-configured instance without changing untouched legacy behavior.',
     'missing_joint_test': 'Create new SuperJSON() with no errorStack; register Error callback; serialize an Error; assert callback runs and receives original message.',
     'classification': 'untested_interaction', 'verifier_validity': 'supported', 'joint_attempt': 'absent',
     'required_components': ['default instance', 'registered Error processor', 'Error serialization', 'callback occurrence check'],
     'patch_explanation': 'Default Error transformation never consults registry; only configured string/frames helper invokes processors.'},
    {'id': 'G2', 'failed_tests': redact_names,
     'contract': 'basename keeps filename in stack frames; the requirement does not restrict path-bearing frames to those inside parentheses.',
     'missing_joint_test': 'Use an unparenthesized frame such as at /Users/john/app.ts:1:1 with basename; assert directory absent and filename retained. Seven failed tests cover ordinary string, frames, max2, frames strip+max, trim=false and processor observation; all fail the same missing layout.',
     'classification': 'different_stimulus', 'verifier_validity': 'supported', 'joint_attempt': 'absent',
     'required_components': ['basename', 'unparenthesized absolute-path frame', 'directory absence check'],
     'patch_explanation': 'Shared basename regex only rewrites text enclosed in parentheses. Extra max/trim/frames/hook factors are not necessary for failure.'},
    {'id': 'G3', 'failed_tests': [x['name'] for x in failures if 'cause errors that fail classFilter' in x['name']],
     'contract': 'classFilter restricts sanitization for each error according to its own name, including kept causes.',
     'missing_joint_test': 'Roundtrip/serialize a TypeError outer with Error cause, both carrying sensitive URLs; classFilter=[TypeError], sanitize=true, direct. Outer must be redacted, inner kept unchanged.',
     'classification': 'untested_interaction', 'verifier_validity': 'supported', 'joint_attempt': 'absent',
     'required_components': ['matching outer', 'nonmatching inner cause', 'sensitive message', 'sanitize=true and cause retention', 'per-object expected message'],
     'patch_explanation': 'Top-level rule selection checks classFilter, but serializeErrorLeaf used by cause helper sanitizes without checking cause.name. Late refactor51 preserves this bypass.'},
]
review = {'case_id': 'S071', 'reviewer': 'Codex /root',
          'full_read': {'line_ranges': [[1, 13179]], 'steps': 68, 'unread': [], 'metadata_read': True,
                        'note': 'All retained text read;2351-2900 output was reread in two bounded ranges. Failed definitions independently read from verifier patch after fullread; old focal review consulted last.'},
          'evaluation_families': families, 'materials': materials, 'recipes': recipes,
          'agent_process': {'joint_attempt': 'absent', 'explanations': [
              {'label': 'explicit_hook_scope_narrowing', 'support': 'direct',
               'interpretation': 'Step14 actively reasons that the name error-stack processor ties hooks to configured processing, so intentionally excludes default Error. Legacy and hook tests are authored together29; their separation is design policy, not evidence of forgetting.',
               'refs': [reasoning(14, "The spec ties it to error stack processing, so I'll only run it in the processing rules."), command(29, "it('keeps existing behavior when errorStack is omitted',"), command(29, "it('runs registerErrorStackProcessor after all serialization steps',")]},
              {'label': 'recognized_input_format_left_unsupported', 'support': 'direct',
               'interpretation': 'At51 Agent explicitly notices unparenthesized frames are unchanged and calls that correct. Its basename tests consistently use parenthesized fixtures. This explains all7 redaction failures more directly than a generic missed pair of options.',
               'refs': [reasoning(51, "on a frame with no parentheses**: unchanged. Good."), command(29, "it('redacts paths to basenames',")]},
              {'label': 'manual_cause_path_bypasses_per_object_selection', 'support': 'inferred',
               'interpretation': 'To control cause depth, Agent serializes causes as plain leaves outside normal rule selection. It tests global sanitization and standalone filter selection separately; at57 it even correctly explains filter behavior for AggregateError.errors, which still follows walker, but does not transfer that relation to cause leaves.',
               'refs': [command(20, 'result.message = sanitizeMessage(result.message);'), command(29, "it('classFilter restricts processing to matching error names',"), command(29, "it('sanitizes the error message and every kept cause message',"), reasoning(57, 'If a non-matching error in errors, default rule used, not sanitized.')]},
              {'label': 'checklist_and_suite_completion', 'support': 'direct',
               'interpretation': 'Repeated requirement checklists and growing49-test suite pass; metadata has unlimited step/cost/time. Submission is voluntary. None of three families has a demonstrated correct failing historical joint check later forgotten.',
               'refs': [reasoning(64, 'All 131 tests pass.'), output(67, '131 passed'), reasoning(68, 'Everything is clean:')]}],
              'forgetting_assessment': 'counterevidence'},
          'prior_record_corrections': ['Old analysis selected only default+hook failure. This review covers all9 failed named records as3 distinct contracts, including7 shared basename-layout failures and mixed-name cause filtering.', 'Hook-count1 from configured deep test52 is not automatically transferable to legacy raw cause recursion; use callback occurrence or a one-error input.', 'Historical basename+all-options probe55/56 already exists, but all source paths are parenthesized. More feature switches alone do not supply the missing input layout.'],
          'uncertainties': ['New material assemblies were not executed in this audit.', 'The no-parentheses input form is explicitly present as reasoning51, not a prior retained executable fixture; removing reasoning requires introducing that stimulus shape from the task/API domain.']}
(directory / 'manual_review.json').write_text(json.dumps(review, ensure_ascii=False, indent=2) + '\n')
(directory / 'reviewer_notes.txt').write_text('Fullread13179lines/68steps+metadata. All9 actual failed names mapped to3families. Hook default excludes registration by explicit14policy. Sevenbasename failures share missing bareframe layout, recognized51 as unchanged/Good. Mixedname cause sanitization bypasses classFilter in manual serializer; standalone filter and sanitizer tests co-resident29. All meaningful source alternatives, semantics needed, and no-parentheses reasoning-only form retained.\n')
