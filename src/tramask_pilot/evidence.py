"""Allowlisted public snapshot reads and blinded, pre-repair evidence packets.

No archive is extracted, no subject or provider is invoked, and no evaluator is
read. Missing selected paths are recorded rather than substituted with guessed
files. Model context excerpts and exact files used for staging are kept distinct.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tarfile

from .corpus import calls
from .hypotheses import _path, apply_exact_edits, build_request, parse_events, validate_hypothesis


class MissingEvidenceError(ValueError):
    def __init__(self, missing):
        self.missing = missing
        super().__init__("missing_or_unreadable_selected_evidence: " + json.dumps(missing, sort_keys=True))


def _read(path):
    return json.loads(Path(path).read_bytes())


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _replay_dir(case_dir):
    case_dir = Path(case_dir).resolve()
    pointer = case_dir / "active_replay.json"
    if not pointer.exists():
        return case_dir / "replay"
    directory = _read(pointer).get("directory")
    if not isinstance(directory, str) or not directory:
        raise ValueError("invalid_active_replay_pointer")
    path = Path(directory)
    path = (path if path.is_absolute() else case_dir / path).resolve()
    if not path.is_relative_to(case_dir) or path == case_dir:
        raise ValueError("active_replay_outside_case_directory")
    return path


def _subject_path(path, *, repository_relative=False):
    if not isinstance(path, str):
        raise ValueError("invalid_subject_path")
    value = "app/" + path if repository_relative else path.removeprefix("/")
    _path(value)
    if PurePosixPath(value).parts[0] not in {"app", "tmp"} or len(PurePosixPath(value).parts) < 2:
        raise ValueError("subject_path_must_be_under_app_or_tmp")
    return value


def read_archive_files(archive, allowlist, *, max_file_bytes=2_000_000, max_total_bytes=8_000_000):
    """Read only explicitly named regular UTF-8 members, without extract/extractall.

    Returns files, hashes, and missing/rejected entries. Unrequested members are
    never opened, including unrequested hidden files, symlinks and special files.
    Duplicate names are rejected rather than relying on tar's last-match rule.
    """
    requested = list(dict.fromkeys(_subject_path(name) for name in allowlist))
    result = {"files": {}, "records": [], "missing": []}
    archive = Path(archive)
    if not archive.is_file():
        result["missing"] = [{"path": name, "reason": "archive_missing"} for name in requested]
        return result
    spent = 0
    try:
        with tarfile.open(archive, "r:*") as stream:
            members = {name: [] for name in requested}
            for member in stream:
                if member.name in members:
                    members[member.name].append(member)
            for name in requested:
                found = members[name]
                reason = None
                if not found:
                    reason = "member_missing"
                elif len(found) != 1:
                    reason = "duplicate_archive_member"
                elif not found[0].isfile() or found[0].issym() or found[0].islnk():
                    reason = "member_not_regular_file"
                elif found[0].size < 0 or found[0].size > max_file_bytes or spent + found[0].size > max_total_bytes:
                    reason = "selected_file_size_limit"
                if reason:
                    result["missing"].append({"path": name, "reason": reason})
                    continue
                handle = stream.extractfile(found[0])
                if handle is None:
                    result["missing"].append({"path": name, "reason": "member_unreadable"})
                    continue
                with handle:
                    raw = handle.read(max_file_bytes + 1)
                spent += len(raw)
                if len(raw) != found[0].size:
                    result["missing"].append({"path": name, "reason": "member_size_mismatch"})
                    continue
                try:
                    content = raw.decode("utf-8")
                except UnicodeDecodeError:
                    result["missing"].append({"path": name, "reason": "not_utf8_text"})
                    continue
                if "\0" in content:
                    result["missing"].append({"path": name, "reason": "binary_nul_in_text"})
                    continue
                result["files"][name] = content
                result["records"].append({"path": name, "bytes": len(raw), "sha256": _sha(raw)})
    except (OSError, tarfile.TarError) as exc:
        result["missing"].append({"path": "<archive>", "reason": "archive_read_error", "error_type": type(exc).__name__})
    return result


def _selection(case_dir):
    from .context_repair import test_paths_with_addendum
    case_dir = Path(case_dir)
    selection_path = case_dir / "localization/selection.json"
    selection = _read(selection_path)
    if selection.get("status") != "located" or not isinstance(selection.get("primary"), dict):
        raise MissingEvidenceError([{"path": "selection.primary", "reason": "no_selected_test"}])
    review = _read(case_dir / "localization/command_review.json")
    if review.get("approved_for_isolated_replay") is not True or review.get("selection_sha256") != _sha(selection_path.read_bytes()):
        raise ValueError("selection_lacks_matching_command_review")
    primary = dict(selection["primary"])
    primary["test_paths"], addendum = test_paths_with_addendum(case_dir, primary.get("test_paths", []))
    command = review.get("test_command", primary.get("test_command"))
    snapshot = _read(_replay_dir(case_dir) / "test_snapshot.json")
    if addendum and (snapshot.get("test_context_addendum") or {}).get("sha256") != addendum["sha256"]:
        raise ValueError("test_context_addendum_not_bound_to_snapshot")
    if not isinstance(command, str) or not command or snapshot.get("command") != command.strip():
        raise ValueError("snapshot_command_differs_from_reviewed_command")
    primary["test_command"] = snapshot["command"]
    primary["working_directory"] = snapshot.get("working_directory", "/app")
    primary["observation_paths"] = snapshot.get("observation_paths", [])
    sources = [_subject_path(p, repository_relative=True) for p in primary.get("source_paths", [])]
    tests = [_subject_path(p) for p in primary.get("test_paths", [])]
    receipts = {_subject_path(row["subject_path"]): row for row in snapshot.get("files", [])}
    if set(receipts) != set(tests):
        raise ValueError("selected_tests_and_snapshot_receipts_differ")
    return primary, sources, tests, receipts


def _selected_files(case_dir, state):
    if state not in {"final", "historical"}:
        raise ValueError("state_must_be_final_or_historical")
    primary, sources, tests, receipts = _selection(case_dir)
    replay = _replay_dir(case_dir)
    original_archive = replay / (state + "_sources") / "sources.tar.gz"
    result = read_archive_files(original_archive, sources + tests)
    provenance = {"original_archive": original_archive.relative_to(Path(case_dir).resolve()).as_posix()
                  if original_archive.is_absolute() else original_archive.as_posix(),
                  "original_archive_sha256": _sha(original_archive.read_bytes()) if original_archive.is_file() else None,
                  "original_missing": list(result["missing"])}
    supplement_archive = replay / (state + "_sources_supplement01") / "sources.tar.gz"
    if supplement_archive.is_file():
        supplement = read_archive_files(supplement_archive, sources + tests)
        original_records = {row["path"]: row for row in result["records"]}
        supplemental_records = {row["path"]: row for row in supplement["records"]}
        merged, records, missing = {}, [], []
        for path in dict.fromkeys(sources + tests):
            if path in supplement["files"]:
                merged[path] = supplement["files"][path]
                records.append({**supplemental_records[path], "archive_role": "checkpoint_explicit_path_supplement"})
            elif path in result["files"]:
                merged[path] = result["files"][path]
                records.append({**original_records[path], "archive_role": "original_snapshot"})
            else:
                missing.append({"path": path, "reason": "missing_from_original_and_supplement",
                                "original": [r for r in result["missing"] if r["path"] in {path, "<archive>"}],
                                "supplement": [r for r in supplement["missing"] if r["path"] in {path, "<archive>"}]})
        provenance.update(supplement_archive=supplement_archive.relative_to(Path(case_dir).resolve()).as_posix(),
                          supplement_archive_sha256=_sha(supplement_archive.read_bytes()),
                          supplement_missing=supplement["missing"],
                          explanation="Explicit selected paths re-exported from the pinned original/final context checkpoint because checkpoint-derived baseline_untracked filtering omitted historical production additions. Supplemental bytes take precedence when present; originals remain recorded.")
        result = {"files": merged, "records": records, "missing": missing}
    for path in tests:
        content = result["files"].get(path)
        if content is not None and _sha(content.encode()) != receipts[path].get("sha256"):
            result["missing"].append({"path": path, "reason": "original_test_hash_mismatch"})
            del result["files"][path]
    return {**result, "primary": primary, "source_paths": sources, "test_paths": tests,
            "archive_provenance": provenance}


def selected_tree_files(case_dir, *, state="final"):
    """Return exact selected source/test text for a small P/Q staging tree.

    Dependencies stay in the checkpoint container. This helper intentionally
    raises MissingEvidenceError with a machine-readable .missing list if any
    selected path is absent; it neither guesses a replacement nor queries a model.
    """
    selected = _selected_files(case_dir, state)
    if selected["missing"]:
        raise MissingEvidenceError(selected["missing"])
    return selected["files"]


def _clip(text, limit):
    raw = text.encode()
    return raw[:limit].decode("utf-8", errors="ignore"), len(raw) > limit


def _patch_centers(patch, *, historical=False):
    centers, current = {}, None
    for line in patch.splitlines():
        if line.startswith("diff --git a/"):
            match = re.match(r"diff --git a/(.+) b/(.+)$", line)
            current = "app/" + match.group(1 if historical else 2) if match else None
        elif current and line.startswith("@@ "):
            match = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)", line)
            if match:
                centers.setdefault(current, []).append(int(match.group(1 if historical else 2)))
    return centers


def _function_ranges(path, text):
    """Recover straightforward Python/Go function envelopes for context only."""
    if path.endswith(".py"):
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return []
        return [(min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1, node.end_lineno)
                for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.end_lineno is not None]
    if path.endswith(".go"):
        lines = text.splitlines()
        ranges = []
        for start, line in enumerate(lines):
            if not re.match(r"^func\b.*\{", line):
                continue
            if line.rstrip().endswith("}"):
                ranges.append((start, start + 1))
                continue
            end = next((i + 1 for i in range(start + 1, len(lines))
                        if re.fullmatch(r"}\s*(?://.*)?", lines[i])), None)
            if end is not None:
                ranges.append((start, end))
        return ranges
    return []


def _contexts(files, patch, target, budget, *, historical=False):
    """Choose exact full lines; source excerpts are labeled metadata, never code."""
    contexts, records = {}, []
    if sum(len(text.encode()) for text in files.values()) <= budget:
        return dict(files), [{"path": path, "complete": True,
                              "selected_lines": [[1, len(text.splitlines())]]}
                             for path, text in files.items()]
    centers = _patch_centers(patch, historical=historical)
    words = list(dict.fromkeys(re.findall(r"[A-Za-z_][A-Za-z_0-9]{4,}", target)))
    per_file = max(1, budget // max(1, len(files)))
    for path, text in files.items():
        if len(text.encode()) <= per_file:
            contexts[path] = text
            records.append({"path": path, "complete": True, "selected_lines": [[1, len(text.splitlines())]]})
            continue
        lines = text.splitlines(keepends=True)
        focus = list(centers.get(path, []))
        focus += [i + 1 for i, line in enumerate(lines) if any(re.search(r"\b" + re.escape(w) + r"\b", line) for w in words)]
        selected, spent = set(), 0
        complete_functions = []
        for start, end in _function_ranges(path, text):
            if not any(start <= center - 1 < end for center in focus):
                continue
            added = set(range(start, end)) - selected
            size = sum(len(lines[index].encode()) for index in added)
            if spent + size <= per_file:
                selected.update(added)
                spent += size
                complete_functions.append([start + 1, end])
        # Nearest lines to patch/target anchors first; imports are a last fallback.
        order = []
        for radius in range(19):
            for center in focus or [1]:
                order.extend([center - 1 - radius, center - 1 + radius])
        order.extend(range(min(20, len(lines))))
        for index in dict.fromkeys(order):
            if 0 <= index < len(lines) and index not in selected and spent + len(lines[index].encode()) <= per_file:
                selected.add(index)
                spent += len(lines[index].encode())
        ranges = []
        for index in sorted(selected):
            if ranges and index == ranges[-1][1]:
                ranges[-1][1] += 1
            else:
                ranges.append([index, index + 1])
        contexts[path] = "\n".join(f"<source_excerpt lines='{start + 1}-{end}'>\n{''.join(lines[start:end])}</source_excerpt>" for start, end in ranges)
        records.append({"path": path, "complete": False, "selected_lines": [[a + 1, b] for a, b in ranges],
                        "complete_function_ranges": complete_functions,
                        "omitted_lines": len(lines) - len(selected), "source_sha256": _sha(text.encode())})
    return contexts, records


_PRIVATE_COMMAND = re.compile(r"(?:evaluation_assets|hidden_tests|reference_solutions?|reward\.txt|(?:^|[\s'\"])/tests/|(?:^|[/\s])\.env(?:[.\s]|$))", re.I)


def _relevant_actions(document, primary, paths, *, max_actions, max_command_bytes, max_output_bytes):
    actions = calls(document)
    mandatory = set(primary.get("creation_call_ids", [])) | {primary["execution_call_id"]}
    needles = list(dict.fromkeys([p.removeprefix("app/") for p in paths] + [PurePosixPath(p).name for p in paths]))
    selected_index = next((i for i, a in enumerate(actions) if a["id"] == primary["execution_call_id"]), None)
    if selected_index is None:
        raise ValueError("selected_execution_missing_from_public_actions")
    eligible, exclusions = [], []
    for index, action in enumerate(actions):
        if _PRIVATE_COMMAND.search(action["command"]):
            exclusions.append({"id": action["id"], "reason": "private_or_evaluator_command"})
        elif action["id"] in mandatory or any(needle in action["command"] for needle in needles):
            eligible.append((index, action))
    prioritized = sorted(eligible, key=lambda row: (row[1]["id"] not in mandatory, abs(row[0] - selected_index), row[0]))
    chosen = {row[0] for row in prioritized[:max_actions]}
    public, truncations = [], []
    for index, action in eligible:
        if index not in chosen:
            exclusions.append({"id": action["id"], "reason": "relevant_action_count_limit"})
            continue
        command, command_cut = _clip(action["command"], max_command_bytes)
        expected = action.get("expected") or {}
        raw_output = expected.get("output", "")
        output, output_cut = _clip(raw_output if isinstance(raw_output, str) else "", max_output_bytes)
        row = {"id": action["id"], "command": command, "output": output}
        if type(expected.get("returncode")) is int:
            row["returncode"] = expected["returncode"]
        public.append(row)
        if command_cut or output_cut:
            truncations.append({"id": action["id"], "command_truncated": command_cut, "output_truncated": output_cut})
    return public, {"ordering": "original chronological order; mandatory and nearest selected execution retained under cap",
                    "included_ids": [a["id"] for a in public], "exclusions": exclusions, "truncations": truncations}


def build_hypothesis_packet(case_dir, input_dir, *, case_id=None, source_context_bytes=200000,
                            historical_context_bytes=24000, max_actions=20,
                            max_command_bytes=4000, max_output_bytes=1000, max_test_bytes=100000):
    """Build deterministic public inputs plus a ready hypotheses/provider request.

    Missing selected paths return status='incomplete_evidence', missing details,
    and request=None. No artifacts are modified. Context excerpt labels are not
    part of source code, and full originals remain available via selected_tree_files.
    """
    case_dir, input_dir = Path(case_dir), Path(input_dir)
    final = _selected_files(case_dir, "final")
    historical = _selected_files(case_dir, "historical")
    missing = [{"state": state, **row} for state, result in (("final", final), ("historical", historical)) for row in result["missing"]]
    primary = final["primary"]
    tests = {p: final["files"][p] for p in final["test_paths"] if p in final["files"]}
    if sum(len(text.encode()) for text in tests.values()) > max_test_bytes:
        missing.append({"state": "selected_test", "path": "<test files>", "reason": "test_context_size_limit"})
    issue = (input_dir / "instruction.md").read_bytes().decode("utf-8")
    patch = (input_dir / "model.patch").read_bytes().decode("utf-8")
    target_anchor = primary.get("target_anchor", "")
    if not isinstance(target_anchor, str):
        target_anchor = json.dumps(target_anchor, sort_keys=True)
    target = {"target": primary.get("target", ""), "target_anchor": target_anchor,
              "execution_call_id": primary["execution_call_id"]}
    selected_test = {"command": primary["test_command"], "working_directory": primary["working_directory"],
                     "observation_paths": primary["observation_paths"], "files": tests, **target}
    contexts = {}
    selections = {}
    for state, result, budget in (("final", final, source_context_bytes), ("historical", historical, historical_context_bytes)):
        sources = {p: result["files"][p] for p in result["source_paths"] if p in result["files"]}
        contexts[state], selections[state] = _contexts(sources, patch, target_anchor, budget, historical=state == "historical")
    actions, action_selection = _relevant_actions(_read(input_dir / "trajectory.json"), primary,
                                                  final["source_paths"] + final["test_paths"], max_actions=max_actions,
                                                  max_command_bytes=max_command_bytes, max_output_bytes=max_output_bytes)
    packet = {"status": "incomplete_evidence" if missing else "ready", "case_id": case_id or case_dir.name,
              "issue": issue, "final_patch": patch, "selected_test": selected_test,
              "final_sources": contexts["final"], "historical_sources": contexts["historical"],
              "actions": actions, "source_context_selection": selections, "action_selection": action_selection,
              "source_records": {"final": final["records"], "historical": historical["records"]},
              "archive_provenance": {"final": final["archive_provenance"], "historical": historical["archive_provenance"]},
              "missing": missing, "request": None}
    if not missing:
        request = build_request(packet["case_id"], issue=issue, final_patch=patch, selected_test=selected_test,
                                final_sources=contexts["final"], actions=actions)
        prompt = json.loads(request["prompt"])
        prompt.update(historical_sources=contexts["historical"], source_context_selection=selections,
                      action_selection=action_selection,
                      source_excerpt_policy="source_excerpt wrappers and line numbers are metadata, not file bytes. Use exact code inside an excerpt for anchors; never span omitted regions or invent missing context.")
        request["prompt"] = json.dumps(prompt, ensure_ascii=False, sort_keys=True)
        packet["request"] = request
    return packet


def _public_hypothesis(hypothesis):
    validate_hypothesis(hypothesis)
    if hypothesis["status"] != "proposed":
        return {"status": hypothesis["status"], "reason": hypothesis["reason"]}
    probe = hypothesis["instrumentation"]
    return {"status": "proposed", "reason": hypothesis["reason"], "original_command": hypothesis["original_command"],
            "target": {k: hypothesis["target"][k] for k in ("behavior", "source_path", "anchor", "logical_effect", "public_observation")},
            "alternative": {k: hypothesis["alternative"][k] for k in ("kind", "rationale", "action_ids", "edits")},
            "instrumentation": {k: probe[k] for k in ("shared_anchors", "common_edits", "p_edits", "q_edits", "helper_files", "command", "noninterference")}}


def _project_public(value, schema, redact):
    """Project a declared schema; never recursively copy unknown metadata."""
    if schema is None:
        if isinstance(value, str):
            return redact(value)
        return value if value is None or type(value) in {bool, int, float} else None
    if isinstance(schema, list):
        return [_project_public(item, schema[0], redact) for item in value] if isinstance(value, list) else []
    if not isinstance(value, dict):
        return {}
    return {key: _project_public(value[key], child, redact) for key, child in schema.items() if key in value}


_DEVIATION_SCHEMA = dict.fromkeys((
    "event", "filesystem_preserved", "process_state_reset", "restoration_deviation",
    "success", "returncode", "error", "check_returncode", "head_after_restart"))
_TEST_EVIDENCE_SCHEMA = {
    "observed_test_evidence": None, "limits": None,
    "summaries": [{"runner": None, "text": None, "tests": None, "counts": [[None]]}],
    "identities": [dict.fromkeys(("runner", "id", "status", "cached", "no_test_files"))],
    "assertion_lines": [None], "execution_blockers": [None],
}
_OUTPUT_FIDELITY_SCHEMA = {
    **dict.fromkeys(("version", "classification", "needs_manual_review", "supports_output_fidelity",
                    "actual_returncode", "expected_returncode", "returncode_match", "archive_completeness",
                    "output_relation", "escape_layer_hypothesis", "shell_returncode_is_not_test_verdict",
                    "possible_pipeline_status_masking", "source_restoration_verified_by_this_helper")),
    "reasons": [None], "normalization_rules": [None],
    "actual_test_evidence": _TEST_EVIDENCE_SCHEMA, "archive_test_evidence": _TEST_EVIDENCE_SCHEMA,
    "historical_test_only": {**dict.fromkeys(("returncode", "timed_out", "transport_error",
                                            "runner_evidence_matches_original", "scope")),
                             "evidence": _TEST_EVIDENCE_SCHEMA},
    "final_test_only": {"returncode": None, "scope": None, "evidence": _TEST_EVIDENCE_SCHEMA},
}
_QUALIFICATION_SCHEMA = {
    **dict.fromkeys(("version", "selected_call", "needs_manual_review", "eligibility_suggestion", "limits")),
    "selected_output_fidelity": _OUTPUT_FIDELITY_SCHEMA,
    "chain_counts": dict.fromkeys(("ancestry_directories", "executed_actions", "omitted_actions", "timeouts",
        "oci_or_transport_failures", "nonzero_returncodes", "returncode_mismatches", "nonzero_returncode_mismatches",
        "output_mismatches", "pipelines", "archived_excerpts", "process_state_resets", "source_mutation_risks",
        "unrecorded_restoration_actions", "historical_rerun_timeouts", "final_test_timeouts", "post_restoration_transport_failures")),
    "restoration_actions": [{**dict.fromkeys(("call_id", "command_sha256", "recorded_command_matches_archive",
        "returncode", "expected_returncode", "nonzero", "returncode_mismatch", "timed_out", "transport_error",
        "pipeline", "restoration_deviation", "output_classification", "archive_completeness", "needs_manual_review")),
        "prior_restoration_deviations": [_DEVIATION_SCHEMA], "comparison_reasons": [None]}],
    "lifecycle_events": [_DEVIATION_SCHEMA],
    "omissions": [dict.fromkeys(("id", "status"))],
    "missing_chain_records": [None], "unrecorded_restoration_action_ids": [None],
    "manual_review_reasons": [None], "evidence_issues": [None],
    "command_checks": dict.fromkeys(("selected_action_matches_localization", "review_matches_frozen_selection",
        "original_command_matches_archive", "test_command_is_recorded_suffix", "historical_and_final_use_reviewed_command",
        "localizer_claims_test_only", "creation_calls_exist_before_execution")),
    "test_snapshot_checks": {**dict.fromkeys(("verified", "reason", "requested_paths_match", "inline_command_is_snapshot", "limits")),
        "files": [dict.fromkeys(("subject_path", "snapshot_sha256", "local_snapshot_receipt_matches",
            "historical_manifest_sha256", "historical_archive_sha256", "historical_test_bytes_match",
            "final_manifest_sha256", "final_archive_sha256", "final_test_bytes_match"))]},
    "source_mutation_risks": [dict.fromkeys(("kind", "scope", "path", "before_sha256", "after_sha256"))],
    "final_source_provenance": dict.fromkeys(("submitted_patch_bytes_match", "patch_apply_returncode")),
}


def _redact_tree(value, redact):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [_redact_tree(item, redact) for item in value]
    if isinstance(value, dict):
        return {redact(key): _redact_tree(item, redact) for key, item in value.items()}
    return value


def _public_qualification(replay_directory, redact):
    """Read only the pre-repair replay qualification, with an explicit allowlist."""
    path = Path(replay_directory) / "fidelity_check.json"
    if path.is_symlink() or not path.is_file():
        return {"status": "qualification_unavailable", "needs_manual_review": True,
                "reason": "qualification_symlink_rejected" if path.is_symlink() else "fidelity_check_missing"}
    try:
        raw = path.read_bytes()
        document = json.loads(raw)
        if not isinstance(document, dict):
            raise ValueError("qualification_not_object")
    except (OSError, ValueError) as error:
        return {"status": "qualification_unreadable", "needs_manual_review": True,
                "error_type": type(error).__name__}
    technical_review = {}
    review_path = Path(replay_directory) / "fidelity_review.json"
    if review_path.is_file() and not review_path.is_symlink():
        review = _read(review_path)
        # Include the earlier replay-relevance reasoning, never a masking label.
        technical_review = {key: _redact_tree(review[key], redact) for key in
                            ("qualification_scope", "historical_basis", "reviewed", "deviation_adjudications", "decision")
                            if key in review}
    return {"status": "recorded_qualification", "source": {"name": "fidelity_check.json", "bytes": len(raw), "sha256": _sha(raw)},
            **_project_public(document, _QUALIFICATION_SCHEMA, redact),
            "technical_replay_reasoning": technical_review,
            "interpretation": "These are recorded replay-qualification findings, not a masking label or an independent correctness verdict."}


def _review_brief(primary, qualification, replay, traces):
    reasons = list(qualification.get("manual_review_reasons", []))
    if qualification.get("status") != "recorded_qualification":
        reasons.append("replay_qualification_unavailable")
    visible_resets = any(record.get("restoration_deviation") or record.get("prior_restoration_deviations") or
                        record.get("restart_after_timeout", {}).get("process_state_reset")
                        for record in [*replay.values(), *traces.values()])
    if visible_resets or qualification.get("chain_counts", {}).get("process_state_resets", 0):
        reasons.append("process_state_reset_requires_relevance_review")
    return {"stage": "read_only_pre_repair_review", "working_directory": primary["working_directory"],
            "observation_paths": primary.get("observation_paths", []),
            "read_order": ["selected_test.json", "replay_qualification.json", "replay.json", "hypothesis.json", "before_traces.json"],
            "recorded_review_requirements": sorted(set(reason for reason in reasons if isinstance(reason, str))),
            "limits": [
                "A later passing command does not undo an earlier process-state reset, timeout, or incomplete restoration.",
                "Output matching and test-file hashes alone do not establish equivalent source, live services, fixtures, collection, or target reachability.",
                "Inspect observation_files as well as stdout/stderr; file bytes are observations only when the unchanged original test consumes them.",
                "Compare original and instrumented P/Q executions for noninterference before interpreting target-effect and public-observation traces.",
                "Missing evidence remains missing. This packet provides no context-repair outcomes or other reviewer's judgments."]}


def _public_execution(record, redact):
    if not isinstance(record, dict):
        raise ValueError("before_execution_must_be_object")
    result = {}
    for key in ("command", "working_directory", "stdout", "stderr", "returncode", "timed_out", "transport_error", "elapsed_seconds", "timeout_seconds", "restoration_deviation"):
        value = record.get(key)
        if isinstance(value, str):
            result[key] = redact(value)
        elif value is None or type(value) in {bool, int, float}:
            result[key] = value
    if "prior_restoration_deviations" in record:
        result["prior_restoration_deviations"] = _project_public(record["prior_restoration_deviations"], [_DEVIATION_SCHEMA], redact)
    if isinstance(record.get("restart_after_timeout"), dict):
        result["restart_after_timeout"] = _project_public(record["restart_after_timeout"], _DEVIATION_SCHEMA, redact)
    activation = record.get("generated_runtime_activation")
    if isinstance(activation, dict) and isinstance(activation.get("execution"), dict):
        result["generated_runtime_activation"] = _public_execution(activation["execution"], redact)
    try:
        result["observation_files"] = [{k: (redact(v) if isinstance(v, str) else v)
            for k, v in row.items() if k in {"subject_path", "sha256", "bytes", "content", "truncated", "error"}}
            for row in record.get("observation_files", [])]
        result["events"] = (parse_events(result.get("stdout") or "") + parse_events(result.get("stderr") or "") +
            parse_events("\n".join(row.get("content", "") for row in result["observation_files"])))
    except ValueError as exc:
        result["event_parse_error"] = str(exc)
    return result


def build_before_review_packet(case_dir, input_dir, destination, *, hypothesis, before_records, opaque_id=None,
                              supplemental_test_paths=(), supplemental_source_paths=()):
    """Write a standalone, explicit allowlist of pre-repair evidence only.

    before_records must map the four P/Q original/instrumented variant names to
    their ORIGINAL-CONTEXT execution records. Caller certifies temporal provenance;
    this utility never discovers records by globbing after-repair directories.
    Original F/S IDs, provider/model/cohort metadata, host paths and benchmark
    outcome fields are excluded. Public task identity remains visible in code.
    """
    case_dir, input_dir, destination = Path(case_dir), Path(input_dir), Path(destination)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    allowed = {"p_original", "q_original", "p_instrumented", "q_instrumented"}
    if not isinstance(before_records, dict) or not before_records or set(before_records) - allowed:
        raise ValueError("before_records_requires_only_original_context_variant_keys")
    final = selected_tree_files(case_dir, state="final")
    historical = selected_tree_files(case_dir, state="historical")
    primary, sources, tests, _ = _selection(case_dir)
    supplemental_receipts = []
    for path in (*supplemental_test_paths, *supplemental_source_paths):
        from .context_repair import is_test_context_path
        is_test = path in supplemental_test_paths
        if is_test and not is_test_context_path("/" + _subject_path(path)):
            raise ValueError("supplement_must_be_existing_test_harness")
        versions = {}
        for state in ("historical", "final"):
            archive = _replay_dir(case_dir) / (state + "_sources") / "sources.tar.gz"
            recovered = read_archive_files(archive, [path])
            if recovered["missing"]:
                raise MissingEvidenceError(recovered["missing"])
            versions[state] = recovered["files"][path]
        if versions["historical"] != versions["final"]:
            raise ValueError("supplemental_test_harness_changed_between_snapshots")
        final[path] = historical[path] = versions["final"]
        if is_test:
            tests = list(dict.fromkeys([*tests, path]))
        else:
            sources = list(dict.fromkeys([*sources, path]))
        supplemental_receipts.append({"path": path, "sha256": _sha(final[path].encode()),
                                      "historical_final_bytes_equal": True,
                                      "purpose": "Existing public test harness/dependency used for insertion-only measurement; no new test or source context restoration.",
                                      "role": "test_harness" if is_test else "production_dependency"})
    validate_hypothesis(hypothesis, source_paths=sources, test_paths=tests, original_command=primary["test_command"])
    clean_hypothesis = _public_hypothesis(hypothesis)
    issue = (input_dir / "instruction.md").read_bytes()
    patch = (input_dir / "model.patch").read_bytes()
    anonymous = opaque_id or "pair_" + _sha(issue + b"\0" + patch + b"\0" + primary["test_command"].encode())[:16]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", anonymous) or re.fullmatch(r"[FS]\d+", anonymous):
        raise ValueError("opaque_id_must_not_encode_case_stratum")
    def redact(text):
        for prefix in sorted({str(case_dir.resolve()), str(input_dir.resolve())}, key=len, reverse=True):
            text = text.replace(prefix, "<CASE_ARTIFACT>")
        # Qualification reasons may mention helper files outside this case.
        # Keep subject /app and /tmp paths, but not host home-directory paths.
        text = re.sub(r"/(?:home|Users)/[^\s\"'<>]+", "<HOST_PATH>", text)
        # Probe module names may embed the case ID after an underscore. Rename
        # these private telemetry identifiers consistently in this review copy.
        return text.replace(case_dir.name, anonymous)
    clean_hypothesis = _redact_tree(clean_hypothesis, redact)
    replay_directory = _replay_dir(case_dir)
    summary = _read(replay_directory / "summary.json")
    replay = {key: _public_execution(summary[key], redact) for key in
              ("original_command_execution", "historical_test_only", "final_test_only") if key in summary}
    traces = {name: _public_execution(record, redact) for name, record in before_records.items()}
    qualification = _public_qualification(replay_directory, redact)
    observation_paths = ["/" + _subject_path(path) for path in primary.get("observation_paths", [])]
    primary["observation_paths"] = observation_paths
    destination.mkdir(parents=True, exist_ok=False)
    def put(path, value):
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value if isinstance(value, bytes) else value.encode())
    def put_json(path, value):
        put(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    put("issue.md", issue)
    put("delivered.patch", patch)
    put_json("selected_test.json", {"command": primary["test_command"], "working_directory": primary["working_directory"], "paths": tests,
                                    "observation_paths": observation_paths,
                                    "target": primary.get("target"), "target_anchor": primary.get("target_anchor")})
    if supplemental_receipts:
        put_json("supplemental_test_harness_receipts.json", supplemental_receipts)
    for state, files in (("final", final), ("historical", historical)):
        for path, content in files.items():
            put("sources/" + state + "/" + path, content)
    for path in tests:
        put("original_tests/" + path, final[path])
    put_json("hypothesis.json", clean_hypothesis)
    if clean_hypothesis["status"] == "proposed":
        put_json("alternative.json", clean_hypothesis["alternative"])
        put_json("instrumentation.json", clean_hypothesis["instrumentation"])
        for path, content in final.items():
            put("sources/alternative/" + path, content)
        edits = apply_exact_edits(destination / "sources/alternative", clean_hypothesis["alternative"]["edits"])
        put_json("alternative_edit_receipts.json", edits)
    put_json("replay.json", replay)
    put_json("replay_qualification.json", qualification)
    put_json("before_traces.json", traces)
    put_json("review_brief.json", _review_brief(primary, qualification, replay, traces))
    records = [{"path": path.relative_to(destination).as_posix(), "bytes": path.stat().st_size,
                "sha256": _sha(path.read_bytes())} for path in sorted(destination.rglob("*")) if path.is_file()]
    manifest = {"pair_id": anonymous, "stage": "before_context_repairs", "artifacts": records,
                "blinding": "No cohort, trial/model outcome, provider metadata, previous labels, other reviewer, or after-repair artifacts included. Public issue and source identity remain visible.",
                "limits": "Caller supplies original-context records. Instrumentation validity, replay fidelity and masking classification require independent review; this packet asserts none of them."}
    put_json("manifest.json", manifest)
    return {"pair_id": anonymous, "destination": str(destination), "manifest_sha256": _sha((destination / "manifest.json").read_bytes()), "artifacts": len(records)}
