"""Offline evaluation of deterministic candidate-validity analyses.

Only recorded candidate/source/runtime artifacts are read. Review labels and
known positive witnesses are joined AFTER source-only analyzer calls; they are
never analyzer inputs. No repository execution, provider calls, or hidden tests.
An unknown result remains unknown, even when a known witness is retained.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
for _directory in (ROOT, ROOT / "scripts"):
    if str(_directory) not in sys.path:
        sys.path.insert(0, str(_directory))

from audit_requested_source_controls import inspect_controls, native
from evaluate_relational_gap import matches_runtime

VERSION = "source-controlled-validity-evaluation-v1"
CAMPAIGN = ROOT / "results/relation_search_20260929_v3/uniform_fresh_impact_v3"
EVALUATION = ROOT / "results/relation_search_20260929_v3/evaluation"
STATUSES = {"invalid", "review", "unknown"}


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def frozen(path):
    return {"path": str(Path(path).resolve()), "sha256": digest(path)}


def loaded_local_sources():
    """Seal imported repository helpers as well as analyzer entry points."""
    result = {}
    for name, module in tuple(sys.modules.items()):
        value = getattr(module, "__file__", None)
        if not value:
            continue
        path = Path(value).resolve()
        if path.suffix == ".py" and path.is_relative_to(ROOT) and path.is_file():
            result[name] = frozen(path)
    return result


def verify_seal(records):
    for record in records.values():
        if digest(record["path"]) != record["sha256"]:
            raise ValueError("Analyzer or imported source changed during evaluation: " + record["path"])


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def named_failure(rows):
    """Match the preregistered SHA2-v1 sample's native eligibility exactly."""
    evidence = []
    for row in rows:
        tests, errors, _ = native(row["result"])
        names = row["test_ids"]
        chosen = [test for test in tests if any(matches_runtime(test["id"], name) for name in names)]
        if errors or not names or any(not any(matches_runtime(test["id"], name) for test in chosen) for name in names):
            return None
        if any(test["status"] not in {"pass", "fail"} for test in chosen):
            return None
        evidence.append({"result": frozen(row["result"]), "manifest": frozen(row["manifest"]),
                         "test_ids": names, "tests": chosen})
    return evidence if any(test["status"] == "fail" for item in evidence for test in item["tests"]) else None


def occurrence_key(case, round_number, candidate_id):
    return f"{case}:{round_number}:{candidate_id}"


def heldout_sample(records, excluded, per_case=2):
    """Freeze unseen failure CANDIDATES within already seen tasks, before analysis."""
    grouped = defaultdict(dict)
    for row in sorted(records, key=lambda row: (row["case"], row["round"], row["candidate_id"])):
        identity = (row["case"], row["candidate_id"])
        if identity not in excluded:
            grouped[row["case"]].setdefault(row["candidate_id"], row)
    selected = []
    for case, candidates in sorted(grouped.items()):
        ordered = sorted(candidates.values(), key=lambda row: hashlib.sha256(
            ("validity-candidate-holdout-v1\0" + case + "\0" + row["candidate_id"]).encode()).hexdigest())
        selected.extend(row["key"] for row in ordered[:per_case])
    return {"selection": "first two distinct candidate IDs per case by fixed salted SHA256; first chronological occurrence",
            "per_case": per_case, "selected_keys": selected,
            "scope": "candidate holdout inside 17 seen development trials; not unseen tasks",
            "excluded": "34 previously reviewed candidates and 16 independently verified positive witnesses",
            "no_validity_prediction_or_failure_message_used": True}


def inventory(campaign=CAMPAIGN, evaluation=EVALUATION, per_case=2):
    campaign, evaluation = Path(campaign), Path(evaluation)
    checkpoint_path = evaluation / "uniform_fresh_impact_v3/checkpoint_14.json"
    checkpoint = read(checkpoint_path)
    known = {(row["case"], cid) for row in checkpoint["cases"]
             for cid in row.get("fixed_configuration_automatic_ids", []) if row.get("fixed_configuration_correct")}
    failures, rounds, all_occurrences = [], [], {}
    for runs_path in sorted(campaign.glob("*/round_*/executed/runs.json")):
        round_dir = runs_path.parents[1]
        case, round_number = round_dir.parent.name, int(round_dir.name.split("_")[1])
        runs = read(runs_path)
        candidates_path = round_dir / "emitted/accepted.json"
        candidates = {row["id"]: row for row in read(candidates_path)}
        inputs = {name: frozen(round_dir / "prepared" / (name + ".json")) for name in ("corpus", "frontend")}
        inputs.update(candidates=frozen(candidates_path), runs=frozen(runs_path))
        grouped = defaultdict(list)
        for row in runs:
            if row["role"] == "generated":
                grouped[row["candidate_id"]].append(row)
        eligible = []
        for cid, rows in sorted(grouped.items()):
            if cid not in candidates:
                raise ValueError(f"Executed candidate absent from accepted source: {case}/{round_number}/{cid}")
            key = occurrence_key(case, round_number, cid)
            base = {"key": key, "case": case, "round": round_number, "candidate_id": cid,
                    "base_test_id": candidates[cid]["base_test_id"], "inputs": inputs}
            all_occurrences[key] = base
            native_evidence = named_failure(rows)
            if native_evidence is None:
                continue
            controls = inspect_controls(rows, runs)
            if controls["status"] != "all_source_controls_passed":
                continue
            eligible.append(cid)
            failures.append({**base, "native_evidence": native_evidence, "controls": controls["controls"]})
        rounds.append({"case": case, "round": round_number, "generated_candidates": len(grouped),
                       "eligible_controlled_failures": len(eligible), "inputs": inputs})
    positives = [{"case": case, "candidate_id": cid, "classification": "valid_complete_issue_witness",
                  "occurrence_keys": [key for key, row in all_occurrences.items() if (row["case"], row["candidate_id"]) == (case, cid)]}
                 for case, cid in sorted(known)]
    reviews, review_files = [], []
    for path in sorted((evaluation / "controlled_failure_sample").glob("*/semantic_review.json")):
        document = read(path)
        review_files.append(frozen(path))
        for row in document["reviews"]:
            item = {"case": document["case"], "candidate_id": row["candidate_id"],
                    "classification": row["classification"], "reason": row["reason"],
                    "initial_failure_classification": "not_separately_adjudicated",
                    "occurrence_keys": [key for key, value in all_occurrences.items()
                                        if (value["case"], value["candidate_id"]) == (document["case"], row["candidate_id"])]}
            # Exact IDs are evaluation annotations, never consulted by analyzers.
            # The original review confirms N08's genuine early failure, but
            # says N04's first failure only MAY expose the true defect. Preserve
            # that difference while rejecting their complete later oracles.
            if (document["case"], row["candidate_id"]) == ("N08", "1a68fd75119e1a528770"):
                item["initial_failure_classification"] = "mixed_valid_early_signal_invalid_complete_oracle"
            if (document["case"], row["candidate_id"]) == ("N04", "oracle_eaf2e6d8f2cbd28ee81dd7f6"):
                item["initial_failure_classification"] = "potential_valid_early_signal_invalid_complete_oracle"
            if row["classification"] == "valid_issue_related_defect":
                item["initial_failure_classification"] = "valid_issue_related_defect"
            reviews.append(item)
    excluded = known | {(row["case"], row["candidate_id"]) for row in reviews}
    result = {"version": VERSION, "created_utc": datetime.now(timezone.utc).isoformat(),
              "campaign": str(campaign.resolve()), "configuration": frozen(campaign / "configuration.json"),
              "positive_checkpoint": frozen(checkpoint_path), "review_files": review_files,
              "population_definition": "all named native failing candidate occurrences with all associated original controls passed, both frozen rounds",
              "counts": {"trials": len({row["case"] for row in rounds}), "rounds": len(rounds),
                         "generated_occurrences": sum(row["generated_candidates"] for row in rounds),
                         "controlled_failure_occurrences": len(failures),
                         "distinct_case_candidate_failures": len({(row["case"], row["candidate_id"]) for row in failures}),
                         "positive_witnesses": len(positives), "reviewed_candidates": len(reviews),
                         "review_classifications": dict(Counter(row["classification"] for row in reviews))},
              "rounds": rounds, "controlled_failures": failures, "positive_witnesses": positives,
              "development_reviews": reviews, "additional_candidate_holdout": heldout_sample(failures, excluded, per_case),
              "accounting": {"strict_false_positive_total": None,
                             "complete_invalid_is_not_necessarily_false_initial_bug_signal": True,
                             "provider_calls": 0, "subject_executions": 0,
                             "positive_oracle_candidates_are_frozen_baseline_not_new_cold_start": True}}
    failure_keys = {row["key"] for row in failures}
    for row in positives:
        if not row["occurrence_keys"] or not any(key in failure_keys for key in row["occurrence_keys"]):
            raise ValueError(f"Positive witness has no independently controlled failing occurrence: {row}")
    return result


def combine(results):
    if any(row.get("status") not in STATUSES for row in results):
        raise ValueError("Analyzer status must be invalid, review, or unknown; absence of errors is not validity")
    return "invalid" if any(row["status"] == "invalid" for row in results) else "review" if any(
        row["status"] == "review" for row in results) else "unknown"


def summarize(baseline, predictions, heldout_reviews=None):
    by_key = {row["key"]: row for row in predictions}
    def decision(keys):
        # A witness is retained if at least one occurrence was analyzed without
        # deterministic rejection. An absent analysis is never counted retained.
        observed = [by_key[key] for key in keys if key in by_key]
        return "not_analyzed" if not observed else "rejected" if all(row["status"] == "invalid" for row in observed) else "retained_unknown_or_review"
    positives = [{**row, "screening": decision(row["occurrence_keys"])} for row in baseline["positive_witnesses"]]
    reviewed = [{**row, "screening": decision(row["occurrence_keys"])} for row in baseline["development_reviews"]]
    strata = defaultdict(Counter)
    for row in reviewed:
        strata[row["classification"]][row["screening"]] += 1
    report = {"prediction_status_counts": dict(Counter(row["status"] for row in predictions)),
            "finding_code_counts": dict(Counter(finding.get("code", "unspecified") for row in predictions
                for analysis in row["analyses"].values() for finding in analysis.get("findings", []))),
            "independent_positive_retention": dict(Counter(row["screening"] for row in positives)),
            "development_review_filtering": {key: dict(counts) for key, counts in strata.items()},
            "positive_details": positives, "review_details": reviewed,
            "strict_false_positive_total": None,
            "interpretation": "rejection is a deterministic contradiction claim; retaining unknown/review is not semantic validation; sample filtering is not full-population precision"}
    if heldout_reviews is not None:
        expected = set(baseline["additional_candidate_holdout"]["selected_keys"])
        reviewed_keys = [row["key"] for row in heldout_reviews["reviews"]]
        if len(set(reviewed_keys)) != len(reviewed_keys) or set(reviewed_keys) != expected:
            raise ValueError("Heldout reviews must label exactly the previously frozen candidate selection")
        rows = [{**row, "screening": decision([row["key"]])} for row in heldout_reviews["reviews"]]
        complete, initial = defaultdict(Counter), defaultdict(Counter)
        for row in rows:
            complete[row["classification"]][row["screening"]] += 1
            initial[row["initial_failure_classification"]][row["screening"]] += 1
        report["heldout_complete_test_filtering"] = {label: dict(counts) for label, counts in complete.items()}
        report["heldout_initial_alarm_filtering"] = {label: dict(counts) for label, counts in initial.items()}
        report["heldout_review_details"] = rows
        report["heldout_scope"] = baseline["additional_candidate_holdout"]["scope"]
        report["heldout_truth_protocol"] = heldout_reviews["review_protocol"]
    return report


def selected_records(baseline, scope="all"):
    if scope == "all":
        return baseline["controlled_failures"]
    groups = {"positive": "positive_witnesses", "development": "development_reviews"}
    if scope == "audited":
        keys = {key for group in groups.values() for row in baseline[group] for key in row["occurrence_keys"]}
        keys.update(baseline["additional_candidate_holdout"]["selected_keys"])
    elif scope == "holdout":
        keys = set(baseline["additional_candidate_holdout"]["selected_keys"])
    elif scope in groups:
        keys = {key for row in baseline[groups[scope]] for key in row["occurrence_keys"]}
    else:
        raise ValueError("Unknown evaluation scope: " + scope)
    return [row for row in baseline["controlled_failures"] if row["key"] in keys]


def summarize_admission(baseline, completed, prepared, heldout_reviews=None):
    """Join independent truth to already completed model decisions, offline."""
    frozen_keys = {row["key"] for row in selected_records(baseline, prepared["scope"])}
    prepared_keys = [row["key"] for row in prepared["items"]]
    decisions = completed["decisions"]
    keys = [row["key"] for row in decisions]
    if (len(set(prepared_keys)) != len(prepared_keys) or set(prepared_keys) - frozen_keys
            or len(set(keys)) != len(keys) or set(keys) != set(prepared_keys)):
        raise ValueError("Admission decisions must match the frozen prepared evaluation candidates")
    by_key, status_counts = {}, Counter()
    for row in decisions:
        decision = row["decision"]
        status = decision["status"]
        status_counts[status] += 1
        if decision.get("alarm_eligible"):
            if status != "semantic_supported":
                raise ValueError("Only a semantic-supported hypothesis may request an alarm")
            value = "admitted_model_hypothesis"
        elif status in {"semantic_rejected", "static_invalid"}:
            value = "rejected"
        elif status.startswith("unknown"):
            value = "not_admitted_unknown"
        else:
            raise ValueError("Unexpected completed admission status: " + status)
        by_key[row["key"]] = value
    def verdict(keys):
        observed = [by_key[key] for key in keys if key in by_key]
        if not observed:
            return "not_analyzed"
        if "admitted_model_hypothesis" in observed:
            return "admitted_model_hypothesis"
        return "not_admitted_unknown" if "not_admitted_unknown" in observed else "rejected"
    positives = [{**row, "admission": verdict(row["occurrence_keys"])} for row in baseline["positive_witnesses"]]
    reviewed = [{**row, "admission": verdict(row["occurrence_keys"])} for row in baseline["development_reviews"]]
    def strata(rows, field):
        result = defaultdict(Counter)
        for row in rows:
            result[row[field]][row["admission"]] += 1
        return {label: dict(counts) for label, counts in result.items()}
    report = {"status_counts": dict(status_counts),
              "independent_positive_admission": dict(Counter(row["admission"] for row in positives)),
              "development_complete_test_admission": strata(reviewed, "classification"),
              "development_initial_alarm_admission": strata(reviewed, "initial_failure_classification"),
              "positive_details": positives, "review_details": reviewed,
              "measured_provider_calls": completed["provider_calls"],
              "accounted_tokens": completed["accounted_tokens"], "usage_missing": completed["usage_missing"],
              "interpretation": "semantic support is a model hypothesis; validity comes only from independent labels; unknown suppression is not successful rejection; no population precision or resolution claim"}
    if heldout_reviews is not None:
        expected = set(baseline["additional_candidate_holdout"]["selected_keys"])
        reviewed_keys = [row["key"] for row in heldout_reviews["reviews"]]
        if len(set(reviewed_keys)) != len(reviewed_keys) or set(reviewed_keys) != expected:
            raise ValueError("Heldout reviews must label exactly the previously frozen candidate selection")
        rows = [{**row, "admission": verdict([row["key"]])} for row in heldout_reviews["reviews"]]
        report["heldout_complete_test_admission"] = strata(rows, "classification")
        report["heldout_initial_alarm_admission"] = strata(rows, "initial_failure_classification")
        report["heldout_review_details"] = rows
        report["heldout_scope"] = baseline["additional_candidate_holdout"]["scope"]
    return report


def programs_for_record(row):
    """Recover the COMPLETE exact emitted test bodies for an offline human audit."""
    from anchor_retrieval.syntax import Source, units
    programs, seen = [], set()
    for native_record in row["native_evidence"]:
        manifest_path = Path(native_record["manifest"]["path"])
        if digest(manifest_path) != native_record["manifest"]["sha256"]:
            raise ValueError("Native manifest changed")
        manifest = read(manifest_path)
        declared = [item for item in manifest["obligations"] if item.get("candidate_id") == row["candidate_id"]]
        if not declared:
            raise ValueError("No declared emitted program for " + row["key"])
        for item in declared:
            source_path = manifest_path.parent / "generated/files" / item["path"]
            identity = (str(source_path.resolve()), item["test_name"])
            if identity in seen:
                continue
            seen.add(identity)
            saved = next((mount for mount in manifest["mounts"] if Path(mount["source"]).resolve() == source_path.resolve()), None)
            if saved is None or digest(source_path) != saved["sha256"]:
                raise ValueError("Emitted source does not match execution manifest")
            language = "go" if source_path.suffix == ".go" else "python" if source_path.suffix == ".py" else "typescript"
            source = Source(item["path"], source_path.read_text(), language)
            matches = [unit for unit in units(source)[0] if unit.name == item["test_name"] and unit.test]
            if len(matches) != 1:
                raise ValueError("Ambiguous or missing complete emitted test: " + str(identity))
            node = matches[0].node
            if node.parent is not None and node.parent.type == "decorated_definition":
                node = node.parent
            programs.append({"source": frozen(source_path), "test_name": item["test_name"],
                             "start_byte": node.start_byte, "end_byte": node.end_byte,
                             "complete_test": source.text(node)})
    round_dir = Path(row["inputs"]["runs"]["path"]).parents[1]
    return {"key": row["key"], "case": row["case"], "candidate_id": row["candidate_id"],
            "programs": programs, "issue": frozen(round_dir / "prepared/issue.md"),
            "inputs": row["inputs"], "native_evidence": row["native_evidence"],
            "controls": row["controls"], "classification": "not_yet_reviewed"}


def evaluate(baseline, module_names, *, scope="all", progress=None):
    modules = {name: importlib.import_module(name) for name in module_names}
    # extract_frontend imports this repository helper lazily. Preload its source
    # before the seal instead of accepting unsealed code after the first call.
    importlib.import_module("relational_gap.balanced_reachability")
    module_identity = {name: frozen(module.__file__) for name, module in modules.items()}
    source_modules = loaded_local_sources()
    cache, predictions = {}, []
    records = selected_records(baseline, scope)
    previous_round = None
    for row in records:
        current_round = (row["case"], row["round"])
        if current_round != previous_round and progress is not None:
            progress({"phase": "source_only_analysis", "case": row["case"], "round": row["round"],
                      "completed": len(predictions), "total": len(records)})
        previous_round = current_round
        inputs = row["inputs"]
        key = tuple(inputs[name]["path"] for name in ("corpus", "frontend", "candidates"))
        if key not in cache:
            for record in inputs.values():
                if digest(record["path"]) != record["sha256"]:
                    raise ValueError("Frozen input changed: " + record["path"])
            cache[key] = (read(inputs["corpus"]["path"]), read(inputs["frontend"]["path"]),
                          {candidate["id"]: candidate for candidate in read(inputs["candidates"]["path"])})
        corpus, frontend, candidates = cache[key]
        # No execution evidence, issue label, review, or positive witness is
        # passed. The source analyses receive the exact same three arguments.
        results, timings = {}, {}
        for name, module in modules.items():
            started = time.perf_counter()
            results[name] = module.analyze(corpus, frontend, candidates[row["candidate_id"]])
            timings[name] = time.perf_counter() - started
        predictions.append({"key": row["key"], "status": combine(list(results.values())), "analyses": results,
                            "analysis_seconds": timings})
    verify_seal(module_identity)
    verify_seal(source_modules)
    newly_imported = set(loaded_local_sources()) - set(source_modules)
    if newly_imported:
        raise ValueError("Source helper imported after the seal; preload it before evaluation: " +
                         ", ".join(sorted(newly_imported)))
    return {"version": VERSION, "scope": scope,
            "modules": module_identity, "imported_source_modules": source_modules,
            "analysis_seconds": {name: sum(row["analysis_seconds"][name] for row in predictions) for name in modules},
            "predictions": predictions, "summary": summarize(baseline, predictions),
            "provider_calls": 0, "subject_executions": 0, "truth_joined_only_after_analysis": True}


def main():
    parser = argparse.ArgumentParser(__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    collect = commands.add_parser("inventory")
    collect.add_argument("--campaign", type=Path, default=CAMPAIGN)
    collect.add_argument("--evaluation", type=Path, default=EVALUATION)
    collect.add_argument("--heldout-per-case", type=int, default=2)
    collect.add_argument("--output", type=Path, required=True)
    check = commands.add_parser("evaluate")
    check.add_argument("--baseline", type=Path, required=True)
    check.add_argument("--modules", nargs="+", default=["relation_search.test_roles", "relation_search.test_preconditions"])
    check.add_argument("--scope", choices=["all", "audited", "positive", "development", "holdout"], default="all")
    check.add_argument("--output", type=Path, required=True)
    programs = commands.add_parser("programs")
    programs.add_argument("--baseline", type=Path, required=True)
    programs.add_argument("--scope", choices=["all", "audited", "positive", "development", "holdout"], default="holdout")
    programs.add_argument("--output", type=Path, required=True)
    report = commands.add_parser("report")
    report.add_argument("--baseline", type=Path, required=True)
    report.add_argument("--predictions", type=Path, required=True)
    report.add_argument("--heldout-reviews", type=Path)
    report.add_argument("--output", type=Path, required=True)
    admission_report = commands.add_parser("admission-report")
    admission_report.add_argument("--baseline", type=Path, required=True)
    admission_report.add_argument("--run", type=Path, required=True)
    admission_report.add_argument("--heldout-reviews", type=Path)
    admission_report.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "inventory":
        result = inventory(args.campaign, args.evaluation, args.heldout_per_case)
    elif args.command == "programs":
        result = {"version": VERSION, "baseline": frozen(args.baseline), "scope": args.scope,
                  "records": [programs_for_record(row) for row in selected_records(read(args.baseline), args.scope)]}
    elif args.command == "report":
        saved = read(args.predictions)
        result = {"version": VERSION, "baseline": frozen(args.baseline),
                  "predictions": frozen(args.predictions), "modules": saved["modules"],
                  "summary": summarize(read(args.baseline), saved["predictions"],
                      read(args.heldout_reviews) if args.heldout_reviews else None),
                  "provider_calls": 0, "subject_executions": 0,
                  "truth_joined_only_after_analysis": True}
        if "imported_source_modules" in saved:
            result["imported_source_modules"] = saved["imported_source_modules"]
        if args.heldout_reviews:
            result["heldout_reviews"] = frozen(args.heldout_reviews)
    elif args.command == "admission-report":
        prepared_path, completed_path = args.run / "prepared.json", args.run / "summary.json"
        prepared, completed = read(prepared_path), read(completed_path)
        if prepared["baseline"]["sha256"] != digest(args.baseline):
            raise ValueError("Admission run refers to a different baseline")
        if completed["prepared"]["sha256"] != digest(prepared_path):
            raise ValueError("Completed admission refers to changed prepared questions")
        result = {"version": VERSION, "baseline": frozen(args.baseline),
                  "prepared": frozen(prepared_path), "completed": frozen(completed_path),
                  "summary": summarize_admission(read(args.baseline), completed, prepared,
                      read(args.heldout_reviews) if args.heldout_reviews else None),
                  "provider_calls_by_evaluator": 0, "subject_executions_by_evaluator": 0,
                  "truth_joined_only_after_decisions": True}
        if args.heldout_reviews:
            result["heldout_reviews"] = frozen(args.heldout_reviews)
    else:
        result = evaluate(read(args.baseline), args.modules, scope=args.scope,
                          progress=lambda row: print(json.dumps(row, ensure_ascii=False), flush=True))
    write_new(args.output, result)
    printable = result.get("counts", {key: value for key, value in result.get("summary", {}).items()
                                     if key not in {"positive_details", "review_details", "heldout_review_details"}})
    print(json.dumps(printable, ensure_ascii=False))


if __name__ == "__main__":
    main()
