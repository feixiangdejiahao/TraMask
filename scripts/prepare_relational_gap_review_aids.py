"""Read-only projection of frozen emitted candidates for independent review."""
import argparse
import hashlib
import json
from pathlib import Path


FIELDS = ("id", "execution_lane", "static_parent_id", "kind", "base_test_id",
          "source_test_ids", "edits", "oracle", "semantic_model_judgment")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--emitted-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-ablation", action="store_true")
    args = parser.parse_args()
    fields = FIELDS + (("ablation", "ablation_parent_id") if args.include_ablation else ())
    args.output.mkdir(parents=True, exist_ok=True)
    written = []
    for source in sorted(args.emitted_root.glob("*/accepted.json")):
        candidates = json.loads(source.read_text())
        rows = [{key: candidate.get(key) for key in fields} for candidate in candidates]
        target = args.output / (source.parent.name + ".json")
        encoded = json.dumps(rows, indent=2) + "\n"
        if target.exists():
            if target.read_text() != encoded:
                raise RuntimeError("frozen_review_aid_mismatch:" + str(target))
            continue
        target.write_text(encoded)
        manifest = {"source": str(source.resolve()), "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "candidate_count": len(rows), "projection_fields": fields}
        (args.output / (source.parent.name + ".manifest.json")).write_text(json.dumps(manifest, indent=2) + "\n")
        written.append(source.parent.name)
    print(json.dumps({"written": written}))


if __name__ == "__main__":
    main()
