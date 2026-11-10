import json
from pathlib import Path

directory = Path(__file__).parent
case = json.loads((directory / 'case.json').read_text())
failures = json.loads((directory / 'evaluation_failures.json').read_text())['failed_tests']
inventory = json.loads(Path(case['repository_materials']).read_text())
entries = {entry['path']: entry for entry in inventory['entries']}
cas = Path(case['repository_materials']).parents[2] / 'cas/sha256'


def command(step, quote):
    return dict(step=step, call=0, channel='command', quote=quote)


def output(step, quote):
    return dict(step=step, call=0, channel='output', quote=quote)


def reasoning(step, quote):
    return dict(step=step, channel='reasoning', quote=quote)


def repo(name, quote):
    sha = entries[name]['sha256']
    return dict(channel='repo', path=str(cas / sha[:2] / sha), quote=quote)


materials = []


def material(mid, kind, availability, unit, supports, refs, artifact='', symbol='', origin='agent_authored'):
    materials.append(dict(id=mid, kind=kind, origin=origin, availability=availability,
                          unit=unit, supports=supports, refs=refs, artifact=artifact, symbol=symbol))


material('L57', 'temporary_probe', 'executed_pass', 'Actual Invalid+recovery callback+lash hard assertion already jointly executed; deliberately expects original Invalid', ['G1:existing_joint_method_test'],
         [command(57, "assert Invalid((1,)).lash(lambda e: Valid('recovered')) == Invalid((1,))"), output(57, 'ALL OK')])
material('L95', 'agent_validation', 'executed_pass', 'Independent pytest test_lash repeats Invalid+recovering callback but expects Invalid', ['G1:existing_joint_method_test'],
         [command(95, 'def test_lash():'), command(95, 'assert Invalid((1,)).lash(lambda e: Valid(2)) == Invalid((1,))'), output(96, '27 passed')], '/tmp/test_validated_full.py', 'test_lash')
material('J84', 'temporary_probe', 'executed_pass', 'Actual joint Fold.collect_all+new Validated mixed input and Valid empty accumulator; wrong accumulated-error hard oracle', ['G2:existing_joint_consumer_test'],
         [command(84, 'res = Fold.collect_all((Invalid((1,)), Invalid((2,)), Valid(3)), Valid(()))'), command(84, 'assert res == Invalid((1, 2))'), output(84, 'ALL EDGE OK')])
material('C61', 'temporary_probe', 'executed_pass', 'Fold.collect all-valid, mixed and multiple-error producer sequence with valid accumulator', ['G2:validated_sequence_and_accumulator'],
         [command(61, 'Fold.collect((Invalid((1,)), Invalid((2,)), Valid(3)), Valid(()))'), output(61, 'Fold.collect OK')])
material('C95', 'agent_validation', 'executed_pass', 'Independent pytest Fold.collect fixture, two Invalid values and valid accumulator', ['G2:validated_sequence_and_accumulator'],
         [command(95, 'def test_fold_collect():'), command(95, 'Fold.collect((Invalid((1,)), Invalid((2,))), Valid(()))'), output(96, '27 passed')], '/tmp/test_validated_full.py', 'test_fold_collect')
material('P57', 'temporary_probe', 'executed_pass', 'Raw Invalid tuple plus alt multi-error fixture; independent producer for recovery or collection', ['G1:invalid_tuple_producer', 'G2:invalid_producer'],
         [command(57, "assert Invalid(('a', 'b')).alt(lambda s: s+'!') == Invalid(('a!', 'b!'))"), output(57, 'ALL OK')])
material('P95', 'agent_validation', 'executed_pass', 'Independent multi-error apply test produces Invalid with three errors', ['G1:invalid_tuple_producer', 'G2:invalid_producer'],
         [command(95, "assert Invalid(('a', 'b')).apply(Invalid(('c',))) == Invalid(('a', 'b', 'c'))"), output(96, '27 passed')], '/tmp/test_validated_full.py', 'test_apply')
material('U57', 'temporary_probe', 'executed_pass', 'from_failure constructor makes single Invalid for later recovery/collection', ['G1:invalid_producer', 'G2:invalid_producer'],
         [command(57, 'assert Validated.from_failure(1) == Invalid((1,))'), output(57, 'ALL OK')])
material('U95', 'agent_validation', 'executed_pass', 'Independent pytest from_failure constructor fixture', ['G1:invalid_producer', 'G2:invalid_producer'],
         [command(95, 'def test_from_failure():'), command(95, "assert Validated.from_failure('a') == Invalid(('a',))"), output(96, '27 passed')], '/tmp/test_validated_full.py', 'test_from_failure')
material('R57', 'temporary_probe', 'executed_pass', 'Result Failure→Validated.from_result producer', ['G1:invalid_producer', 'G2:invalid_producer'],
         [command(57, 'assert Validated.from_result(Failure(1)) == Invalid((1,))'), output(57, 'ALL OK')])
material('R95', 'agent_validation', 'executed_pass', 'Independent pytest Failure→Invalid producer', ['G1:invalid_producer', 'G2:invalid_producer'],
         [command(95, 'def test_from_result():'), command(95, 'assert Validated.from_result(Failure(1)) == Invalid((1,))'), output(96, '27 passed')], '/tmp/test_validated_full.py', 'test_from_result')
material('O8', 'implementation', 'read_only', 'Original Result.lash documentation explicitly includes Failure recovering into Success', ['G1:independent_recovery_oracle'],
         [output(8, "assert Failure('aa').lash(lashable) == Success('aab')")], 'returns/result.py', 'Result.lash', 'repo_preexisting')
material('O9', 'implementation', 'read_only', 'Original Failure.lash directly invokes callback on held error', ['G1:independent_recovery_oracle'],
         [output(9, 'return function(self._inner_value)')], 'returns/result.py', 'Failure.lash', 'repo_preexisting')
material('O25', 'implementation', 'read_only', 'Second existing IOFailure.lash invokes failure recovery callback, not no-op', ['G1:independent_recovery_oracle'],
         [output(25, 'return function(self._inner_value.failure())')], 'returns/io.py', 'IOFailure.lash', 'repo_preexisting')
material('D16', 'implementation', 'read_only', 'Original Fold safe concatenation explicitly calls lash(lambda _: acc) fallback', ['G2:consumer_and_independent_oracle', 'G1:independent_recovery_use'],
         [output(16, 'We need both ``.apply`` and ``.lash`` methods here.'), output(16, 'return _concat_applicative(current, acc, function).lash(lambda _: acc)')], 'returns/iterables.py', '_concat_failable_safely', 'repo_preexisting')
material('N27', 'implementation', 'read_only', 'Existing LashableN abstract contract applies function and returns a new container', ['G1:inherited_interface_contract'],
         [output(27, "Applies 'function' to the result of a previous calculation.")], 'returns/interfaces/lashable.py', 'LashableN.lash', 'repo_preexisting')
material('Q39', 'reasoning', 'reasoning_only', 'Early explicit tuple-recovery proposal; not an executed upstream witness', ['G1:correct_tuple_recovery_proposal'],
         [reasoning(39, 'return function(self._inner_value)'), reasoning(39, 'if the function returns Valid, it becomes Valid')])
material('Q74', 'reasoning', 'reasoning_only', 'Correct consumer/fallback trace explicitly recognizes collect_all would break', ['G1:correct_recovery_alternative', 'G2:correct_fallback_alternative'],
         [reasoning(74, "my no-op `lash` would break it"), reasoning(74, 'if result is Failure, `.lash(lambda _: acc)` recovers to acc.')])
material('Q127', 'reasoning', 'reasoning_only', 'Late after-commit explicit correct recovery example and Fold.collect_all connection; consciously rejected', ['G1:correct_recovery_alternative', 'G2:correct_fallback_alternative'],
         [reasoning(127, "`Invalid((1,2)).lash(lambda errs: Valid('recovered'))` returns `Valid('recovered')`."), reasoning(127, 'That would make `collect_all` behave like Result: on any failure, fallback to acc.')])
material('T44', 'implementation', 'written_unexecuted', 'New Invalid.lash intentionally implemented return self; producer and public consumer API are visible in authored source', ['G1:recovery_target'],
         [command(44, 'def lash('), command(44, 'return self')], 'returns/validated.py', 'Invalid.lash')
material('RC', 'repo_test', 'repo_unseen', 'Preexisting Fold.collect_all Result/IO/Maybe table explicitly skips failures; exact source not retained in Agent reads, despite stock suite execution', ['G2:existing_consumer_and_correct_oracle'],
         [repo('tests/test_iterables/test_fold/test_collect_all.py', "([Failure('a'), Failure('b')], Success(())),"), repo('tests/test_iterables/test_fold/test_collect_all.py', 'assert Fold.collect_all(iterable, sequence.from_value(())) == sequence')], 'tests/test_iterables/test_fold/test_collect_all.py', 'test_collect_all_result', 'repo_preexisting')
material('RL', 'repo_test', 'repo_unseen', 'Preexisting Result Failure.lash replacement test; exact source not read despite running tests/test_result', ['G1:existing_recovery_test'],
         [repo('tests/test_result/test_result_bind.py', 'def test_lash_failure():'), repo('tests/test_result/test_result_bind.py', 'assert Failure(5).lash(factory) == Failure(expected)')], 'tests/test_result/test_result_bind.py', 'test_lash_failure', 'repo_preexisting')
material('WL', 'implementation', 'repo_unseen', 'Generic existing pointfree.lash wrapper plus correct Failure→Success doctest; only export/import list was read by Agent', ['G1:pointfree_wrapper_and_oracle'],
         [repo('returns/pointfree/lash.py', "assert lash(example)(Failure(1)) == Success(2)"), repo('returns/pointfree/lash.py', 'return container.lash(function)')], 'returns/pointfree/lash.py', 'lash', 'repo_preexisting')


def slot(role, alternatives):
    return dict(role=role, alternatives=[[m] for m in alternatives])


recipes = []


def recipe(rid, gap, slots, compatibility, additions, qualification='requires_oracle_inference'):
    recipes.append(dict(id=rid, gap=gap, qualification=qualification, slots=slots,
                        forbidden_pairs=[], compatibility=compatibility, semantic_additions=additions))


oracles = ['O8', 'O9', 'O25', 'Q39', 'Q74', 'Q127', 'RL']
producers = ['P57', 'P95', 'U57', 'U95', 'R57', 'R95']
recipe('G1R1', 'G1', [slot('已实际运行的恢复组合', ['L57', 'L95']), slot('独立恢复合同或正确推理', oracles)],
       '原输入和 callback 已足够；只把原 Invalid 期望替换成 callback 的实际返回容器。单个错误和常量 callback 已能揭错，无需强制拼接字符串或多错误。tuple callback 可进一步用原 P57/P95 值构造。', ['修正原错误 oracle，不需要增加 A+B 刺激。'])
recipe('G1R2', 'G1', [slot('另一处 Invalid 生产者', producers), slot('已有 lash 及 callback 用法', ['L57', 'L95']), slot('独立恢复合同', oracles)],
       '将 producer 的实际输出交给已有 lash(callback)。from_failure/from_result 均实际产出 Invalid，apply/alt 产生的多错误仍是相同容器协议；不复制其局部错误 oracle。', ['跨测试传递生成的 Invalid；采用 callback 返回值作为 oracle。'])
recipe('G1R3', 'G1', [slot('已读旧实现中的恢复调用及合同', ['O8', 'O9', 'O25', 'RL']), slot('任一新容器生产者', producers)],
       '把 Failure/IOFailure 替换为新 Invalid，Success替换为Valid；callback 可返回常量Valid使 error类型差别不阻塞。RL既有的Failure返回型则改为Invalid((len(errors),))或常量Invalid(新值)，要保证与原错误不同。', ['既有接口测试迁移；新 Invalid 的错误参数为tuple。'], 'requires_transfer')
recipe('G1R4', 'G1', [slot('pointfree wrapper和正确doctest', ['WL']), slot('已有 Invalid 生产者或恢复测试', producers + ['L57', 'L95'])],
       'pointfree.lash(callback)(Invalid) 委派到同一方法。WL自身即提供恢复到成功的 oracle；用常量Valid callback无需新的语义推断。该source在仓库中但Agent未读，单独标出。', ['复用现有pointfree包装；将Failure换成Invalid。'], 'requires_transfer')
recipe('G1R5', 'G1', [slot('已有恢复测试', ['L57', 'L95']), slot('Fold 中真实忽略错误并返回成功acc的消费操作', ['D16'])],
       '直接把既有 callback 设为 lambda _: Valid(())，按预存在 Fold 中的 fallback 用法检查 Valid(())，与原 Invalid 必须不同。无需精确知道错误tuple该逐项还是整体传入。', ['将实际仓库fallback使用迁移为更小的接口断言。'], 'requires_transfer')
recipe('G2R1', 'G2', [slot('已经联合运行的collect_all', ['J84']), slot('独立fallback证据', ['D16', 'Q74', 'Q127', 'RC'])],
       '保留84完整输入和Valid(())acc，仅把累积错误期望改为Valid((3,))。全Invalid变体期望Valid(())；都遵守既有跳过失败的collect_all合同。', ['只修正oracle，原联合操作已经执行过。'])
recipe('G2R2', 'G2', [slot('既有collect测试输入和acc', ['C61', 'C95']), slot('collect_all的消费/恢复合同', ['D16', 'RC', 'Q74', 'Q127'])],
       '复用原输入及acc，改用既有Fold.collect_all；按valid成员按序收集。C61有混合输入，C95有全Invalid；不是将collect的错误累积oracle复制过去。', ['consumer从collect换为collect_all；按已有安全收集合同推导结果。'])
recipe('G2R3', 'G2', [slot('预存在repo中的完整collect_all测试', ['RC']), slot('新Invalid生产者', producers)],
       '保持原Fail/Success表格的期待结构，把容器换为Valid/Invalid并将单个error包tuple。RC带混合与全失败两种正确oracle，不需要官方Verifier输入。', ['跨容器实例化旧泛型API测试。'], 'requires_transfer')
recipe('G2R4', 'G2', [slot('已有新容器序列或联合测试', ['C61', 'C95', 'J84']), slot('原Result恢复操作', ['O8', 'O9', 'O25']), slot('明确安全折叠调用连接', ['D16'])],
       '沿Fold实际callsite将Invalid错误经lash回退至之前Validacc；既有输入提供每次迭代对象，Result恢复语义与callback的返回acc对应。不能仅从新container错误实现反推期望。', ['从真实producer→consumer→fallback链得到独立oracle。'])

families = [
    dict(id='G1', failed_tests=[failures[i]['name'] for i in [0, 1, 5]],
         contract='Validated extends FailableN and inherits recovery semantics of lash; failure calls the supplied callback, whose returned Validated replaces the original failure. The pointfree wrapper delegates to that method.',
         missing_joint_test='Invalid(tuple) → lash(callback returning Valid or a different Invalid); verify returned callback container, including pointfree.lash wrapper. The direct method combination was actually executed57/95; its oracle was wrong.',
         classification='weak_oracle', verifier_validity='supported', joint_attempt='weak_oracle',
         required_components=['Invalid producer', 'failure recovery callback', 'method or pointfree lash', 'callback-result oracle independent of current implementation'],
         patch_explanation='Invalid.lash returns self. Original Result/IOFailure methods and docs show recovery, but Agent chooses no-op from speculative upstream memory. A single-error constant-return callback already detects the defect; multiple errors and joins are optional variants.'),
    dict(id='G2', failed_tests=[failures[i]['name'] for i in [2, 3, 4]],
         contract='Existing Fold.collect_all skips failed elements by lash(lambda _: acc), unlike Fold.collect which accumulates Validated errors through apply. Mixed items return Valid(success tuple); all Invalid with Valid(()) accumulator returns Valid(()).',
         missing_joint_test='Combine Valid/Invalid input sequence with existing Fold.collect_all and Valid(()) accumulator; expect successful members only. This exact combination was already executed84, but asserted accumulated errors.',
         classification='weak_oracle', verifier_validity='supported', joint_attempt='weak_oracle',
         required_components=['new Validated producer sequence', 'existing Fold.collect_all consumer', 'Valid empty accumulator', 'skip-failure oracle distinct from collect'],
         patch_explanation='The generic safe concatenation relies on .lash fallback. No-op Invalid.lash retains and accumulates errors. Existing generic consumer tests in repository and source fallback provide independent expected behavior; adding identical inputs alone cannot uncover the bug when the erroneous oracle is retained.')]

review = dict(case_id='S065', reviewer='Codex /root',
              full_read=dict(line_ranges=[[1, 19549]], steps=131, unread=[], metadata_read=True,
                             note='All retained command/output/reasoning text read; output-truncated ranges reread in smaller chunks. Own CAS repo consumer tests, Result tests and pointfree wrapper then inspected separately.'),
              evaluation_families=families, materials=materials, recipes=recipes,
              agent_process=dict(joint_attempt='weak_oracle', explanations=[
                  dict(label='explicit_contract_interpretation', support='direct',
                       interpretation='39 proposes correct tuple recovery,40 settles on no-op because accumulated errors supposedly cannot feed a single-error callback, based on imagined upstream memory after download403. This is a chosen semantic model, not absence of the relevant operation.',
                       refs=[reasoning(40, 'So `lash` is a no-op for both!'), reasoning(40, 'there\'s no way to apply a single-error lash function.')]),
                  dict(label='oracle_matches_implementation', support='direct',
                       interpretation='57 and95 jointly execute Invalid+recovery callback but assert unchanged Invalid.84 jointly runs collect_all+mixedValidated and asserts accumulated errors. Thus all six official failures require correcting an already wrong oracle; these are not untouched A+B inputs.',
                       refs=[command(57, "assert Invalid((1,)).lash(lambda e: Valid('recovered')) == Invalid((1,))"), command(95, 'assert Invalid((1,)).lash(lambda e: Valid(2)) == Invalid((1,))'), command(84, 'assert res == Invalid((1, 2))')]),
                  dict(label='explicit_scope_narrowing', support='direct',
                       interpretation='74 correctly traces fallback dependency but decides only collect is named by task.127 after commit again spells correct recovery and resulting collect_all behavior, then rejects it on the same task scope/type-signature/speculative-upstream grounds. Strong direct counterevidence to a simple long-history forgetting explanation.',
                       refs=[reasoning(74, 'Let me just keep no-op. It satisfies the interface and inherited law.'), reasoning(127, 'That would make `Fold.collect_all` work properly for Validated.'), reasoning(127, 'Fine.')]),
                  dict(label='incomplete_law_as_completion_signal', support='direct',
                       interpretation='Inherited FailableN lash_short_circuit law only asserts success short-circuit, so no-op on failure passes laws. Agent explicitly uses this insufficient law as evidence; repeated stock suites and 27 custom tests are green because old containers still work and new tests encode the no-op.',
                       refs=[reasoning(40, "It doesn't test lash on failure."), output(130, '27 passed')])], forgetting_assessment='counterevidence'),
              prior_record_corrections=[
                  'Full-text actual84 is already new-container+old-consumer execution with a hard wrong oracle. Do not count this as merely never composing two previously separate behaviors.',
                  '57 and95 already directly run failure-recovery operations. Correct oracle is available from old Result/IO source or explicit reasoning39/74/127; increasing stimulus complexity is unnecessary.',
                  'Many donor alternatives exist: raw tuple, apply accumulation, from_failure/from_result, two independently authored lash tests, two collect tests, actualcollect_all, original source and unseen repo test tables. Alternatives are restricted by actual container/callback compatibility.',
                  'Unverified upstream recollection is reasoning only; neither network403 nor law checks establish that upstream really implements no-op.',
                  '95/96 double-swap expectation correction follows explicit issue non-law and is unrelated to six failed evaluations; do not count it as a removed correct bug witness.',
                  'Original test_collect_all and Result bind tests existed and ran in stock suites, but their source was not retained in Agent reads; mark repo_unseen and keep out of trajectory-only counts.'],
              uncertainties=['New material assemblies were manually checked for semantic compatibility and have not been newly executed in this audit. Interface generic type uses individual error parameter while Validated stores a tuple; that design tension explains hesitation but does not justify no-op on all failures or breaking generic fallback.'])
(directory / 'manual_review.json').write_text(json.dumps(review, ensure_ascii=False, indent=2) + '\n')
(directory / 'reviewer_notes.txt').write_text('Full retained19549lines/131steps and metadata read. Six actual failures form two supported families, both already jointly executed with wrong hard oracle. Correct alternative explicitly reasoned early39,mid74 and aftercommit127, rejected because task only namescollect, type ambiguity and imagined upstream. Alternatives include multiple new producers and method tests, actual84consumer, old Result/IO implementation, fallback source and unseen repository test tables.\n')
