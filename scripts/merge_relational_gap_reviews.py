"""Merge independent review annotations without changing frozen candidates/runs."""
import argparse
import hashlib
import json
from pathlib import Path


DIMENSIONS = {"scenario_hit", "correct_oracle", "target_failure_match"}


def merge(inventory, annotations):
    entries = {(row["case"], row["candidate_id"]): row for row in inventory["candidates"]}
    seen = set()
    for source, document in annotations:
        for case in document["cases"]:
            for annotation in case["candidate_reviews"]:
                key = case["case"], annotation["candidate_id"]
                if key not in entries or key in seen:
                    raise ValueError("Unknown or multiply reviewed candidate: " + str(key))
                fields = annotation["review"]
                if not set(fields) <= DIMENSIONS:
                    raise ValueError("Unknown semantic dimension")
                for field in fields.values():
                    verdict = field.get("verdict")
                    if verdict not in {"yes", "no", "unknown"}:
                        raise ValueError("Invalid verdict")
                    if verdict != "unknown" and (not field.get("reason") or not field.get("evidence")):
                        raise ValueError("Independent verdict needs reason and evidence")
                    for item in field.get("evidence", []):
                        if hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest() != item["sha256"]:
                            raise ValueError("Review evidence changed: " + item["path"])
                entries[key]["review"].update(fields)
                seen.add(key)
    inventory["independent_review_sources"] = [
        {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path, _ in annotations]
    return inventory, len(seen)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inventory = json.loads(args.inventory.read_text())
    annotations = [(path, json.loads(path.read_text())) for path in args.annotations]
    result, count = merge(inventory, annotations)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"reviewed_candidates": count, "total_candidates": len(result["candidates"])}))


if __name__ == "__main__":
    main()
