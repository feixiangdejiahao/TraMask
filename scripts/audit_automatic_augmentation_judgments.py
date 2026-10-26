"""Evaluation-only collector for frozen augmentation judgments and goals.

This script does not select seeds, modify prompts, call a model, or execute
tests. Human scope classifications live in a separate evaluation-only file.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import run_automatic_augmentation_pilot as strict
from scripts import run_automatic_augmentation_io_repair as repair

PILOT = ROOT / 'results/automatic_augmentation_pilot_20261005'
REFERENCE = ROOT / 'research/automatic_augmentation_reference_20261005.json'
ANNOTATIONS = ROOT / 'research/automatic_augmentation_judgment_annotations_20261005.json'
OUTPUT = ROOT / 'research/automatic_augmentation_judgment_audit_20261005.json'


def read(path):
    return json.loads(Path(path).read_text())


def receipt(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def verify(item):
    if receipt(item['path']) != item:
        raise ValueError('changed_evaluation_input:' + item['path'])


def key(round_name, case, batch, arm, repeat):
    return '/'.join([round_name, case, batch, arm, str(repeat)])


def collect():
    refs = {r['case']: r for r in read(REFERENCE)['targets']}
    source_audit_path = ROOT / 'research/automatic_augmentation_extraction_audit_20261005.json'
    source_audit = read(source_audit_path)
    annotations = read(ANNOTATIONS) if ANNOTATIONS.exists() else {'annotations': {}}
    manual = annotations['annotations']
    rounds = []
    for name, root, parser in [('strict', PILOT, strict.parse_judgment),
                               ('io_repair_v2', PILOT / 'io_repair_v2', repair.parse_judgment)]:
        protocol = read(root / 'prepared.json'); verify(read(root / 'seal.json'))
        rows = []
        for case in protocol['cases']:
            target = refs[case['case']]
            for batch in case['batches']:
                source = read(batch['source_payload']['path']); history = read(batch['history_payload']['path'])
                verify(batch['source_payload']); verify(batch['history_payload'])
                source_ids = strict.evidence_ids(source)
                history_only = strict.evidence_ids(history) - source_ids
                identities = {s['seed_alias']: s['base_test_id'] for s in batch['candidates']}
                target_aliases = {alias for alias, tid in identities.items() if tid in target['original_test_ids']}
                mapping = read(batch['identifier_map']['path']) if 'identifier_map' in batch else None
                if mapping:
                    verify(batch['identifier_map'])
                for arm in protocol['arms']:
                    for repeat in range(1, protocol['repeats'] + 1):
                        identity = key(name, case['case'], batch['batch_id'], arm, repeat)
                        directory = root / 'cases' / case['case'] / batch['batch_id'] / arm / f'repeat_{repeat}' / 'judgment'
                        decision_path = directory / 'decision.json'
                        row = dict(id=identity, case=case['case'], batch=batch['batch_id'], arm=arm, repeat=repeat,
                            reference_scope_id=target['scope_id'], scoped_reference_label=target['scope_label'],
                            source_candidate_count=len(identities), candidate_identities=identities,
                            target_aliases=sorted(target_aliases), target_test_ids=[identities[a] for a in sorted(target_aliases)],
                            decision_status='pending', manual_review_status='pending_decision', goals=[])
                        if not decision_path.exists() or not (directory / 'decision_seal.json').exists():
                            rows.append(row); continue
                        verify(read(directory / 'decision_seal.json'))
                        decision = read(decision_path)
                        manifest_path = directory / 'completion/manifest.json'
                        manifest = read(manifest_path)
                        raw_path = directory / 'completion/completion.txt'
                        content = raw_path.read_text() if raw_path.exists() else ''
                        expected = parser(content, manifest.get('finish_reason'), set(identities),
                                          strict.evidence_ids(source if arm == 'source_only' else history))
                        if expected != decision:
                            raise ValueError('judgment_does_not_redecode:' + identity)
                        goal_rows = []
                        for goal in decision.get('goals', []):
                            cited = [x for x in goal['evidence_ids'] if x in history_only]
                            goal_rows.append(dict(goal_id=goal['goal_id'], seed_alias=goal['seed_alias'],
                                base_test_id=identities[goal['seed_alias']], goal=goal,
                                explicitly_cited_history_ids=cited,
                                explicitly_cited_original_history_ids=[mapping['reverse'][x] if mapping else x for x in cited],
                                explicitly_cites_history=bool(cited)))
                        row.update(decision_status=decision['status'], issues=decision.get('issues', []),
                            assessments=decision.get('assessments', []),
                            scoped_anchor_assessments=[a for a in decision.get('assessments', []) if target_aliases.intersection(a['seed_aliases'])],
                            unassessed_aliases=decision.get('unassessed_aliases', []),
                            goals=goal_rows, finish_reason=manifest.get('finish_reason'),
                            response_model=manifest.get('response_model'), usage=manifest.get('usage'),
                            external_model_calls=manifest.get('external_model_calls', 0),
                            receipts=dict(decision=receipt(decision_path), decision_seal=receipt(directory / 'decision_seal.json'),
                                manifest=receipt(manifest_path), raw_completion=receipt(raw_path) if raw_path.exists() else None,
                                request=receipt(directory / 'request.json'),
                                source_payload=batch['source_payload'], history_payload=batch['history_payload'],
                                identifier_map=batch.get('identifier_map')),
                            raw_redecode_exact=True)
                        annotation = manual.get(identity)
                        if decision['status'] != 'decoded':
                            row.update(manual_review_status='io_unavailable_not_semantic_no_gap',
                                evaluation=dict(target_recognition='io_unavailable', target_goal_ids=[],
                                    local_control_false_gap=None, note='输出未通过原严格解码规则。不能据此评价缺口识别。'))
                        elif annotation is None:
                            row['manual_review_status'] = 'awaiting_manual_scope_review'
                        else:
                            if annotation['decision_sha256'] != row['receipts']['decision']['sha256']:
                                raise ValueError('stale_manual_annotation:' + identity)
                            unknown_goals = set(annotation.get('target_goal_ids', [])) - {g['goal_id'] for g in goal_rows}
                            if unknown_goals:
                                raise ValueError('annotation_unknown_goal:' + identity)
                            row.update(manual_review_status='source_reference_scope_reviewed', evaluation=annotation)
                        rows.append(row)
        groups = []
        for case in protocol['cases']:
            for arm in protocol['arms']:
                for repeat in range(1, protocol['repeats'] + 1):
                    group = [x for x in rows if x['case'] == case['case'] and x['arm'] == arm and x['repeat'] == repeat]
                    reviewed = [x for x in group if x['manual_review_status'] == 'source_reference_scope_reviewed']
                    evaluations = [x['evaluation'] for x in reviewed]
                    groups.append(dict(case=case['case'], arm=arm, repeat=repeat,
                        scoped_reference_label=refs[case['case']]['scope_label'],
                        batches_expected=len(group), decisions_available=sum(x['decision_status'] != 'pending' for x in group),
                        decoded_batches=sum(x['decision_status'] == 'decoded' for x in group),
                        decoded_batches_reviewed=len(reviewed),
                        source_candidate_count=sum(x['source_candidate_count'] for x in group),
                        target_anchor_batch_ids=[x['batch'] for x in group if x['target_aliases']],
                        recognized_target_any_batch=any(e.get('target_recognition') == 'recognized' for e in evaluations),
                        partially_recognized_target_any_batch=any(e.get('target_recognition') == 'partially_recognized' for e in evaluations),
                        target_goals=[dict(batch=x['batch'], goal_id=g) for x in reviewed for g in x['evaluation'].get('target_goal_ids', [])],
                        explicit_local_control_false_gap=any(e.get('local_control_false_gap') is True for e in evaluations),
                        explicit_local_control_covered=any(e.get('local_control_covered') is True for e in evaluations),
                        other_relation_only_count=sum(e.get('target_recognition') == 'other_relation_only' for e in evaluations),
                        pending=any(x['decision_status'] == 'pending' or x['manual_review_status'] == 'awaiting_manual_scope_review' for x in group)))
        goals = [g for r in rows for g in r['goals']]
        arm_summary = []
        for arm in protocol['arms']:
            arm_rows = [x for x in rows if x['arm'] == arm]
            positive = [g for g in groups if g['arm'] == arm and g['scoped_reference_label'] == 'confirmed_validation_gap']
            controls = [g for g in groups if g['arm'] == arm and g['scoped_reference_label'] == 'locally_covered_control']
            arm_summary.append(dict(arm=arm, judgments_expected=len(arm_rows),
                judgments_decoded=sum(x['decision_status'] == 'decoded' for x in arm_rows),
                judgments_io_unknown=sum(x['decision_status'] == 'unknown' for x in arm_rows),
                judgments_pending=sum(x['decision_status'] == 'pending' for x in arm_rows),
                positive_case_repeats_expected=len(positive),
                positive_case_repeats_with_any_decoded_batch=sum(g['decoded_batches'] > 0 for g in positive),
                positive_case_repeats_all_batches_decoded=sum(g['decoded_batches'] == g['batches_expected'] for g in positive),
                positive_case_repeats_full_target_goal=sum(bool(g['target_goals']) for g in positive),
                positive_case_repeats_partial_recognition=sum(g['partially_recognized_target_any_batch'] for g in positive),
                control_case_repeats_expected=len(controls),
                control_case_repeats_covered=sum(g['explicit_local_control_covered'] for g in controls),
                control_case_repeats_false_gap=sum(g['explicit_local_control_false_gap'] for g in controls),
                control_case_repeats_io_unknown=sum(g['decisions_available'] == g['batches_expected'] and g['decoded_batches'] == 0 for g in controls),
                control_case_repeats_pending=sum(g['pending'] for g in controls)))
        rounds.append(dict(round=name, protocol=receipt(root / 'prepared.json'), rows=rows, by_case_arm_repeat=groups,
            by_arm=arm_summary,
            counts=dict(expected_decisions=len(rows), available_decisions=sum(x['decision_status'] != 'pending' for x in rows),
                decoded=sum(x['decision_status'] == 'decoded' for x in rows),
                io_unknown=sum(x['decision_status'] == 'unknown' for x in rows),
                pending=sum(x['decision_status'] == 'pending' for x in rows),
                awaiting_manual_scope_review=sum(x['manual_review_status'] == 'awaiting_manual_scope_review' for x in rows),
                source_reference_scope_reviewed=sum(x['manual_review_status'] == 'source_reference_scope_reviewed' for x in rows),
                goals=len(goals), history_arm_goals=sum(len(x['goals']) for x in rows if x['arm'] == 'source_and_trajectory'),
                history_arm_goals_explicitly_citing_history=sum(g['explicitly_cites_history'] for x in rows if x['arm'] == 'source_and_trajectory' for g in x['goals']),
                judgment_calls=sum(x.get('external_model_calls', 0) for x in rows),
                measured_judgment_tokens=sum((x.get('usage') or {}).get('total_tokens', 0) for x in rows)),
            completion='complete' if all(not g['pending'] for g in groups) else 'partial_snapshot'))
    report = dict(version='automatic-augmentation-judgment-audit.v1', updated_utc=datetime.now(timezone.utc).isoformat(),
        evaluation_only=True, reviewer=dict(implemented_extractor=True, blind=False,
            evaluated_after_frozen_dispatch=True, new_generated_test_or_native_outputs_used=False,
            secondary_outcome_notifications_received=True,
            disclosure='未读取生成测试或原生结果文件。其他评审随后通知了少数结果及N04目标命中。本文以封存判断文本重新核对；先前目标配方判定不因后续测试修正而回改。'),
        reference=receipt(REFERENCE), source_audit=receipt(source_audit_path),
        source_opportunity=[dict(case=x['case'], counts=x['counts'],
            test_recall=dict(selected=x['test_recall']['selected'], total=x['test_recall']['total']),
            public_evidence_status=x['manual_assessment']['public_evidence_status'],
            history_status=x['manual_assessment']['history_status'],
            facts_established=x['manual_assessment']['facts_established'],
            facts_not_established=x['manual_assessment']['facts_not_established'],
            conclusion=x['manual_assessment']['conclusion']) for x in source_audit['items']],
        annotations=receipt(ANNOTATIONS) if ANNOTATIONS.exists() else None,
        evaluator=receipt(__file__), rounds=rounds,
        other_goal_claim_findings=[dict(round=rd['round'], work_item=row['id'], **finding)
            for rd in rounds for row in rd['rows'] for finding in row.get('evaluation', {}).get('other_goal_claim_findings', [])],
        interpretation=['每个 case/arm/repeat 分开报告。禁止合并两臂或两轮的最佳结果。',
            '未知或格式失败不计作正确拒绝，也不直接计作语义漏检。',
            '局部负对照的其它关系缺口不计作该对照误报。',
            '显式历史引用只能说明引用发生。它不证明历史的因果贡献或模型内部推理过程。',
            '全部参照测试进入两臂原材料。10 个参照测试也均与补丁改动行重叠，不能将该召回归因于新增绑定分析。',
            'N01/N04/P2 原始公开源码足以提出目标问题；P7 缺少 readonly/transform 行为块。目标未被提出时应分开记录材料缺失、目标表述和优先选择。',
            '未表述目标关系，不等于显式否定该关系。只有明确识别但未落实 goal 时，才能直接称为目标优先选择损失。',
            'goals 仍是待审核目标。本文不把目标成立、生成测试有效和补丁缺陷混为一谈。'])
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return dict(output=receipt(OUTPUT), rounds=[dict(round=r['round'], **r['counts']) for r in rounds])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__); parser.parse_args()
    print(json.dumps(collect(), ensure_ascii=False))
