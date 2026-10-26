"""Receipt-gated, bounded deletion scheduling. No provider or subject execution.

The caller executes each proposal with the frozen paired runner, obtains an
independent qualification, and supplies the qualification's JSON file receipt.
This module verifies bytes and bindings; it cannot perform semantic review or
establish a reviewer's real-world independence. Test fixtures must identify
themselves as synthetic and never be reported as experimental observations.

Only original atomic operations are removed. A successful removal restarts the
scan. Eight operations need at most 8+7+...+1 = 36 attempts, including the empty
edit. A complete final scan with only qualified failures establishes deletion
1-minimality; unknown results and truncated scans never establish minimality.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from . import variants
from .evidence import derive_classification, validate_receipt


PHASE_CAPS = {
    "target_qualification_runs": 12,
    "five_candidate_four_variant_runs": 20,
    "success_three_repeat_runs": 60,
    "minimization_eight_operations_worst_36_deletion_attempts_runs": 720,
    "final_three_repeat_runs": 60,
    "total_subject_test_run_cap": 872,
}
DELETE_PHASE = "minimization_eight_operations_worst_36_deletion_attempts_runs"
INVARIANTS = (
    "strict_context_only", "target_operation_preserved", "target_input_values_preserved",
    "target_input_semantics_preserved", "original_observation_preserved",
    "original_assertions_preserved", "instrumentation_noninterference",
    "clean_isolated_runs", "stable_contrast",
)


def _dump(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha(value):
    return hashlib.sha256((_dump(value) if not isinstance(value, str) else value).encode()).hexdigest()


def request_sha256(request):
    """Canonical digest for the external qualification's request_sha256 field."""
    return _sha(request)


def _read(receipt):
    receipt = validate_receipt(receipt)
    path = Path(receipt["path"])
    if ".." in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("noncanonical_or_symlink_evidence")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_evidence_json_key")
            result[key] = value
        return result
    body = json.loads(path.read_bytes(), object_pairs_hook=unique)
    _dump(body)  # Reject NaN and infinity, including in ignored metadata.
    return receipt, body


def _check(value):
    if not isinstance(value, dict) or value.get("status") not in {"pass", "fail", "unresolved"}:
        raise ValueError("qualification_check_requires_pass_fail_or_unresolved")
    receipts = value.get("evidence", [])
    if not isinstance(receipts, list) or (value["status"] != "unresolved" and not receipts):
        raise ValueError("resolved_qualification_requires_artifact_evidence")
    return {**value, "evidence": [validate_receipt(row) for row in receipts]}


class MethodRepeatBudget:
    """Shared accounting for exactly one method/repeat's five candidate slots.

    Reservations count all four invocations even for failed/unknown executions.
    They are never refunded and do not authorize execution. Target qualification
    defaults to its entire registered allowance; physical costs remain separate.
    Alternate protocol ceilings are rejected instead of silently interpreted.
    """

    def __init__(self, protocol, *, target_qualification_runs=12):
        caps = protocol.get("pilot4", {}).get("execution_budget_per_method_repeat")
        if caps != PHASE_CAPS or any(type(v) is not int for v in caps.values()):
            raise ValueError("unsupported_registered_phase_caps_requires_explicit_amendment")
        if type(target_qualification_runs) is not int or not 0 <= target_qualification_runs <= 12:
            raise ValueError("target_qualification_budget_out_of_range")
        self._used = {key: 0 for key in PHASE_CAPS if key != "total_subject_test_run_cap"}
        self._used["target_qualification_runs"] = target_qualification_runs
        self._ranks = set()

    def _reserve(self, phase, runs):
        if self._used[phase] + runs > PHASE_CAPS[phase] or sum(self._used.values()) + runs > 872:
            return False
        self._used[phase] += runs
        return True

    def _initial(self, rank):
        if type(rank) is not int or not 1 <= rank <= 5 or rank in self._ranks:
            raise ValueError("candidate_rank_duplicate_or_outside_five_registered_slots")
        if self._used["five_candidate_four_variant_runs"] + 4 > 20 or self._used["success_three_repeat_runs"] + 12 > 60 or sum(self._used.values()) + 16 > 872:
            raise ValueError("initial_witness_exceeds_registered_budget")
        self._ranks.add(rank)
        self._used["five_candidate_four_variant_runs"] += 4
        self._used["success_three_repeat_runs"] += 12

    def snapshot(self):
        return {"registered_caps": dict(PHASE_CAPS), "reserved_variant_invocations": dict(self._used),
                "total_reserved_variant_invocations": sum(self._used.values()),
                "registered_candidate_ranks": sorted(self._ranks), "execution_authorization": False}


def _base_binding(binding):
    return {k: v for k, v in binding.items() if k not in {"candidate_sha256", "repeats"}}


def _projection(original, retained_ids):
    retained = set(retained_ids)
    indices = sorted(i for group in original["operation_groups"] for op in group["operations"]
                     if op["id"] in retained for i in op["edit_indices"])
    if not indices:
        return None, indices
    remap = {old: new for new, old in enumerate(indices)}
    result = copy.deepcopy(original)
    result["edits"] = [copy.deepcopy(original["edits"][i]) for i in indices]
    groups = []
    for group in original["operation_groups"]:
        operations = [{**copy.deepcopy(op), "edit_indices": [remap[i] for i in op["edit_indices"]]}
                      for op in group["operations"] if op["id"] in retained]
        if operations:
            groups.append({"factor": group["factor"], "operations": operations})
    result["operation_groups"] = groups
    result["semantic_factor_count"] = len(groups)
    return result, indices


def initial_request(candidate, execution_binding):
    """Binding for the original successful run plus three additional clean runs.

    A qualification JSON has schema ``tramask.minimization-qualification.v1``,
    ``request_sha256``, ``reviewer_id``, ``independent_of_generation: true``,
    ``runs: [{pair_receipt: <paired summary receipt>, repeat: <1-based index>}]``,
    ``checks: {E1..E9: {status, evidence}}`` and ``invariants`` with the same
    check shape for INVARIANTS. Unprovided checks/invariants stay unresolved.
    Runs may reference a one-repeat initial summary and a separate three-repeat
    confirmation summary. Order is initial execution followed by confirmations.
    """
    ids = [op["id"] for group in candidate["operation_groups"] for op in group["operations"]]
    return {"schema": "tramask.minimization-request.v1", "phase": "initial_qualification",
            "original_candidate_sha256": _sha(candidate), "candidate": copy.deepcopy(candidate),
            "candidate_sha256": _sha(candidate), "retained_operation_ids": ids,
            "original_edit_indices": list(range(len(candidate["edits"]))),
            "removed_operation_id": None, "clean_repeats": 4,
            "execution_binding": _base_binding(execution_binding),
            "execute_as": "candidate_pair", "execution_authorization": False}


def _qualification(receipt, request, seen_runs, seen_containers):
    receipt, body = _read(receipt)
    if (not isinstance(body, dict) or body.get("schema") != "tramask.minimization-qualification.v1"
            or body.get("request_sha256") != _sha(request)
            or not isinstance(body.get("reviewer_id"), str) or not body["reviewer_id"].strip()
            or body.get("independent_of_generation") is not True):
        raise ValueError("independent_qualification_must_bind_exact_request")
    runs = body.get("runs")
    if not isinstance(runs, list) or len(runs) != request["clean_repeats"]:
        raise ValueError("qualification_requires_exact_clean_repeat_count")
    ids, containers, bound_runs, summary_repeats = set(), set(), [], {}
    complete = True
    physical_runs = 0
    for run in runs:
        pair_receipt, pair = _read(run["pair_receipt"])
        binding = pair.get("binding", {})
        if (pair.get("schema") != "tramask.qualified-pair.v1"
                or _dump(_base_binding(binding)) != _dump(request["execution_binding"])
                or binding.get("candidate_sha256") != request["candidate_sha256"]):
            raise ValueError("execution_pair_binding_mismatch")
        repeats = pair.get("repeats", [])
        index = run.get("repeat")
        if type(index) is not int or not 1 <= index <= len(repeats) or repeats[index - 1].get("repeat") != index:
            raise ValueError("execution_repeat_missing_or_misnumbered")
        if binding.get("repeats") != len(repeats):
            raise ValueError("execution_repeat_binding_mismatch")
        used = summary_repeats.setdefault(pair_receipt["path"], {"indices": set(), "count": len(repeats)})
        used["indices"].add(index)
        # Verify the runner's inventory as well as the summary itself. A hash of
        # a summary does not by itself bind the bytes of its referenced files.
        artifacts = pair.get("artifacts", [])
        if not artifacts:
            raise ValueError("execution_artifact_inventory_required")
        inventory = { _dump(validate_receipt(row)) for row in artifacts }
        reviews = [row for row in artifacts if Path(row["path"]).name == "execution_review.json"]
        if len(reviews) != 1:
            raise ValueError("bound_technical_execution_review_required")
        _, technical = _read(reviews[0])
        if (technical.get("approved_for_execution") is not True
                or not technical.get("reviewer_id")
                or _dump(technical.get("binding")) != _dump(binding)
                or pair.get("review_sha256") != _sha(technical)):
            raise ValueError("technical_execution_review_binding_mismatch")
        row = repeats[index - 1]
        if set(row.get("variants", {})) != set(variants.VARIANTS):
            raise ValueError("all_four_execution_variants_required")
        for name in variants.VARIANTS:
            variant = row["variants"][name]
            runtime_receipt = variant.get("runtime_result")
            if runtime_receipt is None:
                # Invocation exceptions still have a retained pair/artifact
                # receipt, but never provide a passing or negative deletion.
                if not variant.get("failure"):
                    raise ValueError("execution_variant_receipt_or_failure_required")
                complete = False
                continue
            runtime_receipt, runtime = _read(runtime_receipt)
            if _dump(runtime_receipt) not in inventory:
                raise ValueError("runtime_receipt_missing_from_pair_inventory")
            key = runtime_receipt["path"]
            if key in ids or key in seen_runs:
                raise ValueError("execution_receipt_reused_across_clean_repetitions")
            ids.add(key)
            execution = runtime.get("execution")
            if not execution:
                complete = False
                continue
            physical_runs += 1
            if runtime.get("checkpoint") != binding.get("checkpoint"):
                raise ValueError("runtime_checkpoint_binding_mismatch")
            expected = binding["command_mapping"][name]
            if execution.get("command") != expected["command"] or execution.get("working_directory") != expected["working_directory"]:
                raise ValueError("runtime_command_binding_mismatch")
            container = execution.get("container")
            if not isinstance(container, str) or not container or container in containers or container in seen_containers:
                raise ValueError("fresh_isolated_container_receipts_required")
            containers.add(container)
            for stream in ("stdout", "stderr"):
                raw = {"path": execution.get("raw_" + stream), "bytes": execution.get(stream + "_bytes"),
                       "sha256": execution.get(stream + "_sha256")}
                if _dump(validate_receipt(raw)) not in inventory:
                    raise ValueError("raw_execution_capture_missing_from_inventory")
            if (runtime.get("status") != "completed" or execution.get("status") != "completed"
                    or execution.get("timed_out") is not False or variant.get("diagnosis", {}).get("event_errors")):
                complete = False
        bound_runs.append(copy.deepcopy(run))
    if any(row["indices"] != set(range(1, row["count"] + 1)) for row in summary_repeats.values()):
        raise ValueError("unaccounted_pair_repetitions_exceed_phase_budget")
    classification = derive_classification(body.get("checks", {}))
    raw_invariants = body.get("invariants", {})
    if not isinstance(raw_invariants, dict) or set(raw_invariants) - set(INVARIANTS):
        raise ValueError("unknown_qualification_invariant")
    invariants = {key: _check(raw_invariants.get(key, {"status": "unresolved", "evidence": []})) for key in INVARIANTS}
    baseline_pass = all(classification["checks"][f"E{i}"]["status"] == "pass" for i in range(1, 7))
    statuses = [classification["checks"][key]["status"] for key in ("E7", "E8")]
    statuses += [row["status"] for row in invariants.values()]
    # Losing the qualified fixed-target baseline invalidates the comparison; it
    # cannot certify that an otherwise legal operation is necessary.
    outcome = ("unresolved" if not complete or not baseline_pass or "unresolved" in statuses else "fail" if "fail" in statuses
               else "pass" if all(status == "pass" for status in statuses) else "unresolved")
    return {"qualification_receipt": receipt, "outcome": outcome, "checks": classification["checks"],
            "invariants": invariants, "runs": bound_runs, "execution_complete": complete,
            "physical_subject_test_runs": physical_runs,
            "oracle_qualified": outcome == "pass" and classification["oracle_qualified"],
            "E9": classification["checks"]["E9"],
            "runtime_receipt_paths": sorted(ids), "container_ids": sorted(containers)}


class DeletionMinimizer:
    """One original candidate; caller-owned persistence via ``snapshot()``.

    ``initial_evidence`` and ``record_result`` accept a qualification file
    receipt, never a bool or a shell status. ``propose`` is idempotent until its
    result is recorded. Persist its snapshot before launching any external run.
    An empty projection uses execute_qualified_pair, since stage_candidate
    intentionally rejects empty edits. Metadata indices are remapped only for
    runner compatibility; original edit bytes and their identity are retained.
    """

    def __init__(self, source_files, candidate, *, validation_context, execution_binding,
                 initial_evidence, budget, max_deletion_attempts=36):
        if type(max_deletion_attempts) is not int or not 0 <= max_deletion_attempts <= 36:
            raise ValueError("deletion_attempt_cap_must_be_between_zero_and_36")
        if not isinstance(budget, MethodRepeatBudget):
            raise ValueError("shared_method_repeat_budget_required")
        context = {**validation_context, "source_files": source_files, "edit_policy": "context_only"}
        validated = variants._candidate(copy.deepcopy(candidate), context)
        if _dump(validated) != _dump(candidate):
            raise ValueError("candidate_must_already_use_normalized_exact_paths")
        files = variants._files(source_files)
        expected_sources = {"/" + key: _sha(value) for key, value in sorted(files.items())}
        if (execution_binding.get("schema") != "tramask.execution-binding.v1"
                or execution_binding.get("source_file_sha256") != expected_sources
                or execution_binding.get("candidate_sha256") != _sha(candidate)):
            raise ValueError("initial_candidate_or_predecessor_binding_mismatch")
        request = initial_request(candidate, execution_binding)
        qualified = _qualification(initial_evidence, request, set(), set())
        if qualified["outcome"] != "pass":
            raise ValueError("initial_stable_strict_context_witness_not_established")
        budget._initial(candidate["rank"])
        self._budget, self._limit = budget, max_deletion_attempts
        self._original, self._files = copy.deepcopy(candidate), files
        self._binding = request["execution_binding"]
        self._active = request["retained_operation_ids"]
        self._initial = {"request": request, **qualified}
        self._current_receipt = qualified["qualification_receipt"]
        self._seen_runs = set(qualified["runtime_receipt_paths"])
        self._seen_containers = set(qualified["container_ids"])
        self._records, self._scan = [], []
        self._index, self._attempts = 0, 0
        self._pending = None
        self._phase, self._minimality = "deletion", None
        self._final = None

    def _request(self, phase, retained, removed, repeats):
        candidate, indices = _projection(self._original, retained)
        # Each subset is applied independently to the original predecessor.
        variants._apply(self._files, [] if candidate is None else candidate["edits"])
        return {"schema": "tramask.minimization-request.v1", "phase": phase,
                "original_candidate_sha256": _sha(self._original), "candidate": candidate,
                "candidate_sha256": _sha(candidate) if candidate is not None else None,
                "retained_operation_ids": list(retained), "original_edit_indices": indices,
                "removed_operation_id": removed, "clean_repeats": repeats,
                "execution_binding": copy.deepcopy(self._binding),
                "parent_success_qualification_receipt": copy.deepcopy(self._current_receipt),
                "execute_as": "candidate_pair" if candidate is not None else "original_pair",
                "execution_authorization": False}

    def propose(self):
        if self._pending is not None:
            return copy.deepcopy(self._pending)
        if self._phase == "done":
            return None
        if self._phase == "deletion":
            if self._index == len(self._active):
                self._minimality = "one_minimal" if all(row["outcome"] == "fail" for row in self._scan) else "unresolved"
                self._phase = "final_confirmation"
            elif self._attempts == self._limit or not self._budget._reserve(DELETE_PHASE, 4):
                self._minimality, self._phase = "budget_truncated", "final_confirmation"
            else:
                removed = self._active[self._index]
                retained = [op for op in self._active if op != removed]
                self._pending = self._request("deletion", retained, removed, 1)
                self._attempts += 1
                return copy.deepcopy(self._pending)
        if not self._budget._reserve("final_three_repeat_runs", 12):
            self._phase = "done"
            self._final = {"outcome": "unresolved", "reason": "final_confirmation_budget_exhausted"}
            return None
        self._pending = self._request("final_confirmation", self._active, None, 3)
        return copy.deepcopy(self._pending)

    def record_result(self, qualification_receipt):
        if self._pending is None:
            raise ValueError("no_pending_minimization_proposal")
        qualified = _qualification(qualification_receipt, self._pending, self._seen_runs, self._seen_containers)
        record = {"request": copy.deepcopy(self._pending), **qualified}
        self._seen_runs.update(qualified["runtime_receipt_paths"])
        self._seen_containers.update(qualified["container_ids"])
        self._records.append(record)
        if self._pending["phase"] == "final_confirmation":
            self._final, self._phase = qualified, "done"
        elif qualified["outcome"] == "pass":
            self._active = list(self._pending["retained_operation_ids"])
            self._current_receipt = qualified["qualification_receipt"]
            self._index, self._scan = 0, []
        else:
            self._scan.append({"removed_operation_id": self._pending["removed_operation_id"], "outcome": qualified["outcome"]})
            self._index += 1
        self._pending = None
        return copy.deepcopy(record)

    def snapshot(self):
        candidate, indices = _projection(self._original, self._active)
        final_pass = self._final is not None and self._final["outcome"] == "pass"
        return copy.deepcopy({"schema": "tramask.deletion-minimization-state.v1", "phase": self._phase,
            "original_candidate": self._original, "retained_candidate": candidate,
            "retained_operation_ids": self._active, "original_edit_indices": indices,
            "initial_witness": self._initial, "records": self._records, "pending": self._pending,
            "deletion_attempts": self._attempts, "max_deletion_attempts": self._limit,
            "final_scan": self._scan, "minimality_status": self._minimality or "pending",
            "one_minimal": final_pass and self._minimality == "one_minimal",
            "global_minimality_claimed": False, "final_witness_confirmed": final_pass,
            "R2": final_pass, "R3": final_pass and self._final["oracle_qualified"],
            "E9": self._final.get("E9", {"status": "unresolved", "evidence": []}) if self._final else {"status": "unresolved", "evidence": []},
            "final_confirmation": self._final, "budget": self._budget.snapshot(),
            "executed_by_scheduler": False, "scientific_result_created": False})
