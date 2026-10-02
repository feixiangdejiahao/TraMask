"""Independent, stdlib-only audit of frozen admission receipts.

This file intentionally imports no repository analyzer, provider, runner, or
subject module. It reads immutable artifacts and joins existing independent
truth only after reading completed decisions. No provider or subject is run.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))
VERSION = "independent-admission-receipt-audit.v1"
FORBIDDEN_KEYS = {
    "positive_witnesses", "development_reviews", "heldout_reviews", "native_evidence",
    "initial_failure_classification", "execution_outcomes", "runtime_results",
    "fixed_configuration_automatic_ids", "semantic_review", "semantic_revision",
    "failure_message", "reference_patch", "hidden_tests", "reviewer_labels",
    "candidate_id", "case", "review_protocol", "review_files", "positive_checkpoint",
}


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def frozen(path):
    return {"path": str(Path(path).resolve()), "sha256": sha(path)}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(receipt):
    require(sha(receipt["path"]) == receipt["sha256"], "Changed artifact: " + receipt["path"])


def unique(rows, field, description):
    result = {row[field]: row for row in rows}
    require(len(result) == len(rows), "Duplicate " + description)
    return result


def dispatch_fields(request):
    result = {"system": request["system"], "prompt": request["prompt"],
              "thinking": request.get("thinking", "disabled"),
              "max_tokens": request.get("max_tokens", 16384)}
    if "reasoning_effort" in request:
        result["reasoning_effort"] = request["reasoning_effort"]
    return result


def request_identity(request):
    raw = json.dumps(dispatch_fields(request), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def expected_payload(request):
    result = {"model": "deepseek-v4-flash", "temperature": 0,
              "max_tokens": request.get("max_tokens", 16384),
              "messages": [{"role": "system", "content": request["system"]},
                           {"role": "user", "content": request["prompt"]}],
              "response_format": {"type": "json_object"}, "stream": False,
              "thinking": {"type": request.get("thinking", "disabled")}}
    if "reasoning_effort" in request:
        result["reasoning_effort"] = request["reasoning_effort"]
    return result


def parsed_answers(request, completion, method):
    """Validate recorded answers without invoking the admission implementation."""
    try:
        answers = json.loads(completion)
    except (ValueError, TypeError):
        return None
    if method == "compact":
        if (not isinstance(answers, dict) or set(answers) != {"basis", "judgments"}
                or not isinstance(answers["basis"], str)):
            return None
        answers = answers["judgments"]
    if (not isinstance(answers, dict) or set(answers) != set(request["check_ids"])
            or any(not isinstance(value, str) or value not in {"supported", "unsupported", "unknown"}
                   for value in answers.values())):
        return None
    return answers


def parsed_verdict(request, completion, finish_reason, method):
    """Independently derive the coarse gate outcome from recorded enum answers."""
    if finish_reason != "stop":
        return "unknown", False
    answers = parsed_answers(request, completion, method)
    if answers is None:
        return "unknown", False
    if "unsupported" in answers.values():
        return "semantic_rejected", False
    if "unknown" in answers.values():
        return "unknown", False
    if method == "guarded" and not request.get("coverage", {}).get("core_complete", False):
        return "unknown", False
    return "semantic_supported", True


def verify_prompt_program(request, record, cache):
    """Reconstruct the fixed source test independently from frozen edit bytes.

    Native probes are excluded using the accepted candidate's pre-probe edit
    snapshot; later oracle edits without instrumentation remain in the program.
    No parser, analyzer, provider or subject module is imported or executed.
    """
    corpus_path = record["inputs"]["corpus"]["path"]
    candidates_path = record["inputs"]["candidates"]["path"]
    if corpus_path not in cache:
        cache[corpus_path] = read(corpus_path)
    if candidates_path not in cache:
        cache[candidates_path] = unique(read(candidates_path), "id", "accepted candidate")
    corpus = cache[corpus_path]
    candidate = cache[candidates_path][record["candidate_id"]]

    def edit_identity(edit):
        span = edit["span"]
        return (span["path"], span["start_byte"], span["end_byte"], edit["before"], edit["after"])

    if candidate.get("instrumentation", {}).get("status") == "instrumented":
        edits = list(candidate["program_edits"])
        for edit in candidate.get("edits", []):
            if (edit.get("role") == "semantic_expected" and not edit.get("instrumented_prefix")
                    and edit_identity(edit) not in {edit_identity(old) for old in edits}):
                edits.append(edit)
    else:
        edits = candidate.get("edits", [])
    program_candidate = {**candidate, "edits": edits}
    digest = hashlib.sha256(json.dumps(program_candidate, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()
    require(digest == request["candidate_sha256"], "Requested candidate program identity differs from frozen candidate")
    span = corpus["tests"][candidate["base_test_id"]]["span"]
    full_source = corpus["sources"][span["path"]]["code"].encode()
    original = full_source[span["start_byte"]:span["end_byte"]]
    modified = original
    ordered = sorted(edits, key=lambda edit: edit["span"]["start_byte"])
    for left, right in zip(ordered, ordered[1:]):
        require(left["span"]["end_byte"] <= right["span"]["start_byte"], "Overlapping source program edits")
    for edit in reversed(ordered):
        position = edit["span"]
        begin, end = position["start_byte"] - span["start_byte"], position["end_byte"] - span["start_byte"]
        require(position["path"] == span["path"] and 0 <= begin <= end <= len(original),
                "Edited source lies outside selected test")
        require(original[begin:end].decode() == edit["before"], "Edit before bytes differ from frozen source")
        modified = modified[:begin] + edit["after"].encode() + modified[end:]
    payload = json.loads(request["prompt"])
    require(payload["original_test"] == original.decode(), "Prompt original test differs from frozen source")
    require(payload["modified_test"] == modified.decode(), "Prompt modified test differs from frozen complete program")
    return dict(candidate_sha256=digest, original_test_sha256=hashlib.sha256(original).hexdigest(),
                modified_test_sha256=hashlib.sha256(modified).hexdigest(), program_edits=len(edits),
                exact_frozen_test_program=True, native_instrumentation_excluded=True)


def verify_compact_references(request, analysis):
    """Check complete source blocks and every v2 predicate/header excerpt."""
    payload = json.loads(request["prompt"])
    document = analysis["analysis"]
    rendered = payload["source_analysis"]
    sources = document["sources"]
    for identifier, block in sources.items():
        exact = (f"{identifier} {block['path']} bytes {block['start_byte']}:{block['end_byte']}\n"
                 + "```\n" + block["code"] + "\n```")
        require(exact in rendered, "Complete compact source block missing from actual prompt: " + identifier)
    counts = Counter()

    def excerpt(actual, reference):
        require(actual["ref"] == reference, "Compact excerpt points at a different predicate/header")
        block = sources[reference["source"]]["code"].encode()
        require(0 <= reference["start"] <= reference["end"] <= len(block), "Compact excerpt reference out of bounds")
        complete = block[reference["start"]:reference["end"]].decode()
        require(actual["text"] == complete[:320], "Compact excerpt is not the exact source prefix")
        require(actual["omitted_chars"] == max(0, len(complete) - 320), "Compact excerpt omission count differs")
        counts["excerpts"] += 1
        counts["excerpts_with_omitted_suffix"] += bool(actual["omitted_chars"])

    for identifier, site in document["obligations"].items():
        check = payload["checks"][identifier]
        require(check["unit"] == site["unit"] and check["kind"] == site["kind"], "Compact obligation identity changed")
        if "expression" not in check:
            # v1 displayed entire source sites; no source-excerpt schema existed.
            continue
        require(check["at"] == site["at"], "Compact obligation source span changed")
        excerpt(check["expression"], site.get("predicate") or site.get("expected") or site["at"])
        require(len(check["guards"]) == len(site.get("guards", [])), "Compact guard index dropped a condition")
        for actual, guard in zip(check["guards"], site.get("guards", [])):
            require(actual["kind"] == guard["kind"] and actual.get("branch") == guard.get("branch"),
                    "Compact guard kind/branch changed")
            excerpt(actual["expression"], guard.get("condition") or guard.get("header") or guard["at"])
            if guard.get("header"):
                header, control = guard["header"], guard["at"]
                require(header["source"] == control["source"] and header["start"] == control["start"]
                        and header["start"] <= header["end"] <= control["end"], "Compact header is not a source prefix")
                counts["header_references"] += 1
        require(check.get("exception_regions", []) == site.get("exception_regions", []), "Exception-consumption references changed")
        for field in ("requires", "adapter_identity", "region"):
            require(check.get(field) == site.get(field), "Compact predicate semantics omitted: " + field)
    return dict(complete_source_blocks=len(sources), indexed_obligations=len(document["obligations"]),
                **dict(counts), full_source_blocks_present=True,
                excerpt_omissions_are_display_only=True)


def prompt_exclusions(request, truth, record):
    """Inspect dispatched text, not self-reported no-label/no-outcome flags.

    Exact full runtime messages are checked separately from source code, whose
    assertions legitimately appear in both prompt and native failure excerpts.
    This is an artifact/content audit, not a proof against all possible leaks.
    """
    payload = json.loads(request["prompt"])
    bad_keys = []
    strings = []

    def visit(value, location="prompt"):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in FORBIDDEN_KEYS:
                    bad_keys.append(location + "/" + key)
                visit(child, location + "/" + key)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, location + "/" + str(index))
        elif isinstance(value, str):
            strings.append(value)

    visit(payload)
    actual_text = request["system"] + "\n" + request["prompt"]
    decoded_text = "\n".join(strings)
    labels = {row[field] for row in truth for field in ("classification", "initial_failure_classification")
              if row.get(field)}
    label_hits = sorted(label for label in labels if label in actual_text)
    reason_hits = [row.get("key", row.get("candidate_id")) for row in truth
                   if len(row.get("reason", "")) >= 40 and row["reason"] in decoded_text]
    runtime_hits = []
    for evidence in record.get("native_evidence", []):
        for test in evidence["tests"]:
            message = test.get("message", "")
            if len(message) >= 40 and message in decoded_text:
                runtime_hits.append(test["id"])
    require(not (bad_keys or label_hits or reason_hits or runtime_hits),
            "Prompt exclusion violation: " + json.dumps(dict(keys=bad_keys, labels=label_hits,
                                                              reasons=reason_hits, runtime=runtime_hits)))
    return {"top_level_fields": sorted(payload), "forbidden_key_hits": bad_keys,
            "known_label_value_hits": label_hits, "full_review_reason_hits": reason_hits,
            "full_native_failure_message_hits": runtime_hits}


def source_seals(prepared, source_commit=None):
    rows = {}
    for group in ("algorithm_entry_modules", "imported_source_modules"):
        for record in prepared.get(group, {}).values():
            path = Path(record["path"])
            previous = rows.setdefault(str(path), record["sha256"])
            require(previous == record["sha256"], "Conflicting source seals: " + str(path))
    results = []
    for path, digest in sorted(rows.items()):
        current = sha(path) == digest
        basis = "current_file" if current else None
        if not current and source_commit:
            relative = Path(path).relative_to(ROOT)
            saved = subprocess.run(["git", "show", source_commit + ":" + str(relative)],
                                   cwd=ROOT, capture_output=True, check=True).stdout
            if hashlib.sha256(saved).hexdigest() == digest:
                basis = "git_commit"
        require(basis is not None, "Source seal cannot be verified: " + path)
        results.append(dict(path=path, sha256=digest, verification_basis=basis))
    require(bool(results), "No algorithm/imported-source seal")
    for relative, digest in prepared.get("algorithm", {}).items():
        require(rows.get(str(ROOT / relative)) == digest, "Algorithm map disagrees with source seal: " + relative)
    return results


def outcome(decision):
    if decision.get("alarm_eligible"):
        require(decision["status"] == "semantic_supported", "Only semantic support may admit an alarm")
        return "admitted"
    if decision["status"] in {"semantic_rejected", "static_invalid"}:
        return "rejected"
    require(decision["status"].startswith("unknown"), "Unexpected decision status")
    return "unknown"


def summarize_truth(baseline, heldout, decisions):
    """Selection coverage, conditional gate recall and task coverage stay distinct."""
    by_key = {row["key"]: outcome(row["decision"]) for row in decisions}

    def verdict(keys):
        observed = [by_key[key] for key in keys if key in by_key]
        if not observed:
            return "not_selected"
        return "admitted" if "admitted" in observed else "unknown" if "unknown" in observed else "rejected"

    groups = {"positive": [{**row, "outcome": verdict(row["occurrence_keys"])}
                           for row in baseline["positive_witnesses"]],
              "development": [{**row, "outcome": verdict(row["occurrence_keys"])}
                              for row in baseline["development_reviews"]],
              "heldout": [{**row, "outcome": verdict([row["key"]])} for row in heldout["reviews"]]}
    summary = {}
    for name, rows in groups.items():
        labels = {}
        for field in ("classification", "initial_failure_classification"):
            strata = defaultdict(Counter)
            for row in rows:
                if field in row:
                    strata[row[field]][row["outcome"]] += 1
            if strata:
                labels[field] = {label: dict(counts) for label, counts in strata.items()}
        summary[name] = dict(denominator=len(rows), outcomes=dict(Counter(row["outcome"] for row in rows)),
                             labels=labels, details=rows)
    positives = groups["positive"]
    selected = sum(row["outcome"] != "not_selected" for row in positives)
    admitted = sum(row["outcome"] == "admitted" for row in positives)
    task_count = baseline["counts"]["trials"]
    valid_tasks = {row["case"] for row in positives if row["outcome"] == "admitted"}
    for name in ("development", "heldout"):
        for row in groups[name]:
            if row["outcome"] == "admitted" and row.get("classification") == "valid_issue_related_defect":
                valid_tasks.add(row.get("case", row.get("key", "").split(":")[0]))
    known_keys = {key for row in baseline["positive_witnesses"] + baseline["development_reviews"]
                  for key in row["occurrence_keys"]} | {row["key"] for row in heldout["reviews"]}
    admitted_keys = {key for key, value in by_key.items() if value == "admitted"}
    summary["recall"] = dict(known_witnesses= len(positives), selected_known_witnesses=selected,
                              admitted_known_witnesses=admitted,
                              selection_coverage=selected / len(positives) if positives else None,
                              gate_recall_conditional_on_selection=admitted / selected if selected else None,
                              known_witness_retention=admitted / len(positives) if positives else None,
                              independently_confirmed_admitted_task_coverage=dict(
                                  numerator=len(valid_tasks), denominator=task_count, cases=sorted(valid_tasks)))
    summary["frontier"] = dict(selected=len(decisions), admitted=len(admitted_keys),
                               admitted_without_existing_truth=len(admitted_keys - known_keys),
                               admitted_without_existing_truth_keys=sorted(admitted_keys - known_keys),
                               population_false_positive_total=None, population_precision=None)
    return summary


def audit(baseline_path, heldout_path, run_path, *, source_commit=None):
    baseline = read(baseline_path)
    for receipt in [baseline["positive_checkpoint"], *baseline["review_files"]]:
        verify(receipt)
    prepared_path, completed_path = Path(run_path) / "prepared.json", Path(run_path) / "summary.json"
    prepared, completed = read(prepared_path), read(completed_path)
    require(heldout_path is not None or prepared["scope"] in {"positive", "development"},
            "Deferred heldout-label audit only supports positive/development scopes")
    require(completed["stage"] == "complete", "Admission run is not complete")
    verify(completed["prepared"])
    require(completed["prepared"]["sha256"] == sha(prepared_path), "Summary links different prepared run")
    # Open holdout labels only after confirming a completed run tied to its
    # frozen preparation. No evaluator truth can affect provider decisions.
    heldout = (read(heldout_path) if heldout_path is not None else
               dict(reviews=[dict(key=key) for key in baseline["additional_candidate_holdout"]["selected_keys"]]))
    verify(prepared["baseline"])
    selected_inventory = read(prepared["baseline"]["path"])
    if prepared["baseline"]["sha256"] != sha(baseline_path):
        require(selected_inventory["source_inventory"]["sha256"] == sha(baseline_path),
                "Frontier does not refer to independent baseline")
        verify(selected_inventory["source_inventory"])
    pool = unique(baseline["controlled_failures"], "key", "baseline occurrence")
    require(set(heldout_key for heldout_key in baseline["additional_candidate_holdout"]["selected_keys"])
            == set(unique(heldout["reviews"], "key", "heldout label")), "Heldout truth selection differs")
    selected_pool = unique(selected_inventory["controlled_failures"], "key", "selected occurrence")
    for key, record in selected_pool.items():
        require(pool.get(key) == record, "Selected source record differs from baseline: " + key)
    expected_keys = set(selected_pool)
    if prepared["scope"] in {"positive", "development"}:
        group = "positive_witnesses" if prepared["scope"] == "positive" else "development_reviews"
        expected_keys &= {key for row in baseline[group] for key in row["occurrence_keys"]}
    elif prepared["scope"] == "holdout":
        expected_keys &= set(baseline["additional_candidate_holdout"]["selected_keys"])
    else:
        require(prepared["scope"] == "all", "Unexpected admission scope")
    # Runner intentionally deduplicates a candidate occurring in both rounds.
    expected_identities = {(pool[key]["case"], pool[key]["candidate_id"]) for key in expected_keys}
    items = unique(prepared["items"], "key", "prepared item")
    actual_identities = {(row["case"], row["candidate_id"]) for row in items.values()}
    require(actual_identities == expected_identities and len(items) == len(expected_identities),
            "Prepared items omit, add, or duplicate expected scoped candidates")
    decisions = unique(completed["decisions"], "key", "completed decision")
    require(set(items) == set(decisions), "Completed decisions differ from frozen prepared items")
    seals = source_seals(prepared, source_commit)
    truth = baseline["positive_witnesses"] + baseline["development_reviews"] + heldout["reviews"]
    calls = accounted = missing = prompt_tokens = completion_tokens = reasoning_tokens = 0
    seconds = 0.0
    details, receipts, checked_inputs, source_cache = [], [], set(), {}
    for key, item in items.items():
        require(key in expected_keys, "Unexpected occurrence key")
        record, row = pool[key], decisions[key]
        require((item["case"], item["candidate_id"]) == (record["case"], record["candidate_id"]),
                "Prepared case/candidate differs from key")
        require((row["case"], row["candidate_id"]) == (record["case"], record["candidate_id"]),
                "Completed case/candidate differs from key")
        require(item["source_inputs"] == record["inputs"], "Prepared source inputs changed")
        native_receipts = [receipt for evidence in record.get("native_evidence", [])
                           for receipt in (evidence["result"], evidence["manifest"])]
        for receipt in [*item["source_inputs"].values(), item["issue"], *native_receipts,
                        *([item["source_context"]] if item.get("source_context") else [])]:
            if (receipt["path"], receipt["sha256"]) not in checked_inputs:
                verify(receipt)
                checked_inputs.add((receipt["path"], receipt["sha256"]))
        decision = read(row["decision_path"])
        require(decision == row["decision"], "Summary and decision file disagree")
        directory = Path(run_path) / item["name"]
        require(Path(row["decision_path"]).resolve() == (directory / "decision.json").resolve(),
                "Decision is outside the expected item directory")
        detail = dict(key=key, outcome=outcome(decision), decision=frozen(row["decision_path"]),
                      source_analysis=frozen(item["analysis_path"]))
        if item["request_path"]:
            require(sha(item["request_path"]) == item["request_sha256"], "Frozen request changed")
            request = read(item["request_path"])
            if prepared.get("method") in {"guarded", "compact"}:
                require(set(json.loads(request["prompt"])["checks"]) == set(request["check_ids"]),
                        "Request check IDs differ from actual prompt obligations")
                require(read(item["analysis_path"])["coverage"] == request["coverage"],
                        "Request obligation coverage differs from source analysis")
                detail["complete_program_pairing"] = verify_prompt_program(request, record, source_cache)
                if prepared.get("method") == "compact":
                    detail["compact_references"] = verify_compact_references(request, read(item["analysis_path"]))
                    if "additional_source_analyses" in read(item["analysis_path"]):
                        from scripts.audit_admission_source_additions import verify_additions
                        detail["additional_source_provenance"] = verify_additions(
                            request, read(item["analysis_path"]), record, source_cache)
            if request.get("request_identity_version") == "actual-admission-dispatch-fields-v1":
                require(request["id"] == request_identity(request), "Actual dispatch request identity changed")
            size = len(request["system"].encode()) + len(request["prompt"].encode())
            require(size == request["prompt_bytes"] and size <= prepared["max_prompt_bytes"], "Prompt budget/size mismatch")
            require(request["max_tokens"] == prepared["output_token_limit"], "Output token budget mismatch")
            detail["prompt_exclusions"] = prompt_exclusions(request, truth, record)
            detail["request"] = frozen(item["request_path"])
            manifest_path = directory / "completion/manifest.json"
            if manifest_path.exists():
                manifest = read(manifest_path)
                actual_path = directory / "completion/request.json"
                require(read(actual_path) == expected_payload(request), "Actual provider payload differs from frozen request")
                require(sha(actual_path) == manifest["request_sha256"], "Actual provider payload SHA mismatch")
                require(manifest["request_id"] == request["id"], "Provider receipt has different request ID")
                require(manifest["external_model_calls"] in {0, 1}, "Unexpected retry/call count")
                call_count = manifest["external_model_calls"]
                if call_count:
                    require(calls < prepared["max_model_calls"], "Call exceeded configured budget")
                    upper_bound = size + request["max_tokens"] + 256
                    require(accounted + upper_bound <= prepared["max_total_tokens"], "Dispatch lacked token reservation")
                    if prepared.get("deadline_utc"):
                        created = datetime.fromisoformat(manifest["created_at"].replace("Z", "+00:00"))
                        deadline = datetime.fromisoformat(prepared["deadline_utc"].replace("Z", "+00:00"))
                        require(created + timedelta(seconds=300) <= deadline, "Dispatch breached deadline reserve")
                calls += call_count
                usage = manifest.get("usage") or {}
                if usage.get("total_tokens") is not None:
                    accounted += usage["total_tokens"]
                elif usage.get("prompt_tokens") is not None and usage.get("completion_tokens") is not None:
                    accounted += usage["prompt_tokens"] + usage["completion_tokens"]
                elif call_count:
                    accounted += size + request["max_tokens"] + 256
                    missing += 1
                prompt_tokens += usage.get("prompt_tokens", 0)
                completion_tokens += usage.get("completion_tokens", 0)
                reasoning_tokens += (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
                seconds += manifest.get("seconds", 0)
                if manifest["status"] == "complete":
                    response_path, body_path = directory / "completion/response.json", directory / "completion/response.body"
                    completion_path = directory / "completion/completion.txt"
                    require(sha(body_path) == manifest["response_sha256"], "Provider raw response changed")
                    response = read(response_path)
                    require(response == read(body_path), "Parsed provider response differs from raw body")
                    content = response["choices"][0]["message"]["content"]
                    require(content == completion_path.read_text(), "Completion differs from provider response")
                    require(response.get("usage") == manifest.get("usage"), "Provider usage differs from manifest")
                    finish = response["choices"][0].get("finish_reason")
                    require(finish == manifest.get("finish_reason"), "Finish reason differs from provider response")
                    expected = parsed_verdict(request, content, finish, prepared.get("method", "legacy"))
                    require(expected == (decision["status"], decision["alarm_eligible"]), "Decision differs from recorded judgments")
                    judgments = parsed_answers(request, content, prepared.get("method", "legacy"))
                    valid_answers = judgments is not None
                    detail["semantic_checks"] = dict(
                        valid_complete_answer=valid_answers,
                        all_checks_model_supported=valid_answers and all(value == "supported" for value in judgments.values()),
                        model_check_counts=dict(Counter(judgments.values())) if valid_answers else {},
                        unsupported_checks=[name for name, value in judgments.items() if value == "unsupported"] if valid_answers else [],
                        unknown_checks=[name for name, value in judgments.items() if value == "unknown"] if valid_answers else [],
                        core_complete=request.get("coverage", {}).get("core_complete"),
                        source_sites_complete=request.get("coverage", {}).get("source_sites_complete"),
                        completeness_is_hard_admission_requirement=prepared.get("method") == "guarded",
                        gate_reason=decision.get("reason"))
                    if prepared.get("method") == "compact" and valid_answers:
                        detail["semantic_checks"]["basis"] = json.loads(content)["basis"]
                        detail["semantic_checks"]["basis_words"] = len(json.loads(content)["basis"].split())
                    receipts.extend(frozen(path) for path in (response_path, body_path, completion_path))
                else:
                    require(decision["status"] == "unknown" and not decision["alarm_eligible"], "Incomplete provider response admitted")
                receipts.extend((frozen(manifest_path), frozen(actual_path)))
            else:
                require(decision["status"] == "unknown" and not decision["alarm_eligible"], "No receipt for admitted/rejected model decision")
        else:
            analysis = read(item["analysis_path"])
            require(decision["status"] == analysis["status"] and not decision["alarm_eligible"], "Static decision disagrees with analysis")
        details.append(detail)
    require(calls == completed["provider_calls"], "Summary call accounting differs from receipts")
    require(accounted == completed["accounted_tokens"], "Summary token accounting differs from receipts")
    require(missing == completed["usage_missing"], "Summary missing usage count differs from receipts")
    require(accounted <= prepared["max_total_tokens"] and calls <= prepared["max_model_calls"], "Configured budget exceeded")
    model_support = dict(
        model_all_checks_supported=sum(item.get("semantic_checks", {}).get("all_checks_model_supported", False) for item in details),
        model_supported_but_not_admitted=[item["key"] for item in details
            if item.get("semantic_checks", {}).get("all_checks_model_supported") and item["outcome"] != "admitted"],
        core_incomplete=[item["key"] for item in details if item.get("semantic_checks", {}).get("core_complete") is False])
    model_support["source_sites_incomplete"] = [item["key"] for item in details
        if item.get("semantic_checks", {}).get("source_sites_complete") is False]
    model_support["source_sites_incomplete_admitted"] = [item["key"] for item in details
        if item.get("semantic_checks", {}).get("source_sites_complete") is False and item["outcome"] == "admitted"]
    return dict(version=VERSION, created_utc=datetime.now(timezone.utc).isoformat(),
                evaluator_source=frozen(__file__),
                evaluator_dependencies=[frozen(ROOT / "scripts/audit_admission_source_additions.py")],
                heldout_labels_deferred=heldout_path is None,
                inputs=dict(baseline=frozen(baseline_path), heldout=frozen(heldout_path) if heldout_path is not None else None,
                            prepared=frozen(prepared_path), completed=frozen(completed_path)),
                source_seals=seals, checked_unique_input_artifacts=len(checked_inputs),
                source_commit=source_commit, receipt_hashes=receipts, items=details,
                summary=summarize_truth(baseline, heldout, completed["decisions"]), model_support=model_support,
                budget=dict(provider_calls=calls, accounted_tokens=accounted, usage_missing=missing,
                            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                            reasoning_tokens=reasoning_tokens, provider_seconds_sum=seconds,
                            max_model_calls=prepared["max_model_calls"], max_total_tokens=prepared["max_total_tokens"]),
                provider_calls_by_evaluator=0, subject_executions_by_evaluator=0,
                limitations=["Existing labels are candidate holdouts within seen tasks, not unseen-task generalization.",
                             "Model support remains a hypothesis for candidates lacking independent truth.",
                             "Unknown suppression, semantic rejection and pending selection are distinct outcomes.",
                             "Prompt inspection checks actual fields, known label values, full review reasons and full native messages; it is not a proof against every possible information leak.",
                             "Optional source-fact audits verify source bytes, source versions and stated evidence roles; they do not prove binding identity, ranking independence or semantic validity.",
                             "No population precision or zero-FP claim follows from incomplete frontier adjudication."])


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    heldout = parser.add_mutually_exclusive_group(required=True)
    heldout.add_argument("--heldout-reviews", type=Path)
    heldout.add_argument("--defer-heldout-labels", action="store_true")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--source-commit")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.baseline, args.heldout_reviews, args.run, source_commit=args.source_commit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(dict(budget=report["budget"], recall=report["summary"]["recall"],
                         frontier=report["summary"]["frontier"]), ensure_ascii=False))


if __name__ == "__main__":
    main()
