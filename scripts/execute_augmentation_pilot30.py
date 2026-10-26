"""Execute frozen model test additions in original benchmark containers.

No model calls, expected-value repair, reference implementation, or hidden
verifier is involved. Standard framework reports prove actual collection.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from anchor_retrieval.syntax import Source, units
from augmentation.pipeline import parse_response
from combination_testing.runner import freeze_artifact, run_artifact
from generic_composition.runner import infer_harness, NODE_REPORTER
from scripts.execute_relational_gap_v7 import python_source_environment
from scripts.run_augmentation_pilot30 import RUN, read, write, receipt


def mocha_typescript_harness(targets, selector, *, node_test=False):
    """Use the subject's installed Mocha/esbuild; retain model source verbatim."""
    outputs = [f".augmentation-compiled/test-{i}.cjs" for i in range(len(targets))]
    build = "const esbuild = require('esbuild');\n" + "\n".join(
        "esbuild.buildSync(" + json.dumps({"entryPoints": [p], "outfile": o,
        "bundle": True, "platform": "node", "format": "cjs", "packages": "external"}) + ");"
        for p, o in zip(targets, outputs))
    reporter = """module.exports = class Reporter {
  constructor(runner) {
    const emit = (test, status, error) => process.stdout.write('CC_RESULT ' + JSON.stringify({id: test.fullTitle(), status, detail: error ? error.stack || String(error) : ''}) + '\\n');
    runner.on('pass', test => emit(test, 'pass'));
    runner.on('fail', (test, error) => emit(test, 'fail', error));
    runner.on('pending', test => emit(test, 'skip'));
  }
};
"""
    compile_command = "pnpm exec tsc -p tsconfig-cjs.json && pnpm exec tsc -p tsconfig.json && node .augmentation-build.cjs && "
    if node_test:
        command = compile_command + "node --test --test-isolation=none --test-reporter=./.augmentation-node-reporter.mjs --test-name-pattern=" + shlex.quote(selector) + " " + " ".join(map(shlex.quote, outputs))
    else:
        command = compile_command + "pnpm exec mocha --timeout 15000 --reporter ./.augmentation-reporter.cjs --grep " + shlex.quote(selector) + " " + " ".join(map(shlex.quote, outputs))
    return {"command": command, "report_format": "jsonl", "report_path": "stdout.txt",
            "files": {".augmentation-build.cjs": build, ".augmentation-reporter.cjs": reporter,
                      ".augmentation-node-reporter.mjs": NODE_REPORTER}}


def ava_harness(targets, names):
    arguments = ["--tap", *targets, *[arg for n in names for arg in ["--match", n]]]
    code = "const args = " + json.dumps(arguments) + ";\n" + """
const {spawnSync} = require('node:child_process');
const run = spawnSync('./node_modules/.bin/ava', args, {encoding:'utf8', maxBuffer:8*1024*1024});
const log = run.stdout || '';
process.stdout.write(log);
process.stderr.write(run.stderr || '');
for (const line of log.split('\\n')) {
  const m = /^(not ok|ok)\\s+\\d+\\s+-?\\s*(.*)$/.exec(line);
  if (!m) continue;
  const status = /#\\s*(SKIP|TODO)/i.test(m[2]) ? 'skip' : m[1] === 'ok' ? 'pass' : 'fail';
  process.stdout.write('CC_RESULT ' + JSON.stringify({id:m[2],status,detail:status==='fail'?log:''})+'\\n');
}
process.exit(run.status === null ? 2 : run.status);
"""
    return {"command": "node .augmentation-ava.cjs", "report_format": "jsonl", "report_path": "stdout.txt",
            "files": {".augmentation-ava.cjs": code}}


def execute_one(case, directory, phase="native"):
    output = directory / phase
    if (output / "summary.json").exists():
        return read(output / "summary.json")
    output.mkdir(parents=True, exist_ok=True)
    result = {"case": case["id"], "candidate": directory.name, "status": "not_executed"}
    try:
        prepared = read(RUN / "cases" / case["id"] / "prepared.json")
        row = parse_response((directory / "assessment.json").read_text(), prepared, directory.name)
        if row["decision"] != "gap":
            raise ValueError("not_a_generated_gap_test")
        repository = Path(case["repository"])
        files, names = {}, []
        for edit in row["tests"]:
            path = edit["path"]
            original = repository / path
            if not original.resolve().is_relative_to(repository):
                raise ValueError("test_path_escapes_repository")
            if edit["mode"] == "append":
                files[path] = original.read_text() + "\n\n" + edit["code"] + "\n"
            else:
                if original.exists():
                    raise ValueError("new_file_already_exists")
                files[path] = edit["code"] + "\n"
            added = Source(path, edit["code"], case["language"])
            names.extend(u.name for u in units(added)[0] if u.test)
        names = sorted(set(names))
        result["generated_test_names"] = names
        if not names:
            raise ValueError("no_named_test_found_in_generated_code")
        if case["language"] == "python":
            selector = " or ".join(names)
        else:
            selector = "(" + "|".join(re.escape(n) for n in names) + ")"
        environment_path = RUN / "environment" / case["id"] / "setup.json"
        environment = read(environment_path) if environment_path.exists() else {}
        if environment.get("harness") == "mocha_typescript":
            harness = mocha_typescript_harness(list(files), selector,
                node_test=any("node:test" in edit["code"] for edit in row["tests"]))
        elif environment.get("harness") == "ava":
            harness = ava_harness(list(files), names)
        else:
            harness = infer_harness(repository, case["language"], list(files), python="python", name_filter=selector)
        command = harness["command"]
        if environment.get("build_command"):
            command = environment["build_command"] + " && " + command
        if case["language"] == "python":
            command = python_source_environment(repository)["command"] + command
        if case["language"] == "go" and environment.get("go_build_tags"):
            command = command.replace("go test ", "go test -tags " + shlex.quote(environment["go_build_tags"]) + " ", 1)
        files.update(harness.get("files", {}))
        artifact = output / "artifact"
        if not artifact.exists():
            freeze_artifact(artifact, case["id"], files, command, harness["report_format"], harness["report_path"],
                            timeout=300, metadata={"generated_test_names": names, "model_assessment": receipt(directory / "assessment.json"),
                            "source_receipts": prepared["source_receipts"], "mode": "unmodified_model_test_additions"})
        runtime_case = dict(case)
        if environment_path.exists():
            if environment.get("status") == "ready" and environment.get("derived_image"):
                runtime_case["image"] = environment["derived_image"]
            result["environment_setup"] = receipt(environment_path)
        provenance = read(RUN / "cases" / case["id"] / "repository_provenance.json")
        runtime_case["base_commit"] = provenance["base_commit"]
        native_dir = output / "candidate"
        execution = read(native_dir / "result.json") if (native_dir / "result.json").exists() else run_artifact(
            artifact, "candidate", native_dir, registry=[runtime_case])
        result.update(status="executed", run_status=execution["status"], errors=execution.get("errors", []),
                      tests=execution.get("tests", []), process=execution.get("process", {}),
                      artifact=receipt(artifact / "manifest.json"))
    except Exception as exc:
        result.update(status="execution_setup_error", error_type=type(exc).__name__, error=str(exc))
    write(output / "summary.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--case", action="append")
    parser.add_argument("--candidate", action="append")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--phase", choices=("native", "native_environment", "native_environment_final"), default="native")
    args = parser.parse_args()
    cases = [c for c in read(RUN / "cases.json") if args.case is None or c["id"] in args.case]
    jobs = []
    for case in cases:
        for path in sorted((RUN / "cases" / case["id"] / "generation").glob("*/assessment.json")):
            if args.candidate and path.parent.name not in args.candidate:
                continue
            if read(path)["decision"] == "gap":
                jobs.append((case, path.parent))
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for future in as_completed([pool.submit(execute_one, case, directory, args.phase) for case, directory in jobs]):
            result = future.result()
            print(json.dumps({k: result[k] for k in ("case", "candidate", "status", "run_status", "error") if k in result}), flush=True)


if __name__ == "__main__":
    main()
