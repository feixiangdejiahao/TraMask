"""Build immutable, blinded original-context packets for two independent reviewers."""
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src")]
from tramask_pilot.corpus import RUN, read, write, receipt
from tramask_pilot.evidence import build_before_review_packet


def main():
    cases = read(RUN / "formal_failed_cohort.json")["cases"]
    successful = RUN / "formal_successful_cohort.json"
    if successful.exists():
        cases += read(successful)["cases"]
    mapping = []
    for case in cases:
        directory = RUN / "runs" / case["id"]
        pointer = directory / "active_hypothesis.json"
        if not pointer.exists():
            continue
        hypothesis_dir = Path(read(pointer)["directory"])
        hypothesis = read(hypothesis_dir / "hypothesis.json")
        before = directory / "before_pair"
        if hypothesis["status"] == "proposed":
            if not (before / "summary.json").exists():
                continue
            records = {name: read(before / name / "execution.json") for name in
                       ("p_original", "q_original", "p_instrumented", "q_instrumented")}
        else:
            replay = Path(read(directory / "active_replay.json")["directory"])
            records = {"p_original": read(replay / "summary.json")["final_test_only"]}
        opaque = "pair_" + hashlib.sha256(("review-v1:" + case["trial"]).encode()).hexdigest()[:12]
        dest = RUN / "blind_review/packets" / opaque
        if not dest.exists():
            build_before_review_packet(directory, RUN / "inputs" / case["id"], dest,
                                       hypothesis=hypothesis, before_records=records, opaque_id=opaque,
                                       supplemental_test_paths=["app/vm/main_test.go"] if case["id"] == "F034" else [],
                                       supplemental_source_paths=["app/src/error.ts"] if case["id"] == "S030" else [])
        mapping.append({"case_id": case["id"], "pair_id": opaque,
                        "manifest": receipt(dest / "manifest.json"),
                        "original_hypothesis": receipt(hypothesis_dir / "hypothesis.json")})
    write(RUN / "review_private_mapping.json", {"packets": mapping})
    write(RUN / "blind_review/available.json", {"packets": sorted(row["pair_id"] for row in mapping),
          "note": "More frozen pre-repair packets may be added; existing packets are immutable."})
    print("Ready blinded packets:", len(mapping))


if __name__ == "__main__":
    main()
