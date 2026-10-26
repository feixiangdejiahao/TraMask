#!/usr/bin/env python3
"""Render the confirmed-gap Pilot 1 report from its merged report_data.json."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import html
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = ROOT / "results/behavioral_masking/20261025_confirmed_gaps_pilot1_n88_r01"
SUCCESS = {"Single-factor Context Repair", "Multi-factor Context Repair"}
LABELS = {
    "Single-factor Context Repair": "单因素上下文修复",
    "Multi-factor Context Repair": "多因素上下文修复",
    "Assertion Repair Required": "需要修正断言",
    "Different Stimulus Required": "需要改变目标输入",
    "Not Comparable / Unresolved": "不可比或未解决",
    "Step1 Ineligible": "不满足行为失败资格",
    "Step 1 Ineligible": "不满足行为失败资格",
}
O4_LABELS = {
    "same_setup_condition_executed": "相同上下文条件已执行",
    "related_components_executed": "相关组成条件已执行",
    "not_found_or_text_only": "未找到执行，或仅有文字",
}
UNIT_LABELS = {
    "alignment_only": "原测试对齐审查",
    "failed_reference_control": "参考实现对照失败",
    "independent_original_script_section": "原脚本中的独立片段",
    "original_named_test": "原命名测试",
    "whole_original_exception_smoke": "完整原脚本，以无未捕获异常为成功条件",
}


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def text_value(value: object) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value or "")


def table(headers: list[str], rows: list[list[str]], css: str = "") -> str:
    return (
        f'<div class="table-wrap"><table class="{esc(css)}"><thead><tr>'
        + "".join(f"<th>{esc(h)}</th>" for h in headers)
        + "</tr></thead><tbody>"
        + "".join("<tr>" + "".join(f"<td>{v}</td>" for v in row) + "</tr>" for row in rows)
        + "</tbody></table></div>"
    )


def badge(value: str) -> str:
    return f'<span class="result {"pass" if value == "PASS" else "fail"}">{esc(value)} × 2</span>'


class Report:
    def __init__(self, data: dict, run: Path, output: Path):
        self.data, self.run, self.output = data, run, output
        self.cases = data.get("cases", [])
        self.by_id = {case["screen_id"]: case for case in self.cases}
        self.success = [case for case in self.cases if case.get("outcome") in SUCCESS]

    def link(self, path: str, label: str | None = None) -> str:
        p = Path(path)
        if not p.is_absolute():
            p = ROOT / p if (ROOT / p).exists() else self.run / p
        relative = os.path.relpath(p, self.output.parent)
        return f'<a href="{esc(relative)}">{esc(label or Path(path).name)}</a>'

    def evidence(self, case_id: str, extra: list[str] | None = None) -> str:
        case = self.by_id.get(case_id, {})
        paths = list(case.get("evidence_paths") or []) + (extra or [])
        matrix = case.get("matrix_summary")
        if isinstance(matrix, str) and matrix.endswith(".json"):
            paths.append(matrix)
        for name in ["analysis.json", "evidence_index.json", "selected_trajectory_evidence.json"]:
            p = self.run / "screening" / case_id / name
            if p.exists():
                paths.append(str(p))
        links = [self.link(str(p)) for p in dict.fromkeys(paths)]
        return '<details class="evidence"><summary>展开原始证据</summary><div class="links">' + " · ".join(links) + "</div></details>" if links else ""

    def family_table(self) -> str:
        families: dict[str, list[dict]] = defaultdict(list)
        for case in self.success:
            family = case.get("factor_family_zh") or case.get("factor_family") or "其他上下文条件"
            families[str(family)].append(case)
        rows = []
        for family, cases in sorted(families.items(), key=lambda item: (-len(item[1]), item[0])):
            changes = list(dict.fromkeys(c.get("context_change_zh", "") for c in cases))
            change = "；".join(v for v in changes if v)
            rows.append([
                esc(family), str(len(cases)),
                esc(change) if change else "、".join(esc(c.get("name") or c["screen_id"]) for c in cases),
                "、".join(f'<a href="#case-{esc(c["screen_id"])}" data-case-link>{esc(c["screen_id"])}</a>' for c in cases),
            ])
        return table(["上下文类别", "轨迹数", "改变的条件", "对应案例"], rows)

    def outcome_table(self) -> str:
        counts = Counter(c.get("outcome", "未分类") for c in self.cases)
        return table(["结果", "轨迹数"], [[esc(LABELS.get(k, k)), str(v)] for k, v in counts.items()]) + '<p class="muted">不可比或未解决中包含资格不满足的 S044。</p>'

    def o4(self) -> tuple[str, str]:
        o4 = self.data.get("observations", {}).get("O4", {})
        rows = o4.get("rows", [])
        if not rows:
            return '<p class="muted">历史条件的逐例核对仍在汇总。</p>', ""
        counts = Counter(row.get("grade", "") for row in rows)
        supplied = o4.get("counts")
        if supplied and any(int(supplied.get(k, 0)) != counts.get(k, 0) for k in O4_LABELS):
            raise ValueError("O4 counts disagree with the merged per-case rows")
        summary = "；".join(f'<strong>{counts.get(key, 0)} 例</strong>{label}' for key, label in O4_LABELS.items()) + "。"
        detail_rows = []
        for row in rows:
            steps = row.get("steps", [])
            steps_text = "、".join(map(str, steps)) if isinstance(steps, list) else text_value(steps)
            detail_rows.append([
                esc(row["screen_id"]), esc(O4_LABELS.get(row.get("grade"), row.get("grade", ""))),
                esc(row.get("evidence_zh", "")), esc(steps_text), esc(row.get("oracle_zh", "")),
            ])
        details = f'<details id="o4-details"><summary>展开 {len(rows)} 例历史条件与断言证据</summary>' + table(["案例", "历史证据等级", "执行过什么", "轨迹步骤", "当时的断言"], detail_rows) + "</details>"
        return f"<p>{summary}</p>", details

    def all_cases(self) -> str:
        options = sorted({"不满足行为失败资格" if c.get("step1_qualified") is False else LABELS.get(c.get("outcome"), c.get("outcome", "未分类")) for c in self.cases})
        rows = []
        for case in self.cases:
            sid = case["screen_id"]
            outcome = LABELS.get(case.get("outcome"), case.get("outcome", "未分类"))
            if case.get("step1_qualified") is False:
                outcome = "不满足行为失败资格"
            reason = case.get("reason_zh", "")
            name = case.get("name") or case.get("task") or case.get("trial")
            search = " ".join(str(v or "") for v in [sid, name, case.get("trial"), outcome, reason])
            unit = case.get("unit_kind", "")
            metadata = [f'测试单位：{esc(UNIT_LABELS.get(unit, unit))}'] if unit else []
            if case.get("known_case"):
                metadata.append("标记：既有案例")
            if case.get("factor_count") is not None:
                metadata.append(f'语义条件数：{esc(case["factor_count"])}')
            if case.get("matrix_summary"):
                matrix = case["matrix_summary"]
                metadata.append("实验结果：" + (self.link(matrix, "重复实验记录") if isinstance(matrix, str) and matrix.endswith(".json") else esc(text_value(matrix))))
            explanation = esc(reason)
            if metadata:
                explanation += '<details class="case-note"><summary>实验范围</summary>' + "<br>".join(metadata) + "</details>"
            explanation += self.evidence(sid)
            rows.append(f'<tr id="case-{esc(sid)}" data-search="{esc(search.lower())}" data-outcome="{esc(outcome)}"><td>{esc(sid)}</td><td>{esc(name)}<small>{esc(case.get("trial", ""))}</small></td><td>{esc(outcome)}</td><td>{explanation}</td></tr>')
        return (
            f'<details id="all-cases"><summary>展开全部 {len(self.cases)} 条轨迹的结果</summary>'
            '<div class="filters"><label>搜索案例 <input id="case-search" type="search" placeholder="编号、任务或判定原因"></label>'
            '<label>结果 <select id="case-outcome"><option value="">全部</option>'
            + "".join(f'<option>{esc(o)}</option>' for o in options)
            + '</select></label><span id="case-visible" aria-live="polite"></span></div>'
            '<div class="table-wrap"><table class="case-table"><thead><tr><th>编号</th><th>任务 / 轨迹</th><th>结果</th><th>解释与证据</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table></div></details>"
        )

    def scope_details(self) -> str:
        special = [
            ("S074", "既有案例", "主结果包含这 1 条既有案例，保留 known 标记。"),
            ("S063", "隐式断言", "原验证以不抛出异常为成功条件，属于 smoke 单位。"),
            ("S062", "独立原片段", "原 172 行脚本中的独立 24 行片段，保留该片段的显式断言。"),
        ]
        rows = [[esc(sid), esc(kind), esc(note) + self.evidence(sid)] for sid, kind, note in special if sid in self.by_id]
        exploratory = self.data.get("exploratory", [])
        extra = ""
        if exploratory:
            extra_rows = []
            for case in exploratory:
                sid = case.get("screen_id", "S003")
                reason = case.get("reason_zh") or case.get("description_zh") or case.get("explanation_zh") or ""
                if sid == "S003" and not reason:
                    reason = "首个 HTTP 操作的原前缀在真实 bootstrap 路由上下文中得到 P 失败、R 通过；完整原 named test 的末尾断言在 R 上失败，因此此局部单位单列探索性结果。"
                matrix = case.get("matrix_summary", "")
                matrix_link = self.link(matrix, "重复实验记录") if isinstance(matrix, str) and matrix.endswith(".json") else esc(text_value(matrix))
                extra_rows.append([esc(sid), esc(reason), matrix_link + self.evidence(sid)])
            extra = "<h3>探索性与补充结果</h3>" + table(["案例", "解释", "实验与证据"], extra_rows)
        return '<details><summary>展开测试单位与探索性结果</summary>' + table(["案例", "单位标记", "说明"], rows) + extra + "</details>"

    def render(self) -> str:
        source = self.data.get("source", {})
        n = source.get("trials", len(self.cases))
        tasks = source.get("tasks", len({c.get("task") for c in self.cases}))
        qualified = source.get("qualified", sum(c.get("step1_qualified") is True for c in self.cases))
        success_n = len(self.success)
        success_tasks = len({c.get("task") for c in self.success})
        single = sum(c.get("outcome") == "Single-factor Context Repair" for c in self.success)
        multi = sum(c.get("outcome") == "Multi-factor Context Repair" for c in self.success)
        o4_summary, o4_details = self.o4()
        completed = self.data.get("status") in {"complete", "completed", "final", "finalized"}
        title = self.data.get("title") or "已确认组合缺口的上下文修复 · Pilot 1"
        cards = "".join(f'<div class="stat"><b>{value}</b><span>{label}</span></div>' for value, label in [(n, "已筛查轨迹"), (qualified, "具备行为失败资格"), (success_n, "上下文修复轨迹"), (success_tasks, "修复涉及的独立任务")])
        s059 = table(["测试上下文", "关键观测", "交付实现 P", "参考实现 R"], [
            ["原上下文 c₀", "durable 序号：P = 11，R = 10；next seq 均为 11", badge("PASS"), badge("PASS")],
            ["补充 NoSync 序号历史", "历史推进至原等待阈值 100000 附近；原断言保持不变", badge("FAIL"), badge("PASS")],
        ])
        s085 = table(["上下文", "历史记录 2 的耗时", "历史记录 3 的耗时", "交付实现 P", "参考实现 R"], [
            ["原上下文", "300", "200", badge("PASS"), badge("PASS")],
            ["仅 F1", "100", "200", badge("PASS"), badge("PASS")],
            ["仅 F2", "300", "100", badge("PASS"), badge("PASS")],
            ["F1 + F2", "100", "100", badge("FAIL"), badge("PASS")],
        ])
        review_links = " · ".join(self.link(str(p), Path(str(p)).name) for p in self.data.get("review_artifacts", []))
        return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title><style>{CSS}</style></head><body><main>
<header><p class="eyebrow">PILOT 1 · 组合缺口与上下文修复</p><h1>{esc(title)}</h1>
<p class="subtitle">开始：2026-10-25 · {'完成' if completed else '汇总'}：2026-10-26</p></header>
<div class="stats">{cards}</div>
<div id="main-findings">
<p class="lead">在此前确认存在组合缺口的 {n} 条轨迹中，{success_n} 条在保留原目标操作、输入和断言后，仅改变上下文便暴露了交付实现的缺陷，涉及 {success_tasks} 个独立任务。其中 {single} 条为单因素修复，{multi} 条为多因素修复。</p>
<section id="o1"><h2><span>O1</span> 原测试能否仅靠上下文修复？</h2>
<p>可以。这里的“修复”指增强原测试的检错能力：原测试在交付实现 P 和参考实现 R 上都通过；转移相关上下文后，同一测试在 P 上失败，在 R 上仍通过。每个结果重复两次。它说明原来的测试操作与断言可以保留，缺少的条件位于测试周边。</p>
<p>本轮覆盖 {tasks} 个任务的全部 {n} 条入选轨迹，逐例重新核对原测试的成功执行、实际验证失败和任务要求，最终 {qualified} 条满足行为失败资格。S044 的验证器只发生编译失败，未进入这一集合。其余轨迹的具体障碍分别落在断言、目标输入或测试可比性上，见逐例结果。</p>
<p>例如，S025 原测试已同时包含带前导零与不带前导零的文件名，却期待了错误顺序；S029 已建立同名、不同路径的两个 cookie，却把只保留其中一个当作正确结果。这两例需要修正原判据。可见，即使条件已经组合，观察或断言仍可能阻止测试检错。</p>
<h3>S059：已有局部差异，被等待阈值掩盖</h3>
<p>S059 是本轮严格行为掩盖定义的直接证据。原上下文中，两实现的 durable 序号已经不同，但原等待检查仍都通过。补入 NoSync 写入历史，使序号接近原阈值后，这个相同检查才区分出 P 与 R。</p>
{s059}
<p>这里可同时看到“行为已经不同”和“测试仍然通过”。上下文改变了已有差异进入原断言判定范围的方式。{success_n} 个上下文修复案例中，这 1 例进一步提供了原上下文中行为已分化的直接观测。</p>
{self.evidence('S059')}
</section>
<section id="o2"><h2><span>O2</span> 需要改变多少个条件？</h2>
<p>成功修复中，{single} 条只需一个语义条件，{multi} 条通过两个条件共同改变而成功。条件数按状态或配置的含义计算：一次状态完成可能需要几步准备，两条独立历史记录也可能只各改一个数值。</p>
<h3>S085：两条历史记录共同决定是否暴露缺陷</h3>
<p>原测试操作、阈值 150、4 个 JS 测试文件和全部断言均保持原样。唯一变化发生在外部历史缓存：F1 将第 2 条记录的耗时从 300 改为 100，F2 将第 3 条从 200 改为 100。单独应用任何一项时，P 与 R 都通过；同时应用两项时，只有 P 失败。</p>
{s085}
<p>消融检验了原条件、两个单项以及联合条件。在这两条已测试记录构成的范围内，两项变化对该修复共同必要。这解释了为什么只试单因素会漏掉这个候选，也给出了多因素修复所需的直接对照。</p>
<p>S045 则呈现另一种结果：将等待设为 0、将最大并发数设为 1，以及同时改变二者，都能得到 P 失败、R 通过。既然单项已有效，最终采用串行配置作为主修复，计为一个因素。</p>
{self.evidence('S085')}{self.evidence('S045')}
</section>
<section id="o3"><h2><span>O3</span> 哪些上下文条件有效？</h2>
<p>有效变化包括测试执行前或过程中形成的状态、操作依赖的配置，以及外部历史记录。下表按最终修复归类，同一任务的不同轨迹分别计数。</p>
{self.family_table()}
<p>共同点是：目标测试所做的事没有改变，但它面对的系统状态或执行条件发生了变化。对上下文进行组合时，需要考察整组变化及其子集；S085 的历史记录组合与 S045 的两个独立有效条件，体现了两种不同关系。</p>
</section>
<section id="o4"><h2><span>O4</span> 有效条件在历史轨迹中出现过吗？</h2>
{o4_summary}
<p>这里按语义条件核对：“相同条件”表示历史中实际执行过同一种状态或关系，参数与目标数据可以不同；“相关组成条件”表示组成状态或相近调用已经出现。S085 的历史步骤 95 已执行慢文件数少于分片数的关系，因此属于前者；本次修复则通过改写两条缓存记录重建这一关系。Kea 的两条轨迹只分别执行过 disabled 与 enabled 条件，因此属于后者。</p>
<p>历史出现过某个条件，还需继续看它当时配合了什么操作和断言。S045 在步骤 118 已用最大并发数 1 执行 abatch，并在正确的 len(calls) == 2 检查上失败；步骤 119 继续在相同并发条件下运行多个调用路径，却只打印重复调用结果 [1, 1, 2]，未保留计数断言，随后给出 ALL OK。这段历史同时留下了有效条件、失败证据和后续验证弱化的过程。</p>
<p>S063 的步骤 210 则在容量 10、ID 11 的情形下把 ValueError 当作正确结果。它证明相关条件曾经执行，但当时的判据不能直接作为正确测试复用。两例都说明，历史证据的价值在于追回“条件—操作—输出—断言”之间的关系，而不只是检索一个参数或一句成功提示。</p>
<p>这些观察支持从轨迹中恢复候选条件，再回到原测试验证其作用。已有条件未进入最终测试、进入了不同调用路径，或搭配了错误及缺失的断言，都会留下可补足的检错空间。</p>
{o4_details}
</section></div>
<section class="appendix"><h2>逐例结果与证据</h2>
<details><summary>展开结果分类计数</summary>{self.outcome_table()}</details>
{self.scope_details()}
{self.all_cases()}
<details><summary>展开汇总数据与复核材料</summary><div class="links">{self.link(str(self.run / 'report_data.json'), '本轮汇总数据')}{(' · ' + review_links) if review_links else ''}</div></details>
</section><footer>2026-10-25 启动 · 2026-10-26 {'完成汇总' if completed else '汇总中'} · {esc(self.run.name)}</footer>
</main><script>{JS}</script></body></html>'''


CSS = '''
:root{--ink:#18252e;--muted:#586975;--line:#dbe3e8;--blue:#225b7d;--paper:#fff;--wash:#f4f7f9}
*{box-sizing:border-box}body{margin:0;background:#edf2f5;color:var(--ink);font-family:system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;line-height:1.85;font-size:16px}
main{max-width:1100px;margin:32px auto;padding:48px 58px;background:var(--paper);border:1px solid var(--line);border-radius:12px}h1{font-size:31px;line-height:1.4;margin:8px 0 12px;letter-spacing:.01em}.eyebrow{font-size:12px;color:var(--blue);letter-spacing:.13em;font-weight:700;margin:0}.subtitle,small,.muted{color:var(--muted)}.subtitle{font-size:14px;margin:0}p{margin:16px 0}.lead{font-size:18px;line-height:1.9;margin:28px 0 32px}h2{font-size:23px;margin:34px 0 16px;line-height:1.5}h2>span{display:inline-block;font-size:14px;font-weight:700;color:var(--blue);margin-right:12px;vertical-align:3px}h3{font-size:18px;margin:24px 0 10px}section{scroll-margin-top:20px}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:30px 0}.stat{background:var(--wash);padding:16px 14px;border-radius:8px}.stat b{display:block;font-size:31px;line-height:1.3;font-variant-numeric:tabular-nums;color:var(--blue)}.stat span{display:block;margin-top:5px;font-size:13px;color:var(--muted)}a{color:var(--blue);text-underline-offset:3px}a:hover{color:#133b57}.table-wrap{overflow-x:auto;margin:16px 0}table{border-collapse:collapse;width:100%;font-size:14px;line-height:1.7}th{text-align:left;background:var(--wash);font-weight:650}th,td{padding:12px 13px;border-bottom:1px solid var(--line);vertical-align:top}th:first-child,td:first-child{padding-left:12px}.result{font-weight:650;white-space:nowrap;font-size:13px}.pass{color:#236147}.fail{color:#9e3c36}details{margin:14px 0;border:1px solid var(--line);border-radius:7px;padding:10px 14px}summary{cursor:pointer;color:var(--blue);font-size:14px;font-weight:550}details[open]>summary{margin-bottom:12px}.evidence,.case-note{border:0;border-radius:0;background:transparent;padding:0;margin:8px 0}.evidence summary,.case-note summary{font-size:12px;font-weight:400}.links{font-size:13px;overflow-wrap:anywhere}.appendix{border-top:1px solid var(--line);margin-top:34px;padding-top:8px}.case-table{font-size:13px;min-width:780px}.case-table th:nth-child(1){width:6%}.case-table th:nth-child(2){width:26%}.case-table th:nth-child(3){width:17%}.case-table td{overflow-wrap:anywhere}.case-table small{display:block;font-size:11px;margin-top:5px}.filters{display:flex;gap:16px;align-items:end;flex-wrap:wrap;margin:16px 0;font-size:13px}.filters label{display:flex;flex-direction:column;gap:4px}input,select{font:inherit;padding:7px 9px;border:1px solid #b5c6d0;border-radius:5px;background:#fff;color:var(--ink)}input{min-width:260px}#case-visible{color:var(--muted);padding:7px 0}tr[hidden]{display:none}tr:target{background:#fff6d9}footer{font-size:11px;color:var(--muted);border-top:1px solid var(--line);margin-top:30px;padding-top:18px;overflow-wrap:anywhere}
#main-findings table{min-width:620px}#main-findings th{white-space:nowrap}#o4-details table{min-width:900px}
@media(max-width:760px){main{margin:0;padding:28px 20px;border:0;border-radius:0}h1{font-size:25px}h2{font-size:20px}.stats{grid-template-columns:repeat(2,1fr);gap:9px}.lead{font-size:17px}th,td{padding:9px}body{font-size:15px}}
@media print{body{background:white}main{max-width:none;margin:0;border:0;padding:0}.filters,footer{display:none}details:not([open]){display:none}.stats,table{break-inside:avoid}h2,h3{break-after:avoid}a{color:inherit}table{font-size:11px}body{font-size:12px}}
'''

JS = '''
const search=document.getElementById('case-search'), choice=document.getElementById('case-outcome');
const rows=[...document.querySelectorAll('.case-table tbody tr')];
function filterCases(){const query=search.value.trim().toLowerCase();let count=0;for(const row of rows){row.hidden=!(row.dataset.search.includes(query)&&(!choice.value||row.dataset.outcome===choice.value));if(!row.hidden)count++;}document.getElementById('case-visible').textContent=`显示 ${count} / ${rows.length} 条`;}
search.addEventListener('input',filterCases);choice.addEventListener('change',filterCases);filterCases();
function revealCase(){if(location.hash.startsWith('#case-')){document.getElementById('all-cases').open=true;search.value='';choice.value='';filterCases();requestAnimationFrame(()=>document.getElementById(location.hash.slice(1))?.scrollIntoView({block:'center'}));}}
window.addEventListener('hashchange',revealCase);revealCase();
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    run = args.run.resolve()
    data_path = (args.data or run / "report_data.json").resolve()
    output = (args.output or run / "report.html").resolve()
    if not data_path.is_file():
        parser.error(f"Merged report data is not available: {data_path}")
    data = json.loads(data_path.read_text())
    cases = data.get("cases", [])
    if len({case["screen_id"] for case in cases}) != len(cases):
        raise ValueError("Duplicate screen_id in report_data.json")
    expected = data.get("source", {}).get("trials")
    if expected is not None and len(cases) != expected:
        raise ValueError(f"Expected {expected} cases, received {len(cases)}")
    report = Report(data, run, output).render()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report)
    print(f"Rendered {len(cases)} cases: {output}")


if __name__ == "__main__":
    main()
