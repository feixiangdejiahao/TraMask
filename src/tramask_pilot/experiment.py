"""Pilot orchestration; all hypotheses remain distinct from executed evidence."""
from __future__ import annotations

import json
from pathlib import Path
import re
import shlex
import shutil

from .corpus import ROOT, RUN, calls, input_directory, public_packet, read, receipt, write

LOCATE = """You recover an agent-authored validation test from public coding history for a faithful replay study.
Use only the issue, submitted patch and recorded tool actions. Do not infer that the delivered patch is correct.
This stage selects tests by task relevance and recoverability, NOT by suspected weakness or likely repair success.
Choose the latest executed focused agent-authored test that directly exercises a changed task behavior. Prefer a
standalone temporary script or a named unit test over a whole suite. The test must have actually been executed.
If no authored test is recoverable, say so. Do not invent a test or an execution.
Return JSON with keys status ('located' or 'no_authored_test'), rationale, primary (object or null).
primary fields:
- execution_call_id: exact action id of the chosen actual execution
- test_command: exact recorded command, or an exact contiguous suffix containing ONLY the validation execution,
  if the same action first edits source. Include its recorded cd /app prefix where present. Do not rewrite commands.
- test_paths: array of absolute paths of agent-authored test scripts/files needed by that invocation, e.g. /tmp/check.py.
  For a pure inline heredoc test, use [] and preserve the entire heredoc command.
- source_paths: up to 4 repository-relative changed implementation paths needed to understand the target.
- target: one concrete issue-related behavior checked by this test; do not search for masking yet.
- target_anchor: function and path; test_name if available.
- creation_call_ids: exact ids of test creation/revision actions leading to this snapshot.
- historical_expected: concise observable result quoted or paraphrased from the recorded execution.
- command_is_test_only: boolean (must be true; no production writes in test_command).
Do not include candidate context repairs, counterfactual code, prior evaluator labels, or extra tests.
Return JSON only."""


def locate(c):
    from .provider import call
    out = RUN / "runs" / c["id"] / "localization"
    packet = public_packet(c)
    write(RUN / "runs" / c["id"] / "localization_input.json", packet)
    result = call(ROOT, RUN, out, {"id": c["id"] + "/locate", "system": LOCATE,
                  "prompt": json.dumps(packet, ensure_ascii=False)}, max_tokens=6000)
    if result.get("status") != "complete" or not isinstance(result.get("parsed"), dict):
        return {"id": c["id"], "status": "localization_error", "provider": result.get("status")}
    proposal = result["parsed"]
    if proposal.get("status") == "located":
        p = proposal["primary"]
        action = next((a for a in packet["actions"] if a["id"] == p["execution_call_id"]), None)
        if action is None or not p.get("test_command") or p["test_command"].strip() not in action["command"]:
            raise ValueError("localizer did not preserve a recorded command")
        if p.get("command_is_test_only") is not True:
            raise ValueError("selected replay command may modify production source")
        if not isinstance(p.get("test_paths"), list) or not isinstance(p.get("source_paths"), list):
            raise ValueError("invalid snapshot paths")
        if any(not path.startswith(("/app/", "/tmp/")) or ".." in Path(path).parts for path in p["test_paths"]):
            raise ValueError("test path outside allowed subject locations")
        if any(Path(path).is_absolute() or ".." in Path(path).parts for path in p["source_paths"]):
            raise ValueError("source path outside repository")
    write(out / "selection.json", proposal)
    return {"id": c["id"], "status": proposal.get("status"),
            "execution": (proposal.get("primary") or {}).get("execution_call_id")}


def pure_read(command):
    """Only an intentionally narrow set of read-only shell actions can be omitted."""
    if any(x in command for x in (">", "<<", "`", "$(", "\n", ";", "||")):
        return False
    if "&" in command.replace("&&", "") or any(x in command for x in ("(", ")")):
        return False
    parts = re.split(r"\s*(?:&&|\|)\s*", command.strip())
    for part in parts:
        if re.fullmatch(r"cd\s+(?:/app|/|/tmp|[\w./-]+)", part):
            continue
        if re.match(r"^(?:ls|pwd|cat|head|tail|rg|grep|wc|file|which)\b", part):
            continue
        if re.fullmatch(r"sed\s+-n\s+['\"]?[0-9]+(?:,[0-9$]+)?p['\"]?\s+[\w./-]+", part):
            continue
        if re.match(r"^git\s+(?:status|log|diff|show|ls-files|rev-parse)\b", part) and "--output" not in part:
            continue
        return False
    return bool(parts)


def collect_observation_files(runtime, paths, directory, execution):
    """Read explicitly reviewed redirected public test logs after execution."""
    observations = []
    for index, path in enumerate(paths):
        if not path.startswith(("/app/", "/tmp/")) or ".." in Path(path).parts:
            raise ValueError("observation file outside subject tree")
        local = directory / f"{index:02}_{Path(path).name}"
        try:
            runtime.copy_from(path, local)
            raw = local.read_bytes()
            observations.append({"subject_path": path, **receipt(local),
                                 "content": raw[:2_000_000].decode(errors="replace"),
                                 "truncated": len(raw) > 2_000_000})
        except Exception as exc:
            observations.append({"subject_path": path, "error": type(exc).__name__})
    execution["observation_files"] = observations
    return execution


def activate_generated_runtime(runtime, case_dir, label="activate_generated_runtime"):
    """Mechanically rebuild an explicitly reviewed source-derived executable."""
    path = Path(case_dir) / "localization/activation_review.json"
    if not path.exists():
        return None
    review = read(path)
    if (review.get("approved_for_isolated_build") is not True or
            review.get("selection_sha256") != receipt(Path(case_dir) / "localization/selection.json")["sha256"]):
        raise ValueError("generated runtime activation lacks matching review")
    result = runtime.exec(review["command"], label, timeout=180)
    if result["returncode"] != 0 or result.get("timed_out") or result.get("transport_error"):
        raise RuntimeError("generated runtime build failed; do not run stale artifact")
    return {"review": receipt(path), "execution": result}


def replay(c):
    from .runtime import Container
    from .context_repair import (build_test_context_archive, classify_historical_additions,
        is_test_context_path, patch_added_paths, restore_test_context, test_paths_with_addendum,
        _checked, _remove_files)
    out = RUN / "runs" / c["id"] / c.get("replay_run", "replay")
    inherited = None
    if (out / "historical/container.json").exists() and not (out / "summary.json").exists():
        failed_checkpoint = out / "historical/checkpoints/before_selected_call"
        if (failed_checkpoint / "result.json").exists():
            recorded = read(failed_checkpoint / "result.json")
            ids = re.findall(r"^sha256:[0-9a-f]{64}$", (failed_checkpoint / "stdout.bin").read_text(), re.M)
            if recorded.get("returncode") == 0 and len(ids) == 1:
                inherited = {"image_id": ids[0], "head": recorded["head"], "original_replay": str(out),
                             "checkpoint_receipt": receipt(failed_checkpoint / "result.json"),
                             "reason": "Docker commit succeeded but parser rejected warning preceding image ID; retain failed record and recover exact saved pre-call filesystem."}
                out = out.parent / "replay_recovery01"
    if (out / "summary.json").exists():
        return read(out / "summary.json")
    selection = read(RUN / "runs" / c["id"] / "localization/selection.json")
    if selection.get("status") != "located":
        result = {"id": c["id"], "status": "excluded", "reason": "no_recoverable_agent_authored_test"}
        write(out / "summary.json", result); return result
    primary = dict(selection["primary"])
    primary["test_paths"], test_context_addendum = test_paths_with_addendum(
        out.parent, primary["test_paths"])
    review = read(RUN / "runs" / c["id"] / "localization/command_review.json")
    if review.get("approved_for_isolated_replay") is not True or review.get("selection_sha256") != receipt(RUN / "runs" / c["id"] / "localization/selection.json")["sha256"]:
        raise ValueError("selected command lacks a matching manual review")
    primary["test_command"] = review.get("test_command", primary["test_command"])
    added = patch_added_paths(input_directory(c) / "model.patch")
    test_workdir = review.get("test_workdir", "/app")
    observation_paths = review.get("observation_paths", [])
    actions = calls(read(input_directory(c) / "trajectory.json"))
    target_index = next(i for i, a in enumerate(actions) if a["id"] == primary["execution_call_id"])
    chosen = actions[target_index]
    command = primary["test_command"].strip()
    if not chosen["command"].strip().endswith(command):
        raise ValueError("selected test command must be a reviewed executable suffix")
    prefix = chosen["command"].strip()[:-len(command)].rstrip()
    if prefix.endswith("&&"):
        prefix = prefix[:-2].rstrip()
    records = []
    original_untracked = None
    if inherited:
        write(out / "recovery.json", inherited)
        with Container(c["image"], out / "baseline_inventory", c["base_commit"]) as inventory:
            original_untracked = set(inventory.baseline_untracked)
    # One persistent isolated subject environment restores command side effects chronologically.
    with Container(inherited["image_id"] if inherited else c["image"], out / "historical",
                   inherited["head"] if inherited else c["base_commit"]) as runtime:
        initial_untracked = original_untracked if inherited else set(runtime.baseline_untracked)
        for action in ([chosen] if inherited else actions[:target_index + 1]):
            if action["id"] != primary["execution_call_id"] and pure_read(action["command"]):
                records.append({"id": action["id"], "status": "omitted_proven_read_only"})
                write(out / "progress.json", {"id": c["id"], "completed": len(records), "planned": target_index + 1,
                      "last_action": action["id"], "records": records})
                continue
            if "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT" in action["command"]:
                records.append({"id": action["id"], "status": "submission_marker_omitted"}); continue
            if action["id"] == primary["execution_call_id"]:
                before_call = runtime.snapshot("before_selected_call", extra_paths=primary["test_paths"])
                before_image = runtime.checkpoint("before_selected_call")
            result = runtime.exec(action["command"], action["id"], timeout=180, expected=action["expected"])
            records.append({"id": action["id"], "execution": result})
            write(out / "progress.json", {"id": c["id"], "completed": len(records), "planned": target_index + 1,
                  "last_action": action["id"], "records": records})
        after_call = runtime.snapshot("after_selected_call", extra_paths=primary["test_paths"])
        original = records[-1]["execution"]
        collect_observation_files(runtime, observation_paths, out / "original_observation_files", original)
        image = runtime.image_id
    # Recover the exact pre-test filesystem, including a same-action edit prefix,
    # without reusing the state mutated by the first historical execution.
    with Container(before_image["image_id"], out / "context", before_image["head"]) as context:
        prefix_result = context.exec(prefix, "same_action_setup_prefix", timeout=180) if prefix else None
        # A checkpoint-derived Container treats inherited untracked files as its
        # baseline. Explicitly export test helpers/fixtures before any reset.
        untracked = _checked(context, "git -c safe.directory=/app ls-files --others --exclude-standard -z",
                             "context_untracked")
        untracked_paths = [p for p in untracked["stdout"].split("\0") if p]
        cleanup = classify_historical_additions(untracked_paths, baseline_untracked=initial_untracked,
                                                test_paths=primary["test_paths"])
        historical_new_source = cleanup["production_to_remove"]
        context_paths = ["/app/" + p for p in untracked_paths
                         if is_test_context_path(p, primary["test_paths"], repository_relative=True)]
        colliding_patch_paths = ["/app/" + p for p in added if p in untracked_paths]
        deleted = _checked(context, "git -c safe.directory=/app diff --name-only --diff-filter=D "
                           + shlex.quote(c["base_commit"]) + " -z --", "historical_deleted_paths")
        absent_context_paths = ["/app/" + p for p in deleted["stdout"].split("\0")
                                if p and is_test_context_path(p, primary["test_paths"], repository_relative=True)]
        context_snapshot = context.snapshot("before_test", extra_paths=sorted(set(
            primary["test_paths"] + context_paths + colliding_patch_paths
            + ["/app/" + p for p in primary["source_paths"] + historical_new_source])))
        shutil.copytree(Path(context_snapshot["archive"]).parent, out / "historical_sources")
        archived_paths = {row["path"] for row in read(context_snapshot["manifest"])["files"]
                          if row.get("kind") == "file"}
        if any(path not in archived_paths for path in colliding_patch_paths):
            raise ValueError("Patch additions overlap unarchived/nonregular checkpoint files")
        test_context = build_test_context_archive(context_snapshot["archive"], out / "test_context",
            test_paths=primary["test_paths"], manifest_path=context_snapshot["manifest"],
            absent_paths=absent_context_paths)
        test_receipts = []
        for i, path in enumerate(primary["test_paths"]):
            local = out / "test_snapshot" / f"{i:02}_{Path(path).name}"
            context.copy_from(path, local)
            test_receipts.append({"subject_path": path, **receipt(local)})
        checkpoint = context.checkpoint("original_test_context")
    write(out / "test_snapshot.json", {"files": test_receipts, "command": command, "working_directory": test_workdir,
          "observation_paths": observation_paths, "context_image": checkpoint,
          "same_action_prefix": prefix, "prefix_execution": prefix_result,
          "historical_production_additions_to_remove": historical_new_source,
          "historical_addition_classification": cleanup,
          "test_context_addendum": test_context_addendum,
          "historical_test_context": test_context["manifest"]})
    with Container(checkpoint["image_id"], out / "historical_rerun", checkpoint["head"]) as historical:
        rerun = historical.exec(command, "historical_test_only", timeout=180, workdir=test_workdir)
        collect_observation_files(historical, observation_paths, out / "historical_observation_files", rerun)
    with Container(checkpoint["image_id"], out / "final", checkpoint["head"]) as final_runtime:
        _checked(final_runtime, "git -c safe.directory=/app reset --hard " + shlex.quote(c["base_commit"]),
                 "restore_base_source")
        _remove_files(final_runtime, ["/app/" + p for p in historical_new_source],
                      "remove_historical_production_additions")
        # An untracked path added by both history and P must not block git apply.
        _remove_files(final_runtime, ["/app/" + p for p in added], "clear_patch_additions")
        final_runtime.apply_patch(input_directory(c) / "model.patch", "submitted_patch")
        restoration = restore_test_context(final_runtime, test_context, added_paths=added)
        activation = activate_generated_runtime(final_runtime, out.parent)
        write(out / "test_context_restoration.json", restoration)
        final_snapshot = final_runtime.snapshot("before_final_test", extra_paths=sorted(set(
            [row["subject_path"] for row in test_context["files"]] + primary["test_paths"]
            + ["/app/" + p for p in primary["source_paths"]])))
        shutil.copytree(Path(final_snapshot["archive"]).parent, out / "final_sources")
        final_checkpoint = final_runtime.checkpoint("final_test_context")
        final = final_runtime.exec(command, "final_test_only", timeout=180, workdir=test_workdir)
        collect_observation_files(final_runtime, observation_paths, out / "final_observation_files", final)
    result = {"id": c["id"], "status": "replayed_pending_fidelity_review", "image_id": image,
              "selected_call": primary["execution_call_id"], "restoration_calls": len(records),
              "original_command_execution": original, "historical_test_only": rerun, "final_test_only": final,
              "before_original_call": before_call, "after_original_call": after_call,
              "original_context_checkpoint": checkpoint, "final_context_checkpoint": final_checkpoint,
              "generated_runtime_activation": activation,
              "inherited_restoration": inherited,
              "test_snapshot": receipt(out / "test_snapshot.json"),
              "test_context_restoration": receipt(out / "test_context_restoration.json"),
              "qualification": "Replay fidelity and source restoration require review; this is not masking evidence."}
    write(out / "summary.json", result)
    write(out.parent / "active_replay.json", {"directory": str(out), "summary": receipt(out / "summary.json")})
    return {"id": c["id"], "status": result["status"], "restoration_calls": len(records)}


def hypothesize(c):
    from .provider import call
    from .evidence import build_hypothesis_packet, selected_tree_files
    from .hypotheses import build_request, validate_hypothesis, materialize_variants
    case_dir = RUN / "runs" / c["id"]
    packet = build_hypothesis_packet(case_dir, input_directory(c),
                                    source_context_bytes=50000 if c["id"].startswith(("F", "S")) else 200000)
    out = case_dir / c.get("hypothesis_run", "target_hypothesis")
    write(out / "input.json", packet)
    if packet.get("status") != "ready":
        hypothesis = {"status": "insufficient_evidence", "reason": "Selected source/test evidence unavailable: " +
                      json.dumps(packet.get("missing", []), ensure_ascii=False)}
        write(out / "hypothesis.json", hypothesis)
        write(case_dir / "active_hypothesis.json", {"directory": str(out), "hypothesis": receipt(out / "hypothesis.json")})
        return {"id": c["id"], "status": "insufficient_evidence", "provider_call": False}
    request = packet.get("request") or build_request(c["id"], **{k: packet[k] for k in
                            ("issue", "final_patch", "selected_test", "final_sources", "actions")})
    request["id"] = c["id"] + "/" + out.name
    result = call(ROOT, RUN, out, request, max_tokens=8192)
    if result.get("status") != "complete" or not isinstance(result.get("parsed"), dict):
        return {"id": c["id"], "status": "hypothesis_transport_error", "provider_status": result.get("status")}
    hypothesis = result["parsed"]
    hypothesis = validate_hypothesis(hypothesis, source_paths=packet["final_sources"],
                        test_paths=packet["selected_test"]["files"], original_command=packet["selected_test"]["command"])
    write(out / "hypothesis.json", hypothesis)
    write(case_dir / "active_hypothesis.json", {"directory": str(out), "hypothesis": receipt(out / "hypothesis.json")})
    if hypothesis["status"] == "proposed":
        baseline = out / "public_tree"
        if not baseline.exists():
            for path, content in selected_tree_files(case_dir).items():
                target = baseline / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
        staged_path = out / "staging.json"
        if not staged_path.exists():
            staged = materialize_variants(baseline, out / "variants", hypothesis)
            write(staged_path, staged)
    return {"id": c["id"], "status": hypothesis["status"], "reason": hypothesis.get("reason")}


def pair(c):
    from .runtime import Container
    from .hypotheses import parse_events
    case_dir = RUN / "runs" / c["id"]
    out = case_dir / "before_pair"
    if (out / "summary.json").exists():
        return read(out / "summary.json")
    hypothesis_dir = Path(read(case_dir / "active_hypothesis.json")["directory"])
    hypothesis_path = hypothesis_dir / "hypothesis.json"
    hypothesis = read(hypothesis_path)
    review = read(hypothesis_dir / "manual_review.json")
    if review.get("approved_for_execution") is not True or review.get("hypothesis_sha256") != receipt(hypothesis_path)["sha256"]:
        raise ValueError("P/Q instrumentation and command require a matching manual review")
    replay_path = Path(read(case_dir / "active_replay.json")["directory"])
    replay_summary = read(replay_path / "summary.json")
    snapshot = read(replay_path / "test_snapshot.json")
    test_workdir = snapshot.get("working_directory", "/app")
    checkpoint = replay_summary["final_context_checkpoint"]
    staging = read(hypothesis_dir / "staging.json")
    executions = {}
    for name, variant in staging["variants"].items():
        directory = out / name
        if (directory / "execution.json").exists():
            executions[name] = read(directory / "execution.json"); continue
        with Container(checkpoint["image_id"], directory / "container", checkpoint["head"]) as runtime:
            for path in sorted(Path(variant["tree"]).rglob("*")):
                if path.is_file():
                    runtime.copy_to(path, "/" + path.relative_to(variant["tree"]).as_posix())
            activation = activate_generated_runtime(runtime, case_dir)
            execution = runtime.exec(variant["command"], "test", timeout=180, workdir=test_workdir)
            execution["generated_runtime_activation"] = activation
            collect_observation_files(runtime, snapshot.get("observation_paths", []), directory / "observation_files", execution)
            try:
                execution["events"] = parse_events(execution["stdout"] + "\n" + execution["stderr"] + "\n" +
                    "\n".join(row.get("content", "") for row in execution["observation_files"]))
            except ValueError as exc:
                execution.update(events=[], event_error=str(exc))
            write(directory / "execution.json", execution)
            executions[name] = execution
    def trace(name, channel):
        return [{k: e[k] for k in ("anchor", "target_reached", "value")} for e in executions[name]["events"] if e["channel"] == channel]
    effects = {v: trace(v + "_instrumented", "effect") for v in ("p", "q")}
    observations = {v: trace(v + "_instrumented", "observation") for v in ("p", "q")}
    result = {"id": c["id"], "status": "executed_pending_independent_review", "hypothesis": receipt(hypothesis_path),
              "effects": effects, "observations": observations,
              "nonempty_effect_sequences_differ": bool(effects["p"] and effects["q"]) and effects["p"] != effects["q"],
              "nonempty_observation_sequences_equal": bool(observations["p"] and observations["q"]) and observations["p"] == observations["q"],
              "executions": {name: {k: e.get(k) for k in ("returncode", "timed_out", "transport_error", "event_error", "elapsed_seconds")} for name, e in executions.items()},
              "not_a_label": "Trace differences alone do not certify Eq2: independent review must establish target correspondence, public observation, noninterference and an independent masking factor."}
    write(out / "summary.json", result)
    return result
