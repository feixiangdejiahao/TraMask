"""Build report reading copies with current local links; preserve archived sources."""
import argparse
from functools import lru_cache
import hashlib
import html
import json
import os
from pathlib import Path
import re
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from result_paths import ROOT, canonical_path

BASE = ROOT / "experiments/reports"


def sources():
    found = []
    for folder in ("docs", "research"):
        for path in sorted((ROOT / folder).rglob("*")):
            if (path.suffix in (".html", ".md") and path.is_file()
                    and path.name not in ("README.md", "AGENTS.md")
                    and not set(path.relative_to(ROOT).parts) & {
                        "build", "history", "maintenance", "__pycache__"
                    }):
                found.append(path)
    return found


@lru_cache(maxsize=1)
def reading_paths():
    manifest = BASE / "source_manifest.json"
    if manifest.exists():
        rows = json.loads(manifest.read_text())["reports"]
        return {canonical_path(r["source"]): ROOT / r["view"] for r in rows}
    return {}


def reading_path(path):
    """Prefer a report reading copy, if the source is in the report manifest."""
    source = canonical_path(path)
    return reading_paths().get(source, source)


def build(check=False, only_sources=None):
    items = sources()
    selected = ({canonical_path(ROOT / p) for p in only_sources}
                if only_sources is not None else None)
    if selected is not None:
        unknown = selected - {canonical_path(p) for p in items}
        if unknown:
            raise ValueError(f"Unknown report sources: {sorted(map(str, unknown))}")
    views = {}
    for source in items:
        view = BASE / source.relative_to(ROOT)
        for key in (source, canonical_path(source), source.resolve()):
            views[key] = view
    texts, receipts, unresolved = {}, [], []
    if selected is not None:
        # Keep unrelated readers and their receipts intact during a scoped update.
        previous = json.loads((BASE / "source_manifest.json").read_text())
        receipts = [r for r in previous["reports"]
                    if canonical_path(r["source"]) not in selected]
        unresolved = [r for r in previous.get("unresolved_links", [])
                      if canonical_path(r["source"]) not in selected]
    for source in items:
        if selected is not None and canonical_path(source) not in selected:
            continue
        view = views[source]
        local_links = [0]
        # These reports were archived before this migration. Their local URLs
        # still use the original root README or research-document location.
        link_base = source.parent
        if source.parent == ROOT / "research/archive":
            if source.name == "README_pilot.md":
                link_base = ROOT
            elif source.name in ("method_design_action_observation_20260929.md",
                                  "method_design_context_lifting_pilot.md"):
                link_base = ROOT / "research"

        def rewrite(url):
            parsed = urlsplit(html.unescape(url))
            if parsed.scheme or parsed.netloc or not parsed.path:
                return url
            path = unquote(parsed.path)
            fragment = parsed.fragment
            line = re.search(r":(\d+)$", path)
            if line:
                path, fragment = path[:line.start()], fragment or "L" + line[1]
            target = canonical_path(link_base / path)
            try:
                target.relative_to(ROOT)
            except ValueError:
                return url
            local_links[0] += 1
            if not target.exists():
                unresolved.append({"source": source.relative_to(ROOT).as_posix(),
                                   "url": url, "current_target": str(target)})
            destination = views.get(target, views.get(target.resolve(), target))
            relative = quote(os.path.relpath(destination, view.parent), safe="/@:+")
            return urlunsplit(("", "", relative, parsed.query, fragment))

        original = source.read_text()
        portable = (source.suffix == ".html"
                    and '<meta name="deepswe-portable" content="standalone-bilingual-v1">' in original)
        if portable:
            # Portable reports have no external reading dependencies. Preserve
            # their embedded source text byte-for-byte and their bilingual UI.
            content = original
        elif source.suffix == ".html":
            content = re.sub(
                r"""(\b(?:href|src)\s*=\s*)(["'])(.*?)\2""",
                lambda m: m[1] + m[2] + html.escape(rewrite(m[3]), quote=True) + m[2],
                original, flags=re.I,
            )
            archive = os.path.relpath(source, view.parent)
            notice = ('<aside style="padding:10px 16px;background:#f1f5f9;'
                      'border-bottom:1px solid #ccd5df;font:14px/1.6 system-ui">'
                      '阅读副本：本页已更新本地链接。实验结论和正文中的历史路径沿用原文。'
                      f'<a href="{html.escape(archive)}">原报告</a> · '
                      f'<a href="{os.path.relpath(ROOT / "results/path_map.tsv", view.parent)}">'
                      '旧路径映射</a></aside>')
            content, count = re.subn(r"(<body\b[^>]*>)", lambda m: m[1] + notice,
                                    content, count=1, flags=re.I)
            if not count:
                content = notice + content
        else:
            content = re.sub(r"(!?\[[^\]\n]*\]\()([^)\s]+)(\))",
                             lambda m: m[1] + rewrite(m[2]) + m[3], original)
            archive = os.path.relpath(source, view.parent)
            content = (f"> 阅读副本。本页已更新本地链接。正文保留原文。"
                       f"[原记录]({archive}) · "
                       f"[旧路径映射]({os.path.relpath(ROOT / 'results/path_map.tsv', view.parent)})\n\n"
                       + content)
        texts[view] = content
        receipts.append({
            "source": source.relative_to(ROOT).as_posix(),
            "link_base": link_base.relative_to(ROOT).as_posix(),
            "view": view.relative_to(ROOT).as_posix(),
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "view_sha256": hashlib.sha256(content.encode()).hexdigest(),
            "local_links": local_links[0],
        })
    texts[BASE / "source_manifest.json"] = json.dumps({
        "schema_version": 1,
        "purpose": "Reading copies; original reports and scientific data are unchanged.",
        "reports": sorted(receipts, key=lambda r: r["source"]), "unresolved_links": unresolved,
    }, ensure_ascii=False, indent=2) + "\n"
    texts[BASE / "README.md"] = (
        "# 报告阅读入口\n\n"
        "本目录保存链接已更新的报告副本。原报告保持不变。"
        "正文中的历史路径可用 [路径查询工具](../../scripts/result_paths.py) 转换。\n\n"
        "按实验查找请打开 [主要 pilot](../pilots/README.md)，"
        "按报告查找请打开 [报告目录](../../docs/README.md)。\n\n"
        "`source_manifest.json` 保存原文路径、阅读副本路径和两者的校验值。"
        "未能定位的历史链接也记录在该文件中。\n\n"
        "运行 `python3 scripts/build_experiment_index.py` 会更新本目录。"
        "请修改原报告或生成脚本，不要直接编辑阅读副本。\n"
    )
    if selected is not None:
        texts.pop(BASE / "README.md")
    stale = []
    for path, content in texts.items():
        if path.exists() and path.read_text() == content:
            continue
        if check:
            stale.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    if stale:
        raise ValueError(f"报告入口过期：{stale[:8]}")
    reading_paths.cache_clear()
    return {"reports": len(receipts), "local_links": sum(r["local_links"] for r in receipts),
            "unresolved_links": len(unresolved)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--source", action="append", help="Only update this repository-relative report and its manifest receipts")
    args = parser.parse_args()
    print(json.dumps(build(args.check, args.source), ensure_ascii=False, indent=2))
