import json
from pathlib import Path

directory = Path(__file__).parent
case = json.loads((directory / 'case.json').read_text())
failed = json.loads((directory / 'evaluation_failures.json').read_text())['failed_tests']


def command(step, quote):
    return dict(step=step, call=0, channel='command', quote=quote)


def output(step, quote):
    return dict(step=step, call=0, channel='output', quote=quote)


def reasoning(step, quote):
    return dict(step=step, channel='reasoning', quote=quote)


def issue(quote):
    return dict(channel='issue', path=case['issue'], quote=quote)


materials = []


def material(mid, kind, availability, unit, supports, refs, artifact='', symbol='', origin='agent_authored'):
    materials.append(dict(id=mid, kind=kind, origin=origin, availability=availability,
                          unit=unit, supports=supports, refs=refs, artifact=artifact, symbol=symbol))


material('U90', 'temporary_probe', 'executed_output', 'Actual bulk safe UPDATE example with no invariant registered; rows checked by printing', ['G1:bulk_update_stimulus'],
         [command(90, 'update example set name = :name where id = :id'), command(90, '"--safe-mode"'), output(90, "'OneUpdated'")])
material('U153', 'agent_validation', 'executed_pass', 'Permanent test_cli_safe_mode_bulk_update; UPDATE succeeds with no invariant', ['G1:bulk_update_base_test'],
         [command(153, 'def test_cli_safe_mode_bulk_update(tmpdir):'), command(153, 'input=\'{"id": 1, "name": "OneUpdated"}\\n\''), output(154, '18 passed')], 'tests/test_safe_import.py', 'test_cli_safe_mode_bulk_update')
material('U228', 'temporary_probe', 'executed_pass', 'Final comprehensive CLI UPDATE runs with a COUNT invariant which remains true because UPDATE does not change row count', ['G1:bulk_update_with_nondiscriminating_invariant'],
         [command(228, '"COUNT(*) = 1"'), command(228, 'update t set name = :name where id = :id'), output(228, 'ALL FINAL CHECKS PASSED')])
material('C89', 'temporary_probe', 'executed_output', 'CLI add persistent COUNT(*)=2 invariant then insert third row, nonzero exit and unchanged rows actually printed', ['G1:cli_invariant_registration_and_rollback_oracle'],
         [command(89, '"COUNT(*) = 2"'), command(89, 'print("rows after fail:"'), output(89, "rc: 1 out: '' err: 'Error: Import invariant validation failed")])
material('C153', 'agent_validation', 'executed_pass', 'Permanent CLI safe insert invariant failure test with explicit nonzero exit and unchanged row count', ['G1:cli_invariant_registration_and_rollback_oracle'],
         [command(153, 'def test_cli_safe_mode_insert(tmpdir):'), command(153, 'assert result.exit_code != 0'), command(153, 'assert db["t"].count == 2'), output(154, '18 passed')], 'tests/test_safe_import.py', 'test_cli_safe_mode_insert')
material('C185', 'temporary_probe', 'executed_output', 'Another complete subprocess CLI invariant/add/insert/validate/list/remove flow with failing insert', ['G1:cli_invariant_registration_and_rollback_oracle', 'G2:cli_roundtrip'],
         [command(185, '"COUNT(*) = 2"'), command(185, 'run(["insert", p, "items", "-", "--safe-mode"], input=\'[{"id":3,"name":"c"}]\')'), output(185, 'Failing invariants:')])
material('E74', 'temporary_probe', 'executed_output', 'Per-row invariant id<100 succeeds for5 and fails for200, raw SQL SELECT count==3 failure also executed', ['G1:value_sensitive_invariant'],
         [command(74, '"id < 100"'), command(74, '"SELECT COUNT(*) = 3 FROM items"'), output(74, 'non-agg fail:')])
material('E153row', 'agent_validation', 'executed_pass', 'Permanent nonaggregate invariant id<10 plus id100 failing insertion; supplies existing threshold independent of COUNT', ['G1:value_sensitive_invariant_and_oracle'],
         [command(153, 'def test_non_aggregate_invariant(safe_db):'), command(153, '"id < 10"'), command(153, '{"id": 100}'), output(154, '18 passed')], 'tests/test_safe_import.py', 'test_non_aggregate_invariant')
material('E153select', 'agent_validation', 'executed_pass', 'Permanent SELECT invariant count==2 and failing insert; SELECT grammar can embed a value predicate', ['G1:select_invariant_and_oracle'],
         [command(153, 'def test_select_invariant(safe_db):'), command(153, '"SELECT COUNT(*) = 2 FROM t"'), output(154, '18 passed')], 'tests/test_safe_import.py', 'test_select_invariant')
material('E224', 'temporary_probe', 'executed_pass', 'Final check count==2 AND SUM(id)==3 already supplies UPDATE-sensitive aggregate; correct pk version227/228 executes successfully', ['G1:value_sensitive_aggregate_invariant_and_oracle'],
         [command(228, '"COUNT(*) = 2 AND SUM(id) = 3"'), command(228, 'assert r["success"] is False and r["failures"]'), output(228, 'ALL FINAL CHECKS PASSED')])
material('P133', 'temporary_probe', 'executed_output', 'truncate+insert invariant failure and unchanged old row gives strong state restoration oracle', ['G1:unchanged_state_oracle'],
         [command(133, '"COUNT(*) = 1"'), command(133, '"--truncate", "--safe-mode"'), output(133, "[{'id': 1, 'name': 'old'}]")])
material('P144', 'temporary_probe', 'executed_output', 'safe upsert existing id1 namea→nameb success followed by count-violating id2, all rows printed', ['G1:update_equivalent_stimulus_and_invariant_harness'],
         [command(144, 'db.safe_bulk_upsert("t", [{"id":1,"name":"b"}], pk="id")'), command(144, '"COUNT(*) = 1"'), output(144, 'upsert fail:')])
material('R29', 'issue_or_documentation', 'read_only', 'Original bulk command docs show parameterized UPDATE consumption of JSON records', ['G1:preexisting_update_stimulus'],
         [output(29, 'update chickens set name = :name where id = :id')], 'sqlite_utils/cli.py', 'bulk', 'repo_preexisting')
material('R30', 'implementation', 'read_only', 'Original bulk SQL executemany branch; target table unavailable as explicit parameter but SQL and database are available', ['G1:bulk_consumer_connection'],
         [output(30, 'db.conn.cursor().executemany(bulk_sql, doc_chunk)')], 'sqlite_utils/cli.py', 'insert_upsert_implementation', 'repo_preexisting')
material('R31', 'repo_test', 'read_only', 'Original existing bulk INSERT tests and example id/name fixture read completely; can be base for replacing SQL with historical UPDATE', ['G1:repo_bulk_base'],
         [command(31, 'tests/test_cli_bulk.py'), output(31, 'def test_db_and_path(tmpdir):')], 'tests/test_cli_bulk.py', 'test_db_and_path', 'repo_preexisting')
material('D80', 'implementation', 'written_unexecuted', 'Authored bulk _safe_operation table=None bypasses invariants, insert passes table; both branches explicitly present', ['G1:operation_connection'],
         [command(80, '_bulk_execute, strict=False, table=None'), command(80, '_safe_operation(_do_insert, strict=False, table=table)')], 'sqlite_utils/cli.py')
material('Q134', 'reasoning', 'reasoning_only', 'Explicitly considers exact bulk+invariant requirement and rejects it because no table parameter', ['G1:joint_hypothesis'],
         [reasoning(134, 'Now, let me think about hidden tests for the CLI `bulk --safe-mode` with an invariant.'), reasoning(134, "That's impossible without knowing the table. So table=None is correct.")])
material('Q170', 'reasoning', 'reasoning_only', 'Later explicitly rejects validating all registered invariants for bulk', ['G1:alternative_all_tables_solution_considered'],
         [reasoning(170, 'maybe hidden tests expect bulk --safe-mode to validate invariants for ALL tables?'), reasoning(170, "I'll keep table=None.")])
material('ID74', 'temporary_probe', 'executed_output', 'API add returns int1, list returns int1, remove consumes original opaque ID on same db', ['G2:python_id_producer_consumer'],
         [command(74, 'db.remove_import_invariant("items", inv)'), output(74, 'invariant id: 1'), output(74, "list: [{'id': 1, 'expression': 'COUNT(*) = 2'}]")])
material('ID122', 'temporary_probe', 'executed_pass', 'Hard API add→list→remove uses original id without type assumption', ['G2:python_id_roundtrip'],
         [command(122, 'assert inv_id is not None'), command(122, 'db.remove_import_invariant("t", inv_id)'), output(122, 'ALL PYTHON API CHECKS PASSED')])
material('ID153', 'agent_validation', 'executed_pass', 'Permanent invariants CRUD stores opaque API id; CLI list/validate tests separately hardcode string1', ['G2:python_and_cli_bases'],
         [command(153, 'def test_invariants_crud(safe_db):'), command(153, 'def test_cli_list_and_validate_invariants(tmpdir):'), command(153, 'assert "1" in result.output'), output(154, '18 passed')], 'tests/test_safe_import.py')
material('ID139', 'temporary_probe', 'executed_output', 'CLI separate process raw text id1 is listed/validated, string1 remove initially succeeds locally but is not committed;142 fixes persistence', ['G2:cli_text_id_roundtrip'],
         [command(139, 'run(["remove-import-invariant", p, "t", "1"])'), output(139, 'list after remove:'), output(142, 'after remove: []')])
material('ID158', 'temporary_probe', 'executed_output', 'Actual CLI failed invariant output exits0 and contains textual1; error SQL corrected to genuine false COUNT', ['G2:validate_failure_text_oracle'],
         [command(158, '"COUNT(*) = 1"'), output(158, 'Failing invariant ids: 1')])
material('Q17', 'reasoning', 'reasoning_only', 'Explicit original interpretation opaque ID may be integer, consistently retained to222', ['G2:type_contract_choice'],
         [reasoning(17, 'could be integer autoincrement'), reasoning(222, 'The spec says "invariant_id (opaque)" — integer is opaque enough.')])
material('I1', 'issue_or_documentation', 'read_only', 'Global safe-mode requirement validates invariants after writes, including bulk UPDATE; opaque invariant ID does not specify str', ['G1:independent_contract', 'G2:opaque_id_contract'],
         [issue('validates table invariants after writes'), issue('bulk --safe-mode must support UPDATE.'), issue('add_import_invariant(table, sql) -> invariant_id (opaque)')], 'instruction.md', origin='issue')


def slot(role, alternatives):
    return dict(role=role, alternatives=[[m] for m in alternatives])


recipes = []


def recipe(rid, gap, slots, compatibility, additions, qualification='requires_oracle_inference'):
    recipes.append(dict(id=rid, gap=gap, qualification=qualification, slots=slots,
                        forbidden_pairs=[], compatibility=compatibility, semantic_additions=additions))


recipe('R1', 'G1', [slot('已有bulk UPDATE基测试', ['U90', 'U153', 'U228']), slot('已有值敏感条件', ['E74', 'E153row', 'E224']), slot('CLI注册与失败状态oracle', ['C89', 'C153', 'C185']), slot('独立合同', ['I1'])],
       '保持单一目标表和同一数据库，CLI执行前登记谓词。E74/E153row以已有id字段阈值为条件，UPDATE id为200/100；E224保留COUNT=2 AND SUM(id)=3，UPDATE id1→3破坏SUM而非COUNT。U228的COUNT=1本来不随name更新改变，不能直接当揭错输入。更新SQL、JSON参数、谓词中的列共同适配，CLI必须非零且旧行不变。', ['连接同一表的注册与UPDATE；选用已有值敏感谓词；添加原安全插入的失败及回滚oracle。'])
recipe('R2', 'G1', [slot('已有CLI invariant failure基测试', ['C89', 'C153', 'C185']), slot('UPDATE来源', ['U90', 'U153', 'R29']), slot('值敏感谓词', ['E74', 'E153row', 'E224']), slot('独立合同', ['I1'])],
       '从失败insert测试出发，保留注册/打开文件/非零退出/旧行不变框架，将insert改bulk UPDATE。COUNT条件不能照搬，使用历史id阈值或SUM。R29文档UPDATE可直接转成id列或保持name列并实例化不变量。', ['替换写入操作并使其违反既有值敏感约束。'])
recipe('R3', 'G1', [slot('原repo bulk调用/fixture', ['R31']), slot('已实际UPDATE调用', ['U90', 'U153']), slot('安全模式注册和oracle', ['C89', 'C153']), slot('值敏感条件', ['E74', 'E153row', 'E224']), slot('合同', ['I1'])],
       '原repo测试可提供文件/CLI/JSON/fixture骨架，新增安全模式和已有注册函数。对同表UPDATE使用既有id阈值或SUM，不是无关测试的字符串拼接；相较Agent tests只是另一处基程序。', ['给旧bulk测试增加safe-mode和持久不变量，选择会破坏条件的UPDATE。'])
recipe('R4', 'G1', [slot('已有UPDATE等价生产者', ['P144']), slot('原bulk消费者', ['R30']), slot('原UPDATE参数形式', ['R29']), slot('值敏感条件', ['E74', 'E153row', 'E224']), slot('CLI注册oracle', ['C89', 'C153']), slot('合同', ['I1'])],
       '历史safe upsert更新现有行的行为可迁移给bulk消费者，同表id/name接线。count-preserving UPDATE需额外值敏感断言；COUNT=1单独无效。允许从另一操作而非同名UPDATE切片获得更新行为。', ['将upsert现有行更新迁移到参数化bulk UPDATE；连接已有invariant。'])
recipe('R5', 'G1', [slot('完整UPDATE+不变量失败假说', ['Q134', 'Q170']), slot('已有UPDATE执行', ['U90', 'U153']), slot('注册与oracle', ['C89', 'C153', 'C185']), slot('值敏感条件', ['E74', 'E153row', 'E224']), slot('合同', ['I1'])],
       '将Agent已明确想到却否定的交互写为测试；不将推理当执行，也不从其错误“bulk无需验证”结论借oracle。独立合同和历史安全插入提供正确应拒绝结果。', ['实体化已讨论交互；校正错误的需求例外。'])
recipe('R6', 'G1', [slot('UPDATE现成代码', ['U90', 'U153']), slot('原安全模式代码连接', ['D80']), slot('值敏感条件', ['E74', 'E153row', 'E224']), slot('失败state oracle', ['P133']), slot('合同', ['I1'])],
       '静态比较bulk传None与insert传table的差异，沿同db注册状态→UPDATE→validate连接；P133旧行恢复oracle适用但其truncate动作不必保留。', ['将原插入回滚oracle迁移到UPDATE，无需参考实现。'])
recipe('R7', 'G2', [slot('API opaque ID来源', ['ID74', 'ID122', 'ID153']), slot('CLI list/remove文本来源', ['ID139', 'C185']), slot('原合同', ['I1'])],
       '真正API→CLI集成必须str(id)后放入args或字符串membership；官方直接传int导致TypeError在Click参数解析前/测试自身发生。材料足够写正确集成测试，但没有证据其会揭示实现错误；只有擅自增加ID必须str约束才复现官方失败。', ['未获合同支持的str返回类型要求；不能计入有效揭错组合。'], 'incomplete')
recipe('R8', 'G2', [slot('API ID来源', ['ID74', 'ID122', 'ID153']), slot('真实CLI验证失败输出', ['ID158']), slot('原合同', ['I1'])],
       '输出ID本来就是文本，断言str(id) in output满足opaque约定；int in str是测试表达式非法。可构造列表/验证正确roundtrip，但不支持把原官方TypeError算SUT bug。', ['官方未规定的ID必须为字符串约束。'], 'incomplete')

families = [
    dict(id='G1', failed_tests=[failed[0]['name']],
         contract='Safe mode validates registered invariants after writes and commits only on success; bulk UPDATE is explicitly part of the safe CLI operations.',
         missing_joint_test='Register a value-sensitive invariant for an existing table, run bulk UPDATE --safe-mode that makes it false, require nonzero exit and unchanged rows. COUNT-only invariants on a row-preserving UPDATE do not provide this trigger.',
         classification='untested_interaction', verifier_validity='supported', joint_attempt='absent',
         required_components=['existing populated table', 'persisted value-sensitive invariant on same table', 'bulk safe UPDATE violates predicate without SQL error', 'nonzero exit and unchanged-state oracle'],
         patch_explanation='Bulk calls _safe_operation(table=None), which skips validation. Existing bulk tests cover valid UPDATE and SQL-error rollback, not invariant-violating UPDATE. Final smoke228 includes COUNT=1 but updates name; count stays1 so it cannot reveal bypass.'),
    dict(id='G2', failed_tests=[row['name'] for row in failed[1:]],
         contract='Invariant IDs are opaque; issue gives no string-return requirement. CLI arguments/output are strings and proper adapters use str(id).',
         missing_joint_test='API add ID→CLI list/remove/validate roundtrip is a useful missing integration check, but the recorded failures assume ID is str without contract support.',
         classification='verifier_disputed', verifier_validity='disputed', joint_attempt='absent',
         required_components=['API-produced opaque ID', 'CLI argument or output consumption', 'explicit agreed ID representation'],
         patch_explanation='list and validate assertions execute int in str, raising TypeError in test code. remove passes int into CliRunner args, raising len(int) before command implementation. Agent intentionally uses opaque integer and correctly textifies CLI output; these failures do not establish a task-specified behavioral error.')]

review = dict(case_id='S067', reviewer='Codex /root',
              full_read=dict(line_ranges=[[1,26895]], steps=249, unread=[], metadata_read=True,
                             note='All retained fulltext and metadata read; original harness output_head/tail elisions retained as elisions. No sampling substituted for full reading.'),
              evaluation_families=families, materials=materials, recipes=recipes,
              agent_process=dict(joint_attempt='absent', explanations=[
                  dict(label='explicit_contract_exception', support='direct', interpretation='134 and170 explicitly consider bulk with registered invariants, then declare it exempt because CLI lacks target table. This is an explicit scope/requirement error despite remembered interaction, not memory forgetting.', refs=[reasoning(134, "That's impossible without knowing the table. So table=None is correct."), reasoning(170, "I'll keep table=None.")]),
                  dict(label='nondiscriminating_joint_stimulus', support='direct', interpretation='90 tests safe UPDATE with no invariant.228 eventually runs UPDATE with COUNT=1, but only modifies name, so predicate remains true. Having all APIs in one script is insufficient unless UPDATE can make the invariant false.', refs=[command(90, 'update example set name = :name where id = :id'), command(228, '"COUNT(*) = 1"'), command(228, 'update t set name = :name where id = :id'), output(228, 'ALL FINAL CHECKS PASSED')]),
                  dict(label='explicit_type_contract_choice', support='direct', interpretation='17 chooses int as opaque;222 still explicitly reasons integer satisfies opaque. Three failures instead assume str. This is a disputed test representation assumption, distinct from actual safe-mode bug.', refs=[reasoning(17, 'could be integer autoincrement'), reasoning(222, 'The spec says "invariant_id (opaque)" — integer is opaque enough.')]),
                  dict(label='green_suite_as_completion_signal', support='direct', interpretation='249 completes voluntarily after repeatedly checking1070green tests. Peak context245487 and long spec rechecks alone do not identify forgetting, and late134/170 show exact interaction remains considered.', refs=[output(248, '1070 passed'), reasoning(249, 'The task is complete.')])], forgetting_assessment='counterevidence'),
              prior_record_corrections=[
                  'Sole supported evaluation bug is UPDATE violating invariant, not absence of basic UPDATE support:90 and153 both execute valid safe UPDATE.',
                  'Final228 actually combines invariant registration and UPDATE but uses COUNT=1 and name-only update, so the joint stimulus is nondiscriminating. Do not label all co-occurrence absent.',
                  'Three opaque-ID failed records are test-side int/string assumptions unsupported by issue; isolate from genuine combination observation.',
                  'CLI remove persistence initially fails139/141 and is correctly fixed142; this historical bug is not the final recorded remove test failure, which occurs at argument parsing.',
                  'Repeated imagined upstream sqlite-utils memories are reasoning, not observed repository source. Only actual commands/outputs counted as executed material.',
                  'COUNT-only insert constraints cannot simply migrate unchanged onto UPDATE; value-sensitive historical id<10/id<100 or COUNT+SUM alternatives are required.'],
              uncertainties=['Assemblies are manually checked evidence alternatives, not newly executed synthesized tests. Opaque ID representation remains verifier-disputed under supplied issue.'])
(directory / 'manual_review.json').write_text(json.dumps(review, ensure_ascii=False, indent=2)+'\n')
(directory / 'reviewer_notes.txt').write_text('Full26895lines/249steps+metadata read. Four eval fails→two families: supported safeUPDATE×value-sensitive persisted invariant vs three disputed opaqueint→CLIstring test errors. Agent134/170 explicitly rejects bulk validation, so counterforgetting. Final228 registers COUNT invariant yet updates only name and cannot falsify it. Historical probes/tests/oldbulkdocs+tests/SQLpredicate alternatives enumerated with sharedtable compatibility; COUNT donor alone excluded.\n')
(directory / 'reading_status.json').write_text(json.dumps(dict(case_id='S067', reviewer='root', fulltext_ranges_read=[[1,26895]], next_line=26896, metadata_read=True),indent=2)+'\n')
