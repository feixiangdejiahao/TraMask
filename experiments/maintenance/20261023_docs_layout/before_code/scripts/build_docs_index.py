"""Build document navigation from the named document catalog."""
import argparse
import csv
import io
import json
import os
from pathlib import Path

from build_report_readers import reading_path
from result_paths import ROOT


def link(label, target, parent):
    return f"[{label}]({os.path.relpath(reading_path(target), ROOT / parent)})"


def build(check=False):
    documents = json.loads((ROOT / "docs/catalog.json").read_text())["documents"]
    current = [r for r in documents if r["status"] == "current"]
    archived = [r for r in documents if r["status"] == "archive"]
    lines = ["# 研究文档", "",
             "先阅读下表中的当前入口。旧版评价、实现说明和前期汇报见 "
             "[归档目录](archive/README.md)。每个归档项都说明原因和后续阅读位置。", "",
             "本页链接使用已修复本地地址的阅读副本。原报告正文保持不变。"
             "211 个 trial 的双语报告及其阅读副本完全一致，可离线打开。", "",
             "[主要 pilot](../experiments/pilots/README.md) · "
             "[跨轮任务索引](../experiments/pilots/tasks.tsv) · "
             "[独立研究审查](../experiments/reports/research/independent_review_20261019/independent_report.html)", "",
             "## 当前阅读入口", "",
             "当前入口表示适合继续查阅。各报告仍采用自己的实验设置和判断规则。"
             "30 项 pilot 的目标修订与 211 个 trial 的新归因使用不同范围，不合并其分母。", "",
             "| 日期 | 文档 | 内容与范围 |", "|---|---|---|"]
    for row in current:
        lines.append(f"| {row['date']} | {link(row['title'], row['path'], 'docs')} | {row['reason']} |")
    lines += ["", "211 项报告的数据入口："
              "[evaluation 归因记录](../research/deepswe_counterfactual_review_20261021/README.md) · "
              "[双语展示](../research/deepswe_report_presentation_20261022/README.md) · "
              "[组合表与测试生成过程](../research/deepswe_gap_visuals_20261022/README.md)。", "",
              "## 文件命名", "",
              "文档使用 `YYYYMMDD_<主题>_<文档类型>[_vNN][_nNN].扩展名`。"
              "使用小写英文和下划线。例如 `20261009_behavioral_gap_detection_v03_n30.html`。"
              "主题用词与 experiments/、results/ 的主题含义一致。", "",
              "日期取报告或研究记录明确标注的日期，不取本次整理日期。"
              "v2 的 30 项报告使用完成日期 20261009；17 项进展报告使用证据截止日期 20261003；"
              "当前双语报告使用展示版本日期 20261022。", "",
              "`vNN` 表示文档所讨论的方法版本。`nNN` 表示报告明确涉及的案例数。"
              "T08 等单项修订可使用案例 ID。实验运行 ID 单独记录，不从文件名推定运行次数。", "",
              "`README.md`、`catalog.json`、`path_map.tsv` 和 `Makefile` 使用固定名称。"
              "[catalog.json](catalog.json)记录主题、原路径、日期、归档依据和关联 pilot。", "",
              "## 归档标准", "",
              "旧评价被新规则或复核替代、旧实现被后续版本修正、早期方法讨论已形成后续规格时，"
              "将对应报告移入 archive/。前期阶段性进展和汇报材料也放在这里。", "",
              "有独立设置或观察价值的 pilot 继续保留。文件较早或实验结果较差都不足以单独构成归档理由。"
              "归档报告及其原始实验数据继续可读。", "",
              "## 路径与维护", "",
              "[本目录的旧路径映射](path_map.tsv) · [全仓库映射](../results/path_map.tsv) · "
              "[整理检查](../experiments/maintenance/20261023_docs_layout/verification.json)", "",
              "```bash", "# 查询旧文档位置。",
              "python3 scripts/result_paths.py docs/deepswe_failure_manual_20261006.html", "",
              "# 更新阅读副本、文档目录和实验索引。",
              "python3 scripts/build_experiment_index.py",
              "python3 scripts/build_experiment_index.py --check", "```", "",
              "原 HTML 中的相对链接按 catalog.json 的 link_base 解释。"
              "从本页进入阅读副本，可使用更新后的链接。冻结记录中的原路径不改写。", ""]
    archive_lines = ["# 归档文档", "", "[返回当前文档](../README.md)", "",
                     "本目录保存旧版评价、已被后续版本修正的实现说明和前期汇报。"
                     "每份文档保留原内容。归档原因只说明其在阅读顺序中的位置。", "",
                     "| 文件 | 归档原因 | 后续阅读 |", "|---|---|---|"]
    by_path = {r["path"]: r for r in documents}
    for row in archived:
        following = " · ".join(link(by_path.get(p, {}).get("title", "独立审查"), p, "docs/archive")
                               for p in row["next_readings"])
        archive_lines.append(f"| {link(Path(row['path']).name, row['path'], 'docs/archive')} | "
                             f"{row['reason']} | {following} |")
    archive_lines += ["", "## 历史汇报的构建", "",
                      "20261001_test_augmentation_slides.pdf 与同名 .tex 配套保存。"
                      "从仓库根目录执行 `make -C docs` 可重新构建。构建需要 latexmk、pdflatex、"
                      "Beamer、TikZ/PGF、FontAwesome5、Latin Modern、AMS math、booktabs 和 listings。"
                      "中间文件写入 docs/build/。本次整理保留了原 PDF，未重新编译。", ""]
    mapping = io.StringIO()
    writer = csv.DictWriter(mapping, ["old", "new", "kind"], delimiter="\t", lineterminator="\n")
    writer.writeheader()
    for row in documents:
        writer.writerow({"old": row["original_path"], "new": row["path"], "kind": "document"})
        if row.get("reader"):
            writer.writerow({"old": row["original_reader"], "new": row["reader"], "kind": "document_reader"})
    outputs = {"docs/README.md": "\n".join(lines),
               "docs/archive/README.md": "\n".join(archive_lines),
               "docs/path_map.tsv": mapping.getvalue()}
    stale = []
    for name, content in outputs.items():
        path = ROOT / name
        if path.exists() and path.read_text() == content:
            continue
        if check:
            stale.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    if stale:
        raise ValueError(f"文档索引过期：{stale}")
    return {"documents": len(documents), "current": len(current), "archived": len(archived)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    print(json.dumps(build(parser.parse_args().check), ensure_ascii=False, indent=2))
