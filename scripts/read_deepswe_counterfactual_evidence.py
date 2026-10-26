"""Print bounded evidence windows for manual review; never assign labels."""
import argparse
import json
from pathlib import Path
import re

from result_paths import canonical_path

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "research/deepswe_failure_manual_20261006"
EVAL = ROOT / "results/failure_analysis/20261021_counterfactual_gap_n211_r01/evaluation"


def clip(value, length):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if len(text) <= length:
        return text
    return text[:length * 2 // 3] + " ... [READING WINDOW; FULL FILE LINKED] ... " + text[-length // 3:]


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("start", type=int)
    parser.add_argument("end", type=int, nargs="?")
    parser.add_argument("--message-limit", type=int, default=800)
    parser.add_argument("--inventory", action="store_true")
    parser.add_argument("--compact", action="store_true", help="Compact reading windows; full originals remain available")
    parser.add_argument("--patch", help="Regex selecting patch windows, not a classifier")
    parser.add_argument("--steps", nargs="*", type=int)
    parser.add_argument("--instruction", action="store_true")
    parser.add_argument("--details-only", action="store_true", help="Only optional inventory / source windows")
    parser.add_argument("--group-errors", action="store_true", help="Collapse identical failure messages for reading; retain counts and representative names")
    parser.add_argument("--evaluation-patch", help="Regex for retrospective evaluation-test source windows")
    args = parser.parse_args()
    paths = sorted((OLD / "trials").glob("*.json"))
    for ordinal in range(args.start, (args.end or args.start) + 1):
        path = paths[ordinal - 1]
        row = json.loads(path.read_text())
        raw = canonical_path(f"results/deepswe_failure_manual_20261006/trials/{path.stem}")
        print(f"\n=== {ordinal} {path.stem} ===")
        if args.evaluation_patch:
            source = EVAL.parent / "evaluation_tests" / row["task"] / "test.patch"
            lines = source.read_text().splitlines()
            selected = set()
            for i, line in enumerate(lines):
                if re.search(args.evaluation_patch, line, re.I):
                    selected.update(range(max(0, i-5), min(len(lines), i+40)))
            print("EVALUATION TEST SOURCE", source.relative_to(ROOT))
            for i in sorted(selected):
                print(f"{i+1}: {lines[i]}")
        if args.details_only:
            if args.inventory:
                print("VALIDATION", json.dumps(row.get("validation_inventory"), ensure_ascii=False))
            if args.instruction:
                print("INSTRUCTION", (raw / "instruction.md").read_text())
            if args.patch:
                lines = (raw / "model.patch").read_text().splitlines()
                selected = set()
                for i, line in enumerate(lines):
                    if re.search(args.patch, line, re.I):
                        selected.update(range(max(0, i-4), min(len(lines), i+7)))
                for i in sorted(selected):
                    print(f"{i+1}: {lines[i]}")
            if args.steps is not None:
                trajectory = json.loads((raw / "trajectory.json").read_text())
                for step in trajectory["steps"]:
                    if step["step_id"] in args.steps:
                        print("STEP", step["step_id"], json.dumps({k:v for k,v in step.items() if k != "reasoning_content"}, ensure_ascii=False))
            continue
        print("OLD", row["verdict"], row["verdict_reason"])
        for index, gap in enumerate(row.get("combination_gaps", [])):
            print("GAP", index, clip(gap, 800) if args.compact else json.dumps(gap, ensure_ascii=False))
        for key in ("selection_problems", "validation_feedback_problems", "counter_evidence"):
            if row.get(key):
                print(key, clip(row[key], 700) if args.compact else json.dumps(row[key], ensure_ascii=False))
        if args.inventory:
            print("VALIDATION", json.dumps(row.get("validation_inventory"), ensure_ascii=False))
        meta = json.loads((raw / "metadata.json").read_text())
        print("METRICS", {k: meta.get(k) for k in ("f2p_passed", "f2p_total", "p2p_passed", "p2p_total")})
        evaluation = EVAL / path.stem
        if (evaluation / "ctrf.json").exists():
            report = json.loads((evaluation / "ctrf.json").read_text())
            tests = report.get("results", {}).get("tests", [])
            failed = [t for t in tests if t["status"] not in ("passed", "skipped")]
            if args.group_errors:
                grouped = {}
                for test in failed:
                    grouped.setdefault(test.get("message", ""), []).append(test)
                failed = [dict(items[0], name=f"{len(items)} rows: " + " | ".join(t["name"] for t in items[:3])) for items in grouped.values()]
            for test in failed:
                message = test.get("message", "")
                if args.compact:
                    lines = message.splitlines()
                    useful = [line.strip() for line in lines if re.search(r"expected:|actual\s*:|Expected |got |received:|panic:|Error:|missing from report", line)]
                    if useful:
                        message = " | ".join(useful)
                print("EVAL", test["name"], clip(message, args.message_limit))
            if not failed:
                print("EVAL no failing CTRF rows; inspect reward and stdout")
        else:
            print("EVAL acquisition pending")
        stdout = evaluation / "test-stdout.txt"
        if stdout.exists():
            lines = stdout.read_text(errors="replace").splitlines()
            snippets = [line for line in lines if re.search(r"undefined:|build failed|cannot use|no required module|undefined reference|ModuleNotFound|ImportError|error\[E|error TS|Cannot find|panicked", line)]
            print("STDOUT WINDOWS", clip("\n".join(snippets), 600 if args.compact else 2000))
        if args.instruction:
            print("INSTRUCTION", (raw / "instruction.md").read_text())
        if args.patch:
            lines = (raw / "model.patch").read_text().splitlines()
            selected = set()
            for i, line in enumerate(lines):
                if re.search(args.patch, line, re.I):
                    selected.update(range(max(0, i-4), min(len(lines), i+7)))
            print("PATCH WINDOWS")
            for i in sorted(selected):
                print(f"{i+1}: {lines[i]}")
        if args.steps is not None:
            trajectory = json.loads((raw / "trajectory.json").read_text())
            for step in trajectory["steps"]:
                if step["step_id"] in args.steps:
                    print("STEP", step["step_id"], json.dumps({k:v for k,v in step.items() if k != "reasoning_content"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
