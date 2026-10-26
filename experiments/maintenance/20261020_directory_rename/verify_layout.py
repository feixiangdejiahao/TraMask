"""Audit the completed directory rename without running subject experiments."""
import csv
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


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        self.urls += [v for k, v in attrs if k in ("href", "src") and v]


def read(path):
    return json.loads(path.read_text())


def main():
    failures = []
    index = build(check=True)
    original = read(AUDIT / "before_metadata.json")
    for row in original:
        path = canonical_path(row["path"])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            failures.append({"kind": "original_content", "path": row["path"]})
    locations = read(AUDIT / "before_locations.json")
    for row in locations:
        path = canonical_path(row["old"])
        if (not path.exists() or (path.lstat().st_ino, path.lstat().st_dev)
                != (row["inode"], row["device"])):
            failures.append({"kind": "moved_inode", "path": row["old"]})
    mappings = read(ROOT / "results/path_map.json")["mappings"]
    for row in mappings:
        if not (ROOT / row["new"]).exists():
            failures.append({"kind": "mapping_target", "path": row["new"]})
    removed = set(read(AUDIT / "removed_topic_aliases.json"))
    links = read(AUDIT / "before_symlinks.json")
    checked_symlinks = 0
    for row in links:
        if row["path"] in removed or not row["target_existed"]:
            continue
        checked_symlinks += 1
        path = canonical_path(row["path"])
        if not path.is_symlink() or not path.exists():
            failures.append({"kind": "original_symlink", "path": str(path)})
    topics = read(ROOT / "experiments/directory_layout.json")["topics"]
    mirrors = 0
    for topic in topics:
        result = ROOT / "results" / topic["name"]
        mirror = ROOT / "experiments" / topic["name"] / "results"
        if not result.exists():
            continue
        mirrors += 1
        if not mirror.is_symlink() or mirror.resolve() != result:
            failures.append({"kind": "topic_mirror", "path": str(mirror)})
    reports = read(ROOT / "experiments/reports/source_manifest.json")
    docs = [ROOT / p for p in ("README.md", "docs/README.md", "research/README.md",
                               "prototypes/README.md", "results/README.md",
                               "experiments/README.md", "experiments/NAMING.md",
                               "experiments/INVENTORY.md", "experiments/index.html",
                               "experiments/reports/README.md")]
    docs += list((ROOT / "experiments/pilots").rglob("README.md"))
    docs += list((ROOT / "research/history").glob("*.md"))
    docs += list((ROOT / "experiments").glob("*/README.md"))
    docs += list((ROOT / "results").glob("*/README.md"))
    docs += list((ROOT / "prototypes").rglob("*.md"))
    docs += [ROOT / r["view"] for r in reports["reports"]]
    checked_urls = 0
    for source in sorted(set(docs)):
        text = source.read_text()
        if source.suffix == ".html":
            parser = Links()
            parser.feed(text)
            urls = parser.urls
        else:
            urls = re.findall(r"!?\[[^\]\n]*\]\(([^)\s]+)\)", text)
        for url in urls:
            parsed = urlsplit(url)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            checked_urls += 1
            target = source.parent / unquote(parsed.path)
            if not target.exists():
                failures.append({"kind": "current_link",
                                 "source": str(source.relative_to(ROOT)), "url": url})
    tasks = list(csv.DictReader((ROOT / "experiments/pilots/tasks.tsv").open(), delimiter="\t"))
    task_paths = 0
    for row in tasks:
        for name in ("reader", "case_list", "summary", "review", "supplement_review",
                     "artifacts", "source", "repository", "issue", "trajectory", "candidate_patch"):
            for path in filter(None, row[name].split(";")):
                task_paths += 1
                if not (ROOT / path).exists():
                    failures.append({"kind": "task_path", "path": path})
    prototype = read(AUDIT / "prototype_migration.json")
    for row in prototype["changed_sources"]:
        path = ROOT / row["path_after"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256_after"]:
            failures.append({"kind": "prototype_source_hash", "path": str(path)})
    old_roots = [row["old"] for row in mappings
                 if (row["old"].startswith("results/") and len(Path(row["old"]).parts) == 2)
                 or row["kind"] == "topic" or row["old"] == "experimental"]
    for path in old_roots:
        if (ROOT / path).exists() or (ROOT / path).is_symlink():
            failures.append({"kind": "old_root_remains", "path": path})
    worktree = ROOT / "results/evidence_guided_search/source_evidence_search_restart_20261004/source_round02"
    git = subprocess.run(["git", "-C", str(worktree), "rev-parse", "--show-toplevel"],
                         check=True, capture_output=True, text=True)
    if git.stdout.strip() != str(worktree):
        failures.append({"kind": "git_worktree", "actual": git.stdout.strip()})
    test_log = AUDIT / "unit_tests.log"
    test_result = None
    if test_log.exists():
        match = re.search(r"(?:(\d+) failed, )?(\d+) passed, (\d+) skipped[^\n]*$",
                          test_log.read_text().strip())
        if match:
            test_result = {"summary": match[0], "failed": int(match[1] or 0),
                           "passed": int(match[2]), "skipped": int(match[3])}
    baseline = read(AUDIT / "preexisting_test_failure.json")
    baseline_only = bool(test_result and test_result["failed"] == 1 and baseline["reproduced"]
                         and all(r["unchanged_from_HEAD"] for r in baseline["files"]))
    status = "incomplete"
    if not failures and test_result:
        if baseline_only:
            status = "layout_verified_with_preexisting_test_failure"
        elif not test_result["failed"]:
            status = "passed"
    result = {
        "status": status,
        "scope": "Directory, link, source-import and evidence-preservation checks only.",
        "index": index,
        "original_metadata_sha256_checked": len(original),
        "moved_locations_inode_checked": len(locations),
        "path_mapping_entries": len(mappings),
        "original_valid_symlinks_still_valid": checked_symlinks,
        "pre_prototype_symlink_target_audit": read(AUDIT / "symlink_target_audit.json"),
        "prototype_target_symlinks_in_original_inventory": sum(
            "/experimental/" in r["target_path"] for r in links),
        "topic_result_mirrors": mirrors,
        "current_navigation_documents": len(set(docs)),
        "current_local_links_checked": checked_urls,
        "task_rows": len(tasks), "task_paths_checked": task_paths,
        "prototype_directories_renamed": len(prototype["moves"]),
        "python_sources_updated": len(prototype["changed_sources"]),
        "unit_tests": test_result,
        "unit_test_suite_status": "one_preexisting_failure" if baseline_only else
                                 ("passed" if test_result and not test_result["failed"] else "incomplete"),
        "preexisting_test_failure": "preexisting_test_failure.json" if baseline_only else None,
        "failures": failures,
        "model_calls": 0, "benchmark_reruns": 0,
    }
    (AUDIT / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
