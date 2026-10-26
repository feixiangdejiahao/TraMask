"""Build the P2 evidence index, machine-readable observations and HTML report."""
from __future__ import annotations

import hashlib
from html import escape
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "research/constructive_abstraction_20261021"
RESULTS = ROOT / "results/behavioral_gap_augmentation"
TRIALS = ROOT / "results/failure_analysis/deepswe_failed_trials_n211_20261006/trials"
FIELDS = ["Mechanism", "Property", "Derivation", "Construction", "Simplification", "Scope", "Counterexample", "Prior Art"]


def main():
    findings = json.loads((STUDY / "findings.json").read_text())
    evidence = []
    selected = {
        "tengo-callable-instance-isolatio__t9BgKmx": [98, 99, 101, 104],
        "tengo-destructuring-bindings__ckNqCrH": [13, 34, 99, 137, 165],
        "koota-query-predicates__HMm8bxx": [90, 97],
    }
    for trial, step_ids in selected.items():
        source = TRIALS / trial / "trajectory.json"
        raw = source.read_text()
        steps = {s["step_id"]: s for s in json.loads(raw)["steps"]}
        for step_id in step_ids:
            match = re.search(r'"step_id"\s*:\s*' + str(step_id) + r'\s*[,}]', raw)
            step = steps[step_id]
            evidence.append({"trial": trial, "step_id": step_id,
                "path": str(source.relative_to(ROOT)),
                "line": raw.count("\n", 0, match.start()) + 1 if match else None,
                "trajectory_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "reasoning_content": step.get("reasoning_content"),
                "tool_calls": step.get("tool_calls"),
                "observation": step.get("observation")})
    (STUDY / "trajectory_evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    executions = []
    for run in sorted(RESULTS.glob("20261021_constructive_p2_check_r*")):
        paths = sorted(run.glob("cases/*/*/execution.json")) + sorted(run.glob("boundaries/*/execution.json"))
        for path in paths:
            data = json.loads(path.read_text())
            out = (path.parent / "stdout.log").read_text()
            rows = []
            for line in out.splitlines():
                line = re.sub(r'\x1b\[[0-9;]*m', '', line)
                if "P2_RESULT " in line:
                    rows.append(json.loads(line.split("P2_RESULT ", 1)[1]))
            executions.append({"path": str(path.relative_to(ROOT)), **data,
                "observations": rows, "observations_passed": sum(r["pass"] for r in rows),
                "observations_failed": sum(not r["pass"] for r in rows)})
    (STUDY / "executions.json").write_text(json.dumps(executions, ensure_ascii=False, indent=2) + "\n")
    canonical = {"T13": "r01", "T17": "r04", "T25": "r03", "T29": "r02"}
    selected_executions = [e for e in executions if any(
        f"check_{r}/cases/{c}/generated/" in e["path"] for c, r in canonical.items())]
    assert len(selected_executions) == 4
    assert sum(e["observations_failed"] for e in selected_executions) == 10
    assert sum(len(e["observations"]) for e in selected_executions) == 106
    for c in findings["candidates"]:
        assert all(field in c for field in FIELDS)
    def para(text):
        return "<p>" + escape(text) + "</p>"
    def local(path, label):
        return '<a href="../../' + escape(path, quote=True) + '">' + escape(label) + '</a>'
    parts = ['''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>P2 构造性抽象核查</title><style>
body{max-width:1080px;margin:40px auto;padding:0 24px;font:16px/1.75 system-ui,sans-serif;color:#202b35;background:#fafbfc}
p{margin:14px 0}strong{color:#15283d}a{color:#1663a5}table{width:100%;border-collapse:collapse;background:white;margin:20px 0}
td,th{padding:12px;border:1px solid #d9e0e6;vertical-align:top;text-align:left}th{background:#edf2f6}
dt{font-weight:700;margin-top:16px;color:#15283d}dd{margin:3px 0 16px}.card{padding:22px;margin:24px 0;border:1px solid #d9e0e6;border-radius:8px;background:white}
pre{white-space:pre-wrap;background:#eef2f5;padding:16px}details{margin:12px 0}small{color:#536273}</style><body>''']
    parts += ["<p><strong>" + escape(findings["title"]) + "</strong></p>", para(findings["verdict"]), para(findings["evidence_policy"])]
    parts.append('<p>' + local('src/constructive_p2.py', '生成器') + ' · ' + local('scripts/run_constructive_p2.py', '执行脚本') + ' · ' + local('research/constructive_abstraction_20261021/findings.json', '完整结构化结论') + ' · ' + local('research/constructive_abstraction_20261021/trajectory_evidence.json', '原轨迹摘录') + ' · ' + local('research/constructive_abstraction_20261021/executions.json', '全部执行记录') + '</p>')
    parts.append('<p><strong>确认的原补丁执行结果</strong></p><table><tr><th>案例</th><th>生成测试</th><th>观察到的失败</th><th>输出</th></tr>')
    for e in selected_executions:
        case = e["path"].split('/cases/')[1].split('/')[0]
        parts.append('<tr><td>' + case + '</td><td>' + str(len(e['observations'])) + '</td><td>' + str(e['observations_failed']) + '</td><td>' + local(e['path'].replace('execution.json','stdout.log'), '原始日志') + '</td></tr>')
    parts.append('</table>' + para('10 个失败测试对应 2 个已分析根因；不是 10 个独立漏洞。T25 的通过是独立系统正例复用；T29 的通过没有提供新故障证据。'))
    parts.append('<p><strong>P2-A：实现、测试与生成过程分别解释</strong></p>')
    for row in findings['disentanglement']:
        parts.append('<div class="card"><strong>' + row['case'] + '</strong><dl>')
        for key in ['implementation','test','agent_process','observable']:
            parts.append('<dt>' + key + '</dt><dd>' + escape(row[key]) + '</dd>')
        parts.append('</dl></div>')
    parts.append('<p><strong>P2-B：竞争解释与反证</strong></p><table><tr><th>案例</th><th>假设</th><th>检验</th></tr>')
    for h in findings['competing_hypotheses']:
        parts.append('<tr>' + ''.join('<td>' + escape(h[k]) + '</td>' for k in ['case','hypothesis','result']) + '</tr>')
    parts.append('</table>')
    source_ids = {'A':['cpython','copy-contract','mt','korat'], 'B':['adapton','adapton-lab','rondo'], 'C':['quickcheck','ecmascript']}
    for candidate in findings['candidates']:
        parts.append('<div class="card"><strong>候选 ' + candidate['id'] + '：' + escape(candidate['name']) + '</strong><dl>')
        for field in FIELDS:
            parts.append('<dt>' + field + '</dt><dd>' + escape(candidate[field]))
            if field == 'Prior Art':
                sources = [s for s in findings['sources'] if s['id'] in source_ids[candidate['id']]]
                parts.append(' ' + ' · '.join('<a href="' + escape(s['url'],quote=True) + '">' + escape(s['title']) + '</a>' for s in sources))
            parts.append('</dd>')
        parts.append('</dl><pre>' + escape(json.dumps(candidate['hard_gates'], ensure_ascii=False, indent=2)) + '</pre></div>')
    parts += [para(findings['hard_gate_interpretation']), '<p><strong>尚未建立的结论</strong></p><ul>']
    parts += ['<li>' + escape(x) + '</li>' for x in findings['what_is_not_established']]
    parts += ['</ul><p><strong>执行修订记录</strong></p><ul>']
    parts += ['<li>' + escape(x) + '</li>' for x in findings['execution_corrections']]
    parts += ['</ul><p><strong>轨迹定位</strong></p><ul>']
    for e in evidence:
        parts.append('<li>' + local(e['path'],e['trial'] + ' step ' + str(e['step_id'])) + '，JSON 第 ' + str(e['line']) + ' 行</li>')
    parts += ['</ul>', '<pre>' + escape(findings['reproduce']) + '</pre>', '</body></html>']
    (STUDY / "report.html").write_text(''.join(parts))
    print(json.dumps({"trajectories_indexed": len(selected), "steps": len(evidence), "execution_records": len(executions), "canonical_generated": 106, "failed_variants": 10, "report": str((STUDY / 'report.html').relative_to(ROOT))}))


if __name__ == "__main__":
    main()
