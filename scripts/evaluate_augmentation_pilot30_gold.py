"""Post-generation gold comparison of the frozen 30-trial pilot.

Gold and benchmark evidence are evaluation-only. This script does not call a
model, select new candidates, edit assertions, or repair subject patches.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from combination_testing.runner import run_artifact, compare_pair, load_artifact, freeze_artifact
from scripts.run_augmentation_pilot30 import RUN, read, write, receipt

OUT = RUN / "gold_comparison_v1"
TASKS = Path("/home/jhx/oracle_gap/external/deep-swe/tasks")


def preferred_native(directory):
    return next(directory / phase for phase in
                ("native_environment_final", "native_environment", "native")
                if (directory / phase / "summary.json").exists())


def prepare():
    protocol = OUT / "protocol.json"
    if protocol.exists():
        return read(protocol)
    rows = []
    for case in read(RUN / "cases.json"):
        cid = case["id"]
        dest = OUT / "cases" / cid
        dest.mkdir(parents=True, exist_ok=True)
        task = TASKS / case["task"]
        gold = task / "solution/solution.patch"
        shutil.copy2(gold, dest / "gold.patch")
        # Keep original benchmark tests/configuration separate from all inputs.
        for name in ("test.patch", "config.json", "test.sh"):
            shutil.copy2(task / "tests" / name, dest / ("benchmark_" + name))
        runtime = dict(case)
        runtime["base_commit"] = read(RUN / "cases" / cid / "repository_provenance.json")["base_commit"]
        setup = RUN / "environment" / cid / "setup.json"
        if setup.exists():
            env = read(setup)
            if env.get("status") == "ready" and env.get("derived_image"):
                runtime["image"] = env["derived_image"]
        reviews = {r["candidate"]: r for r in read(RUN / "evaluation/reviews" / (cid + ".json"))["claims"]}
        items = []
        for path in sorted((RUN / "cases" / cid / "generation").glob("*/assessment.json")):
            assessment = read(path)
            if assessment["decision"] != "gap":
                continue
            native = preferred_native(path.parent)
            artifact = native / "artifact"
            load_artifact(artifact)
            items.append({"candidate": path.parent.name, "assessment": receipt(path),
                          "artifact": receipt(artifact / "manifest.json"),
                          "candidate_result": receipt(native / "candidate/result.json"),
                          "candidate_summary": receipt(native / "summary.json"),
                          "previous_review": reviews[path.parent.name]})
        metadata = read(Path(case["candidate_patch"]).parent / "metadata.json")
        rows.append({"case": cid, "trial": case["trial"], "task": case["task"],
                     "runtime": runtime, "gold_original": receipt(gold),
                     "gold": receipt(dest / "gold.patch"),
                     "candidate_patch": receipt(Path(case["candidate_patch"])),
                     "previous_benchmark": {k: metadata[k] for k in
                         ("outcome", "reward", "f2p_total", "f2p_passed", "p2p_total", "p2p_passed")},
                     "items": items})
    p = {"created_at": datetime.now(timezone.utc).isoformat(), "evaluation_only": True,
         "selection": "Every accepted gap response from the completed pilot; no changes to tests or expected values.",
         "previous_summary": receipt(RUN / "summary.json"),
         "previous_reviews": [receipt(p) for p in sorted((RUN / "evaluation/reviews").glob("*.json"))],
         "reference_role": "Post-generation differential comparison, not evidence provided to generation.",
         "cases": rows, "model_calls": 0,
         "interpretation": "Candidate assertion failure and gold pass supports a repair-relevant test, not an observed resolution-rate increase."}
    write(protocol, p)
    return p


def verify(rec):
    if hashlib.sha256(Path(rec["path"]).read_bytes()).hexdigest() != rec["sha256"]:
        raise ValueError("Frozen evidence changed: " + rec["path"])


def run_one(case, item):
    directory = OUT / "cases" / case["case"] / "tests" / item["candidate"]
    output = directory / "comparison.json"
    if output.exists():
        return read(output)
    directory.mkdir(parents=True, exist_ok=True)
    for record in (case["gold"], item["artifact"], item["candidate_result"], item["assessment"]):
        verify(record)
    original = read(item["candidate_result"]["path"])
    try:
        reference_path = directory / "gold/result.json"
        reference = read(reference_path) if reference_path.exists() else run_artifact(
            Path(item["artifact"]["path"]).parent, "reference", directory / "gold",
            reference_patch=Path(case["gold"]["path"]), registry=[case["runtime"]])
        pair = compare_pair(original, reference)
        pair.update(case=case["case"], candidate=item["candidate"],
                    previous_classification=item["previous_review"]["classification"],
                    previous_test_validity=item["previous_review"]["test_validity"],
                    known_gap_indices=item["previous_review"]["known_gap_indices"],
                    gold_result=receipt(reference_path), candidate_result=item["candidate_result"])
    except Exception as error:
        pair = {"case": case["case"], "candidate": item["candidate"],
                "evaluation_error": type(error).__name__, "message": str(error)}
    write(output, pair)
    return pair


def acquire_benchmark(case):
    import httpx
    dest = OUT / "cases" / case["case"] / "original_benchmark"
    receipts = []
    for name in ("ctrf.json", "reward.json"):
        path = dest / name
        url = f'https://d3ujjcmjq6o8v6.cloudfront.net/v1.1/trial-artifacts/{case["trial"]}/verifier/{name}'
        if not path.exists():
            cached = ROOT / "results/expanded_trials_20260926/trials" / case["trial"] / "verifier" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if cached.exists():
                shutil.copy2(cached, path)
            else:
                with httpx.Client(timeout=90, follow_redirects=True) as client:
                    response = client.get(url)
                    response.raise_for_status()
                json.loads(response.content)
                path.write_bytes(response.content)
        receipts.append({**receipt(path), "url": url})
    write(dest / "acquisition.json", {"files": receipts, "evaluation_only": True})
    return {"case": case["case"], "downloaded": len(receipts)}


def align_go_environment(case, item):
    """T11 requires the documented diff build tag and original test helpers.

    Preserve every generated byte. Add the same original validation files on
    both sides. No production file or expected result changes.
    """
    assert case["case"] == "T11"
    directory = OUT / "cases/T11/environment_pair" / item["candidate"]
    output = directory / "comparison.json"
    if output.exists():
        return read(output)
    original_artifact = Path(item["artifact"]["path"]).parent
    manifest = load_artifact(original_artifact)
    files = {f["target"]: (original_artifact / f["source"]).read_text() for f in manifest["files"]}
    support = []
    for name in ("diff_test.go", "diff_more_test.go"):
        if name not in files:
            path = Path(case["runtime"]["repository"]) / name
            files[name] = path.read_text()
            support.append(receipt(path))
    artifact = directory / "artifact"
    if not artifact.exists():
        freeze_artifact(artifact, "T11", files, manifest["command"].replace("go test ", "go test -tags diff ", 1),
                        manifest["report"]["format"], manifest["report"]["path"], timeout=300,
                        metadata={"original_artifact": item["artifact"], "added_original_test_support": support,
                                  "generated_source_unchanged": True, "gold_build_tag": "diff",
                                  "build_tag_source": str(TASKS / case["task"] / "tests/test.sh")})
    runs = {}
    for program in ("candidate", "reference"):
        dest = directory / program
        runs[program] = read(dest / "result.json") if (dest / "result.json").exists() else run_artifact(
            artifact, program, dest, reference_patch=Path(case["gold"]["path"]), registry=[case["runtime"]])
    pair = compare_pair(runs["candidate"], runs["reference"])
    pair.update(case="T11", candidate=item["candidate"], environment_aligned=True,
                previous_classification=item["previous_review"]["classification"],
                previous_test_validity=item["previous_review"]["test_validity"],
                known_gap_indices=item["previous_review"]["known_gap_indices"])
    write(output, pair)
    return pair


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("stage", choices=("prepare", "run", "benchmark", "align_go"))
    parser.add_argument("--case", action="append")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    protocol = prepare()
    cases = [c for c in protocol["cases"] if not args.case or c["case"] in args.case]
    if args.stage == "prepare":
        print(json.dumps({"cases": len(cases), "test_packets": sum(len(c["items"]) for c in cases)}))
        return
    if args.stage == "benchmark":
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for f in as_completed([pool.submit(acquire_benchmark, c) for c in cases]):
                try:
                    print(json.dumps(f.result()), flush=True)
                except Exception as e:
                    print(json.dumps({"error": type(e).__name__, "message": str(e)}), flush=True)
        return
    if args.stage == "align_go":
        case = next(c for c in cases if c["case"] == "T11")
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for f in as_completed([pool.submit(align_go_environment, case, item) for item in case["items"]]):
                row = f.result()
                print(json.dumps({k: row[k] for k in ("case", "candidate", "candidate_run_status",
                                  "reference_run_status", "counts")}), flush=True)
        return
    jobs = [(c, item) for c in cases for item in c["items"]]
    # Prioritize the informative failures, but eventually execute every packet.
    jobs.sort(key=lambda x: (read(x[1]["candidate_result"]["path"])["status"] != "fail",
                             not x[1]["previous_review"]["known_gap_indices"], x[0]["case"], x[1]["candidate"]))
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for f in as_completed([pool.submit(run_one, case, item) for case, item in jobs]):
            row = f.result()
            print(json.dumps({k: row[k] for k in ("case", "candidate", "candidate_run_status",
                              "reference_run_status", "counts", "evaluation_error") if k in row}), flush=True)


if __name__ == "__main__":
    main()
