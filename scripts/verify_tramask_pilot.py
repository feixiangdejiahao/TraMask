"""Read-only verification of this pilot's frozen receipts and derived totals."""
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import hashlib
import sys
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tramask_pilot.corpus import ROOT, RUN, read, receipt


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    out = RUN / "evaluation/pilot_v01"
    summary = read(out / "summary.json")
    assert summary["status"] == "complete"
    reviews = read(out / "review.json")["pairs"]
    assert len(reviews) == len({r["task"] for r in reviews}) == 40
    assert Counter(r["label"] for r in reviews) == summary["pilot1"]["labels"]
    checked = 0
    for r in read(RUN / "blind_review/reviewer_a/freeze_receipts.json")["judgment_files"]:
        assert sha(RUN / "blind_review/reviewer_a" / r["file"]) == r["sha256"]
        checked += 1
    for r in read(RUN / "blind_review/reviewer_b/freeze_receipt.json")["receipts"]:
        assert sha(RUN / "blind_review/reviewer_b" / r["judgment_file"]) == r["judgment_sha256"]
        assert sha(RUN / "blind_review/packets" / r["pair_id"] / "manifest.json") == r["packet_manifest_sha256"]
        checked += 1
    assert checked == 80
    for r in reviews:
        for key in ("reviewer_a", "reviewer_b", "fidelity_review", "packet_manifest"):
            assert sha(r[key]["path"]) == r[key]["sha256"]
    for r in summary["post_experiment_independent_reviews"] + summary["protocol_amendments"]:
        assert sha(r["path"]) == r["sha256"]
    for key in ("summary", "review", "report"):
        r = read(RUN / "active_evaluation.json")[key]
        assert sha(r["path"]) == r["sha256"]
    runs, slots, untouched = 0, 0, 0
    for cid in ("F023", "F034"):
        case = RUN / "runs" / cid
        base = read(Path(read(case / "active_hypothesis.json")["directory"]) / "staging.json")
        for p in (case / "downstream").glob("pilot*/*/repeat_*/candidate_*/evaluation.json"):
            slots += 1
            evaluation = read(p)
            if not evaluation.get("executed"):
                continue
            d = p.parent
            candidate = read(d / "candidate.json")
            allowed = {e["path"] for e in candidate["edits"]} | {e["path"] for e in candidate.get("new_files", [])}
            review = read(d / "manual_review.json")
            assert review["approved_for_execution"] and review["candidate_sha256"] == sha(d / "candidate.json")
            staged = read(d / "staging.json")
            assert set(staged["variants"]) == {"p_original", "q_original", "p_instrumented", "q_instrumented"}
            for name, variant in staged["variants"].items():
                original, tree = Path(base["variants"][name]["tree"]), Path(variant["tree"])
                for file in original.rglob("*"):
                    if file.is_file() and file.relative_to(original).as_posix() not in allowed:
                        assert file.read_bytes() == (tree / file.relative_to(original)).read_bytes()
                        untouched += 1
                for r in variant["files"]:
                    assert sha(r["path"]) == r["sha256"]
                execution = read(d / "paired_execution" / name / "execution.json")
                assert not execution.get("timed_out") and not execution.get("transport_error") and not execution.get("event_error")
                runs += 1
    assert slots == 140 and runs == summary["downstream"]["subject_runs"] == 64
    ledger = read(RUN / "provider_budget.json")
    actual = sum(r["charged_tokens"] for r in ledger["calls"].values())
    assert actual == summary["cost"]["charged_input_output_tokens"] <= 10_000_000
    assert all(r["status"] == "settled" for r in ledger["calls"].values())

    class Links(HTMLParser):
        def __init__(self):
            super().__init__()
            self.links = []

        def handle_starttag(self, tag, attrs):
            if tag == "a":
                self.links.extend(value for key, value in attrs if key == "href")
    parser = Links()
    parser.feed((out / "report.html").read_text())
    for href in parser.links:
        url = urlsplit(href)
        if not url.scheme and url.path:
            assert (out / unquote(url.path)).exists(), href
    result = {"status": "passed", "frozen_judgments_verified": checked,
              "downstream_slots": slots, "downstream_subject_runs": runs,
              "unchanged_non_candidate_files_verified": untouched,
              "report_local_links_verified": len(parser.links), "provider_tokens": actual,
              "paper_unchanged": sha(ROOT / "TraMask_Behavioral_Masking.pdf") == summary["paper"]["sha256"],
              "verification_script": receipt(Path(__file__))}
    import json
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
