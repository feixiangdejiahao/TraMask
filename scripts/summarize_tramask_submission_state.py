"""Publish the state audit separately from the frozen selected-test pilot."""
from collections import Counter
from datetime import datetime,timezone
import html
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from tramask_pilot.corpus import RUN,read,write,receipt
from tramask_pilot.submission_replay import OUTPUT,state_directory

def main():
    out=RUN/'submission_state_audit'
    cases=sum([read(RUN/f'formal_{k}_cohort.json')['cases'] for k in ('failed','successful')],[])
    rows=[]
    for case in cases:
        cid=case['id'];directory=state_directory(cid)
        summary=read(directory/'summary.json') if (directory/'summary.json').exists() else None
        report_path=directory/'validation_v03/report.json'
        v=read(report_path) if report_path.exists() else None
        row={'case_id':cid,'task':case['task'],'status':v['submission_state_status'] if v else 'validation_pending' if summary else 'replay_pending',
             'source':str(directory),'actions':summary['actions_executed'] if summary else None}
        if summary:row.update(checkpoint_image=summary['checkpoint']['image_id'],inventory=summary['inventory'])
        if v:row.update(validation=receipt(report_path),submitted_commit_tree_matches=v['submitted_commit_tree_matches'],
            working_tree_matches=v['working_tree_matches_submitted_commit'],compared_paths=v['compared_paths'],
            mismatched_paths=[m['path'] for m in v['mismatches']],unverified=v['unverified'])
        if (directory/'error.json').exists() and not summary:row.update(status='execution_error',error=read(directory/'error.json'))
        rows.append(row)
    summary={'created_at':datetime.now(timezone.utc).isoformat(),'requested_criterion':'trajectory final state immediately before patch submission; stdout differences irrelevant',
        'formal_cases':40,'counts':dict(Counter(r['status'] for r in rows)),
        'total_actions_replayed':sum(r['actions'] or 0 for r in rows),
        'provider_calls_added':0,'previous_output_23_vs_12_is_not_a_state_acceptance_gate':True,
        'previous_static_audit':receipt(out/'static_existing_replay_audit.json'),
        'original_terminal_authority':receipt(out/'original_terminal_authority.json'),
        'tool_semantics':receipt(out/'tool_semantics.json'),
        'acceptance':['Every recorded action before the unique submission marker is executed in order. Original command text is retained; F027 has one explicit dynamic-PID binding and F004 one build-only CPU visibility adaptation.',
                      'Frozen HEAD tree matches the submitted patch oracle independently.',
                      'Frozen working files match expected checkout bytes, paths, types and Git modes.',
                      'The checkpoint preserves the container filesystem; files under /app and /tmp, including ignored dependencies and builds, have content inventories. Global dependency/cache paths outside those roots are preserved but not inventoried.'],
        'limitations':['Original full filesystem snapshots are unavailable. The independent patch oracle proves committed source/test files; untracked/tmp/dependency state is reconstructed from the recorded actions, not proven byte-identical to an original disk manifest.',
                       'Original environment overrides are not retained by ATIF. Execution uses verified mini-swe-agent 2.4.5 defaults and the original image.',
                       'Docker checkpoints preserve filesystem state, not live process memory. Process listings are retained.',
                       'The old pilot uses historical test contexts over final production code. Its frozen judgments and downstream outcomes are not automatically validated for these new terminal checkpoints.'],
        'cases':rows}
    runtime_path=out/'runtime_state_audit.json'
    runtime_audit=read(runtime_path) if runtime_path.exists() else {'status':'pending'}
    summary['runtime_state_audit']=runtime_audit
    evidence_names=['verification_v01.json','generated_runtime_audit.json',
        'dependency_audit_complete_v01.json','final_state_review_a.json','final_state_review_b.json']
    summary['additional_evidence']=[receipt(out/name) for name in evidence_names if (out/name).exists()]
    write(out/'summary.json',summary)
    def esc(v):return html.escape(str(v))
    def link(path,label):return '<a href="'+esc(Path(path).relative_to(out))+'">'+esc(label)+'</a>'
    additional=' · '.join(link(out/name,name) for name in evidence_names if (out/name).exists())
    table=[]
    for row in rows:
        target=Path(row['source'])/'validation_v03/report.json'
        label=link(target,row['status']) if target.exists() else esc(row['status'])
        table.append('<tr><td>'+esc(row['case_id'])+'</td><td>'+esc(row['task'])+'</td><td>'+label+'</td><td>'+esc(row['actions'])+'</td><td>'+esc(', '.join(row.get('mismatched_paths',[])))+'</td></tr>')
    doc='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>TraMask 提交前状态复核</title>
<style>body{max-width:1180px;margin:36px auto;font:16px/1.65 system-ui;padding:0 24px;color:#202a33}table{border-collapse:collapse;width:100%}td,th{padding:9px;border-bottom:1px solid #ddd;text-align:left}.note{background:#fff4d8;padding:18px}a{color:#1663a7}code{font-size:.9em}</style>
<h1>TraMask 提交前状态复核</h1>
<p>验收目标：恢复 trajectory 最终提交前的状态。日志、耗时、测试输出以及 commit ID 的文字差异不作为失败依据。</p>
<p class="note">旧报告中的“23 个归一化一致、12 个不一致”仅比较选定测试的输出，不能证明提交前状态。本复核单独检查完整轨迹终点，保留旧记录。旧 pilot 的 masking 与下游结论尚不能直接移用于新的终态容器。</p>
<h2>提交树与工作区文件校验</h2><p>'''+esc(json.dumps(summary['counts'],ensure_ascii=False))+'''；已顺序执行 '''+esc(summary['total_actions_replayed'])+''' 条原始命令；新增模型请求 0 次。</p>
<p>生成产物及后台进程专项检查：'''+esc(runtime_audit['status'])+'。'+link(runtime_path,'专项证据')+'''。文件树一致不能代替该专项检查。</p>
<h2>校验方法</h2><p>从原始 Docker image 开始，使用 /bin/sh 和原工具的 30 秒超时、进程组终止规则，执行提交标记前的全部命令。保存最终 checkpoint 后，在新容器中独立重建 base + model.patch，分别核对 HEAD 树和经过仓库 checkout 规则生成的工作区文件。实际 replay 文件不被 patch 覆盖，也不做输出或文件内容归一化。</p>
<p>原始收集 hook 使用 <code>git diff --binary BASE HEAD</code>，因此 patch 的直接证明范围是最终已提交文件。40 条轨迹最后一次 git status 均显示干净；完整证据及后续动作已逐案记录。</p>
<p>三项专项处理另行留证：F004 仅在原构建命令中将构建工具可见 CPU 数限制为实际分配的 2 核，恢复 dist；F027 将原轨迹的 PID 绑定到本次实际启动的同一服务器，仅替换 kill 的 PID；S026 新一次重放在原第 41 步已自然结束后台测试，第 80 步后的完成检查没有等待或强制终止。旧尝试全部保留，S026 首次停滞的具体原因未确定。</p>
<h2>已纠正的旧状态问题</h2><p>38/40 个旧 replay 的选定测试后仍有轨迹动作。现存旧快照有 11 个案例、16 个测试或 fixture 文件被较早版本覆盖，确定不等于最终提交。另有 19 个提交文件被旧归档规则漏收，不能据此断言容器文件缺失。</p>
<h2>逐案证据</h2><table><tr><th>案例</th><th>任务</th><th>状态</th><th>完整动作数</th><th>文件差异</th></tr>'''+''.join(table)+'''</table>
<h2>证明范围</h2><p>容器文件系统保存在新 checkpoint 中；文件内容清单覆盖 /app 和 /tmp，包括这些目录内的忽略文件、依赖及构建产物。其他目录的全局依赖与缓存保存在 checkpoint 中，但未进入 JSON 内容清单。由于没有原始运行结束时的全盘快照，这部分是按完整轨迹重建，不能声称与原始磁盘逐字节独立核验。容器 checkpoint 不保存进程内存；原始环境变量覆盖配置也未保存在 ATIF 中。</p>
<p>原始证据：'''+link(out/'summary.json','完整汇总')+' · '+link(out/'static_existing_replay_audit.json','旧快照审计')+' · '+link(out/'original_terminal_authority.json','原始提交机制与终态证据')+' · '+link(out/'tool_semantics.json','原工具执行语义')+'''</p><p>收尾核验与独立审查：'''+additional+'''</p></html>'''
    (out/'report.html').write_text(doc)
    print(json.dumps({'counts':summary['counts'],'actions':summary['total_actions_replayed'],'report':str(out/'report.html')},ensure_ascii=False))

if __name__=='__main__':main()
