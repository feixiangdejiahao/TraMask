"""Run all automatic candidates, with immutable per-request provider records."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from augmentation.pipeline import build_request, parse_response
from augmentation.provider import dispatch
from scripts.run_augmentation_pilot30 import RUN, read, receipt, write


def run_one(job, prepared):
    directory = RUN / "cases" / job["case"] / "generation" / job["candidate"]
    result_path = directory / "result.json"
    if result_path.exists():
        return read(result_path)
    request = build_request(prepared, job["candidate"])
    request.update(max_tokens=32768, reasoning_effort="high")
    manifest_path = directory / "manifest.json"
    if manifest_path.exists():
        manifest = read(manifest_path)
        if manifest["status"] in {"prepared", "dispatching"}:
            raise RuntimeError("unfinished_previous_dispatch:" + str(directory))
    else:
        manifest = dispatch(request, directory, root=ROOT)
    result = {**job, "provider_status": manifest["status"],
              "external_model_calls": manifest["external_model_calls"],
              "response_model": manifest.get("response_model"), "usage": manifest.get("usage"),
              "status": "provider_error"}
    if manifest["status"] == "complete":
        content = (directory / "completion.txt").read_text()
        try:
            raw = json.loads(content)
            if isinstance(raw, dict):
                result["raw_decision"] = raw.get("decision")
                result["raw_reason"] = raw.get("reason")
                result["raw_distinction"] = raw.get("distinction")
            assessment = parse_response(content, prepared, job["candidate"])
            write(directory / "assessment.json", assessment)
            result.update(status="decoded", decision=assessment["decision"], tests=len(assessment["tests"]))
        except (ValueError, TypeError, KeyError) as exc:
            result.update(status="invalid_response", error=str(exc))
    write(result_path, result)
    return result


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--case", action="append")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int, help="Only for a first transport check; remaining candidates stay pending")
    args = parser.parse_args()
    cases = [c for c in read(RUN / "cases.json") if args.case is None or c["id"] in args.case]
    jobs, prepared = [], {}
    for case in cases:
        directory = RUN / "cases" / case["id"]
        path = directory / "prepared.json"
        if not path.exists():
            continue
        prepared[case["id"]] = read(path)
        plan = {"case": case["id"], "prepared": receipt(path), "model": "deepseek-v4-flash",
                "created_at": datetime.now(timezone.utc).isoformat(), "temperature": 0,
                "thinking": "enabled", "reasoning_effort": "high", "max_output_tokens": 32768,
                "source": [receipt(p) for p in sorted((ROOT / "src/augmentation").glob("*.py"))],
                "selection": "All automatic candidates, including existing-test execution reviews; no manual target matching or top-k cap.",
                "candidate_ids": [c["id"] for c in prepared[case["id"]]["candidates"]]}
        plan_path = directory / "generation_plan.json"
        if plan_path.exists():
            previous = read(plan_path)
            if previous["prepared"] != plan["prepared"]:
                raise ValueError("prepared_input_changed_after_generation_plan")
        else:
            write(plan_path, plan)
        jobs.extend({"case": case["id"], "candidate": c["id"], "family": c["family"]} for c in prepared[case["id"]]["candidates"])
    if args.limit is not None:
        jobs = jobs[:args.limit]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for future in as_completed([pool.submit(run_one, job, prepared[job["case"]]) for job in jobs]):
            result = future.result()
            print(json.dumps({k: result[k] for k in ("case", "candidate", "status", "decision", "raw_decision", "tests", "response_model") if k in result}), flush=True)


if __name__ == "__main__":
    main()
