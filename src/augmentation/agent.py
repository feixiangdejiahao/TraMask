"""Bounded evidence queries and test augmentation through the recorded provider.

Every model response is one explicit action. Commands are supplied by the
caller, never by the model or historical trajectory. Token accounting includes
all queries and retries, and unfinished candidates remain unfinished.
"""
from __future__ import annotations

import json
from pathlib import Path

from .pipeline import TASK_SYSTEM, TEST_EDIT_RULES, parse_response, write_json
from .presentation import evidence_payload, inspect
from .program import stable_id
from .distinctions import check_generated_conditions, resolve_target
from .ranking import rank_candidates


AGENT_SYSTEM = TASK_SYSTEM + TEST_EDIT_RULES + """
Use the evidence tools to examine one local behavior. A proposed relation can
be rejected or refined. Rejecting one candidate does not establish adequacy of
the surrounding behavior. Source rows retain joint conditions, object identity,
operation order and assertion predicates. Unknown and omitted evidence is not
coverage. Gold patches and benchmark failures are not available to this method.

Return exactly one JSON action:
{"action":"inspect", "reason":"specific missing evidence", "query":
 {"kind":"source|tests|scope|relations|history|requirement", "path":"optional source path",
  "start_line":1, "end_line":80, "test_ids":[], "offset":0, "operation_id":"optional relation node", "ordinal":0}}
{"action":"run_existing", "reason":"what the run will resolve", "test_ids":["existing test id"]}
{"action":"augment", "reason":"requirement-supported joint target", "target":{"id":"a supplied target id"}, "response":
 {"decision":"gap", "reason":"requirement basis", "distinction":"concrete joint conditions and observation",
  "tests":[{"path":"repository-relative test path", "mode":"new|append", "code":"complete test code"}],
  "existing_test_ids":[]}}
{"action":"finish", "decision":"no_gap|selection_problem|unknown", "reason":"evidence and limits",
 "distinction":"what was checked", "existing_test_ids":[]}

Write small tests in the existing framework. Keep relevant existing assertions.
Use the public requirement for expected behavior, which can be equal or different
across scenarios. Do not edit production code or supply shell commands. No formal
specification or separate rule-generation document is required. The caller runs
tests when execution is configured. A blocked downstream operation may itself
be the defect. Do not change an expected result merely to make the patch pass.
Execution errors, test failures, uncovered combinations and patch defects differ.
The active target retains the selected input conditions across actions. You may
choose another supplied target, or use target.condition_values with supplied
condition IDs and domain values. The target is optional: omission keeps the
active target. To change a target after proposing a test, give target_change_reason.
Do not replace a difficult condition with an easier one without explaining why.
The source analysis describes possible behavior, not the correct expected result.
After generating a test, check condition_check and execution feedback. Repair
test setup errors or missing conditions. Keep a requirement-supported failing
assertion; a patch failure is not a reason to weaken it. Unknown condition checks
need review and never certify a valid combination. Use finish unknown when the
test is useful but the defect needs review; finish no_gap withdraws the hypothesis.
Exploration and post-generation review have separate bounded call allowances.
Each action consumes the shared token budget. Inspect only evidence that can change
the current decision; repeated identical queries or tests stop this candidate.
Query fields are optional and depend on kind. For history, omit ordinal for the
summary or supply a shown step ordinal for its full public feedback. For tests,
path searches all indexed tests in that file or directory; start_line/end_line
restrict the range. Without a path or IDs, offset pages the candidate's tests.
"""


def _usage(record, reserved):
    usage = record.get("usage") or {}
    total = usage.get("total_tokens")
    if not isinstance(total, int) or total < 0:
        prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
        total = prompt + completion if isinstance(prompt, int) and isinstance(completion, int) and min(prompt, completion) >= 0 else None
    return {"charged_tokens": total if total is not None else reserved,
            "accounting": "provider_usage" if total is not None else "conservative_reservation_without_usage",
            "provider_usage": usage}


def _execution_view(result, directory):
    view = {k: result[k] for k in ("decision", "candidate_id", "interpretation") if k in result}
    for key in ("baseline", "augmented", "execution"):
        if key not in result:
            continue
        run = dict(result[key])
        folder = directory / ("selection" if key == "execution" else key)
        full = folder / "result.json"
        if full.exists():
            try:
                details = json.loads(full.read_text())
                if isinstance(details, dict) and isinstance(details.get("tests"), list):
                    run["tests"] = details["tests"]
            except (ValueError, OSError):
                pass
        if isinstance(run.get("tests"), list):
            tests = run["tests"]
            failed = lambda t: str(t.get("status", t.get("outcome", ""))).lower() in {"failed", "failure", "error", "fail", "broken"}
            run["tests"] = sorted(tests, key=lambda t: not failed(t))[:20]
            run["test_results_total"] = len(tests)
            run["test_results_truncated"] = len(tests) > 20
        if "activation" in run:
            activation = run["activation"]
            run["activation"] = {**activation, "events": activation.get("events", [])[:36],
                                 "event_view_truncated": activation.get("event_view_truncated", False) or len(activation.get("events", [])) > 36}
        for name in ("stdout", "stderr"):
            path = folder / (name + ".txt")
            text = path.read_text(errors="replace") if path.exists() else ""
            run[name] = text[-7000:]
            run[name + "_truncated"] = len(text) > 7000
        # Go compilation diagnostics may live only in the structured event log.
        go_log = folder / "go.jsonl"
        if go_log.exists():
            tail = ""
            with go_log.open(errors="replace") as stream:
                for line in stream:
                    try:
                        event = json.loads(line)
                        tail = (tail + str(event.get("Output", "")))[-10000:]
                    except ValueError:
                        continue
            run["structured_output_tail"] = tail
        view[key] = run
    return view


def _select(prepared, candidate_ids, limit):
    known = {c["id"]: c for c in prepared["candidates"]}
    if candidate_ids is not None:
        ids = list(dict.fromkeys(candidate_ids))
        if any(cid not in known for cid in ids):
            raise ValueError("unknown_candidate_id")
        return [known[cid] for cid in ids[:limit]]
    return rank_candidates(prepared["candidates"], prepared.get("issue", ""), limit=limit)[0]


def run_agent(prepared, output, *, candidate_ids=None, provider=None, provider_root=None,
              command=None, max_rounds=3, max_executions=2, token_budget=100000,
              max_output_tokens=8192, max_candidates=8, timeout=300, executor=None,
              max_feedback_rounds=2):
    if min(max_rounds, token_budget, max_output_tokens, max_candidates) < 1 or min(max_executions, max_feedback_rounds) < 0 or timeout <= 0:
        raise ValueError("invalid_agent_budget")
    if provider is None:
        from .provider import dispatch
        provider = dispatch
    if executor is None:
        from .execution import execute
        executor = execute
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    root = Path(provider_root) if provider_root else Path(__file__).resolve().parents[2]
    if candidate_ids is None:
        selected, ranking = rank_candidates(prepared["candidates"], prepared.get("issue", ""), limit=max_candidates)
    else:
        selected, ranking = _select(prepared, candidate_ids, max_candidates), []
    ledger, results = [], []
    spent = 0
    protocol = {"version": "joint-observation-agent.v2", "max_exploration_rounds_per_candidate": max_rounds,
                "max_feedback_rounds_per_candidate": max_feedback_rounds,
                "max_total_rounds_per_candidate": max_rounds + max_feedback_rounds,
                "max_executions_per_candidate": max_executions, "total_token_budget": token_budget,
                "max_output_tokens_per_call": max_output_tokens, "candidate_limit": max_candidates,
                "execution_command": command, "selected_candidates": [c["id"] for c in selected],
                "omitted_candidates": len(prepared["candidates"]) - len(selected),
                "selection_basis": "source_effect_requirement_overlap_and_evidence_diversity" if candidate_ids is None else "caller_selected_ids",
                "selection_ranking": ranking, "reference_information_used": False}
    write_json(output / "protocol.json", protocol)

    def checkpoint():
        summary = {"results": results, "ledger": ledger, "charged_tokens": spent,
                   "external_model_calls": sum(r.get("external_model_calls", 0) for r in ledger),
                   "generated_proposals": sum(len(r.get("proposals", [])) for r in results),
                   "confirmed_bug_count": None,
                   "interpretation": "Model assessments and execution evidence require semantic review. Unfinished candidates are not no-gap results."}
        write_json(output / "results.json", summary)
        return summary

    for candidate in selected:
        cid = candidate["id"]
        directory = output / cid
        directory.mkdir()
        evidence = evidence_payload(prepared, candidate)
        history, seen_actions = [], set()
        count_execution = 0
        target = resolve_target(candidate)
        feedback_started, feedback_left = False, max_feedback_rounds
        result = {"candidate_id": cid, "status": "unknown", "stop_reason": "round_limit", "proposals": [], "rounds": 0}
        results.append(result)
        for number in range(1, max_rounds + max_feedback_rounds + 1):
            if feedback_started:
                if feedback_left <= 0:
                    break
                feedback_left -= 1
            elif number > max_rounds:
                break
            prompt = json.dumps({"evidence": evidence, "actions_and_feedback": history,
                                 "active_target": target,
                                 "remaining": {"phase": "feedback" if feedback_started else "exploration",
                                               "model_rounds": feedback_left + 1 if feedback_started else max_rounds - number + 1,
                                               "reserved_feedback_rounds": feedback_left if not feedback_started else 0,
                                               "executions": max_executions - count_execution,
                                               "tokens": max(0, token_budget - spent)}}, ensure_ascii=False)
            # UTF-8 bytes plus framing provide a conservative preflight reservation.
            # Actual provider prompt/completion totals replace it when available.
            input_reservation = len((AGENT_SYSTEM + prompt).encode()) + 256
            # Keep one feedback call affordable before accepting a proposal.
            # This is a conservative byte reservation, not a claim about model tokenization.
            review_reserve = input_reservation + 24000 + min(max_output_tokens, 4096) if not feedback_started and max_feedback_rounds else 0
            completion_limit = min(max_output_tokens, token_budget - spent - input_reservation - review_reserve)
            if completion_limit < 256:
                result["stop_reason"] = "total_token_budget"
                break
            request = {"id": cid + ":" + str(number), "system": AGENT_SYSTEM, "prompt": prompt,
                       "thinking": "enabled", "max_tokens": completion_limit, "reasoning_effort": "high"}
            round_dir = directory / ("round" + str(number))
            reservation = input_reservation + completion_limit
            record = provider(request, round_dir, root=root)
            accounting = _usage(record, reservation)
            spent += accounting["charged_tokens"]
            ledger.append({"candidate_id": cid, "round": number, "reserved_tokens": reservation,
                           "external_model_calls": record.get("external_model_calls", 0),
                           "provider_status": record.get("status"), "reserved_feedback_tokens": review_reserve,
                           "phase": "feedback" if feedback_started else "exploration", **accounting})
            result["rounds"] = number
            if record.get("status") != "complete":
                result["stop_reason"] = "provider_incomplete"
                history.append({"error": "Previous call did not complete. No decision or test was accepted."})
                checkpoint()
                continue
            try:
                action = json.loads((round_dir / "completion.txt").read_text())
                if not isinstance(action, dict) or action.get("action") not in {"inspect", "run_existing", "augment", "finish"}:
                    raise ValueError("invalid_agent_action")
                if not isinstance(action.get("reason"), str) or not action["reason"].strip():
                    raise ValueError("missing_action_reason")
                kind = action["action"]
                identity = stable_id(kind, action.get("query"), action.get("test_ids"), action.get("response"), action.get("target"))
                if identity in seen_actions:
                    result["stop_reason"] = "repeated_action_without_new_evidence"
                    break
                seen_actions.add(identity)
                write_json(round_dir / "action.json", action)
                if kind == "inspect":
                    feedback = inspect(prepared, candidate, action["query"])
                    encoded = json.dumps(feedback, ensure_ascii=False)
                    if len(encoded) > 42000:
                        # Do not silently truncate a source record into invalid or misleading code.
                        feedback = {"status": "query_too_broad", "characters": len(encoded),
                                    "instruction": "Request a narrower source range or selected test IDs."}
                elif kind in {"augment", "run_existing"}:
                    if kind == "augment":
                        response = parse_response(json.dumps(action["response"]), prepared, cid)
                        if response["decision"] != "gap":
                            raise ValueError("augment_requires_gap_response")
                        selected_target = resolve_target(candidate, action["target"]) if "target" in action else target
                        if result["proposals"] and selected_target["condition_values"] != target["condition_values"] and not str(action.get("target_change_reason", "")).strip():
                            raise ValueError("target_change_requires_reason")
                        target = selected_target
                        condition_check = check_generated_conditions(prepared, candidate, response, target)
                        write_json(round_dir / "condition_check.json", {"target": target, **condition_check})
                        # Review remains available even when generation used the
                        # final exploration call, or static checking found a drift.
                        feedback_started = True
                        write_json(round_dir / "assessment.json", response)
                        result["proposals"].append({"round": number, "assessment": str(round_dir / "assessment.json"),
                                                    "target": target, "condition_check": str(round_dir / "condition_check.json"),
                                                    "condition_status": condition_check["status"], "feedback_reviewed": False})
                        result["status"] = "generated_test_missing_target" if condition_check["status"] == "not_preserved" else "generated_test_unverified"
                    else:
                        response = parse_response(json.dumps({"decision": "selection_problem", "reason": action["reason"],
                            "distinction": "Probe existing tests; this action alone does not claim a selection problem.",
                            "tests": [], "existing_test_ids": action["test_ids"]}), prepared, cid)
                    if command is None:
                        feedback = {"status": "execution_unavailable", "reason": "No caller-supplied test command."}
                    elif count_execution >= max_executions:
                        feedback = {"status": "execution_budget_exhausted"}
                    else:
                        count_execution += 1
                        execution_dir = round_dir / "execution"
                        execution = executor(prepared, response, execution_dir, command, timeout=timeout, run_baseline=False)
                        feedback = _execution_view(execution, execution_dir)
                        if kind == "augment":
                            result["proposals"][-1]["execution"] = str(execution_dir / "result.json")
                        else:
                            feedback["purpose"] = "existing_test_probe_not_selection_verdict"
                        if not feedback_started and number == max_rounds:
                            feedback_started = True
                    if kind == "augment":
                        feedback["condition_check"] = condition_check
                        feedback["active_target"] = target
                else:
                    response = parse_response(json.dumps({"decision": action["decision"], "reason": action["reason"],
                        "distinction": action.get("distinction", action["reason"]), "tests": [],
                        "existing_test_ids": action.get("existing_test_ids", [])}), prepared, cid)
                    if response["decision"] == "gap":
                        raise ValueError("finish_cannot_claim_gap_without_augmentation")
                    result.update(status="model_" + response["decision"], stop_reason="model_finished", response=response)
                    if result["proposals"]:
                        result["proposals"][-1]["feedback_reviewed"] = True
                    write_json(round_dir / "assessment.json", response)
                    break
                write_json(round_dir / "feedback.json", feedback)
                # Complete proposals and logs stay on disk. Keep a bounded view
                # so a feedback opportunity is not consumed by duplicated code.
                brief = {k: v for k, v in action.items() if k != "response"}
                if kind == "augment":
                    brief["target"] = response["distinction"]
                    brief["generated_tests"] = response["tests"]
                history.append({"action": brief, "feedback": feedback})
                if len(history) > 2:
                    history = history[-2:]
            except (ValueError, KeyError, TypeError, OSError) as exc:
                failure = {"status": "action_error", "error": str(exc)}
                write_json(round_dir / "feedback.json", failure)
                history.append(failure)
                result["stop_reason"] = "action_error"
            checkpoint()
        result["executions"] = count_execution
        write_json(directory / "result.json", result)
        checkpoint()
    return checkpoint()
