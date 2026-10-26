"""Audit existing TraMask replay evidence without executing subjects or models.

Writes a new fidelity_check.json under each active replay. Existing reports are
immutable: rerunning reuses an identical input audit or asks for a new filename.
This is a replay-eligibility aid, never a masking or correctness adjudication.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from tramask_pilot.corpus import RUN, calls
from tramask_pilot.fidelity import evaluate_replay
from tramask_pilot.runtime import TRANSPORT_FAILURE

VERSION = "tramask-replay-qualification-v1"
SOURCE_SUFFIXES = {".py", ".go", ".rs", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".c", ".cpp", ".h"}


def digest(path):
    sha = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


class Evidence:
    def __init__(self, case_directory):
        self.case_directory = Path(case_directory).resolve()
        self.receipts = {}
        self.issues = []

    def note(self, path):
        path = Path(path).resolve()
        self.receipts[str(path)] = {"path": str(path), "bytes": path.stat().st_size, "sha256": digest(path)}
        return self.receipts[str(path)]

    def read(self, path, *, optional=False):
        path = Path(path)
        if optional and not path.exists():
            return None
        value = json.loads(path.read_text())
        self.note(path)
        return value

    def replay_path(self, value):
        path = Path(value)
        path = (self.case_directory / path).resolve() if not path.is_absolute() else path.resolve()
        if not path.is_relative_to(self.case_directory):
            raise ValueError("Replay ancestry points outside its case evidence directory")
        return path

    def verify_receipt(self, expected, *, description):
        if not isinstance(expected, dict) or not expected.get("path") or not expected.get("sha256"):
            self.issues.append(description + ":missing_receipt")
            return False
        path = Path(expected["path"])
        if not path.resolve().is_relative_to(self.case_directory):
            self.issues.append(description + ":receipt_path_outside_case_evidence")
            return False
        if not path.is_file():
            self.issues.append(description + ":missing_file")
            return False
        actual = self.note(path)
        if actual["sha256"] != expected["sha256"]:
            self.issues.append(description + ":hash_mismatch")
            return False
        return True


def has_pipeline(command):
    """Conservative shell-token detection; heredoc parsing still needs review."""
    try:
        lexer = shlex.shlex(command, posix=False, punctuation_chars="|&")
        lexer.whitespace_split = True
        return any(token in {"|", "|&"} for token in lexer)
    except ValueError:
        return "|" in command


def source_write_risk(command, source_paths):
    hits = []
    if re.search(r"\bgit\s+(?:-[^\s]+\s+\S+\s+)*(?:apply|reset|checkout|restore|clean|stash|merge|rebase)\b", command):
        hits.append("git_source_state_mutation")
    if re.search(r"apply_patch|\bsed\s+-[^\n]*i|\bperl\s+-[^\n]*i|write_text\s*\(|write_bytes\s*\(|\bopen\([^\n]*['\"](?:w|a)", command):
        hits.append("possible_source_edit_program")
    for path in source_paths:
        if path in command and re.search(r"\b(?:cp|mv|rm)\s|(?<![<>&])>(?![>&])", command):
            hits.append("write_like_command_mentions_target_source:" + path)
    return sorted(set(hits))


def ancestry(evidence, active_directory):
    ordered, visiting, seen = [], set(), set()
    def visit(directory):
        directory = evidence.replay_path(directory)
        if directory in visiting:
            raise ValueError("Cycle in replay recovery ancestry")
        if directory in seen:
            return
        visiting.add(directory)
        summary = evidence.read(directory / "summary.json", optional=True) or {}
        recovery = evidence.read(directory / "recovery.json", optional=True) or summary.get("inherited_restoration")
        if recovery:
            parent = recovery.get("original_replay")
            if not parent:
                evidence.issues.append("recovery_parent_missing:" + directory.name)
            else:
                evidence.verify_receipt(recovery.get("checkpoint_receipt"), description="inherited_checkpoint")
                visit(parent)
        visiting.remove(directory)
        seen.add(directory)
        ordered.append({"directory": directory, "summary": summary, "recovery": recovery})
    visit(active_directory)
    return ordered


def chain_records(evidence, chain, original_actions):
    rows, omissions, lifecycles, missing = [], [], [], []
    for entry in chain:
        directory = entry["directory"]
        progress = evidence.read(directory / "progress.json", optional=True)
        actual_records = evidence.read(directory / "historical/records.json", optional=True)
        if progress:
            omissions.extend({"directory": str(directory), **row} for row in progress.get("records", []) if "execution" not in row)
        if actual_records is None and progress:
            actual_records = [row["execution"] for row in progress.get("records", []) if "execution" in row]
        if actual_records is None:
            missing.append(str(directory / "historical/records.json"))
            actual_records = []
        for actual in actual_records:
            call_id = actual.get("label")
            archived = original_actions.get(call_id)
            expected = archived.get("expected") if archived else None
            fidelity = evaluate_replay(actual, expected)
            transport_text = str(actual.get("stdout", "")) + str(actual.get("stderr", ""))
            detected_transport = bool(actual.get("transport_error") or
                                      (actual.get("returncode") and TRANSPORT_FAILURE.search(transport_text)))
            row = {"directory": str(directory), "call_id": call_id,
                   "command_sha256": hashlib.sha256(actual.get("command", "").encode()).hexdigest(),
                   "recorded_command_matches_archive": bool(archived and actual.get("command") == archived["command"]),
                   "returncode": actual.get("returncode"), "expected_returncode": (expected or {}).get("returncode"),
                   "nonzero": actual.get("returncode") not in (0, None),
                   "returncode_mismatch": fidelity.get("returncode_match") is False,
                   "timed_out": bool(actual.get("timed_out")), "transport_error": detected_transport,
                   "pipeline": has_pipeline(actual.get("command", "")),
                   "restoration_deviation": actual.get("restoration_deviation"),
                   "prior_restoration_deviations": actual.get("prior_restoration_deviations", []),
                   "output_classification": fidelity["classification"],
                   "archive_completeness": fidelity.get("archive_completeness", "unknown"),
                   "needs_manual_review": fidelity["needs_manual_review"],
                   "comparison_reasons": fidelity["reasons"],
                   "raw_result_path": str(directory / "historical/calls" / str(call_id) / "result.json")}
            rows.append(row)
        container = evidence.read(directory / "historical/container.json", optional=True)
        if container:
            lifecycles.extend({"directory": str(directory), **event} for event in container.get("lifecycle", []))
    return rows, omissions, lifecycles, missing


def bundle(evidence, directory):
    """Verify frozen bundle receipts; never extract an archive onto the host."""
    directory = Path(directory)
    manifest = evidence.read(directory / "manifest.json", optional=True)
    receipt = evidence.read(directory / "receipt.json", optional=True)
    archive = directory / "sources.tar.gz"
    result = {"directory": str(directory), "manifest": manifest, "archive": archive,
              "receipt_integrity": True, "exists": bool(manifest is not None and archive.is_file())}
    if not result["exists"]:
        evidence.issues.append("missing_source_bundle:" + str(directory))
        result["receipt_integrity"] = False
        return result
    actual_archive = evidence.note(archive)
    if not receipt:
        evidence.issues.append("missing_bundle_receipt:" + str(directory))
        result["receipt_integrity"] = False
    else:
        for key, path in (("archive", archive), ("manifest", directory / "manifest.json")):
            if evidence.note(path)["sha256"] != receipt.get(key + "_sha256"):
                evidence.issues.append("bundle_hash_mismatch:" + str(path))
                result["receipt_integrity"] = False
    result["archive_sha256"] = actual_archive["sha256"]
    return result


def archive_file_hash(archive, member_name):
    with tarfile.open(archive, "r:*") as handle:
        members = [member for member in handle if member.name == member_name]
        if len(members) != 1 or not members[0].isfile():
            return None
        stream = handle.extractfile(members[0])
        sha = hashlib.sha256()
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(data)
        return sha.hexdigest()


def test_snapshot_checks(evidence, replay_directory, primary, summary):
    snapshot = evidence.read(replay_directory / "test_snapshot.json", optional=True)
    if not snapshot:
        return {"verified": False, "reason": "test_snapshot_missing", "files": []}, None, None
    evidence.verify_receipt(summary.get("test_snapshot"), description="test_snapshot_manifest")
    historical = bundle(evidence, replay_directory / "historical_sources")
    final = bundle(evidence, replay_directory / "final_sources")
    results = []
    for item in snapshot.get("files", []):
        local_valid = evidence.verify_receipt(item, description="test_source:" + str(item.get("subject_path")))
        result = {"subject_path": item.get("subject_path"), "snapshot_sha256": item.get("sha256"),
                  "local_snapshot_receipt_matches": local_valid}
        for name, source in (("historical", historical), ("final", final)):
            rows = [row for row in (source.get("manifest") or {}).get("files", []) if row.get("path") == item.get("subject_path")]
            row = rows[0] if len(rows) == 1 else None
            actual_hash = (archive_file_hash(source["archive"], row["archive_path"])
                           if source["exists"] and row and row.get("kind") == "file" else None)
            result[name + "_manifest_sha256"] = row.get("sha256") if row else None
            result[name + "_archive_sha256"] = actual_hash
            result[name + "_test_bytes_match"] = bool(local_valid and row and actual_hash == item.get("sha256")
                                                       and row.get("sha256") == actual_hash and source["receipt_integrity"])
        results.append(result)
    requested = set(primary.get("test_paths", []))
    found = {row["subject_path"] for row in results}
    inline = not requested and bool(re.search(r"\b(?:python\w*|node|ruby|bash)\b[^\n]*<<", snapshot.get("command", "")))
    verified = (bool(results) and requested == found and all(row["historical_test_bytes_match"] and row["final_test_bytes_match"] for row in results))
    if inline:
        verified = (snapshot.get("command") == summary.get("historical_test_only", {}).get("command")
                    == summary.get("final_test_only", {}).get("command"))
    return {"verified": bool(verified), "files": results, "requested_paths_match": requested == found,
            "inline_command_is_snapshot": inline,
            "limits": "Matching bytes do not prove these tests were collected or reached the target."}, historical, final


def qualify(case_directory, *, output_name="fidelity_check.json", write_report=True):
    from tramask_pilot.context_repair import test_paths_with_addendum
    case_directory = Path(case_directory).resolve()
    evidence = Evidence(case_directory)
    evidence.note(Path(__file__))
    evidence.note(ROOT / "src/tramask_pilot/fidelity.py")
    active = evidence.read(case_directory / "active_replay.json")
    replay_directory = evidence.replay_path(active["directory"])
    evidence.verify_receipt(active.get("summary"), description="active_summary")
    summary = evidence.read(replay_directory / "summary.json")
    selection_path = case_directory / "localization/selection.json"
    selection = evidence.read(selection_path)
    primary = dict(selection.get("primary") or {})
    primary["test_paths"], addendum = test_paths_with_addendum(case_directory, primary.get("test_paths", []))
    if addendum:
        evidence.verify_receipt(addendum, description="additional_historical_test_paths")
    review = evidence.read(case_directory / "localization/command_review.json", optional=True) or {}
    trajectory = evidence.read(case_directory.parent.parent / "inputs" / case_directory.name / "trajectory.json")
    actions = calls(trajectory)
    indexed = {action["id"]: action for action in actions}
    chosen_id = summary.get("selected_call") or primary.get("execution_call_id")
    chosen = indexed.get(chosen_id)
    expected = chosen.get("expected") if chosen else None
    fidelity = evaluate_replay(summary, expected)
    chain = ancestry(evidence, replay_directory)
    records, omissions, lifecycle, missing = chain_records(evidence, chain, indexed)
    covered_ids = {row["call_id"] for row in records} | {row.get("id") for row in omissions}
    required_ids = [action["id"] for action in actions[:actions.index(chosen) + 1]] if chosen else []
    unrecorded_ids = [call_id for call_id in required_ids if call_id not in covered_ids]
    snapshots, historical, final = test_snapshot_checks(evidence, replay_directory, primary, summary)
    command = review.get("test_command", primary.get("test_command", ""))
    commands = {name: summary.get(name, {}).get("command") for name in
                ("original_command_execution", "historical_test_only", "final_test_only")}
    command_checks = {
        "selected_action_matches_localization": chosen_id == primary.get("execution_call_id"),
        "review_matches_frozen_selection": review.get("approved_for_isolated_replay") is True and review.get("selection_sha256") == digest(selection_path),
        "original_command_matches_archive": bool(chosen and commands["original_command_execution"] == chosen["command"]),
        "test_command_is_recorded_suffix": bool(chosen and command and chosen["command"].strip().endswith(command.strip())),
        "historical_and_final_use_reviewed_command": bool(command and commands["historical_test_only"] == commands["final_test_only"] == command),
        "localizer_claims_test_only": primary.get("command_is_test_only") is True,
        "creation_calls_exist_before_execution": bool(primary.get("creation_call_ids")) and all(
            call_id in indexed and chosen and actions.index(indexed[call_id]) <= actions.index(chosen)
            for call_id in primary.get("creation_call_ids", [])),
    }
    risks = [{"kind": value, "scope": "selected_test_command"} for value in source_write_risk(command, primary.get("source_paths", []))]
    if historical and historical.get("manifest"):
        after_path = (summary.get("after_original_call") or {}).get("manifest")
        after = evidence.read(evidence.replay_path(after_path), optional=True) if after_path else None
        before_rows = {row["path"]: row for row in historical["manifest"]["files"]}
        after_rows = {row["path"]: row for row in (after or {}).get("files", [])}
        for path in primary.get("source_paths", []):
            absolute = "/app/" + path
            before, later = before_rows.get(absolute), after_rows.get(absolute)
            if not before or not later or before.get("kind") != "file" or later.get("kind") != "file":
                risks.append({"kind": "target_source_snapshot_missing", "path": absolute})
            elif before.get("sha256") != later.get("sha256"):
                risks.append({"kind": "target_source_changed_during_selected_execution", "path": absolute,
                              "before_sha256": before.get("sha256"), "after_sha256": later.get("sha256")})
    else:
        risks.append({"kind": "historical_source_bundle_missing"})
    applied = replay_directory / "final/patches/submitted_patch/implementation.patch"
    submitted = case_directory.parent.parent / "inputs" / case_directory.name / "model.patch"
    patch_result = evidence.read(applied.parent / "result.json", optional=True)
    source_provenance = {"submitted_patch_bytes_match": applied.is_file() and submitted.is_file() and
                         evidence.note(applied)["sha256"] == evidence.note(submitted)["sha256"],
                         "patch_apply_returncode": (patch_result or {}).get("returncode")}
    counts = {"ancestry_directories": len(chain), "executed_actions": len(records), "omitted_actions": len(omissions),
              "timeouts": sum(row["timed_out"] for row in records),
              "oci_or_transport_failures": sum(row["transport_error"] for row in records),
              "nonzero_returncodes": sum(row["nonzero"] for row in records),
              "returncode_mismatches": sum(row["returncode_mismatch"] for row in records),
              "nonzero_returncode_mismatches": sum(row["returncode_mismatch"] and row["nonzero"] for row in records),
              "output_mismatches": sum(row["output_classification"] == "mismatch" for row in records),
              "pipelines": sum(row["pipeline"] for row in records),
              "archived_excerpts": sum(row["archive_completeness"] == "excerpt" for row in records),
              "process_state_resets": sum(bool(event.get("process_state_reset")) for event in lifecycle),
              "source_mutation_risks": len(risks)}
    counts["unrecorded_restoration_actions"] = len(unrecorded_ids)
    counts["historical_rerun_timeouts"] = int(bool(summary.get("historical_test_only", {}).get("timed_out")))
    counts["final_test_timeouts"] = int(bool(summary.get("final_test_only", {}).get("timed_out")))
    counts["post_restoration_transport_failures"] = sum(bool(summary.get(name, {}).get("transport_error"))
                                                       for name in ("historical_test_only", "final_test_only"))
    manual = []
    if fidelity["needs_manual_review"]:
        manual.append("selected_output_requires_manual_review")
    if counts["pipelines"] or has_pipeline(command):
        manual.append("pipeline_exit_status_or_output_filter_requires_review")
    if counts["process_state_resets"] or any(row["restoration_deviation"] or row["prior_restoration_deviations"] for row in records):
        manual.append("restoration_chain_process_state_was_reset")
    if counts["archived_excerpts"] or fidelity.get("archive_completeness") == "excerpt":
        manual.append("archived_output_is_truncated")
    if counts["timeouts"] or counts["oci_or_transport_failures"] or counts["returncode_mismatches"]:
        manual.append("restoration_chain_execution_deviation")
    if counts["output_mismatches"]:
        manual.append("restoration_output_differences_need_relevance_review")
    if not all(command_checks.values()) or unrecorded_ids or any(not row["recorded_command_matches_archive"] for row in records):
        manual.append("command_or_authored_test_provenance_uncertain")
    if counts["historical_rerun_timeouts"] or counts["final_test_timeouts"] or counts["post_restoration_transport_failures"]:
        manual.append("historical_or_final_test_execution_failed_at_runtime")
    if not snapshots["verified"]:
        manual.append("test_snapshot_bytes_not_fully_verified")
    if risks:
        manual.append("selected_execution_source_mutation_risk")
    if missing or evidence.issues:
        manual.append("missing_or_changed_evidence_receipts")
    if not source_provenance["submitted_patch_bytes_match"] or source_provenance["patch_apply_returncode"] != 0:
        manual.append("final_source_patch_provenance_unverified")
    if not fidelity["actual_test_evidence"]["observed_test_evidence"]:
        manual.append("test_collection_and_assertions_need_manual_confirmation")
    result = {"version": VERSION, "case_id": case_directory.name, "active_replay": str(replay_directory),
              "selected_call": chosen_id, "selected_output_fidelity": fidelity,
              "restoration_chain": [str(entry["directory"]) for entry in chain], "chain_counts": counts,
              "restoration_actions": records, "omissions": omissions, "lifecycle_events": lifecycle,
              "missing_chain_records": missing, "command_checks": command_checks,
              "unrecorded_restoration_action_ids": unrecorded_ids,
              "test_snapshot_checks": snapshots, "source_mutation_risks": risks,
              "final_source_provenance": source_provenance, "evidence_issues": evidence.issues,
              "needs_manual_review": bool(manual), "manual_review_reasons": sorted(set(manual)),
              "eligibility_suggestion": "pending_manual_review" if manual else "mechanical_checks_satisfied",
              "scientific_masking_verdict": None,
              "limits": "No scientific masking, target-exercise, oracle-validity, or defect claim is made. Historical nonzero commands and environmental output differences require relevance review; they are not silently treated as negative masking cases.",
              "evidence_receipts": sorted(evidence.receipts.values(), key=lambda item: item["path"])}
    result["audit_input_sha256"] = fingerprint({"version": VERSION, "receipts": result["evidence_receipts"]})
    target = replay_directory / output_name
    if write_report:
        if target.exists():
            previous = json.loads(target.read_text())
            if previous.get("audit_input_sha256") != result["audit_input_sha256"]:
                raise FileExistsError(f"Frozen qualification inputs changed; choose a new --output-name: {target}")
            return previous
        with target.open("x") as handle:
            handle.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--run", type=Path, default=RUN)
    parser.add_argument("--case", action="append", help="Default: all cases with active_replay.json")
    parser.add_argument("--output-name", default="fidelity_check.json")
    parser.add_argument("--dry-run", action="store_true", help="Read and report without writing qualification artifacts")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.json", args.output_name):
        parser.error("--output-name must be a simple JSON filename")
    directories = sorted(path.parent for path in (args.run / "runs").glob("*/active_replay.json"))
    if args.case:
        directories = [path for path in directories if path.name in set(args.case)]
    for directory in directories:
        try:
            result = qualify(directory, output_name=args.output_name, write_report=not args.dry_run)
            print(json.dumps({"case_id": directory.name, "status": result["eligibility_suggestion"],
                  "output_fidelity": result["selected_output_fidelity"]["classification"],
                  "chain_counts": result["chain_counts"], "manual_review_reasons": result["manual_review_reasons"],
                  "report": str(Path(result["active_replay"]) / args.output_name)}, ensure_ascii=False), flush=True)
        except (OSError, ValueError, KeyError, tarfile.TarError) as error:
            print(json.dumps({"case_id": directory.name, "status": "qualification_error", "error": str(error)}), flush=True)


if __name__ == "__main__":
    main()
