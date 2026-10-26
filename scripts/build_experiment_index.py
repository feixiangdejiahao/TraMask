"""Build local reading indexes without moving, rewriting, or executing experiment data."""
import argparse
from collections import Counter
import csv
import hashlib
import html
import io
import json
import os
from pathlib import Path
import re
from result_paths import canonical_path, relative_path
from build_report_readers import build as build_readers, reading_path
from build_docs_index import build as build_docs

ROOT = Path(__file__).resolve().parents[1]
KINDS = {
    "pilot": "主要 pilot",
    "stopped": "已停止的技术尝试",
    "preparation": "输入准备",
    "implementation_check": "实现与接口检查",
    "historical": "历史结果或支撑材料",
}
TASK_FIELDS = [
    "pilot_id", "namespace", "case_id", "trial", "task", "language", "reader",
    "case_list", "summary", "review", "supplement_review", "artifacts",
    "source", "repository", "issue", "trajectory", "candidate_patch",
]


def read(path):
    return json.loads(canonical_path(path).read_text())


def dump(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def digest(path):
    return hashlib.sha256(canonical_path(path).read_bytes()).hexdigest()


def local(path):
    """Translate archived addresses without rewriting the source evidence."""
    p = canonical_path(path)
    relative = p.relative_to(ROOT).as_posix()
    if not p.exists():
        raise ValueError(f"材料不存在：{relative}")
    return relative


def link(label, path, parent):
    return f"[{label}]({os.path.relpath(reading_path(path), ROOT / parent)})"


def tsv(rows, fields):
    output = io.StringIO()
    writer = csv.DictWriter(output, fields, delimiter="\t", lineterminator="\n",
                            extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def active_files(pilot):
    files = dict(pilot["files"])
    if pilot.get("active_evaluation"):
        active = local(pilot["active_evaluation"])
        files["active_evaluation.json"] = active
        data = read(active)
        for key, name in [
            ("summary", "current_summary.json"), ("review", "review.json"),
            ("reference", "reference_targets.json"), ("labels", "reference_targets.json"),
        ]:
            item = data.get(key)
            if item is None:
                continue
            path = item["path"] if isinstance(item, dict) else item
            # Receipt paths are repository-relative. Newer plain-string pointers
            # can be relative to the original run, not to this reading directory.
            if not Path(path).is_absolute() and Path(path).parts[0] not in (
                "experiments", "results", "research", "docs", "data"
            ):
                path = str(Path(pilot["root"]) / path)
            path = local(path)
            if isinstance(item, dict) and item.get("sha256") != digest(path):
                raise ValueError(f"当前评价凭据与文件不一致：{path}")
            files[name] = path
    files["case_list.json"] = pilot["case_list"]
    return {name: local(path) for name, path in files.items()}


def case_rows(pilot, files):
    cases = read(files["case_list.json"])
    if isinstance(cases, dict):
        cases = cases["cases"]
    if len(cases) != pilot["case_count"]:
        raise ValueError(f"{pilot['id']} 案例数与登记不一致")
    raw = ROOT / pilot["root"]
    rows = []
    for case in cases:
        cid = case.get("id", case.get("case"))
        if not cid:
            raise ValueError(f"{pilot['id']} 中有案例缺少 ID")
        locations = [
            raw / "cases" / cid, raw / "runs" / cid,
            raw / "inputs" / cid, raw / "inputs" / f"{cid}.json",
            raw / "observation_view" / "runs" / cid,
        ]
        if pilot["case_namespace"] == "early_development":
            locations += list(raw.glob(f"generation*/cases/{cid}"))
            locations += list(raw.glob(f"extraction*/{cid}"))
        row = {
            "pilot_id": pilot["id"], "namespace": pilot["case_namespace"],
            "case_id": cid, "trial": case.get("trial", ""),
            "task": case.get("task", ""), "language": case.get("language", ""),
            "reader": f"experiments/pilots/{pilot['id']}/README.md",
            "case_list": files["case_list.json"],
            "summary": files["current_summary.json"],
            "review": files.get("review.json", ""),
            "supplement_review": files.get("supplement_review.json", ""),
            "artifacts": ";".join(sorted({
                p.relative_to(ROOT).as_posix() for p in locations if p.exists()
            })),
        }
        for field in ("source", "repository", "issue", "trajectory", "candidate_patch"):
            value = case.get(field)
            if isinstance(value, dict):
                value = value.get("path")
            row[field] = local(value) if value else ""
        rows.append(row)
    return rows


def inventory(catalog, pilots):
    discovered = {}
    layout = read("experiments/directory_layout.json")
    candidates = []
    for topic in layout["topics"]:
        base = ROOT / "results" / topic["name"]
        if base.is_dir():
            candidates += [(p, topic["name"]) for p in sorted(base.iterdir())
                           if p.name not in ("README.md", "NAMING.md")]
    for group in sorted((ROOT / "experiments").iterdir()):
        base = group / "results"
        if base.is_dir():
            candidates += [(p, group.name) for p in sorted(base.iterdir())
                           if p.name != "README.md"]
    primary = {str((ROOT / p["root"]).resolve()): p for p in pilots}
    for p, group in candidates:
        real, relative = str(p.resolve()), local(p)
        if real in discovered:
            discovered[real]["aliases"].append(relative)
            continue
        kind, status_source = "historical", ""
        if real in primary:
            kind = "pilot"
        elif (p / "stopped.json").is_file():
            kind, status_source = "stopped", str(p / "stopped.json")
        elif (p / "preflight_closeout.json").is_file():
            kind, status_source = "stopped", str(p / "preflight_closeout.json")
        elif "preparation" in p.name:
            kind = "preparation"
        elif any(word in p.name for word in ("implementation", "verification", "preflight", "smoke_check")):
            kind = "implementation_check"
        pilot = primary.get(real, {})
        discovered[real] = {
            "group": pilot.get("group", group), "kind": kind,
            "name": p.name, "path": relative, "aliases": [],
            "pilot_id": pilot.get("id", ""), "title": pilot.get("title", p.name),
            "reader": f"experiments/pilots/{pilot['id']}/README.md" if pilot else "",
            "status_source": local(status_source) if status_source else "",
            "summary": pilot.get("resolved_files", {}).get("current_summary.json", ""),
            "report": pilot.get("report", ""),
        }
    return sorted(discovered.values(), key=lambda row: (row["group"], row["path"]))


def render_pilot(pilot, files, rows):
    folder = f"experiments/pilots/{pilot['id']}"
    text = [
        f"# {pilot['title']}", "",
        f"统一名称：`{pilot['id']}`。本目录只提供读取入口。原始数据位于 "
        f"{link(pilot['root'], pilot['root'], folder)}。", "",
        pilot["settings"], "", pilot["scope"], "",
        "## 读取顺序", "",
        f"1. {link('实验报告', pilot['report'], folder)}：先了解设置和评价范围。",
        "2. [current_summary.json](current_summary.json)：读取当前统计。",
        "3. [protocol.json](protocol.json)：核对设置、预算和输入边界。",
        "4. [tasks.tsv](tasks.tsv)：按任务查找输入、输出和评价。",
        "5. [artifacts/](artifacts/)：查看完整原始目录。", "",
        "## 文件对应关系", "",
        "| 本目录名称 | 原始文件 |", "|---|---|",
    ]
    text += [f"| `{name}` | {link(source, source, folder)} |" for name, source in files.items()]
    text += ["", "`manifest.json` 记录本入口的路径映射和所引用文件的 SHA-256。"
             "这些校验值只核对材料版本，不证明实验结论。", "", "## 相关材料", ""]
    text += [f"- {link(item['label'], item['path'], folder)}" for item in pilot["related"]]
    text += ["", "## 阅读时区分", ""]
    text += [f"- {note}" for note in pilot["notes"]]
    text += ["- 这些 pilot 没有测量修复后的 resolution rate。",
             "- 静态语义判断与动态差分执行按原始记录分别读取。", "",
             f"任务命名空间：`{pilot['case_namespace']}`。本索引包含 {len(rows)} 个案例。"
             "不同命名空间中的短 ID 不应直接合并。", ""]
    return "\n".join(text)


def render_pilot_list(pilots, studies):
    parent = "experiments/pilots"
    text = ["# Pilot 实验读取入口", "",
            "按轮次读取设置、当前评价和原始输出。此表不重新计算或合并成功率。"
            "按任务查询见 [tasks.tsv](tasks.tsv)。", "",
            "| 统一目录名 | 实验 | 案例数 |", "|---|---|---|"]
    for p in pilots:
        reader = f"experiments/pilots/{p['id']}/README.md"
        text.append(f"| {link(p['id'], reader, parent)} | {p['title']} | {p['case_count']} |")
    text += ["", "## 观察研究与统计修订", "",
             "这些材料帮助解释 pilot，不是新的算法效果实验。", ""]
    for study in studies:
        text.append(f"- {link(study['title'], study['report'], parent)}：{study['note']} "
                    f"{link('数据', study['summary'], parent)}。")
    text += ["", "## 当前评价的选择", "",
             "30 项 v1/v2/v3 实验从各自的 `active_evaluation.json` 读取当前口径。"
             "旧结果继续保留。v3 的原预算统计与追加判断统计分开。", "",
             "12 项实验的入口使用 `combined_summary.json`，包含四个主设置及第五个补充设置。"
             "两份逐项审阅分别保留。", "",
             "早期 P/N 案例与后期 T01–T30 使用不同命名空间。"
             "任务数量、目标数量、输出数量和命名测试数量也使用不同分母。", "",
             "正式运行中出现的格式失败和未定结果仍属于该轮的原始记录。"
             "总目录只把有停止记录的尝试标为停用，不能据此删除不利结果。", "",
             "完整目录见 " + link("实验总览", "experiments/README.md", parent) + "。", ""]
    return "\n".join(text)


def render_inventory(rows, groups):
    lines = ["# 全部结果目录", "",
             "每行对应一个真实文件或目录。`aliases` 指向同一位置，不能重复计为实验。"
             "历史材料不自动获得“正式完成”状态。", "",
             "机器可读版本：[runs.json](runs.json) · [runs.tsv](runs.tsv)。"
             "主要 pilot 见 [pilots/README.md](pilots/README.md)。", ""]
    for group, title in groups.items():
        selected = [row for row in rows if row["group"] == group]
        if not selected:
            continue
        lines += [f"## {title}", "", "| 类型 | 原始目录或文件 | 读取入口 / 状态依据 |",
                  "|---|---|---|"]
        for row in selected:
            destination = row["reader"] or row["status_source"]
            extra = link("打开", destination, "experiments") if destination else "保留历史状态"
            lines.append(f"| {KINDS[row['kind']]} | "
                         f"{link(row['path'], row['path'], 'experiments')} | {extra} |")
        lines.append("")
    return "\n".join(lines)


def render_group(group, title, pilots, rows, studies=()):
    parent = f"experiments/{group}"
    lines = [f"# {title}", "",
             link("返回实验总览", "experiments/README.md", parent) + " · "
             + link("全部结果目录", "experiments/INVENTORY.md", parent), ""]
    selected = [p for p in pilots if p["group"] == group]
    if selected:
        lines += ["## 主要 pilot", ""]
        for p in selected:
            reader = f"experiments/pilots/{p['id']}/README.md"
            lines.append(f"- {link(p['title'], reader, parent)}：`{p['id']}`。")
        lines.append("")
    for name, label in [("results", "本主题的结果入口"), ("research", "方案与研究记录")]:
        if (ROOT / parent / name).is_dir():
            lines.append(f"- [{label}]({name}/)")
    for study in studies:
        if study.get("group") == group:
            lines.append(f"- {link(study['title'], study['report'], parent)}：{study['note']} "
                         f"{link('当前数据', study['summary'], parent)}。")
    others = [r for r in rows if r["group"] == group and r["kind"] != "pilot"]
    if others:
        lines += ["", "## 其他结果与材料", "",
                  "| 类型 | 位置 |", "|---|---|"]
        for row in others:
            lines.append(f"| {KINDS[row['kind']]} | {link(row['name'], row['path'], parent)} |")
    lines += ["", "本主题与 results/ 中的同名主题对应。旧路径见 results/path_map.json。"
              "各轮结果按自己的协议和评价版本读取。"
              "历史支撑材料、准备运行和实现检查不自动计入主要 pilot 的效果。", ""]
    return "\n".join(lines)


def render_html(catalog, pilots, rows):
    sections, entries = [], []
    for p in pilots:
        entries.append(
            f'<tr><td>{html.escape(p["id"])}</td><td>'
            f'<a href="pilots/{p["id"]}/README.md">{html.escape(p["title"])}</a><br>'
            f'{html.escape(p["settings"])}<br>'
            f'<a href="../{p["resolved_files"]["current_summary.json"]}">当前统计</a> · '
            f'<a href="../{reading_path(p["report"]).relative_to(ROOT)}">报告</a></td></tr>'
        )
    sections.append("<details open><summary>主要 pilot</summary><table><tbody>"
                    + "".join(entries) + "</tbody></table></details>")
    support = [r for r in rows if r["kind"] in ("stopped", "preparation", "implementation_check")]
    sections.append("<details><summary>技术尝试、准备与实现检查</summary><table><tbody>" + "".join(
        f'<tr><td>{KINDS[r["kind"]]}</td><td><a href="../{r["path"]}">'
        f'{html.escape(r["path"])}</a></td></tr>' for r in support
    ) + "</tbody></table></details>")
    counts = Counter(row["group"] for row in catalog["entries"])
    for group, title in catalog["groups"].items():
        entries = []
        for entry in catalog["entries"]:
            if entry["group"] != group:
                continue
            current = reading_path(local(entry["old"])).relative_to(ROOT).as_posix()
            old = html.escape(current, quote=True)
            entries.append(
                f'<tr><td><a href="../{old}">{html.escape(Path(current).name)}</a>'
                f'<br><small>{html.escape(current)}</small></td><td>{entry["files"]:,}</td></tr>'
            )
        sections.append(
            f'<details><summary>早期归档：{html.escape(title)} ({counts[group]})</summary>'
            f'<table><tbody>{"".join(entries)}</tbody></table></details>'
        )
    return """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>实验结果索引</title><style>
body{font:16px/1.65 system-ui,sans-serif;max-width:1150px;margin:40px auto;padding:0 22px;color:#243047;background:#fafbfc}
a{color:#125fb5}input{font:inherit;box-sizing:border-box;width:100%;padding:12px;margin:18px 0}
details{background:white;border:1px solid #dce2ea;border-radius:8px;padding:14px 18px;margin:14px 0}
summary{cursor:pointer;font-weight:650}small{color:#65758a;overflow-wrap:anywhere}
table{border-collapse:collapse;width:100%;margin-top:12px}td{border-bottom:1px solid #e9edf2;padding:9px;vertical-align:top}
tr[hidden],details[hidden]{display:none}</style></head><body><h1>实验结果索引</h1>
<p>先查主要 pilot 的设置和当前统计，再读取原始输出。数据按主题统一存放于 results/。
正式结果、停止的技术尝试和实现检查分别列出。目录整理不重新判定成绩。</p>
<p><a href="README.md">读取说明与命名规则</a> · <a href="INVENTORY.md">全部结果</a> ·
<a href="pilots/tasks.tsv">跨轮任务索引</a> · <a href="runs.json">机器可读目录</a> ·
<a href="../docs/README.md">全部报告</a></p>
<label for="filter">按日期、实验名称或原目录名查找</label>
<input id="filter" type="search" placeholder="例如：20261016、pilot30、trajectory">
""" + "\n".join(sections) + """
<script>
document.querySelector('#filter').addEventListener('input', event => {
  const term = event.target.value.trim().toLowerCase();
  document.querySelectorAll('details').forEach(section => {
    let visible = 0;
    section.querySelectorAll('tbody tr').forEach(row => {
      row.hidden = !(row.textContent + ' ' + Array.from(row.querySelectorAll('a'))
        .map(a => a.getAttribute('href')).join(' ')).toLowerCase().includes(term);
      if (!row.hidden) visible += 1;
    });
    section.hidden = visible === 0;
    if (term) section.open = true;
  });
});
</script></body></html>
"""


def build(check=False):
    reports = build_readers(check=check)
    documents = build_docs(check=check)
    config = read("experiments/pilot_catalog.json")
    catalog = read("experiments/legacy_catalog_20261007.json")
    layout = read("experiments/directory_layout.json")
    groups = {t["name"]: t["title"] for t in layout["topics"]}
    topic_map = {t["old"]: t["name"] for t in layout["topics"]}
    groups["unclassified"] = "尚未分类的结果"
    texts, links, task_index, pilots, seen = {}, {}, [], [], set()
    for record in config["pilots"]:
        pilot, pid = dict(record), record["id"]
        pilot["root"] = local(pilot["root"])
        pilot["group"] = topic_map.get(pilot["group"], pilot["group"])
        if not re.fullmatch(r"\d{8}_[a-z0-9_]+_n\d{2,}_r\d{2,}", pid) or pid in seen:
            raise ValueError(f"统一名称重复或格式不符：{pid}")
        seen.add(pid)
        local(pilot["root"])
        local(pilot["report"])
        for item in pilot["related"]:
            local(item["path"])
        files = active_files(pilot)
        pilot["resolved_files"] = files
        rows = case_rows(pilot, files)
        folder = f"experiments/pilots/{pid}"
        links[f"{folder}/artifacts"] = pilot["root"]
        links.update({f"{folder}/{name}": path for name, path in files.items()})
        texts[f"{folder}/README.md"] = render_pilot(pilot, files, rows)
        texts[f"{folder}/tasks.tsv"] = tsv(rows, TASK_FIELDS)
        texts[f"{folder}/manifest.json"] = dump({
            **pilot,
            "file_receipts": {name: {"path": path, "sha256": digest(path)}
                              for name, path in files.items()},
            "resolution_rate_measured": False,
            "generated_by": "scripts/build_experiment_index.py",
        })
        task_index += rows
        pilots.append(pilot)
    for study in config["studies"]:
        for field in ("root", "report", "summary"):
            local(study[field])
    rows = inventory(catalog, pilots)
    for row in rows:
        groups.setdefault(row["group"], row["group"])
    for group, title in groups.items():
        if (ROOT / "experiments" / group).is_dir():
            texts[f"experiments/{group}/README.md"] = render_group(group, title, pilots, rows, config["studies"])
        if (ROOT / "results" / group).is_dir():
            parent = f"results/{group}"
            matching = [r for r in rows if r["group"] == group]
            lines = [f"# {title}：实验结果", "",
                     link("实验设置与分析", f"experiments/{group}/README.md", parent)
                     + " · " + link("命名规范", "experiments/NAMING.md", parent), "",
                     "| 类型 | 运行目录或文件 |", "|---|---|"]
            lines += [f"| {KINDS[r['kind']]} | {link(r['name'], r['path'], parent)} |"
                      for r in matching]
            texts[f"{parent}/README.md"] = "\n".join(lines) + "\n"
    texts["experiments/pilots/README.md"] = render_pilot_list(pilots, config["studies"])
    texts["experiments/pilots/tasks.tsv"] = tsv(task_index, TASK_FIELDS)
    texts["experiments/INVENTORY.md"] = render_inventory(rows, groups)
    texts["experiments/runs.json"] = dump({
        "schema_version": 1,
        "scope": "Result roots under results/<topic>/; experiments/<topic>/results mirrors the same data.",
        "groups": groups, "kinds": KINDS, "entries": rows, "studies": config["studies"],
    })
    texts["experiments/runs.tsv"] = tsv(
        [{**r, "aliases": ";".join(r["aliases"])} for r in rows],
        ["group", "kind", "pilot_id", "title", "path", "aliases", "reader",
         "status_source", "summary", "report"],
    )
    texts["experiments/index.html"] = render_html(catalog, pilots, rows)
    # Refuse collisions before writing any output.
    for name in links:
        p = ROOT / name
        if p.exists() and not p.is_symlink():
            raise ValueError(f"拒绝覆盖真实文件：{name}")
    for name in texts:
        if (ROOT / name).is_symlink():
            raise ValueError(f"拒绝通过链接写入文件：{name}")
    stale = []
    for name, target in links.items():
        destination = ROOT / name
        expected = os.path.relpath(ROOT / target, destination.parent)
        if destination.is_symlink() and os.readlink(destination) == expected:
            continue
        if check:
            stale.append(name)
        else:
            if destination.is_symlink():
                destination.unlink()
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.symlink_to(expected)
    for name, text in texts.items():
        path = ROOT / name
        if path.exists() and path.read_text() == text:
            continue
        if check:
            stale.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    if stale:
        raise ValueError(f"{len(stale)} 个索引文件缺失或过期；先运行构建命令。示例：{stale[:10]}")
    return {
        "status": "checked" if check else "built", "pilots": len(pilots),
        "task_rows": len(task_index), "unique_result_roots": len(rows),
        "result_kinds": dict(Counter(row["kind"] for row in rows)),
        "generated_text_files": len(texts), "reading_links": len(links),
        "report_readers": reports,
        "documents": documents,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check sources and index freshness without writing.")
    args = parser.parse_args()
    print(dump(build(check=args.check)), end="")
