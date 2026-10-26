"""Re-evaluate saved pilots after the T08-R1 oracle classification correction.

Frozen method outputs and original evaluations stay intact. New current
evaluation pointers select these versioned results. No model or subject runs.
"""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
from html import escape
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT/'experiments/relation_distinction/results'
BASE = RESULTS/'pilot30_20261007_v1'
OLD = BASE/'benchmark_reverse_v4'
NEW = BASE/'benchmark_reverse_v5'
AUDIT = ROOT/'research/t08_statistics_revision_20261010'
REPORT = ROOT/'docs/20261010_behavioral_gap_evaluation_revision_t08.html'
EXCLUDED = 'T08-R1'
VERSION = 't08-oracle-reclassification-20261010.v1'

def read(path): return json.loads(Path(path).read_text())
def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
def receipt(path):
    path = Path(path)
    return {'path':str(path.relative_to(ROOT)), 'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
def stamp(source):
    return {'version':VERSION, 'previous_evaluation':receipt(source),
        'excluded_target':EXCLUDED, 'new_category':'existing_wrong_oracle',
        'evidence':receipt(ROOT/'research/trajectory_program_search30_20261010/evidence/T08.json'),
        'reason':'轨迹第36步已创建缺少结束分隔符的测试，并断言接受；第37步记录通过。它不是缺少输入组合。',
        'new_model_calls':0,'new_subject_executions':0}

def filtered(values): return [x for x in values if x != EXCLUDED]

def change_target(row):
    row['category'] = 'existing_wrong_oracle'
    row['primary_positive'] = False
    row['original_validation'] = ('原 trajectory 第36步 test_missing_closing_delimiter 使用合法 part 前缀且没有结束分隔符，'
        '断言 len(ps)==1 且 content==body text。第37步输出该测试通过；第54步又观察到同样行为。')
    row['classification_reason'] = ('同一关键输入类别已经生成并执行。问题是接受预期与公开完整性要求相反。'
        '保留原补丁与 gold 的差分事实，但从组合输入缺口和对应漏检分母中移除。')
    row['classification_revision'] = stamp(OLD/'review.json')

def recompute_metrics(old, targets):
    m = deepcopy(old)
    positive = sorted({r['case'] for r in targets})
    det = [r['id'] for r in targets if r['method_detected']]
    gen = [r['id'] for r in targets if r['method_generated_fault_revealing_test']]
    miss = [r['id'] for r in targets if not r['method_detected']]
    m.update(eligible_targets=len(targets), eligible_trials=len(positive),positive_trials=positive,
        detected_targets=det,generated_targets=gen,false_negative_targets=miss,
        detected_target_count=len(det),generated_target_count=len(gen),false_negative_target_count=len(miss),
        target_recall=len(det)/len(targets),
        benchmark_related_targets=sum(t['source']=='benchmark_reverse' for t in targets),
        additional_historical_targets=sum(t['source']=='historical_static' for t in targets))
    sensitivity=[t for t in targets if t['id']!='T15-R1']
    m['boundary_sensitivity']={'excluded':'T15-R1','targets':len(sensitivity),
        'trials':len({t['case'] for t in sensitivity}),
        'detected_targets':sum(t['method_detected'] for t in sensitivity),
        'generated_targets':sum(t['method_generated_fault_revealing_test'] for t in sensitivity)}
    return m

def baseline():
    review=deepcopy(read(OLD/'review.json'))
    review['version']='pilot30-benchmark-guided-semantic-reverse-v5'
    review['date']='2026-10-10'
    change_target(next(t for t in review['targets'] if t['id']==EXCLUDED))
    review['revision']=stamp(OLD/'review.json')
    write(NEW/'review.json',review)
    labels=deepcopy(read(OLD/'labels.json'))
    labels['version']=review['version'];labels['review_receipt']=receipt(NEW/'review.json')
    change_target(next(t for t in labels['targets'] if t['id']==EXCLUDED))
    write(NEW/'labels.json',labels)
    combined=deepcopy(read(OLD/'combined_targets.json'))
    removed=[t for t in combined['targets'] if t['id']==EXCLUDED]
    assert len(removed)==1 and not removed[0]['method_detected'] and not removed[0]['method_generated_fault_revealing_test']
    combined['targets']=[t for t in combined['targets'] if t['id']!=EXCLUDED]
    metrics=recompute_metrics(combined['summary'],combined['targets'])
    combined.update(review=receipt(NEW/'review.json'),benchmark_labels=receipt(NEW/'labels.json'),summary=metrics,
        excluded_oracle_targets=[{**removed[0], 'category':'existing_wrong_oracle'}],revision=stamp(OLD/'combined_targets.json'))
    write(NEW/'combined_targets.json',combined)
    summary=deepcopy(read(OLD/'summary.json'))
    summary.update(version=review['version'],date=review['date'],
        classification_counts=dict(Counter(t['category'] for t in labels['targets'])),
        combined_static_screening=metrics,primary_metrics=metrics,revision=stamp(OLD/'summary.json'))
    benchmark=[t for t in labels['targets'] if t['primary_positive']]
    summary['benchmark_combination_trials']=[t['case'] for t in benchmark]
    bm=summary['benchmark_subset_metrics']
    bm.update(eligible_trials=len(benchmark),eligible_targets=len(benchmark),
        false_negative_targets=[t['id'] for t in benchmark if not t['method_detected']],
        false_negative_count=sum(not t['method_detected'] for t in benchmark),
        target_recall=sum(t['method_detected'] for t in benchmark)/len(benchmark))
    summary['boundary_sensitivity']['eligible_targets']=len(benchmark)-1
    write(NEW/'summary.json',summary)
    diag=deepcopy(read(BASE/'diagnosis_v5/summary.json'))
    diag.update(reference_targets=len(combined['targets']),reference_missed_targets=metrics['false_negative_target_count'],
        revision=stamp(BASE/'diagnosis_v5/summary.json'))
    write(NEW/'diagnosis_summary.json',diag)
    return summary,combined

def projected(run, paths, target_ids):
    out=run/'evaluation/t08_oracle_reclassification_v1'
    written={}
    for rel in paths:
        oldpath=run/rel
        d=deepcopy(read(oldpath))
        d['revision']=stamp(oldpath)
        if rel=='summary.json' and 'reference' in d:  # v2
            r=d['reference'];r['targets']=len(target_ids)
            for field in ('detected_targets','generated_targets','missed_targets'):
                r[field]=filtered(r[field])
            r['missed_target_count']=len(r['missed_targets'])
            r['target_recall']=len(r['detected_targets'])/len(target_ids)
            for task in d.get('tasks', []):
                for field in ('reference_targets','detected_reference_targets','generated_reference_targets','missed_reference_targets'):
                    if field in task:
                        task[field]=filtered(task[field])
        elif rel.endswith('summary.json') and 'primary_targets' in d:
            d['primary_targets']=len(target_ids)
            d['primary_missed']=len(target_ids)-d['primary_detected']
            d['expanded_targets']=len(target_ids)+1
            d['expanded_missed']=d['expanded_targets']-d['expanded_detected']
            if 'selected_representation_review' in d:
                target_rows=read(run/'evaluation/target_review.json')['targets']
                d['selected_representation_review']=dict(Counter(t['selected_representation'] for t in target_rows if t['id']!=EXCLUDED))
        elif rel=='diagnosis_v1/summary.json':
            d.update(fixed_targets=len(target_ids),fixed_misses=len(target_ids)-d['fixed_hits'],
                expanded_targets=len(target_ids)+1,expanded_misses=d['expanded_misses']-1,reference_label_edits=1)
            for group in d['main_diagnostic_categories'].values():
                group['targets']=filtered(group['targets']);group['count']=len(group['targets'])
        elif rel in ('evaluation/reference_targets.json','evaluation/target_review.json'):
            d['excluded_targets']=[{**t,'current_category':'existing_wrong_oracle'} for t in d['targets'] if t['id']==EXCLUDED]
            d['targets']=[t for t in d['targets'] if t['id']!=EXCLUDED]
            for t in d['targets']:
                if t['set']=='primary23':t['set']='primary22'
            if 'primary_count' in d:d['primary_count']=len(target_ids)
            if 'expanded_count' in d:d['expanded_count']=len(target_ids)+1
        else:raise ValueError(rel)
        path=out/rel
        write(path,d);written[rel]=path
    write(run/'active_evaluation.json',{'version':VERSION,'summary':receipt(written['summary.json']),
        'reference':receipt(NEW/'combined_targets.json'),
        'revised_artifacts':{k:receipt(v) for k,v in written.items()},
        'rebuild_command':'.venv/bin/python scripts/reclassify_t08_oracle.py',
        'scope':'Current re-evaluation of frozen outputs; original summaries retain the original reference set.'})
    if 'decision_recovery_v1/summary.json' in written:
        write(run/'decision_recovery_v1/active_evaluation.json',{'version':VERSION,
            'summary':receipt(written['decision_recovery_v1/summary.json']),
            'reference':receipt(NEW/'combined_targets.json')})
        inventory=deepcopy(read(run/'diagnosis_v1/case_inventory.json'))
        for c in inventory:
            c['fixed_targets']=filtered(c['fixed_targets']);c['missed_fixed_targets']=filtered(c['missed_fixed_targets'])
        write(out/'diagnosis_v1/case_inventory.json',inventory)
        for p in (run/'diagnosis_v1/targets').glob('*.json'):
            d=deepcopy(read(p))
            if p.stem==EXCLUDED:
                d['excluded_from_current_combination_diagnosis']=True
                d['current_category']='existing_wrong_oracle'
                write(out/'diagnosis_v1/excluded'/p.name,d)
            else:
                if d.get('reference_set')=='primary23':d['reference_set']='primary22'
                write(out/'diagnosis_v1/targets'/p.name,d)
    return written

def html_table(headers,rows):
    return '<table><tr>'+''.join('<th>'+escape(v)+'</th>' for v in headers)+'</tr>'+''.join(
        '<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</table>'

def main():
    NEW.mkdir(parents=True,exist_ok=True)
    previous_active=NEW/'prior_active_evaluation.json'
    if not previous_active.exists():write(previous_active,read(BASE/'active_evaluation.json'))
    summary,combined=baseline();ids={t['id'] for t in combined['targets']}
    v2=projected(RESULTS/'pilot30_v2_20261008_v1',['summary.json'],ids)
    v3=projected(RESULTS/'pilot30_v3_detection_20261009_v1',[
        'summary.json','decision_recovery_v1/summary.json','diagnosis_v1/summary.json',
        'evaluation/reference_targets.json','evaluation/target_review.json'],ids)
    metrics=[
        ('原方法','1/23','1/22',22,21,'1 → 1'),
        ('改进后补测 v2','0/23','0/22',23,22,'0 → 0'),
        ('检测 v3 原预算','1/23','1/22',22,21,'未生成测试'),
        ('检测 v3 统一追加判断后','2/23','2/22',21,20,'未生成测试')]
    data={'version':VERSION,'reclassification':stamp(OLD/'review.json'),
        'fixed_reference_before':23,'fixed_reference_after':len(ids),'positive_tasks_before':18,
        'positive_tasks_after':len({t['case'] for t in combined['targets']}),
        'benchmark_representatives_before':13,'benchmark_representatives_after':12,
        'classification_counts_after':summary['classification_counts'],
        'fixed_target_comparisons':[dict(zip(['run','detection_before','detection_after','misses_before','misses_after','generation'],m)) for m in metrics],
        'v2_any_valid_detection_tasks':read(v2['summary.json'])['correct_detection_tasks'],
        'v2_false_positive_claims':read(v2['summary.json'])['false_positive_claim_count'],
        'v3_original_correct_tasks':read(v3['summary.json'])['correct_task_ids'],
        'v3_recovered_correct_tasks':read(v3['decision_recovery_v1/summary.json'])['combined_correct_task_ids'],
        'v3_recovered_false_positive_tasks':read(v3['decision_recovery_v1/summary.json'])['combined_false_positive_task_ids'],
        'revised_summaries':[receipt(NEW/'summary.json'),*[receipt(p) for p in v2.values()],*[receipt(p) for p in v3.values()]],
        'unaffected':['原始模型输出、测试文件、执行结果和费用','原历史41项目标池','不含T08的两组八任务pilot','T08-G1和T08-N1；恢复阶段另报的资源关闭目标'],
        'new_model_calls':0,'new_subject_executions':0}
    assert ids=={t['id'] for t in read(OLD/'combined_targets.json')['targets']}-{EXCLUDED}
    assert len(ids)==22 and data['positive_tasks_after']==18
    assert summary['primary_metrics']['false_negative_target_count']==21
    assert read(v2['summary.json'])['reference']['missed_target_count']==22
    assert read(v3['decision_recovery_v1/summary.json'])['primary_missed']==20
    write(AUDIT/'summary.json',data)
    body=['''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>T08 统计修订</title><style>body{max-width:1100px;margin:32px auto;padding:0 22px;font:16px/1.85 system-ui;color:#243344}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccd6df;padding:10px;text-align:left}th{background:#edf3f7}pre{white-space:pre-wrap;background:#f4f6f8;padding:16px}a{color:#146078}</style></head><body><h1>T08 统计修订：已有输入，错误预期</h1><p>2026-10-10。按用户要求，将 T08-R1 从组合输入缺口移至已有测试的预期判断问题。重新评价各轮保存结果，没有重跑模型或被测项目。</p>
<h2>修订依据</h2><p>第 36 步已经创建如下测试。第 37 步记录 PASS。它包含有效 part 前缀和缺少结束分隔符的输入，断言却接受该输入。</p><pre>def test_missing_closing_delimiter():
    ps = parts(b"--boundary\\r\\n\\r\\nbody text")
    assert len(ps) == 1 and ps[0].content == b"body text"</pre>
<p>原补丁与 gold 的差分事实仍保留。修订的是缺口类别，而不是宣称原补丁正确。T08-G1 的引号内分号缺口仍保留。T08-N1 的头部终止目标和后来单列的资源关闭目标也不受本次修订影响。</p>
<h2>重算后的统计</h2><p>固定参照从 23 项变为 22 项，仍涉及 18 个任务。T08-R1 在各轮均未命中，所以只减少参照漏检数，不增加成功数。下表的分母是固定目标，不是全部任务，也不是全部肯定报告。</p>''']
    body.append(html_table(['实验','原检测命中','现检测命中','原漏检数','现漏检数','固定目标正确补测数'],metrics))
    body.append('<p>对应目标召回率：原方法和 v3 原预算从 4.35% 变为 4.55%；v2 仍为 0%；v3 追加判断后从 8.70% 变为 9.09%。这只是标签修订，不是算法效果提升。</p>')
    body.append('<p>仅按 benchmark 代表性失败统计时，组合类从 13 项变为 12 项，已有测试预期问题从 3 项变为 4 项。另有 9 项非组合差异、1 项复验问题和 4 项待定。原方法仍命中 1 项，漏检从 12 项变为 11 项。</p>')
    body.append('<p>v2 对任意已接受目标的检测和补测仍各为 1 个任务，来自 T08 的其他目标；77 条误报不变。v3 原预算仍正确检测 2 个任务，追加判断后为 4 个任务，其中 T08 只接受资源关闭这一限定观察；严格剔除该限定观察时为 3 个任务。两项误报仍来自 T11 和 T23。</p>')
    body.append('<p>v3 的扩展参照从 24 项变为 23 项。原预算仍命中 1 项、漏检 22 项；追加后仍命中 2 项、漏检 21 项。漏检诊断的“关系或阶段未连通”从 12 项变为 11 项，其他三类保持 4、4、1 项。固定漏检总数为 20。</p>')
    body.append('<h2>当前结果入口</h2><p>原始实验输出和冻结协议保持不变。新的 active_evaluation.json 指向此次重算，避免把历史分母与当前分母混用。</p>')
    for label,path in [('完整修订统计',AUDIT/'summary.json'),('原方法当前参照',NEW/'combined_targets.json'),('原方法当前统计',NEW/'summary.json'),('v2 当前统计',v2['summary.json']),('v3 原预算当前统计',v3['summary.json']),('v3 追加判断后当前统计',v3['decision_recovery_v1/summary.json']),('v3 当前漏检诊断',v3['diagnosis_v1/summary.json']),('T08 原始证据',ROOT/'research/trajectory_program_search30_20261010/evidence/T08.json')]:
        body.append(f'<p><a href="../{escape(str(path.relative_to(ROOT)))}">{label}</a></p>')
    body.append('<p>本轮没有测量修复后的 resolution rate。当前筛选仍主要依据静态语义审阅，不是独立人工或新动态实验。</p></body></html>')
    REPORT.write_text('\n'.join(body))
    prior=read(previous_active)
    prior.update(version='pilot30-benchmark-guided-semantic-reverse-v5',
        labels=receipt(NEW/'combined_targets.json'),combined_static_targets=receipt(NEW/'combined_targets.json'),
        review=receipt(NEW/'review.json'),benchmark_failure_labels=receipt(NEW/'labels.json'),
        summary=receipt(NEW/'summary.json'),report=receipt(REPORT),
        previous_evaluation=receipt(previous_active),
        rebuild_command='.venv/bin/python scripts/reclassify_t08_oracle.py')
    write(BASE/'active_evaluation.json',prior)
    write(NEW/'verification.json',{'fixed_targets':len(ids),'positive_tasks':data['positive_tasks_after'],
        'only_removed_target':EXCLUDED,'frozen_v4_files_not_written':True,
        'new_model_calls':0,'new_subject_executions':0,'report':receipt(REPORT)})
    print(json.dumps({'fixed_targets':len(ids),'positive_tasks':data['positive_tasks_after'],
        'metrics':data['fixed_target_comparisons'],'report':str(REPORT.relative_to(ROOT))},ensure_ascii=False))

if __name__=='__main__':main()
