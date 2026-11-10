import json
from pathlib import Path

directory = Path(__file__).parent
case = json.loads((directory / 'case.json').read_text())
failed = json.loads((directory / 'evaluation_failures.json').read_text())['failed_tests']
inventory = json.loads(Path(case['repository_materials']).read_text())
entries = {e['path']: e for e in inventory['entries']}
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


material('A75', 'temporary_probe', 'executed_pass', 'Exact uppercase AGGREGATE+GROUP BY formatter test with independent complete expected layout', ['G1:aggregate_input_and_complete_layout_oracle'],
         [command(75, 'it(\'pipe aggregate group by\''), command(75, 'FROM t |> AGGREGATE SUM(a) AS total GROUP BY b'), output(75, '3 passed')], 'test/pipe_repro.test.ts', 'pipe aggregate group by')
material('A92', 'agent_validation', 'executed_pass', 'Permanent feature AGGREGATE+GROUP BY test; survives final commit', ['G1:aggregate_input_and_complete_layout_oracle'],
         [command(92, "it('formats pipe query with AGGREGATE and nested GROUP BY'"), command(92, 'FROM t |> AGGREGATE SUM(a) AS total GROUP BY b'), output(94, '5734 passed')], 'test/features/pipeSyntax.ts', 'formats pipe query with AGGREGATE and nested GROUP BY')
material('A89', 'temporary_probe', 'executed_pass', 'Independent COUNT aggregate with multi-column GROUP BY and extra nested ORDER BY, actual full output printed', ['G1:aggregate_input_and_layout'],
         [command(89, "it('aggregate group by multi and order by'"), command(89, 'FROM t |> AGGREGATE COUNT(*) AS n GROUP BY a, b ORDER BY n'), output(90, 'AGG2:')], 'test/pipe_edge.test.ts')
material('A111', 'temporary_probe', 'executed_output', 'tabWidth4 multi-step pipeline with aggregate/groupby, printed result, no hard oracle', ['G1:aggregate_input_and_alternative_harness'],
         [command(111, 'FROM t |> WHERE a > 1 |> AGGREGATE SUM(a) AS total GROUP BY b'), command(111, '{ tabWidth: 4 }'), output(111, '1 passed')], '/tmp/pipe_tab.test.ts')
material('A133', 'temporary_probe', 'executed_output', 'Final comprehensive users pipeline contains COUNT aggregate, GROUP BY, EXTEND, WHERE, ORDER, LIMIT and AS; printed only', ['G1:aggregate_input_and_alternative_harness'],
         [command(133, 'FROM users'), command(133, '|> AGGREGATE COUNT(*) AS total GROUP BY country'), output(133, '1 passed')], '/tmp/final_check.test.ts')
material('L89', 'temporary_probe', 'executed_output', 'Lowercase aggregate source under preserve; initially parse fails89, after promotion fix90 prints correct preserved lowercase', ['G1:lowercase_exclusive_keyword_and_format_harness'],
         [command(89, "format(`from t |> where a > 1 |> aggregate sum(a) as x`, { keywordCase: 'preserve' })"), output(90, 'PRESERVE:'), output(90, '|> aggregate')], 'test/pipe_edge.test.ts', 'keywordCase preserve')
material('K76', 'temporary_probe', 'executed_pass', 'Basic standard pipe WHERE/SELECT with keywordCase lower and exact expected result; no aggregate', ['G1:keywordCase_option_harness'],
         [command(76, "{ keywordCase: 'lower' }"), command(76, "it('keywordCase lower'"), output(76, 'LOWER:')], 'test/pipe_more.test.ts', 'keywordCase lower')
material('K86', 'temporary_probe', 'executed_pass', 'Rewritten basic WHERE/SELECT lower option hard test, later full-suite pass88', ['G1:keywordCase_option_harness'],
         [command(86, "it('keywordCase lower'"), command(86, "{ keywordCase: 'lower' }"), output(88, '5736 passed')], 'test/pipe_more.test.ts', 'keywordCase lower')
material('K92', 'agent_validation', 'executed_pass', 'Permanent keywordCase lower test only standard WHERE and SELECT, no pipe-exclusive token', ['G1:keywordCase_option_harness'],
         [command(92, "it('supports keywordCase for pipe keywords'"), command(92, 'from t |> where a > 1 |> select a'), command(92, "{ keywordCase: 'lower' }"), output(94, '5734 passed')], 'test/features/pipeSyntax.ts', 'supports keywordCase for pipe keywords')
material('D12', 'implementation', 'read_only', 'Original formatter upper branch returns node.text while preserve consumes node.raw', ['G1:upper_option_and_contract', 'G1:canonical_text_consumer'],
         [output(12, 'switch (this.cfg.keywordCase)'), output(12, "case 'upper':"), output(12, 'return node.text;')], 'src/formatter/ExpressionFormatter.ts', 'showNonTabularKw', 'repo_preexisting')
material('D11', 'implementation', 'read_only', 'Original tokenizer reserved-word producer canonicalizes text to uppercase; identifiers do not', ['G1:canonicalization_invariant'],
         [output(11, 'const toCanonical = (v: string) => equalizeWhitespace(v.toUpperCase());')], 'src/lexer/Tokenizer.ts', 'toCanonical', 'repo_preexisting')
material('P90', 'implementation', 'written_unexecuted', 'Authored fix promotes lowercase identifier by comparing toUpperCase but only changes token.type, retaining lowercase token.text', ['G1:new_producer_old_consumer_connection'],
         [command(90, "token.text.toUpperCase() === "), command(44, 'return { ...token, type: TokenType.RESERVED_CLAUSE };')], 'src/languages/bigquery/bigquery.formatter.ts', 'promotePipeClauses')
material('Q89', 'reasoning', 'reasoning_only', 'Explicit plan to test preserve and upper after lower, but actual authored command contains preserve only', ['G1:upper_combination_plan_not_execution'],
         [reasoning(89, 'Let me also test `preserve` and `upper`.')])
material('Q90', 'reasoning', 'reasoning_only', 'Correctly identifies formerly ordinary lowercase identifier lacks canonical uppercase text', ['G1:missing_canonicalization_clue'],
         [reasoning(90, "identifiers preserve case. Yes! AGGREGATE is not in any reserved list"), reasoning(90, "text: 'aggregate'"), reasoning(90, 'So promotion should be case-insensitive.')])
material('Q132', 'reasoning', 'reasoning_only', 'Final inference: KeywordNode type alone means showKw applies keywordCase to exclusive tokens', ['G1:unsupported_completion_inference'],
         [reasoning(132, 'keywords are KeywordNodes with tokenType RESERVED_CLAUSE/RESERVED_KEYWORD, so showKw applies keywordCase.')])
material('RK', 'repo_test', 'repo_unseen', 'Original full uppercase keywordCase test with lowercase/mixed source and exact expected result; stock suite ran, source not read', ['G1:existing_upper_option_and_independent_oracle'],
         [repo('test/options/keywordCase.ts', "it('converts keywords to uppercase'"), repo('test/options/keywordCase.ts', "keywordCase: 'upper',"), repo('test/options/keywordCase.ts', 'SELECT DISTINCT')], 'test/options/keywordCase.ts', 'converts keywords to uppercase', 'repo_preexisting')
material('RK2', 'repo_test', 'repo_unseen', 'Distinct existing uppercase option test excludes string-literal contents, giving clause-only expected transformation boundary', ['G1:existing_upper_option_and_literal_preservation'],
         [repo('test/options/keywordCase.ts', "it('does not uppercase keywords inside strings'"), repo('test/options/keywordCase.ts', "'distinct' AS foo")], 'test/options/keywordCase.ts', 'does not uppercase keywords inside strings', 'repo_preexisting')
material('I1', 'issue_or_documentation', 'read_only', 'Original explicit requirement that keywordCase governs pipe-exclusive keywords as well', ['G1:independent_cross_feature_oracle'],
         [dict(channel='issue', path=case['issue'], quote='`keywordCase` governs all pipe keywords including pipe-exclusive ones.')], 'instruction.md', origin='issue')


def slot(role, alternatives):
    return dict(role=role, alternatives=[[m] for m in alternatives])


recipes = []


def recipe(rid, slots, compatibility, additions, qualification='requires_oracle_inference'):
    recipes.append(dict(id=rid, gap='G1', qualification=qualification, slots=slots,
                        forbidden_pairs=[], compatibility=compatibility, semantic_additions=additions))


recipe('R1', [slot('已有 lowercase aggregate 实际输入', ['L89']), slot('upper 选项及其独立合同', ['D12', 'RK', 'RK2']), slot('大写aggregate的原预期布局', ['A75', 'A92']), slot('issue联合要求', ['I1'])],
       '把preserve改upper，保留lowercase aggregate输入，按现有uppercaseAGGREGATE布局预期。sum函数大小写是functionCase独立选项，不能用全SQL.toUpperCase处理；可继续保留sum或从A75的SUM输入只lowercase目标aggregate，避免混淆。无需官方orders/customer字面值。', ['切换已存在upper选项；组合正确的关键字oracle。'])
recipe('R2', [slot('另一处aggregate运行', ['A75', 'A92', 'A89', 'A111', 'A133']), slot('另一处lowercase exclusive输入', ['L89']), slot('upper选项/原测试', ['D12', 'RK', 'RK2']), slot('独立合同', ['I1'])],
       '仅将已有AGGREGATE关键字改为aggregate并启用upper。A75/A92本身有完整字符串oracle；A89/A111/A133仅输出，须补oracle，按原布局只规范关键字。多column、tabWidth4、完整管道都可承载同一缺陷，非唯一简单aggregate片段。', ['目标关键字lowercase；upper配置；打印脚本补独立断言。'])
recipe('R3', [slot('原repo uppercase或literal-preservation测试', ['RK', 'RK2']), slot('已有aggregate输入和布局', ['A75', 'A92', 'A89']), slot('独立合同', ['I1'])],
       '在旧upper测试format包装器/选项/断言基础上，用已有FROM管道替换传统SELECT；lowercase其中AGGREGATE，预期保留对应大写布局。RK2表明字符串literal不该一起uppercase。repo源不在Agent读出的历史中，单独统计。', ['替换旧测试刺激为pipe-exclusive token；实例化现有大写oracle。'], 'requires_transfer')
recipe('R4', [slot('已有keywordCase测试', ['K76', 'K86', 'K92']), slot('已有lowercase aggregate实际执行', ['L89']), slot('upper选项/语义', ['D12', 'RK', 'RK2']), slot('独立合同', ['I1'])],
       '将lower模式测试改成upper，插入L89的aggregate步骤。目标刺激与API全来自历史；期望必须按upper而非复制lower测试字符串。repo选项测试可直接给upper参数，纯trajectory路线由已读D12提供。', ['把lower测试迁移到upper分支；加入exclusive关键字及对应大写断言。'])
recipe('R5', [slot('已执行 lowercase aggregate 输入', ['L89']), slot('新promotion代码', ['P90']), slot('原formatter upper消费者', ['D12']), slot('原lexer canonicalization', ['D11']), slot('独立合同', ['I1'])],
       '真实数据连接是IDENTIFIER.text保留原文→只改type的promotion→upper分支返回node.text。沿这一连接在同一format调用选upper即可，不依赖手工选中的唯一pipeline。', ['将已存在producer/consumer不变量显式变为集成测试。'])
recipe('R6', [slot('已有aggregate测试或实际lowercase执行', ['A75', 'A92', 'L89']), slot('Agent明确计划的upper条件', ['Q89']), slot('原upper合同实现', ['D12']), slot('独立合同', ['I1'])],
       '89明确列出upper但没有写执行；将这一计划实体化而非称其已经执行。若从A75/A92起步还须lowercaseAGGREGATE，否则upper与输入同大小写会掩盖缺陷。', ['兑现未执行的upper计划；确保输入大小写与目标变换相反。'])

family = dict(id='G1', failed_tests=[failed[0]['name']],
              contract='keywordCase upper applies to pipe-exclusive AGGREGATE. A lowercase source keyword promoted from IDENTIFIER must be canonicalized before the old upper formatter consumes token.text.',
              missing_joint_test="Format historical lowercase '|> aggregate ...' with keywordCase:'upper', and check AGGREGATE is uppercase while identifiers/literals preserve their separate policies. Existing uppercase aggregate layout can supply the rest of the expected string.",
              classification='untested_interaction', verifier_validity='supported', joint_attempt='absent',
              required_components=['lowercase pipe-exclusive input', 'promotion from IDENTIFIER', 'keywordCase upper configuration', 'actual keyword casing assertion'],
              patch_explanation='90 fixes case-insensitive recognition using token.text.toUpperCase() but only changes token.type; text remains aggregate. The existing upper formatter returns node.text without uppercasing. Lower and preserve tests pass, but their outputs cannot validate this producer→consumer invariant.')
review = dict(case_id='S066', reviewer='Codex /root',
              full_read=dict(line_ranges=[[1, 20067]], steps=134, unread=[], metadata_read=True,
                             note='All retained fulltext and metadata read; tool-truncated intervals reread in smaller chunks, including the long grammar-design reasoning. Own CAS keywordCase tests inspected separately.'),
              evaluation_families=[family], materials=materials, recipes=recipes,
              agent_process=dict(joint_attempt='absent', explanations=[
                  dict(label='unfulfilled_test_plan', support='direct',
                       interpretation='89 explicitly plans preserve and upper after lower tests. Actual89 command writes only preserve;90 fixes its parse failure and accepts printed lowercase.92 permanent option test again covers lower only. This is a concrete missing execution despite a remembered requirement, not evidence that upper was already tested.',
                       refs=[reasoning(89, 'Let me also test `preserve` and `upper`.'), command(89, "{ keywordCase: 'preserve' }"), command(92, "{ keywordCase: 'lower' }")]),
                  dict(label='producer_consumer_effect_not_transferred', support='direct',
                       interpretation='90 correctly realizes ordinary identifier text preserves source case, fixes recognition by comparing uppercase but does not update produced token.text.132 concludes KeywordNode/tokenType alone means keywordCase works, without tracing old upper consumer returning node.text. This is an incorrect cross-layer invariant, not simply independent feature coverage.',
                       refs=[reasoning(90, "text: 'aggregate'"), command(90, 'token.text.toUpperCase()'), reasoning(132, 'keywords are KeywordNodes with tokenType RESERVED_CLAUSE/RESERVED_KEYWORD, so showKw applies keywordCase.')]),
                  dict(label='green_suite_as_completion_signal', support='direct',
                       interpretation='132 lists exclusive-token keywordCase as complete after5735green tests;133 last check prints comprehensive uppercase-input pipeline in default preserve, which cannot detect upper transformation of lowercase exclusive text. A long grammar ambiguity detour exists, but no direct claim of forgetting or enforced budget stop is supported.',
                       refs=[output(132, '5735 passed'), command(133, '|> AGGREGATE COUNT(*) AS total GROUP BY country'), reasoning(134, 'The comprehensive output looks great and matches the issue requirements.')])],
                                 forgetting_assessment='not_identifiable'),
              prior_record_corrections=[
                  'Old focal inventory labels upper transformation as Exact Executed Fragment. Full retained trajectory contains no Agent-authored format call with keywordCase upper: only lower76/86/92 and preserve89. Upper is source/requirement/reasoning and available in existing repository tests, not an executed Agent snippet.',
                  'Lowercase aggregate actually executed after90 fix is transient pipe_edge, later deleted94. Final repo only contains uppercase aggregate and lower standard-keyword tests, so final-state-only extraction loses the strongest trigger.',
                  'Original keywordCase upper tests existed and ran in stock suite but their exact source was not read in retained Agent outputs; mark repo_unseen.',
                  'Temporary failing indent expectations57/74 are corrected according to tabWidth and are unrelated to sole failed evaluation. Their correction is not weakening a correct casing witness.',
                  'COUNT, SUM, multicolumn/groupby, tabWidth4, finalcomprehensivepipe and original option tests are alternative material routes; no requirement to reproduce officialorders/customer identifiers.'],
              uncertainties=['Alternative source assemblies were manually checked and not newly executed. The transcript supports an unfinished upper-test plan and wrong canonicalization assumption; it cannot identify a latent memory failure from peak context204835 alone.'])
(directory / 'manual_review.json').write_text(json.dumps(review, ensure_ascii=False, indent=2) + '\n')
(directory / 'reviewer_notes.txt').write_text('Full retained20067lines/134steps+metadata read. One supported missing interaction: lowercase pipe-exclusive aggregate × upper. Actual90 executes lowercaseaggregate+preserve only; plannedupper89 never implemented. Old exact-executed upper label corrected. Multiple aggregate pipelines, transientpreserve input, olduppercase source consumer, genericrepo optiontests provide alternative material assemblies. Producer canonicaltext invariant missed; final132 remembersrequirement but infers KeywordNode⇒works.\n')
(directory / 'reading_status.json').write_text(json.dumps(dict(case_id='S066', reviewer='root', fulltext_ranges_read=[[1,20067]], next_line=20068, metadata_read=True), indent=2) + '\n')
