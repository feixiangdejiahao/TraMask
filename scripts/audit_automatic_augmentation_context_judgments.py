import json
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/home/jhx/combination_coverage')
sys.path.insert(0, str(ROOT))
from scripts import run_automatic_augmentation_io_repair as main
from scripts import run_automatic_augmentation_pilot as base

def read(p):
    return json.loads(Path(p).read_text())

def receipt(p):
    p = Path(p).resolve()
    return dict(path=str(p), sha256=hashlib.sha256(p.read_bytes()).hexdigest())

def verify(x):
    assert receipt(x['path']) == x, x['path']

directory = ROOT / 'results/automatic_augmentation_pilot_20261005/io_repair_v2/context_diagnostic'
prepared = read(directory / 'prepared.json')
verify(read(directory / 'seal.json'))
for key in ('algorithm', 'source_record', 'main_protocol', 'original_payload', 'augmented_payload'):
    verify(prepared[key])
old = read(prepared['original_payload']['path'])
new = read(prepared['augmented_payload']['path'])
assert set(new) - set(old) == {'supplemental_original_source'}
assert {k: v for k, v in new.items() if k != 'supplemental_original_source'} == old
source = next(c for c in read(prepared['source_record']['path'])['cases'] if c['case'] == 'P7')
spans = source['additional_original_source']
assert len(spans) == len(new['supplemental_original_source']) == 6
span_receipts = []
for index, (expected, actual) in enumerate(zip(spans, new['supplemental_original_source']), 1):
    verify(expected['source_file'])
    text = ''.join(Path(expected['source_file']['path']).read_text().splitlines(keepends=True)[expected['start_line']-1:expected['end_line']])
    assert text == expected['text'] == actual['text']
    assert actual == dict(evidence_id=f'D{index:04d}', kind='original_repository_source', path=expected['path'], start_line=expected['start_line'], end_line=expected['end_line'], text=text)
    original = ROOT / 'data/relational_gap_v1/P7/repository' / actual['path']
    assert ''.join(original.read_text().splitlines(keepends=True)[actual['start_line']-1:actual['end_line']]) == text
    span_receipts.append(dict(evidence_id=actual['evidence_id'], path=actual['path'], start_line=actual['start_line'], end_line=actual['end_line'], original_source=receipt(original), text_sha256=hashlib.sha256(text.encode()).hexdigest()))
judgment = directory / 'cases/P7/B01/source_and_trajectory/repeat_1/judgment'
req = read(judgment / 'request.json')
old_req_path = directory.parent / 'cases/P7/B01/source_and_trajectory/repeat_1/judgment/request.json'
old_req = read(old_req_path)
assert req['system'] == old_req['system'] == base.JUDGMENT_SYSTEM
assert req['prompt'] == base.canonical(new)
assert json.loads(req['prompt']) == new
diff = sorted(k for k in set(req) | set(old_req) if req.get(k) != old_req.get(k))
assert set(diff) == {'id', 'query_sha256', 'prompt', 'manual_context_selection', 'diagnostic_only', 'supplied_human_goal'}
assert req['id'] == req['query_sha256'] == base.digest({k:v for k,v in req.items() if k not in {'id','query_sha256'}})
wire = read(judgment / 'completion/request.json')
assert wire['messages'] == [dict(role='system', content=req['system']), dict(role='user', content=req['prompt'])]
assert wire['model'] == 'deepseek-flash' and wire['max_tokens'] == 65536 and wire['reasoning_effort'] == 'low'
assert wire['thinking'] == {'type':'enabled'} and wire['temperature'] == 0
report = dict(version='automatic-augmentation-context-judgment-audit.v1', created_utc=datetime.now(timezone.utc).isoformat(), diagnostic_only=True, main_scores_unchanged=True,
    reviewer=dict(role='extractor_author_postfreeze_source_and_judgment_review', blind=False, generation_and_native_files_read=False),
    input_validation=dict(original_payload_retained_exactly=True, added_raw_source_spans=span_receipts, human_goals_in_prompt=False, evaluation_labels_in_prompt=False, later_outputs_in_prompt=False, request_difference_keys=diff, same_semantic_system=True, request_prompt_exact=True, wire_messages_exact=True, raw_source_manual_selection=True),
    source_scope_change=dict(previous='主轮有runtime和type-only原测试，但缺readonly/transform行为源码。', added='D0001显示transform替换dataset.value；D0003显示readonly原样返回dataset。其余四段给出原export。', remaining='新增材料补齐这两项动作语义。它本身不证明递归outer pipeline实际执行次数、原断言覆盖或目标缺口；仍需跨源码推理。'),
    receipts=dict(prepared=receipt(directory/'prepared.json'), seal=receipt(directory/'seal.json'), original_payload=prepared['original_payload'], augmented_payload=prepared['augmented_payload'], algorithm=prepared['algorithm'], source_record=prepared['source_record'], request=receipt(judgment/'request.json'), original_request=receipt(old_req_path), wire_request=receipt(judgment/'completion/request.json'), main_judgment_audit=receipt(ROOT/'research/automatic_augmentation_judgment_audit_20261005.json'), evaluator=receipt(__file__)),
    limitations=['仅一次人工选择源码补齐诊断。不能并入主方法分数。','prompt没有目标标签，但人工选择这两个API仍引入有针对性的上下文选择。','显式引用D只证明引用；不能证明原因或内部推理。','不读取生成或原生输出，不作测试有效性或缺陷检出判断。'])
manifest = read(judgment / 'completion/manifest.json')
report['provider'] = dict(status=manifest['status'], finish_reason=manifest.get('finish_reason'), response_model=manifest.get('response_model'), usage=manifest.get('usage'), calls=manifest.get('external_model_calls'))
report['receipts']['manifest'] = receipt(judgment / 'completion/manifest.json')
if (judgment/'decision_seal.json').exists():
    verify(read(judgment/'decision_seal.json'))
    decision = read(judgment/'decision.json')
    raw = (judgment/'completion/completion.txt').read_text()
    protocol = read(prepared['main_protocol']['path'])
    batch = next(c for c in protocol['cases'] if c['case']=='P7')['batches'][0]
    aliases = {s['seed_alias']:s['base_test_id'] for s in batch['candidates']}
    assert main.parse_judgment(raw, manifest.get('finish_reason'), set(aliases), base.evidence_ids(new)) == decision
    report['raw_redecode_exact'] = True
    report['decision'] = decision
    report['candidate_identities'] = aliases
    d_ids = {s['evidence_id'] for s in new['supplemental_original_source']}
    report['explicit_new_source_citations'] = dict(assessments=[dict(seed_aliases=a['seed_aliases'], scope=a['scope'], ids=sorted(set(a['evidence_ids']) & d_ids)) for a in decision.get('assessments',[]) if set(a['evidence_ids']) & d_ids], goals=[dict(goal_id=g['goal_id'], seed_alias=g['seed_alias'], ids=sorted(set(g['evidence_ids']) & d_ids)) for g in decision.get('goals',[]) if set(g['evidence_ids']) & d_ids])
    report['receipts'].update(decision=receipt(judgment/'decision.json'), decision_seal=receipt(judgment/'decision_seal.json'), raw_completion=receipt(judgment/'completion/completion.txt'))
    # Human judgment below is tied to this exact frozen diagnostic decision.
    expected_decision = '32d3874b8f8bb028fe784c73125c786478d12cee081802749c83bb0ed8dbffbe'
    if report['receipts']['decision']['sha256'] == expected_decision:
        report['semantic_review'] = dict(status='complete',
            reference_scope='recursive_pipe_runtime_nonidentity_transform',
            runtime_outer_transform_target_recognized=False, target_goal_ids=[],
            goal_count=2, goals_explicitly_citing_added_source=0,
            assessments_explicitly_citing_added_source=0,
            scoped_anchor_assessment='S011与其它sync容器测试被归组为no_gap，理由是自引用身份及parse/safeParse覆盖。',
            goal_review=[dict(goal_id='G1', purpose='编译期拒绝input-only Recur', target_match=False,
                reason='transform用于抹除输出类型中的Recur；不执行递归outer管道并观察非恒等输出。'),
                dict(goal_id='G2', purpose='编译期拒绝output-only Recur', target_match=False,
                reason='transform返回Recur用于类型约束；仍不是递归运行时转换观察。')],
            source_gap_status='previously_missing_action_source_now_present_exactly',
            diagnosis='此前readonly/transform原始行为源码缺项已补齐。这一次输出仍未将readonly同值行为与transform非恒等行为转化为运行时验证目标。',
            interpretation='目标未表述不等于模型明确否定该关系。无D显式引用不能证明模型没有读取或使用新增材料；不能从一次人工补齐诊断推断平均因果效果。')
    else:
        report['semantic_review'] = dict(status='awaiting_manual_scope_review')
else:
    report['semantic_review'] = dict(status='pending_judgment')
output = ROOT/'research/automatic_augmentation_context_judgment_audit_20261005.json'
output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(dict(output=receipt(output), provider=report['provider'], semantic_review=report['semantic_review']), ensure_ascii=False))
