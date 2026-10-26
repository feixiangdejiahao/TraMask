"""Acquire public evaluation evidence for the 2026-10-21 retrospective review.

This is evaluation-side analysis, not an agent-input or blind-generation run.
Existing evidence is copied byte for byte; frozen study records are not changed.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request

from result_paths import canonical_path

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "research/deepswe_failure_manual_20261006"
OUT = ROOT / "results/failure_analysis/20261021_counterfactual_gap_n211_r01"
FILES = ("ctrf.json", "reward.json", "test-stdout.txt")


def acquire(trial):
    records = []
    for name in FILES:
        destination = OUT / "evaluation" / trial / name
        source = canonical_path(f"results/expanded_trials_20260926/trials/{trial}/verifier/{name}")
        url = f"https://d3ujjcmjq6o8v6.cloudfront.net/v1.1/trial-artifacts/{trial}/verifier/{name}"
        record = {"trial": trial, "file": name, "url": url,
                  "path": str(destination.relative_to(ROOT))}
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                record["acquisition"] = "already_acquired"
            elif source.exists():
                shutil.copyfile(source, destination)
                record.update(acquisition="local_copy", source=str(source.relative_to(ROOT)))
            else:
                request = urllib.request.Request(url, headers={"User-Agent": "DeepSWE-retrospective-evidence-review/1.0"})
                with urllib.request.urlopen(request, timeout=45) as response:
                    content = response.read()
                if name.endswith(".json"):
                    json.loads(content)
                temporary = destination.with_suffix(destination.suffix + ".part")
                temporary.write_bytes(content)
                temporary.replace(destination)
                record["acquisition"] = "public_download"
            content = destination.read_bytes()
            if name.endswith(".json"):
                json.loads(content)
            record.update(bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
        except Exception as error:
            record["error"] = f"{type(error).__name__}: {error}"
        records.append(record)
    return records


def main():
    trials = sorted(p.stem for p in (STUDY / "trials").glob("*.json"))
    records = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(acquire, trial): trial for trial in trials}
        for index, future in enumerate(as_completed(futures), 1):
            items = future.result()
            records.extend(items)
            if index % 20 == 0 or any("error" in item for item in items):
                print(json.dumps({"completed_trials": index, "total_trials": len(trials),
                                  "errors": [x for x in items if "error" in x]}, ensure_ascii=False), flush=True)
    manifest = {"purpose": "retrospective_evaluation_side_counterfactual_review",
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "trials": len(trials), "files": sorted(records, key=lambda r: (r["trial"], r["file"])),
                "errors": sum("error" in r for r in records),
                "new_subject_executions": 0, "new_coding_agent_runs": 0}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "acquisition.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in manifest.items() if k != "files"}))
    if manifest["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
