"""Prepare existing subjects with v2; record extraction evidence without LLM calls.

The manifest supplies only repository, original patch, public issue and public
trajectory paths. Reference patches and expected targets are not read. Counts
are extraction counts, never detection or bug-revealing-test success rates.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
from augmentation.pipeline import prepare, build_request, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--case", action="append")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-regions", type=int, default=80)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    cases = json.loads(args.cases.read_text())
    selected = [c for c in cases if not args.case or c["id"] in args.case]
    summary = {"version":"augmentation-v2-extraction-verification.v1", "external_model_calls":0,
               "subject_test_runs":0, "reference_information_used_by_algorithm":False,
               "meaning":"Extraction and serialization checks only; not combination-gap detection or test-generation evaluation.", "cases":[]}
    summary["implementation_sha256"] = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                          for p in sorted((ROOT / "src/augmentation").glob("*.py"))}
    for case in selected:
        started = time.monotonic()
        print(json.dumps({"case":case["id"],"status":"preparing"}), flush=True)
        output = args.output / case["id"]
        output.mkdir()
        result = prepare(case["repository"], Path(case["candidate_patch"]).read_text(), Path(case["issue"]).read_text(),
                         json.loads(Path(case["trajectory"]).read_text()), max_regions=args.max_regions)
        write_json(output / "prepared.json", result)
        candidates = result["candidates"]
        examples = []
        seen = set()
        for candidate in candidates:
            if candidate["family"] in seen:
                continue
            seen.add(candidate["family"])
            request = build_request(result, candidate["id"])
            write_json(output / (candidate["family"] + ".request.json"), request)
            examples.append({"family":candidate["family"],"candidate_id":candidate["id"],
                             "request_utf8_bytes":len(request["prompt"].encode()),
                             "condition_dimensions":candidate.get("behavior",{}).get("condition_dimensions"),
                             "related_tests":len(candidate["test_ids"])})
        receipt = {"case":case["id"],"seconds":time.monotonic()-started,"counts":result["counts"],
                   "families":dict(Counter(c["family"] for c in candidates)),"examples":examples,
                   "search":result["analysis"]["joint_search"],
                   "inputs":[{"path":case[key],"sha256":hashlib.sha256(Path(case[key]).read_bytes()).hexdigest()}
                             for key in ("candidate_patch","issue","trajectory")]}
        write_json(output / "verification.json", receipt)
        summary["cases"].append(receipt)
        write_json(args.output / "summary.json", summary)
        print(json.dumps({"case":case["id"],"status":"complete","seconds":round(receipt["seconds"],2),"families":receipt["families"]}),flush=True)


if __name__ == "__main__":
    main()
