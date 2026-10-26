"""Offline material and result inventory for the contrast pilot. No model calls."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from augmentation.pipeline import write_json
from scripts.run_augmentation_contrast_pilot import RUN, OLD, read


def paired_sources():
    """Reconstruct only patch-touched files for static review, in a new directory."""
    for case in read(RUN / "cases.json"):
        directory = RUN / "evaluation/source_pairs" / case["id"]
        if (directory / "manifest.json").exists():
            continue
        gold = ROOT / "experiments/relation_distinction/results/pilot30_20261007_v1/gold_comparison_v1/cases" / case["id"] / "gold.patch"
        original = Path(case["candidate_patch"])
        paths = set(re.findall(r"^(?:---|\+\+\+) [ab]/([^\n\t]+)", original.read_text() + "\n" + gold.read_text(), re.M))
        work = directory / "gold"
        work.mkdir(parents=True, exist_ok=False)
        receipts = []
        for path in sorted(paths):
            p = Path(path)
            if p.is_absolute() or ".." in p.parts:
                raise ValueError("unsafe_patch_path")
            source = Path(case["repository"]) / path
            if source.is_file():
                target = work / path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                receipts.append({"path": path, "original_sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
        phases = []
        for name, patch, reverse in [("reverse_original", original, True), ("apply_gold", gold, False)]:
            command = ["patch", "--batch", "--fuzz=0", "--no-backup-if-mismatch", "-p1", "--input", str(patch)]
            if reverse:
                command.append("--reverse")
            result = subprocess.run(command, cwd=work, capture_output=True, text=True)
            (directory / (name + ".stdout")).write_text(result.stdout)
            (directory / (name + ".stderr")).write_text(result.stderr)
            phases.append({"phase": name, "returncode": result.returncode})
            if result.returncode:
                break
        status = "ready" if all(p["returncode"] == 0 for p in phases) and len(phases) == 2 else "failed_do_not_use"
        write_json(directory / "manifest.json", {"case": case["id"], "status": status, "phases": phases,
                   "original_receipts": receipts, "evaluation_only": True, "subject_execution": False,
                   "gold_patch_sha256": hashlib.sha256(gold.read_bytes()).hexdigest()})
        print(case["id"], status, flush=True)


def inventory():
    rows = []
    for path in sorted(RUN.glob("runs/*/*/*/result.json")):
        r = read(path)
        for i, claim in enumerate(r["final"].get("reviews", [])):
            rows.append({"key": f"{r['case']}/{r['arm']}/{r['repeat']}/{i + 1}",
                         "case": r["case"], "arm": r["arm"], "repeat": r["repeat"],
                         "decision": claim.get("decision"), "claim": claim, "result_path": str(path.relative_to(ROOT))})
    write_json(RUN / "evaluation/final_inventory.json", rows)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["sources", "inventory", "show"])
    parser.add_argument("--case")
    parser.add_argument("--arm")
    parser.add_argument("--decision", default="gap")
    args = parser.parse_args()
    if args.stage == "sources":
        paired_sources()
        return
    rows = inventory()
    if args.stage == "inventory":
        print(json.dumps({"claims": len(rows), "decisions": dict(Counter(r['decision'] for r in rows))}))
        return
    for row in rows:
        if (not args.case or row["case"] == args.case) and (not args.arm or row["arm"] == args.arm) and (args.decision == "all" or row["decision"] == args.decision):
            print(json.dumps(row, ensure_ascii=False))


if __name__ == "__main__":
    main()
