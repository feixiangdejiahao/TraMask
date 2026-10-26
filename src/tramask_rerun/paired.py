"""Execute explicitly reviewed four-variant pairs; never infer scientific labels.

All inputs are caller supplied. No historical run, global checkpoint pointer,
review label, or provider is read. Complete runs may be reused after receipt
verification; incomplete output directories are never silently retried.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time

from tramask_pilot.fidelity import test_evidence
from . import variants
from .evidence import compare_events
from .runtime import execute_variant


DEFAULT_ENV = {"PAGER": "cat", "MANPAGER": "cat", "LESS": "-R", "PIP_PROGRESS_BAR": "off", "TQDM_DISABLE": "1"}
MARKER = b"TRAMASK_EVENT"


def _dump(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _sha(value):
    raw = value if isinstance(value, bytes) else value.encode() if isinstance(value, str) else _dump(value).encode()
    return hashlib.sha256(raw).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat()


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def _output(path):
    path = Path(path).absolute()
    if ".." in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("noncanonical_or_symlink_output")
    return path


def _receipt(path):
    path = Path(path).absolute()
    if path.is_symlink() or not path.is_file():
        raise ValueError("receipt_requires_regular_file")
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": _sha(raw)}


def _verify(row, root):
    path = _output(row["path"])
    if not path.is_relative_to(root) or _receipt(path) != row:
        raise ValueError("paired_artifact_receipt_mismatch")
    return path


def _positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError("invalid_" + name)
    return value


def execution_binding(case, source_files, hypothesis, *, source_origins=None, test_paths,
                      build_commands=(), generated_runtime=False, observation_paths=(), repeats=3,
                      candidate=None):
    """Return the exact object a technical review must approve in ``binding``.

    Review shape: {approved_for_execution: true, reviewer_id: str,
    rationale: str, binding: execution_binding(...)}. Extra review metadata is
    retained. This is permission for technical execution, never an E3/E7/E9 vote.
    ``case.working_directory`` defaults to /app; ``case.environment`` defaults
    to the same pager settings as baseline. Runtime currently gives build and
    test commands the task test timeout; that effective limit is explicit here.
    """
    if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not case["id"]:
        raise ValueError("case_id_required")
    files = variants._files(source_files)
    tests = sorted({variants._path(path) for path in test_paths})
    if not tests or not set(tests) <= set(files):
        raise ValueError("test_paths_require_complete_public_files")
    if type(repeats) is not int or repeats < 1:
        raise ValueError("repeats_requires_positive_integer")
    if type(generated_runtime) is not bool:
        raise ValueError("generated_runtime_requires_boolean")
    if not isinstance(build_commands, (tuple, list)) or any(not isinstance(c, str) or not c or "\0" in c for c in build_commands):
        raise ValueError("build_commands_require_exact_shell_strings")
    if generated_runtime and not build_commands:
        raise ValueError("generated_runtime_requires_explicit_build_plan")
    checkpoint = case.get("checkpoint", {})
    image, head = checkpoint.get("image_id"), checkpoint.get("head")
    if (not isinstance(image, str) or not image.startswith("sha256:") or len(image) != 71
            or any(c not in "0123456789abcdef" for c in image[7:])):
        raise ValueError("immutable_checkpoint_image_required")
    if not isinstance(head, str) or len(head) not in {40, 64} or any(c not in "0123456789abcdefABCDEF" for c in head):
        raise ValueError("full_checkpoint_head_required")
    workdir = case.get("working_directory", "/app")
    if workdir not in {"/app", "/tmp"}:
        variants._path(workdir)
    if not isinstance(workdir, str) or not workdir.startswith("/"):
        raise ValueError("working_directory_requires_absolute_subject_path")
    environment = case.get("environment", DEFAULT_ENV)
    if not isinstance(environment, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in environment.items()):
        raise ValueError("environment_requires_string_mapping")
    timeout = _positive(case.get("test_timeout_seconds"), "test_timeout_seconds")
    original = hypothesis.get("original_command") if isinstance(hypothesis, dict) else None
    instrumented = hypothesis.get("instrumentation", {}).get("command") if isinstance(hypothesis, dict) else None
    if any(not isinstance(c, str) or not c or "\0" in c for c in (original, instrumented)):
        raise ValueError("exact_original_and_instrumented_commands_required")
    origins = {} if source_origins is None else {variants._path(k): v for k, v in source_origins.items()}
    # Validate capsule declarations and input hashes before allowing any subject.
    checkpoint_hashes, _ = variants._origins(files, origins)
    observation_paths = sorted({"/" + variants._path(path) for path in observation_paths})
    result = {"schema": "tramask.execution-binding.v1", "case_id": case["id"],
        "checkpoint": {"image_id": image, "head": head.lower()},
        "hypothesis_sha256": _sha(hypothesis),
        "hypothesis_hash_encoding": "UTF8 sorted-key compact JSON, ensure_ascii=false, finite JSON",
        "source_file_sha256": {"/" + path: _sha(text) for path, text in sorted(files.items())},
        "checkpoint_predecessor_sha256": checkpoint_hashes, "source_origins_sha256": _sha(origins),
        "test_paths": ["/" + p for p in tests], "observation_paths": observation_paths,
        "command_mapping": {name: {"command": instrumented if name.endswith("_instrumented") else original,
                                    "working_directory": workdir} for name in variants.VARIANTS},
        "environment": dict(environment), "resources": dict(case.get("resources", {})),
        "test_timeout_seconds": timeout, "repeats": repeats,
        "build_plan": {"commands": list(build_commands), "generated_runtime": generated_runtime,
            "production_paths": sorted("/" + p for p in set(files) - set(tests)),
            "effective_timeout_seconds": timeout,
            "declared_task_build_timeout_seconds": case.get("build_timeout_seconds"),
            "timeout_scope": "runtime applies the test-command timeout to each build; any inner build deadline must be explicit in the reviewed command"}}
    if candidate is not None:
        result["candidate_sha256"] = _sha(candidate)
    return result


def _review(review, binding):
    if (not isinstance(review, dict) or review.get("approved_for_execution") is not True
            or not isinstance(review.get("reviewer_id"), str) or not review["reviewer_id"].strip()
            or not isinstance(review.get("rationale"), str) or not review["rationale"].strip()):
        raise ValueError("explicit_technical_execution_review_required")
    if _dump(review.get("binding")) != _dump(binding):
        raise ValueError("technical_review_binding_mismatch")


def _strict_json(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result
    def finite(value):
        raise ValueError("nonfinite_json_value")
    return json.loads(text, object_pairs_hook=unique, parse_constant=finite)


def _parse_events(raw, source):
    events, errors, rows = [], [], []
    for number, line in enumerate(raw.splitlines(), 1):
        if MARKER not in line:
            continue
        provenance = {"source": source, "line": number, "line_sha256": _sha(line)}
        try:
            if not line.startswith(MARKER) or len(line) <= len(MARKER) or line[len(MARKER):len(MARKER) + 1] not in {b" ", b"\t"}:
                raise ValueError("marker_requires_start_of_line_and_whitespace")
            value = _strict_json(line[len(MARKER):].strip().decode("utf-8"))
            # This validates typed event values, aliases and required semantic
            # fields without assigning a scientific label or inferring a match.
            compare_events([value], [value])
            events.append(value)
            rows.append({**provenance, "event_index": len(events) - 1})
        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
            errors.append({**provenance, "error_type": type(exc).__name__, "reason": str(exc)})
    return events, errors, rows


def _raw_capture(path, directory, claimed_sha=None, claimed_bytes=None):
    path = _output(path)
    if not path.is_relative_to(directory):
        raise ValueError("raw_capture_outside_variant_output")
    receipt = _receipt(path)
    if claimed_sha is not None and receipt["sha256"] != claimed_sha:
        raise ValueError("raw_capture_hash_mismatch")
    if claimed_bytes is not None and receipt["bytes"] != claimed_bytes:
        raise ValueError("raw_capture_size_mismatch")
    return path.read_bytes(), receipt


def _diagnose(result, directory):
    execution = result.get("execution") or {}
    events, errors, event_sources, captures, texts = [], [], [], [], []
    for stream in ("stdout", "stderr"):
        path = execution.get("raw_" + stream)
        if path is None:
            if execution:
                errors.append({"source": stream, "reason": "raw_stream_capture_missing"})
            continue
        try:
            raw, receipt = _raw_capture(path, directory, execution.get(stream + "_sha256"), execution.get(stream + "_bytes"))
            parsed, failed, sources = _parse_events(raw, stream)
            captures.append({"source": stream, "receipt": receipt})
            texts.append(raw.decode("utf-8", errors="replace"))
            start = len(events)
            events += parsed
            errors += failed
            event_sources += [{**row, "event_index": row["event_index"] + start} for row in sources]
        except (ValueError, OSError) as exc:
            errors.append({"source": stream, "reason": str(exc)})
    observation_capture_status = []
    for observed in result.get("observations", []):
        source = "observation:" + str(observed.get("path", "unknown"))
        observation_capture_status.append({"path": observed.get("path"), "status": observed.get("status")})
        if not observed.get("raw_path"):
            continue
        try:
            raw, receipt = _raw_capture(observed["raw_path"], directory, observed.get("sha256"), observed.get("bytes"))
            parsed, failed, sources = _parse_events(raw, source)
            captures.append({"source": source, "receipt": receipt})
            start = len(events)
            events += parsed
            errors += failed
            event_sources += [{**row, "event_index": row["event_index"] + start} for row in sources]
        except (ValueError, OSError) as exc:
            errors.append({"source": source, "reason": str(exc)})
    return {"event_status": "event_error" if errors else "parsed" if events else "no_events",
        "events": events, "effects": [e for e in events if e["channel"] == "effect"],
        "observations": [e for e in events if e["channel"] == "observation"],
        "event_errors": errors, "event_sources": event_sources, "raw_captures": captures,
        "explicit_observation_capture_status": observation_capture_status,
        "runner_collection_facts": test_evidence("\n".join(texts)),
        "returncode": execution.get("returncode"), "timed_out": execution.get("timed_out"),
        "execution_status": result.get("status"), "scientific_label": None,
        "note": "No events, parse errors, exit codes and collection summaries do not establish masking or test PASS."}


def _comparison(left, right):
    if left["event_errors"] or right["event_errors"]:
        return {"status": "event_error", "comparison": None, "scientific_label": None}
    try:
        return {"status": "diagnostic_only", "comparison": compare_events(left["events"], right["events"]), "scientific_label": None}
    except (ValueError, TypeError, KeyError) as exc:
        return {"status": "event_error", "comparison": None, "reason": str(exc), "scientific_label": None}


def _resume(out, binding, review):
    completion, summary_path = out / "completion.json", out / "summary.json"
    if not completion.exists() or not summary_path.exists():
        raise FileExistsError("partial_paired_output_preserved_no_implicit_retry: " + str(out))
    completed = json.loads(completion.read_text())
    if _verify(completed["summary"], out) != summary_path:
        raise ValueError("completion_points_to_wrong_summary")
    summary = json.loads(summary_path.read_text())
    if _dump(summary.get("binding")) != _dump(binding) or summary.get("review_sha256") != _sha(review):
        raise ValueError("existing_pair_inputs_or_review_differ")
    expected_paths = set()
    for artifact in summary["artifacts"]:
        expected_paths.add(_verify(artifact, out))
    inventory = list(out.rglob("*"))
    if any(p.is_symlink() for p in inventory):
        raise ValueError("symlink_in_paired_artifacts")
    actual_paths = {p for p in inventory if p.is_file()} - {completion, summary_path}
    if actual_paths != expected_paths:
        raise ValueError("paired_artifact_inventory_changed")
    return {**summary, "reused_verified_output": True}


def _finish_summary(out, summary):
    artifacts = []
    for path in sorted(out.rglob("*")):
        if path.is_symlink():
            raise ValueError("symlink_in_paired_artifacts")
        if path.is_file():
            artifacts.append(_receipt(path))
    summary["artifacts"] = artifacts
    _write(out / "summary.json", summary)
    _write(out / "completion.json", {"schema": "tramask.paired-completion.v1", "summary": _receipt(out / "summary.json")})
    return summary


def _execute(case, source_files, hypothesis, out, *, source_origins, test_paths, review,
             build_commands, generated_runtime, observation_paths, repeats, candidate=None):
    binding = execution_binding(case, source_files, hypothesis, source_origins=source_origins,
        test_paths=test_paths, build_commands=build_commands, generated_runtime=generated_runtime,
        observation_paths=observation_paths, repeats=repeats, candidate=candidate)
    _review(review, binding)
    out = _output(out)
    if out.exists():
        return _resume(out, binding, review)
    out.mkdir(parents=True)
    _write(out / "execution_review.json", review)
    _write(out / "hypothesis.json", hypothesis)
    _write(out / "binding.json", binding)
    if candidate is not None:
        _write(out / "candidate.json", candidate)
    summary = {"schema": "tramask.qualified-pair.v1", "case_id": case["id"], "started_at": _now(),
        "binding": binding, "review_sha256": _sha(review), "status": "staging", "repeats": [],
        "cost": {"variant_invocations": 0, "subject_test_command_runs": 0, "build_command_runs": 0,
                 "elapsed_subject_test_seconds": 0.0, "elapsed_build_seconds": 0.0, "elapsed_wall_seconds": 0.0,
                 "invocations_with_unknown_physical_counts": 0},
        "scientific_label": None, "reused_verified_output": False,
        "interpretation": "Technical execution and raw comparisons only; E1-E9 and oracle judgments remain independent."}
    started = time.monotonic()
    try:
        if candidate is None:
            staged = variants.stage_hypothesis(source_files, hypothesis, out / "staged", source_origins=source_origins, test_paths=test_paths)
        else:
            staged = variants.stage_candidate(source_files, hypothesis, candidate, out / "staged", test_paths, source_origins=source_origins)
    except (ValueError, TypeError, KeyError) as exc:
        summary.update(status="staging_failed", staging_error={"type": type(exc).__name__, "reason": str(exc)}, completed_at=_now())
        summary["cost"]["elapsed_wall_seconds"] = time.monotonic() - started
        return _finish_summary(out, summary)
    if staged["variants"]["p_original"]["full_text"] == staged["variants"]["q_original"]["full_text"]:
        summary.update(status="staging_failed", staging_error={"reason": "empty_or_no_op_counterfactual"}, completed_at=_now())
        summary["cost"]["elapsed_wall_seconds"] = time.monotonic() - started
        return _finish_summary(out, summary)
    for repeat in range(1, repeats + 1):
        rows = {}
        for name in variants.VARIANTS:
            directory = out / f"repeat_{repeat:02d}" / name
            variant = staged["variants"][name]
            expected_command = binding["command_mapping"][name]["command"]
            if variant["command"] != expected_command:
                raise ValueError("staged_command_differs_from_review")
            summary["cost"]["variant_invocations"] += 1
            try:
                result = execute_variant(binding["checkpoint"], directory, expected_command, binding["test_timeout_seconds"],
                    files=variant["files"], observation_paths=binding["observation_paths"],
                    build_commands=binding["build_plan"]["commands"], env=binding["environment"],
                    workdir=binding["command_mapping"][name]["working_directory"], resources=binding["resources"],
                    production_paths=binding["build_plan"]["production_paths"], generated_runtime=generated_runtime)
                result_path = directory / "result.json"
                if not result_path.is_file() or _dump(json.loads(result_path.read_text())) != _dump(result):
                    raise ValueError("runtime_result_not_bound_to_result_json")
                diagnosis = _diagnose(result, directory)
                execution = result.get("execution")
                summary["cost"]["subject_test_command_runs"] += int(execution is not None)
                summary["cost"]["build_command_runs"] += len(result.get("builds", []))
                summary["cost"]["elapsed_subject_test_seconds"] += float((execution or {}).get("elapsed_seconds", 0) or 0)
                summary["cost"]["elapsed_build_seconds"] += sum(float(b.get("elapsed_seconds", 0) or 0) for b in result.get("builds", []))
                rows[name] = {"runtime_result": _receipt(result_path), "diagnosis": diagnosis,
                              "builds": [{k: build.get(k) for k in ("command", "status", "returncode", "timed_out", "elapsed_seconds")} for build in result.get("builds", [])]}
            except Exception as exc:
                # Subject failures normally return result.json. Unexpected glue/
                # transport exceptions stay visible; no retry or repaired run.
                failure = {"status": "runtime_invocation_exception", "error_type": type(exc).__name__, "reason": str(exc)}
                _write(directory / "invocation_failure.json", failure)
                summary["cost"]["invocations_with_unknown_physical_counts"] += 1
                rows[name] = {"failure": failure, "diagnosis": {"event_status": "event_error", "events": [],
                    "effects": [], "observations": [], "event_errors": [failure], "execution_status": failure["status"],
                    "returncode": None, "timed_out": None, "runner_collection_facts": {}, "scientific_label": None}}
            _write(directory / "diagnosis.json", rows[name]["diagnosis"])
        diagnostics = {"original_PQ": _comparison(rows["p_original"]["diagnosis"], rows["q_original"]["diagnosis"]),
                       "instrumented_PQ": _comparison(rows["p_instrumented"]["diagnosis"], rows["q_instrumented"]["diagnosis"])}
        diagnostics["noninterference_checks"] = {variant: {
            "returncodes_equal": rows[variant + "_original"]["diagnosis"]["returncode"] == rows[variant + "_instrumented"]["diagnosis"]["returncode"]
                if rows[variant + "_original"]["diagnosis"]["returncode"] is not None and rows[variant + "_instrumented"]["diagnosis"]["returncode"] is not None else None,
            "original_collection_facts": rows[variant + "_original"]["diagnosis"]["runner_collection_facts"],
            "instrumented_collection_facts": rows[variant + "_instrumented"]["diagnosis"]["runner_collection_facts"],
            "approved_noninterference": None} for variant in ("p", "q")}
        row = {"repeat": repeat, "variants": rows, "diagnostics": diagnostics}
        _write(out / f"repeat_{repeat:02d}" / "summary.json", row)
        summary["repeats"].append(row)
    summary["between_repeat_diagnostics"] = [{"first_repeat": 1, "other_repeat": i + 1,
        "variants": {name: _comparison(summary["repeats"][0]["variants"][name]["diagnosis"], row["variants"][name]["diagnosis"])
                     for name in variants.VARIANTS}} for i, row in enumerate(summary["repeats"][1:], 1)]
    problems = [row["diagnosis"]["execution_status"] != "completed" or bool(row["diagnosis"]["event_errors"])
                for repeat in summary["repeats"] for row in repeat["variants"].values()]
    summary.update(status="completed_with_execution_or_event_errors" if any(problems) else "completed_pending_evidence_qualification", completed_at=_now())
    summary["cost"]["elapsed_wall_seconds"] = time.monotonic() - started
    return _finish_summary(out, summary)


def execute_qualified_pair(case, source_files, hypothesis, out, *, source_origins=None,
                           test_paths, review, build_commands=(), generated_runtime=False,
                           observation_paths=(), repeats=3):
    """Three clean repetitions × original/probed P/Q; review binds all inputs."""
    return _execute(case, source_files, hypothesis, out, source_origins=source_origins, test_paths=test_paths,
        review=review, build_commands=build_commands, generated_runtime=generated_runtime,
        observation_paths=observation_paths, repeats=repeats)


def execute_candidate_pair(case, source_files, hypothesis, candidate, out, *, source_origins=None,
                           test_paths, review, build_commands=(), generated_runtime=False,
                           observation_paths=(), repeats=3):
    """Same evidence-only engine after independently staging one candidate edit.

    Call the candidate response validator and semantic reviewer separately.
    The technical review's binding additionally includes candidate_sha256.
    """
    return _execute(case, source_files, hypothesis, out, source_origins=source_origins, test_paths=test_paths,
        review=review, build_commands=build_commands, generated_runtime=generated_runtime,
        observation_paths=observation_paths, repeats=repeats, candidate=candidate)
