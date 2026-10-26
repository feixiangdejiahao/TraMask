"""Audit the revised data, reports, source links and scoped reading copies.

This checks artifact consistency, not the truth of the manual causal judgments.
"""
from collections import Counter
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import unquote, urlsplit

from build_deepswe_counterfactual_report import (
    ROOT, STUDY, RUN, OLD, DEST, LABELS, POSITIVE, read, receipt, verify_receipts, write,
)
from build_report_readers import build as check_readers


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.ids = []
        self.cards = []
        self.links = []
        self.script = False
        self.scripts = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.append(a["id"])
        if "trial" in a.get("class", "").split():
            self.cards.append(a)
        for k in ("href", "src"):
            if k in a:
                self.links.append(a[k])
        if tag == "script":
            self.script = a.get("type", "") in ("", "text/javascript", "application/javascript")

    def handle_endtag(self, tag):
        if tag == "script":
            self.script = False

    def handle_data(self, data):
        if self.script:
            self.scripts.append(data)


def audit():
    rows = [json.loads(line) for line in (STUDY / "reviews.jsonl").read_text().splitlines()]
    summary = read(STUDY / "summary.json")
    paths = sorted((OLD / "trials").glob("*.json"))
    assert len(rows) == 211 and {r["trial"] for r in rows} == {p.stem for p in paths}
    assert Counter(r["decision"] for r in rows) == summary["decisions"]
    assert len({r["task"] for r in rows}) == 90
    assert len(list((STUDY / "trials").glob("*.json"))) == 211
    drafts = {r["n"]: r for p in sorted(STUDY.glob("batch_*.json")) for r in read(p)}
    for correction in read(STUDY / "adjudications.json"):
        drafts[correction["n"]].update(correction)
    for row in rows:
        assert read(STUDY / "trials" / f'{row["trial"]}.json') == row
        for key, value in drafts[row["n"]].items():
            assert row[key] == value, (row["n"], key)
        assert row["actual_f2p_delta"] is row["actual_p2p_delta"] is None
        assert not row["repair_rerun"]
        assert row["positive_under_current_definition"] == (row["decision"] in POSITIVE)
    sources = ["docs/20261022_deepswe_failure_analysis_n211.html", "docs/archive/20261007_combination_relation_census_n211.html"]
    check_readers(check=True, only_sources=sources)
    targets = [ROOT / p for p in sources] + [ROOT / "experiments/reports" / p for p in sources]
    broken = []
    reports = []
    node = shutil.which("node")
    assert node, "node is required to syntax-check the report's JavaScript"
    for path in targets:
        page = Page(path.read_text())
        assert len(page.ids) == len(set(page.ids)), f"duplicate IDs in {path}"
        if path.name == DEST.name:
            assert len(page.cards) == 211
            assert {c["id"] for c in page.cards} == {r["trial"] for r in rows}
            assert Counter(c["data-status"] for c in page.cards) == summary["decisions"]
        else:
            assert "counterfactual-revision" in page.ids
        for url in page.links:
            u = urlsplit(url)
            if u.scheme or u.netloc:
                continue
            target = (path.parent / unquote(u.path)).resolve() if u.path else path
            if not target.exists():
                broken.append({"source": str(path.relative_to(ROOT)), "url": url})
            elif u.fragment and target.suffix == ".html":
                ids = Page(target.read_text()).ids
                if unquote(u.fragment) not in ids:
                    broken.append({"source": str(path.relative_to(ROOT)), "url": url, "reason": "missing anchor"})
        with tempfile.TemporaryDirectory(prefix="deepswe-report-js-") as tmp:
            script = Path(tmp) / "viewer.js"
            script.write_text("\n".join(page.scripts))
            subprocess.run([node, "--check", str(script)], check=True, capture_output=True, text=True)
        reports.append({**receipt(path), "local_link_count": sum(not urlsplit(u).scheme for u in page.links),
                        "trial_cards": len(page.cards), "javascript_syntax": "passed"})
    assert not broken, json.dumps(broken[:20], ensure_ascii=False)
    frozen = verify_receipts(read(RUN / "inputs/frozen_baseline.json")["files"])
    # Current prose indexes must not retain a stale count after a manual revision.
    expected = f'{summary["directly_supported"]} 条直接支持、{summary["conditionally_supported"]} 条有条件支持'
    assert expected in (ROOT / "docs/README.md").read_text()
    study_text = (STUDY / "README.md").read_text()
    assert f'{summary["directly_supported"]} 条直接支持，{summary["conditionally_supported"]} 条有条件支持' in study_text
    result = read(STUDY / "audit.json")
    result["report_checks"] = {
        "status": "passed", "manual_inputs_match_all_outputs": True,
        "per_trial_json_matches_jsonl": True, "local_links_broken": 0,
        "reading_copies_current": True, "historical_files_unchanged": frozen,
        "reports": reports,
        "limitation": "No independent semantic re-labeling or coding-agent repair experiment.",
    }
    result["tooling_receipts"] = [receipt(ROOT / "scripts" / name) for name in (
        "build_deepswe_counterfactual_report.py", "build_deepswe_failure_manual_report.py",
        "build_combination_relation_census.py", "build_report_readers.py",
        "build_experiment_index.py", "audit_deepswe_counterfactual_review.py",
    )]
    write(STUDY / "audit.json", result)
    print(json.dumps({"status": "passed", "trials": len(rows), "reports": len(reports),
                      "broken_links": 0, "historical_files_unchanged": frozen}, ensure_ascii=False))


if __name__ == "__main__":
    audit()
