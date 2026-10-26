"""Check renamed reports, current navigation and reading-copy freshness."""
import ast
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[3]
AUDIT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))
from result_paths import canonical_path
from build_experiment_index import build


def read(path):
    return json.loads(path.read_text())


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        self.urls += [v for k, v in attrs if k in ("href", "src") and v]


def main():
    failures = []
    catalog = read(ROOT / "docs/catalog.json")["documents"]
    before = {r["path"]: r for r in read(AUDIT / "before_documents.json")}
    operations = read(AUDIT / "operations.json")
    for row in catalog:
        path = ROOT / row["path"]
        original = before[row["original_path"]]
        if hashlib.sha256(path.read_bytes()).hexdigest() != original["sha256"]:
            failures.append({"kind": "original_content", "path": row["path"]})
        if path.stat().st_ino != original["inode"]:
            failures.append({"kind": "original_inode", "path": row["path"]})
        if not re.fullmatch(r"\d{8}_[a-z0-9_]+\.(html|pdf|tex)", path.name):
            failures.append({"kind": "filename", "path": row["path"]})
    for row in operations["moves"]:
        if (ROOT / row["old"]).exists() or not (ROOT / row["new"]).exists():
            failures.append({"kind": "move", **row})
        if canonical_path(row["old"]) != ROOT / row["new"]:
            failures.append({"kind": "path_mapping", **row})
    index = build(check=True)
    manifest = read(ROOT / "experiments/reports/source_manifest.json")
    navigation = {ROOT / p for p in ("README.md", "docs/README.md", "docs/archive/README.md",
                                    "research/README.md", "research/history/README.md",
                                    "experiments/README.md", "experiments/NAMING.md",
                                    "experiments/index.html", "experiments/INVENTORY.md",
                                    "experiments/reports/README.md")}
    navigation.update((ROOT / "experiments/pilots").rglob("README.md"))
    navigation.update((ROOT / "experiments").glob("*/README.md"))
    navigation.update(ROOT / r["view"] for r in manifest["reports"])
    for name in ("deepswe_counterfactual_review_20261021", "deepswe_report_presentation_20261022",
                 "deepswe_gap_visuals_20261022"):
        navigation.add(ROOT / "research" / name / "README.md")
    count = 0
    for source in sorted(navigation):
        content = source.read_text()
        if source.suffix == ".html":
            parser = Links()
            parser.feed(content)
            urls = parser.urls
        else:
            urls = re.findall(r"!?\[[^\]\n]*\]\(([^)\s]+)\)", content)
        for url in urls:
            parsed = urlsplit(url)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            count += 1
            path = source.parent / unquote(parsed.path)
            # This report is written after all other checks finish.
            if path.resolve() == AUDIT / "verification.json":
                continue
            if not path.exists():
                failures.append({"kind": "local_link", "source": str(source.relative_to(ROOT)), "url": url})
    scripts = set(operations["updated_scripts"]) | {"scripts/build_experiment_index.py",
                "scripts/build_report_readers.py", "scripts/build_docs_index.py"}
    for name in scripts:
        ast.parse((ROOT / name).read_text(), filename=name)
    portable = read(AUDIT / "portable_report_audit.json")
    if portable["status"] != "passed":
        failures.append({"kind": "portable_report", "status": portable["status"]})
    make = subprocess.run(["make", "-n", "-B", "-C", str(ROOT / "docs")],
                          check=True, capture_output=True, text=True)
    (AUDIT / "make_dry_run.log").write_text(make.stdout)
    if "archive/20261001_test_augmentation_slides.tex" not in make.stdout:
        failures.append({"kind": "presentation_build_source"})
    result = {"status": "passed" if not failures else "failed", "documents": len(catalog),
              "current_documents": sum(r["status"] == "current" for r in catalog),
              "archived_files": sum(r["status"] == "archive" for r in catalog),
              "original_document_hashes_and_inodes_checked": len(catalog),
              "document_and_reader_paths_checked": len(operations["moves"]),
              "current_navigation_files": len(navigation), "current_local_links_checked": count,
              "python_scripts_syntax_checked": len(scripts), "index": index,
              "portable_report_audit": {k: portable[k] for k in ("status", "trials", "tasks",
                  "html_sha256", "original_metrics_and_decisions_unchanged", "javascript_syntax",
                  "external_resources", "reading_copies_byte_equal")},
              "presentation_build": "dry_run_passed_original_pdf_preserved",
              "failures": failures, "model_calls": 0, "benchmark_reruns": 0}
    (AUDIT / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
