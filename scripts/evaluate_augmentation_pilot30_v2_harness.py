"""Evaluator-only run of frozen T28 tests using its declared workspace script.

The online harness missed Vitest because query-core declares it in test:lib
rather than in its local dependencies. Do not change tests or call a model.
"""
from pathlib import Path
import re
import shlex
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from scripts.run_augmentation_pilot30_v2 import RUN, read, receipt, runtime_case
from scripts.review_augmentation_pilot30_v2 import inventory, OUT
from anchor_retrieval.syntax import Source, units
from combination_testing.runner import freeze_artifact, run_artifact
from augmentation.pipeline import write_json


def main():
    case = next(c for c in read(RUN / "cases.json") if c["id"] == "T28")
    runtime, _ = runtime_case(case)
    repository = Path(case["repository"])
    package = repository / "packages/query-core/package.json"
    assert read(package)["scripts"]["test:lib"] == "vitest"
    for claim in inventory():
        if claim["case"] != "T28":
            continue
        directory = OUT / "harness_recovery" / "T28" / claim["candidate"]
        if (directory / "summary.json").exists():
            continue
        files, names = {}, []
        for edit in claim["tests"]:
            source = repository / edit["path"]
            files[edit["path"]] = (source.read_text() + "\n\n" if edit["mode"] == "append" else "") + edit["code"] + "\n"
            names.extend(u.name for u in units(Source(edit["path"], edit["code"], "typescript"))[0] if u.test)
        selector = "(" + "|".join(re.escape(n) for n in names) + ")"
        paths = [str(Path(path).relative_to("packages/query-core")) for path in files]
        command = "cd packages/query-core && pnpm exec vitest run " + " ".join(map(shlex.quote, paths)) + " -t " + shlex.quote(selector) + ' --reporter=json --outputFile="$COMBINATION_REPORT_DIR/vitest.json"'
        artifact = directory / "artifact"
        freeze_artifact(artifact, "T28", files, command, "vitest-json", "vitest.json", timeout=300,
                        metadata={"assessment": claim["assessment"], "generated_code_unchanged": True,
                                  "package_script": receipt(package), "evaluation_only": True})
        result = run_artifact(artifact, "candidate", directory / "candidate", registry=[runtime])
        summary = {"claim": claim["id"], "status": result["status"], "errors": result["errors"],
                   "tests": [t for t in result["tests"] if t["status"] != "skip"],
                   "result": receipt(directory / "candidate/result.json"),
                   "artifact": receipt(artifact / "manifest.json"),
                   "feedback_returned_to_model": False, "model_calls": 0}
        write_json(directory / "summary.json", summary)
        print(summary, flush=True)


if __name__ == "__main__":
    main()
