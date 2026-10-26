"""Run a twelve-task, four-setting, three-target validation evolution pilot."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/"src"), str(ROOT)]
from augmentation import validation_evolution as method
from augmentation.pipeline import write_json
from augmentation.provider import dispatch, MODEL

ORIGINAL = ROOT/"experiments/relation_distinction/results/pilot30_20261007_v1"
RUN = ROOT/"experiments/validation_evolution/results/pilot12_20261016_v1"
ARMS = ["A_final", "B_versions", "C_history", "D_probe"]
SEED = "validation-evolution-20261016"
REPEATS = [1, 2]
read = method.read


def select():
    cases = read(ORIGINAL/"cases.json")
    selected = {"T11", "T13", "T17", "T23", "T24", "T28"}
    for language, count in [("python", 4), ("go", 1), ("typescript", 1)]:
        available = [c for c in cases if c["language"] == language and c["id"] not in selected]
        available.sort(key=lambda c: hashlib.sha256((SEED+":"+c["id"]).encode()).hexdigest())
        selected.update(c["id"] for c in available[:count])
    result = [c for c in cases if c["id"] in selected]
    for c in result:
        c["base_commit"] = read(ORIGINAL/"cases"/c["id"]/"repository_provenance.json")["base_commit"]
    return result


def hashes():
    files = [Path(__file__), Path(method.__file__), ROOT/"src/augmentation/provider.py",
             ROOT/"src/augmentation/validation_context_pilot.py", ROOT/"src/augmentation/context_query_recovery.py",
             ROOT/"src/augmentation/trajectory_contrast.py", ROOT/"src/augmentation/program.py",
             ROOT/"src/augmentation/contrast_pilot.py", ROOT/"anchor_retrieval/syntax.py",
             ROOT/"combination_testing/runner.py", ROOT/"combination_testing/container_runner.py",
             ROOT/"combination_testing/test_reports.py", ROOT/"generic_composition/runner.py"]
    return {str(p.relative_to(ROOT)): method.previous.digest(p) for p in files}


def prepare():
    RUN.mkdir(parents=True, exist_ok=False)
    cases = select()
    write_json(RUN/"cases.json", cases)
    for case in cases:
        base, evolution, history, events = method.build_inputs(case)
        directory = RUN/"inputs"/case["id"]
        for name, data in [("base", base), ("evolution", evolution), ("history", history), ("events", events)]:
            write_json(directory/f"{name}.json", data)
        write_json(directory/"source_receipts.json", {p: method.previous.digest(Path(case["repository"])/p) for p in method.previous.file_index(case["repository"])})
        print(json.dumps({"prepared": case["id"], "final_tests": len(base["validation_tests"]),
                          "historical_tests": len(evolution["historical_tests"]), "transitions": len(evolution["transitions"]),
                          "edit_fragments": len(evolution["edit_fragments"]),
                          "base_chars": len(json.dumps(base)), "history_chars": len(json.dumps(evolution))+len(json.dumps(history))}), flush=True)
    write_json(RUN/"preparation.json", {"created_at": datetime.now(timezone.utc).isoformat(), "selection_seed": SEED,
                "cases": [c["id"] for c in cases], "code_sha256": hashes()})


def preflight_one(case):
    directory = RUN/"preflight"/case["id"]
    repo = Path(case["repository"])
    base = read(RUN/"inputs"/case["id"]/"base.json")
    paths = [p for p in base["source_file_index"] if method.is_test_path(p)]
    if case["language"] == "python":
        path = "tests/test_cc_evolution_preflight.py"
        code = "def test_CCPilotEnvironment():\n    assert 2 + 2 == 4\n"
    elif case["language"] == "go":
        p = min((p for p in paths if p.endswith("_test.go")), key=lambda x: (len(Path(x).parts), x))
        package = re.search(r"(?m)^package\s+(\w+)", (repo/p).read_text()).group(1)
        path = str(Path(p).parent/"cc_evolution_preflight_test.go")
        code = f'package {package}\nimport "testing"\nfunc TestCCPilotEnvironment(t *testing.T) {{ if 2+2!=4 {{ t.Fatal("unexpected") }} }}\n'
    else:
        p = min((p for p in paths if re.search(r"\.(test|spec)\.tsx?$", p)), key=lambda x: (len(Path(x).parts), x))
        suffix = ".unit.test.ts" if ".unit.test." in p else ".spec.ts" if ".spec." in p else ".test.ts"
        path = str(Path(p).parent/("cc-evolution-preflight"+suffix))
        h = method.previous.harness(case, [path])
        imports = "import { test, expect } from 'vitest'\n" if "vitest" in h["command"] else ""
        code = imports+"test('CCPilotEnvironment', () => { expect(2 + 2).toBe(4) })\n"
    response = {"tests": [{"path": path, "mode": "new", "code": code}]}
    if (directory/"feedback.json").exists() and read(directory/"input.json") != response:
        directory = directory/"filename_alignment"
    write_json(directory/"input.json", response)
    result = method.execute(case, response, directory, probe=True)
    print(json.dumps({"preflight": case["id"], "status": result["status"], "error": result.get("error")}), flush=True)
    return {"case": case["id"], "status": result["status"], "evidence": str(directory.relative_to(RUN))}


def preflight(workers):
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(preflight_one, read(RUN/"cases.json")))
    write_json(RUN/"preflight_summary.json", results)


def transport_preflight():
    directory = RUN/"transport_preflight"
    directory.mkdir(parents=True, exist_ok=True)
    inputs = [
        {"id": "schema-inspect", "system": method.COMMON+method.INVESTIGATE,
         "prompt": json.dumps({"public_evidence": {"public_requirement": "Synthetic fixture only: return the sum of two integers.", "source": [{"path": "calc.py", "line": 1, "code": "def add(a, b): return a+b"}], "validation_tests": [{"id": "tests/test_calc.py:1:test_add", "code": "def test_add(): assert add(1, 2) == 3"}]}}), "max_tokens": 32768, "reasoning_effort": "medium"},
        {"id": "schema-build", "system": method.COMMON+method.BUILD,
         "prompt": json.dumps({"public_evidence": {"public_requirement": "Synthetic fixture only: return the sum of two integers.", "source": [{"path": "calc.py", "line": 1, "code": "def add(a, b): return a+b"}], "validation_tests": []}, "instruction": "No concrete defect has been established. Report the justified status."}), "max_tokens": 32768, "reasoning_effort": "medium"},
        {"id": "schema-code", "system": method.COMMON+method.BUILD,
         "prompt": json.dumps({"public_evidence": {"public_requirement": "Synthetic Python fixture: total(xs, scale) sums all integer elements then multiplies by integer scale. join(xs, ys) concatenates the integer lists, preserving order and duplicates.",
                   "source": [{"path": "calc.py", "line": 1, "code": "def total(xs, scale=1): return sum(x for x in xs if x > 0)*scale\ndef join(xs, ys): return sorted(set(xs+ys))"}],
                   "validation_tests": [{"id": "test_calc.py:1:test_old", "code": "def test_old():\n    assert total([1,2], 1)==3\n    assert join([1], [2])==[1,2]"}], "test_environment": "pytest; new test file per target"},
                   "ranked_hypotheses_and_probes": {"hypotheses": [{"id": "h1", "alternate_context": "mixed-sign integers and non-unit scaling"}, {"id": "h2", "alternate_context": "duplicates across lists with descending order"}]},
                   "diagnostic_observations": "withheld"}), "max_tokens": 32768, "reasoning_effort": "medium"},
    ]
    records = []
    for i, req in enumerate(inputs):
        out = directory/f"call{i+1}"
        if (out/"request.json").exists():
            old = read(out/"request.json")
            if old["messages"] != [{"role": "system", "content": req["system"]}, {"role": "user", "content": req["prompt"]}]:
                out = out/("prompt_revision_"+method.hid([req["system"], req["prompt"]]))
        manifest = read(out/"manifest.json") if (out/"manifest.json").exists() else dispatch(req, out, root=ROOT, model=MODEL)
        if manifest["status"] != "complete":
            raise RuntimeError("transport_preflight_incomplete")
        method.validate(read(out/"completion.txt"), 1 if i == 0 else 3)
        records.append({"stage": i+1, "status": "parsed", "path": str(out.relative_to(RUN)), "usage": manifest.get("usage"), "response_model": manifest.get("response_model")})
    write_json(directory/"summary.json", records)
    print(json.dumps({"transport_preflight": records}), flush=True)


def freeze():
    if (RUN/"protocol.json").exists():
        raise RuntimeError("already_frozen")
    preparation = read(RUN/"preparation.json")
    preflight = read(RUN/"preflight_summary.json")
    if len(preflight) != 12 or len(read(RUN/"transport_preflight/summary.json")) != 3:
        raise RuntimeError("preflight_incomplete")
    write_json(RUN/"protocol.json", {
        "created_at": datetime.now(timezone.utc).isoformat(), "model": MODEL, "cases": preparation["cases"],
        "selection": "Previous six cases plus SHA256(seed:case_id) first four Python/one Go/one TypeScript from the remaining original 30; no outcome-based replacement.",
        "selection_seed": SEED, "development_cases": True, "repeats": REPEATS, "arms": ARMS,
        "research_question": "Do recovered validation changes guide selection of legal contexts that reveal repair-relevant behavioral distinctions, and do executable observations improve those decisions?",
        "A_final": "Current issue/patch source/current test bodies only. Original-source queries and AST local slices.",
        "B_versions": "A plus recovered historical test bodies, same-name version differences, and literal test edit fragments. No notes or execution events.",
        "C_history": "B plus automatically indexed original reasoning, source-edit and execution events.",
        "D_probe": "Shares exactly C investigation, queries, ranked hypotheses and diagnostic probe code. Receives original-patch probe executions before generating final tests; C performs self-review without these outputs.",
        "stages": ["Propose up to three ranked hypotheses and six read-only queries.",
                   "Refine targets and propose one diagnostic observation file per target.",
                   "After diagnostic feedback or self-review, generate up to three independent augmentations.",
                   "One revision after original-patch test execution; final execution follows."],
        "planned_final_outputs": 96, "unique_planned_model_calls": 336,
        "target_cap": 3, "named_tests_per_target_cap": 2, "file_per_target_cap": 1,
        "max_tokens_per_call": 32768, "reasoning_effort": "medium", "thinking": "enabled", "temperature": 0,
        "technical_recovery": "One identical-input retry after terminal incomplete/invalid output. No evaluator input or manual semantic edit. Never resend ambiguous inflight calls.",
        "transport_normalization": "For exactly one target, misplaced top-level tests are assigned to it verbatim. Missing tests on a non-gap decision become an empty list. No expectation or code changes.",
        "budget_comparison": "Four logical model calls per setting. C/D share first two physically. D adds up to three diagnostic executions; other settings see identical probe code but no outcomes. Report runtime and tokens separately.",
        "test_budget_analysis": "Report rank-one and up-to-three target yield on the same frozen ranked output. This is a descriptive prefix analysis, not an independently randomized one-target algorithm.",
        "metrics": "Correct repair-relevant detection and generated tests, explicit false claims, gold-ineligible claims, fixed-reference misses, unknowns. Task and target units reported separately; mixed outputs retained.",
        "evaluation_boundary": "No gold, benchmark failure tests, annotations or previous pilot outputs are read by generation. Gold used only offline. Source/trajectory/test semantic review by Codex is not independent human annotation. Original-only/private API cases are static-only for reference compatibility.",
        "success_limit": "Original-fail/gold-pass with independent requirement basis is not measured patch repair or resolution-rate improvement.",
        "program_limits": "Literal test recovery and named AST alignment are incomplete. Local slices are text dependencies, not alias/path proofs. Runtime probes establish only executed observations, not correctness.",
        "preflight": preflight,
        "code_sha256": hashes(),
        "input_sha256": {str(p.relative_to(RUN)): method.previous.digest(p) for p in sorted((RUN/"inputs").glob("*/*.json"))}
    })
    print(json.dumps({"frozen": str(RUN), "cases": preparation["cases"], "outcomes": 96, "calls": 336}), flush=True)


def check():
    protocol = read(RUN/"protocol.json")
    if protocol["code_sha256"] != hashes():
        raise RuntimeError("frozen_code_changed")
    for path, digest in protocol["input_sha256"].items():
        if method.previous.digest(RUN/path) != digest:
            raise RuntimeError("frozen_input_changed:"+path)
    return protocol


def model_call(directory, system, material, stage):
    directory = Path(directory)
    if (directory/"parsed.json").exists():
        return read(directory/"parsed.json")
    request = {"id": str(directory.relative_to(RUN)), "system": method.COMMON+system,
               "prompt": json.dumps(material, ensure_ascii=False), "max_tokens": 32768, "reasoning_effort": "medium"}
    for attempt in range(2):
        out = directory/("primary" if attempt == 0 else "technical_recovery")
        if (out/"manifest.json").exists():
            manifest = read(out/"manifest.json")
            if manifest["status"] in {"prepared", "dispatching"}:
                raise RuntimeError("ambiguous_inflight:"+str(out))
        else:
            manifest = dispatch(request, out, root=ROOT, model=MODEL)
        try:
            if manifest["status"] != "complete":
                raise ValueError("provider_incomplete")
            result = method.validate(read(out/"completion.txt"), stage)
            if stage >= 3:
                prior = material.get("draft", {}).get("targets") if stage == 4 else material.get("ranked_hypotheses_and_probes", {}).get("hypotheses")
                allowed = [r["id"] for r in prior or []]
                returned = [r["id"] for r in result["targets"]]
                if any(i not in allowed for i in returned) or returned != [i for i in allowed if i in returned]:
                    raise ValueError("target_ids_or_ranking_changed")
            write_json(directory/"parsed.json", result)
            print(json.dumps({"stage": request["id"], "attempt": attempt+1, "tokens": (manifest.get("usage") or {}).get("total_tokens")}), flush=True)
            return result
        except (ValueError, TypeError, KeyError, OSError) as exc:
            write_json(directory/f"parse_error_{attempt}.json", {"error_type": type(exc).__name__, "error": str(exc)[:400]})
    result = {"hypotheses" if stage < 3 else "targets": [], "queries": [], "technical_unknown": True}
    write_json(directory/"parsed.json", result)
    return result


def execute_targets(case, response, directory):
    return {row["id"]: method.execute(case, row, Path(directory)/row["id"]) for row in response.get("targets", [])}


def run_one(case, arm, repeat):
    cid = case["id"]
    directory = RUN/"runs"/cid/arm/f"repeat{repeat}"
    final_arms = [arm, "D_probe"] if arm == "C_history" else [arm]
    if all((RUN/"runs"/cid/a/f"repeat{repeat}/result.json").exists() for a in final_arms):
        return
    base = read(RUN/"inputs"/cid/"base.json")
    evolution = read(RUN/"inputs"/cid/"evolution.json")
    public = dict(base)
    if arm != "A_final":
        public["validation_evolution"] = evolution
    if arm == "C_history":
        public["development_history"] = read(RUN/"inputs"/cid/"history.json")
    first = model_call(directory/"stage1", method.INVESTIGATE, {"public_evidence": public}, 1)
    queries_path = directory/"retrieved.json"
    if queries_path.exists():
        answers = read(queries_path)
    else:
        answers = method.serve_queries(case, base, evolution, read(RUN/"inputs"/cid/"events.json"), first.get("queries", []), arm)
        write_json(queries_path, answers)
    material = {"public_evidence": public, "investigation": first, "retrieved_evidence": answers}
    second = model_call(directory/"stage2", method.PROBE, material, 2)
    shared = {**material, "ranked_hypotheses_and_probes": second}
    observations = None
    if arm == "C_history":
        observations = {h["id"]: method.execute(case, h.get("probe", {}), directory/"probe_execution"/h["id"], probe=True)
                        for h in second.get("hypotheses", [])}
    for final_arm in final_arms:
        out = RUN/"runs"/cid/final_arm/f"repeat{repeat}"
        if (out/"result.json").exists():
            continue
        supplied = {**shared, "diagnostic_observations": observations if final_arm == "D_probe" else "Withheld. Review the probe code and original evidence without assuming execution."}
        draft = model_call(out/"stage3", method.BUILD, supplied, 3)
        feedback = execute_targets(case, draft, out/"draft_execution")
        final = model_call(out/"stage4", method.BUILD+method.REVISE, {**supplied, "draft": draft, "original_patch_execution": feedback}, 4)
        final_feedback = execute_targets(case, final, out/"final_execution")
        result = {"case": cid, "arm": final_arm, "repeat": repeat, "final": final,
                  "execution_status": {key: v["status"] for key, v in final_feedback.items()},
                  "technical_unknown": bool(final.get("technical_unknown")),
                  "shared_prefix": str(directory.relative_to(RUN)) if final_arm == "D_probe" else None}
        write_json(out/"result.json", result)
        print(json.dumps({"finished": f"{cid}/{final_arm}/{repeat}", "decisions": [x["decision"] for x in final.get("targets", [])], "execution": result["execution_status"]}), flush=True)


def status():
    logs = [read(p) for p in RUN.glob("runs/**/manifest.json") if "model" in read(p)]
    print(json.dumps({"finished": len(list(RUN.glob("runs/*/*/*/result.json"))), "planned": 96,
                      "calls": sum(r.get("external_model_calls", 0) for r in logs), "inflight": sum(r["status"] == "dispatching" for r in logs),
                      "tokens": sum((r.get("usage") or {}).get("total_tokens", 0) for r in logs),
                      "response_models": sorted({str(r.get("response_model")) for r in logs if r.get("response_model")})}), flush=True)


def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument("action", choices=["prepare", "preflight", "transport", "freeze", "run", "status"])
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--case", action="append")
    p.add_argument("--arm", action="append", choices=ARMS[:3])
    p.add_argument("--repeat", type=int, action="append", choices=REPEATS)
    a = p.parse_args()
    if a.action == "prepare": prepare(); return
    if a.action == "preflight": preflight(a.workers); return
    if a.action == "transport": transport_preflight(); return
    if a.action == "freeze": freeze(); return
    check()
    if a.action == "status": status(); return
    cases = [c for c in read(RUN/"cases.json") if not a.case or c["id"] in a.case]
    jobs = [(c, arm, repeat) for repeat in a.repeat or REPEATS for c in cases for arm in a.arm or ARMS[:3]]
    failures = []
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures = {pool.submit(run_one, *job): (job[0]["id"], *job[1:]) for job in jobs}
        for future in as_completed(futures):
            try: future.result()
            except Exception as exc:
                failures.append(futures[future]); print(json.dumps({"failed": futures[future], "error_type": type(exc).__name__, "message": str(exc)[:200]}), flush=True)
    status()
    if failures: raise SystemExit(1)


if __name__ == "__main__":
    main()
