"""Assemble evaluation-only packets; never imported by model generation."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from scripts.run_augmentation_pilot30 import RUN, read, write


def build():
    truth = {r["id"]: r for r in read(RUN / "evaluation_truth.json")}
    for case in read(RUN / "cases.json"):
        directory = RUN / "cases" / case["id"]
        prepared_path = directory / "prepared.json"
        if not prepared_path.exists():
            continue
        prepared = read(prepared_path)
        candidates = {c["id"]: c for c in prepared["candidates"]}
        rows = []
        for path in sorted((directory / "generation").glob("*/result.json")):
            result = read(path)
            if result.get("raw_decision") not in {"gap", "selection_problem"}:
                continue
            completion = path.parent / "completion.txt"
            try:
                response = json.loads(completion.read_text())
            except (ValueError, OSError):
                response = {}
            candidate = candidates[result["candidate"]]
            native = next((p for p in [path.parent / "native_environment_final/summary.json", path.parent / "native_environment/summary.json", path.parent / "native/summary.json"] if p.exists()), None)
            rows.append({"candidate": result["candidate"], "family": candidate["family"], "scope": candidate["scope"],
                         "functions": candidate["function_ids"], "result": result, "response": response,
                         "native_path": str(native.relative_to(ROOT)) if native else None,
                         "native": read(native) if native else None})
        packet = {"case": case["id"], "trial": case["trial"], "requirement": Path(case["issue"]).read_text(),
                  "truth": truth[case["id"]], "prepared_counts": prepared["counts"], "claims": rows,
                  "evaluation_only": True, "not_model_input": True}
        write(RUN / "evaluation/packets" / (case["id"] + ".json"), packet)
    print(json.dumps({"packets": len(list((RUN / "evaluation/packets").glob("*.json")))}))


if __name__ == "__main__":
    build()
