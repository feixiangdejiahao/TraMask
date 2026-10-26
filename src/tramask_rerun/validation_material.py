"""Pure, receipt-bound execution plans for one frozen Track B validation.

``load_validation_material`` reads only explicitly supplied evidence receipts.
``plan_validation`` returns fresh-checkpoint P/candidate-P file specifications;
an optional evaluator Q requires a previously frozen model output receipt.
Neither function runs commands, repairs syntax, or assigns semantic verdicts.
Build steps and their fresh-executable receipt requirements must be enforced by
the runtime in the same clone, after writes and before the exact test command.

Usage::

    material = load_validation_material(public_receipt, inventory_receipt, test_id,
        checkpoint_proof_receipt=replay_summary_receipt,
        terminal_export_receipts=[terminal_sources_receipt])
    direct = plan_validation(material, candidate)  # No Q required.
    target = plan_validation(material, fixed_q_receipt=planning_receipt,
        frozen_output_receipt=planning_receipt)  # Frozen stage1 Q is allowed.

Each ``arms`` value exposes ``files``, ``command``, ``working_directory`` and
``build_commands`` for the runtime; a differing build cwd instead requires the
explicit ``build_steps`` coordinator. Fresh-binary receipt gates are mandatory.
The caller enforces which protocol stage may supply Q. Invalid Q does not block
an independent ``plan_validation(material)`` for the original P baseline.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from .validation_inventory import _heredocs
from .variants import _apply, _collisions, _edits, _files, _path


def _sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode("utf-8")).hexdigest()


def _digest(value):
    return _sha(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")))


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _read(bound, *, json_value=True):
    if not isinstance(bound, dict) or set(bound) != {"path", "bytes", "sha256"}:
        raise ValueError("exact_receipt_required")
    path = Path(bound["path"])
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("receipt_path_must_be_absolute_without_symlinks")
    data = path.read_bytes()
    if type(bound["bytes"]) is not int or len(data) != bound["bytes"] or _sha(data) != bound["sha256"]:
        raise ValueError("receipt_hash_or_size_mismatch")
    if not json_value:
        return data
    return json.loads(data, object_pairs_hook=_unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite_json")))


def _checkpoint(value):
    if not isinstance(value, dict):
        raise ValueError("immutable_checkpoint_required")
    image, head = value.get("image_id"), value.get("head")
    if not isinstance(image, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise ValueError("immutable_checkpoint_required")
    if not isinstance(head, str) or not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", head):
        raise ValueError("immutable_checkpoint_head_required")
    return {"image_id": image, "head": head.lower()}


def _cwd(value):
    if value in ("/app", "/tmp"):
        return value
    if not isinstance(value, str) or not value.startswith("/"):
        raise ValueError("absolute_working_directory_required")
    return "/" + _path(value)


def _shell_quotes(command):
    """Check shell quoting without interpreting or executing the command."""
    if not isinstance(command, str) or not command or "\0" in command:
        raise ValueError("invalid_shell_command")
    heredocs = _heredocs(command)
    if any(not row["terminated"] for row in heredocs):
        raise ValueError("unterminated_shell_heredoc")
    skipped = {row["body_start"]: row["end"] for row in heredocs}
    quote, escaped, i = None, False, 0
    while i < len(command):
        if i in skipped and quote is None and not escaped:
            i = skipped[i]
            continue
        char = command[i]
        if escaped:
            escaped = False
        elif char == "\\" and quote != "'":
            escaped = True
        elif quote:
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        i += 1
    if quote or escaped:
        raise ValueError("invalid_shell_quoting")


def _inline_mapping(test):
    inline = test.get("inline_test")
    if not inline:
        return None
    if "path" in inline:
        result = copy.deepcopy(inline)
    else:
        text = inline["content"]
        if _sha(text) != inline["sha256"] or test["command"].count(text) != 1:
            raise ValueError("inline_requires_unique_exact_command_range")
        start = len(test["command"][:test["command"].index(text)].encode())
        extension = {"python": "py", "javascript": "js", "typescript": "ts", "bash": "sh"}.get(inline.get("language"), "txt")
        result = {"path": "tmp/tramask_inline/" + _sha(text) + "." + extension,
                  "text": text, "command_mapping": {"original_command": test["command"],
                  "script_start_byte": start, "script_end_byte": start + len(text.encode())}}
    result["path"] = _path(result["path"])
    mapping = result["command_mapping"]
    command, text = test["command"], result["text"]
    start, end = mapping["script_start_byte"], mapping["script_end_byte"]
    if (mapping["original_command"] != command or type(start) is not int or type(end) is not int
            or not 0 <= start < end <= len(command.encode())
            or command.encode()[start:end] != text.encode() or command.count(text) != 1):
        raise ValueError("inline_command_byte_binding_mismatch")
    # Both boundaries must be UTF-8 boundaries, even for an unchanged body.
    command.encode()[:start].decode("utf-8")
    command.encode()[end:].decode("utf-8")
    return result


def _replace_inline(command, inline, text):
    """Substitute literal bytes only in a supported, unchanged shell enclosure."""
    if not isinstance(text, str) or "\0" in text:
        raise ValueError("invalid_inline_text")
    mapping = inline["command_mapping"]
    start, end = mapping["script_start_byte"], mapping["script_end_byte"]
    raw = command.encode(); prefix, suffix = raw[:start], raw[end:]
    left, right = len(prefix.decode()), len(raw[:end].decode())
    quote, opener, escaped = None, None, False
    for index, char in enumerate(prefix.decode()):
        if escaped:
            escaped = False
        elif char == "\\" and quote != "'":
            escaped = True
        elif quote:
            if char == quote:
                quote, opener = None, None
        elif char in "'\"":
            quote, opener = char, index
    docs = [h for h in _heredocs(command) if h["body_start"] == left and h["body_end"] == right]
    if docs:
        h = docs[0]
        if not h["quoted"] or h["strip_tabs"] or not h["terminated"]:
            raise ValueError("unsupported_inline_heredoc_enclosure")
        if not text.endswith("\n") or h["delimiter"] in text.splitlines():
            raise ValueError("inline_heredoc_delimiter_collision")
    elif quote == "'" and opener == left - 1 and suffix.startswith(b"'"):
        if "'" in text:
            raise ValueError("inline_single_quote_collision")
    elif quote == '"' and opener == left - 1 and suffix.startswith(b'"'):
        if any(c in text for c in ('"', "$", "`")) or re.search(r'\\[\n\\"$`]', text):
            raise ValueError("inline_double_quote_or_expansion_collision")
    else:
        raise ValueError("unsupported_inline_shell_enclosure")
    result = (prefix + text.encode() + suffix).decode()
    _shell_quotes(result)
    return result


def _indexed(rows, key, name):
    result = {}
    for row in rows:
        value = row[key]
        if value in result:
            raise ValueError("duplicate_" + name)
        result[value] = row
    return result


def load_validation_material(public_input_receipt, inventory_receipt, test_id, *,
                             checkpoint_proof_receipt, terminal_export_receipts=()):
    """Bind exact frozen inputs to a proven checkpoint and one inventory entry.

    Proof schema: ``state_validation_passed: true``, immutable ``checkpoint``,
    and an ``inventory`` receipt for a complete filesystem manifest (``files``
    plus empty ``errors``). Existing replay summary receipts satisfy this API.
    Exports provide terminal bytes for mixed production/test modules; all bytes
    are independently checked against that checkpoint's filesystem manifest.
    """
    public, inventory, proof = map(_read, (public_input_receipt, inventory_receipt, checkpoint_proof_receipt))
    if proof.get("state_validation_passed") is not True:
        raise ValueError("checkpoint_state_proof_required")
    checkpoint = _checkpoint(proof["checkpoint"])
    if _checkpoint(inventory["checkpoint"]) != checkpoint:
        raise ValueError("inventory_checkpoint_mismatch")
    if inventory.get("inventory_complete_for_declared_recovery_scope") is not True:
        raise ValueError("complete_qualified_inventory_required")
    if public.get("case_id", public.get("id")) != inventory.get("case_id"):
        raise ValueError("public_inventory_case_mismatch")
    manifest = _read(proof["inventory"])
    if manifest.get("errors"):
        raise ValueError("incomplete_checkpoint_filesystem_inventory")
    metadata = _indexed(manifest["files"], "path", "manifest_path")
    authorities = [public_input_receipt, inventory_receipt, checkpoint_proof_receipt, proof["inventory"]]
    native = _files(public.get("final_sources", {}))
    for bound in terminal_export_receipts:
        exported = _read(bound); authorities.append(bound)
        if _checkpoint(exported["checkpoint"]) != checkpoint or exported.get("status") != "complete":
            raise ValueError("terminal_export_checkpoint_mismatch")
        for row in exported["files"]:
            if row.get("status") != "present" or not isinstance(row.get("content"), str):
                continue
            path = _path(row["path"]); text = row["content"]
            if _sha(text) != row.get("sha256") or (path in native and native[path] != text):
                raise ValueError("terminal_export_content_mismatch")
            native[path] = text
    for path, text in native.items():
        meta = metadata.get("/" + path, {})
        if meta.get("kind") != "file" or meta.get("sha256") != _sha(text):
            raise ValueError("terminal_content_manifest_mismatch: " + path)
    public_tests = _indexed(public["validation_tests"], "id", "public_test_id")
    qualified = _indexed(inventory["validation_tests"], "id", "qualified_test_id")
    if public_tests.keys() != qualified.keys() or test_id not in qualified:
        raise ValueError("frozen_inventory_test_set_mismatch")
    # Bind the complete public test inventory, not just a conveniently matching ID.
    for identifier, test in qualified.items():
        frozen = public_tests[identifier]; expected = _files(test["files"])
        inline = _inline_mapping(test)
        if inline:
            if inline["path"] in expected:
                raise ValueError("inline_virtual_path_collision")
            expected[inline["path"]] = inline["text"]
        if (frozen["command"] != test["command"] or frozen["working_directory"] != test["working_directory"]
                or _files(frozen["files"]) != expected or frozen.get("inline_test") != inline):
            raise ValueError("frozen_public_test_mismatch: " + identifier)
    selected = copy.deepcopy(qualified[test_id]); files = _files(selected["files"])
    if set(files) != {_path(p) for p in selected["test_paths"]}:
        raise ValueError("test_path_mapping_mismatch")
    materialization = selected["materialization"]
    if materialization.get("production_overlay") is not False or materialization.get("after_terminal_stateproof_only") is not True:
        raise ValueError("explicit_test_only_materialization_required")
    bindings = _indexed(materialization["files"], "path", "materialization_path")
    if set(bindings) != {"/" + p for p in files}:
        raise ValueError("materialization_path_mapping_mismatch")
    predecessors = {}
    for path, text in files.items():
        binding = bindings["/" + path]; file_receipt = selected["file_receipts"][path]
        status = binding.get("status", materialization.get("kind"))
        expected = binding["expected_terminal_sha256"]; meta = metadata.get("/" + path)
        for flag in ("assert_absent_before_materialization", "replace_existing_test_only"):
            if flag in binding and type(binding[flag]) is not bool:
                raise ValueError("materialization_flags_must_be_boolean")
        if ("assert_absent_before_materialization" in binding
                and binding["assert_absent_before_materialization"] != (expected is None)):
            raise ValueError("explicit_new_file_flag_disagrees_with_predecessor")
        if expected is None and binding.get("replace_existing_test_only") is True:
            raise ValueError("new_file_cannot_replace_existing_file")
        if _sha(text) != file_receipt["sha256"] or _sha(text) != binding["content_sha256"]:
            raise ValueError("selected_test_hash_mismatch")
        authority = file_receipt["authority_receipt"]; _read(authority, json_value=False); authorities.append(authority)
        if file_receipt.get("terminal_sha256") != expected:
            raise ValueError("test_predecessor_receipts_disagree")
        if expected is None:
            roots = manifest.get("roots", [])
            covered = any(isinstance(root, str) and ("/" + path).startswith(root.rstrip("/") + "/") for root in roots)
            if not covered or meta is not None or status != "explicit_historical_test_version":
                raise ValueError("new_test_requires_proven_absence")
        elif not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected) or not meta or meta.get("kind") != "file" or meta.get("sha256") != expected:
            raise ValueError("test_terminal_predecessor_mismatch")
        if status == "terminal":
            if expected != _sha(text):
                raise ValueError("native_test_bytes_differ_from_terminal")
        elif status != "explicit_historical_test_version":
            raise ValueError("unknown_materialization_status")
        for parent in PurePosixPath("/" + path).parents:
            if str(parent) in metadata and metadata[str(parent)].get("kind") not in {"directory", "dir"}:
                raise ValueError("test_path_non_directory_ancestor")
        predecessors[path] = expected
    guards = {}
    for guard in selected.get("protected_test_regions", []):
        path = _path(guard["path"])
        if path not in files or path in guards or path not in native:
            raise ValueError("mixed_test_requires_unique_terminal_bytes")
        raw, terminal = files[path].encode(), native[path].encode()
        start, end = guard["selected_region_utf8_offsets"]; old_start, old_end = guard["terminal_region_utf8_offsets"]
        if (any(type(i) is not int for i in (start, end, old_start, old_end))
                or not 0 <= start < end == len(raw) or not 0 <= old_start < old_end == len(terminal)
                or raw[:start] != terminal[:old_start]
                or _sha(raw[:start]) != guard["terminal_production_prefix_sha256"]
                or _sha(raw[start:]) != guard["original_test_region_sha256"]
                or _sha(terminal[old_start:]) != guard["terminal_test_region_sha256"]):
            raise ValueError("mixed_test_region_or_prefix_hash_mismatch")
        prefix, suffix = raw[:start].decode(), raw[start:].decode()
        marker = guard["marker"]
        if (guard.get("region_kind") != "cfg_test_module_suffix" or marker != "#[cfg(test)]\nmod tests {"
                or not suffix.startswith(marker) or raw.decode().count(marker) != 1):
            raise ValueError("unsupported_protected_test_region")
        guards[path] = {"prefix": prefix, "suffix": suffix, "guard": guard}
    if any(bindings["/" + p].get("test_region_only") is True and p not in guards for p in files):
        raise ValueError("missing_mixed_test_region_guard")
    if files.keys() & public.get("final_sources", {}).keys() - guards.keys():
        raise ValueError("production_test_overlap_requires_region_guard")
    inline = _inline_mapping(selected)
    if inline:
        virtual = inline["path"]
        all_test_files = {_path(p) for t in qualified.values() for p in t["files"]}
        if "/" + virtual in metadata or virtual in native or virtual in all_test_files:
            raise ValueError("inline_virtual_path_collision")
        if any(str(parent) in metadata and metadata[str(parent)].get("kind") not in {"directory", "dir"}
               for parent in PurePosixPath("/" + virtual).parents):
            raise ValueError("inline_virtual_path_ancestor_collision")
        _collisions(set(native) | all_test_files | {virtual})
        _replace_inline(selected["command"], inline, inline["text"])
    _collisions(set(native) | set(files))
    command = selected["command"]; _shell_quotes(command)
    workdir = _cwd(selected["working_directory"])
    build = copy.deepcopy(selected.get("build_contract"))
    if build:
        if build.get("required_before_execution") is not True:
            raise ValueError("explicit_required_build_contract_expected")
        _shell_quotes(build["exact_original_build_command"]); _cwd(build["working_directory"])
        binary_path = _path(build["expected_binary_path"])
        if binary_path in files or binary_path in public.get("final_sources", {}):
            raise ValueError("build_output_collides_with_test_or_source")
    result = {"case_id": inventory["case_id"], "test_id": test_id, "checkpoint": checkpoint,
              "command": command, "working_directory": workdir, "test_files": files,
              "production_files": _files(public.get("final_sources", {})), "terminal_files": native,
              "predecessors": predecessors, "protected_regions": guards, "inline": inline,
              "build_contract": build, "environment_binding": copy.deepcopy(selected.get("environment_binding", {})),
              "authorities": list({_digest(b): b for b in authorities}.values()),
              "inventory_receipt": copy.deepcopy(inventory_receipt), "public_input_receipt": copy.deepcopy(public_input_receipt)}
    result["integrity_sha256"] = _digest(result)
    return result


def plan_validation(material, candidate=None, *, fixed_q_receipt=None, frozen_output_receipt=None):
    """Return deterministic runtime-ready arms; a direct candidate needs no Q.

    A candidate is ``{status: 'proposed', edits: [{path, old, new}, ...]}``.
    ``None``/``no_proposal`` stays an abstention with no candidate arm. Optional
    Q JSON supplies ``edits`` or ``alternative.edits``; its exact receipt and a
    frozen JSON output containing this candidate are required before Q staging.
    """
    bound = copy.deepcopy(material); seal = bound.pop("integrity_sha256", None)
    if seal != _digest(bound):
        raise ValueError("validation_material_changed_after_binding")
    for authority in bound["authorities"]:
        _read(authority, json_value=False)
    tests = dict(bound["test_files"]); inline = bound["inline"]
    if inline:
        tests[inline["path"]] = inline["text"]
    base = {**bound["production_files"], **tests}
    guards = bound["protected_regions"]
    changed = None
    if candidate is not None:
        if not isinstance(candidate, dict):
            raise ValueError("candidate_must_be_object_or_none")
        if candidate.get("status") == "no_proposal":
            if candidate.get("edits"):
                raise ValueError("abstention_must_not_contain_edits")
        elif candidate.get("status") == "proposed" and candidate.get("edits"):
            edits = _edits(candidate["edits"])
            if any(e["path"] not in tests for e in edits):
                raise ValueError("candidate_outside_selected_test_material")
            changed = _apply(base, edits)
            for path, guard in guards.items():
                if not changed[path].startswith(guard["prefix"]) or not changed[path][len(guard["prefix"]):].startswith(guard["guard"]["marker"]):
                    raise ValueError("candidate_changed_production_prefix_or_region_boundary")
        else:
            raise ValueError("candidate_requires_proposed_edits_or_no_proposal")
    q = None
    if fixed_q_receipt is not None:
        if frozen_output_receipt is None:
            raise ValueError("fixed_Q_requires_frozen_output_receipt")
        frozen, fixed = _read(frozen_output_receipt), _read(fixed_q_receipt)
        if not isinstance(fixed, dict):
            raise ValueError("fixed_Q_must_be_object")
        frozen_candidates = frozen.get("candidates", []) if isinstance(frozen, dict) else []
        if not isinstance(frozen_candidates, list):
            raise ValueError("frozen_candidates_must_be_list")
        if candidate is not None and not (frozen == candidate or isinstance(frozen, dict) and
                (frozen.get("candidate") == candidate or candidate in frozen_candidates)):
            raise ValueError("candidate_not_in_frozen_output")
        edits = fixed.get("edits", fixed.get("alternative", {}).get("edits"))
        if not edits:
            raise ValueError("fixed_Q_requires_exact_edits")
        edits = _edits(edits)
        if any(e["path"] not in bound["production_files"] and e["path"] not in guards for e in edits):
            raise ValueError("fixed_Q_outside_production_material")
        q = _apply(base, edits)
        for path, guard in guards.items():
            if not q[path].endswith(guard["suffix"]) or q[path].count(guard["guard"]["marker"]) != 1:
                raise ValueError("fixed_Q_changed_protected_test_region")
        for path in tests.keys() - guards.keys():
            if q[path] != base[path]:
                raise ValueError("fixed_Q_changed_test_material")
    maps = {"p_original": base}
    if changed is not None:
        maps["p_candidate"] = changed
    if q is not None:
        maps["q_original"] = q
        if changed is not None:
            combined = dict(q)
            for path in tests:
                if path in guards:
                    suffix = guards[path]["suffix"]
                    combined[path] = q[path][:-len(suffix)] + changed[path][len(guards[path]["prefix"]):]
                else:
                    combined[path] = changed[path]
            maps["q_candidate"] = combined
    records = {}
    for name, full in maps.items():
        specs = {}; command = bound["command"]
        for path, text in full.items():
            if inline and path == inline["path"]:
                command = _replace_inline(command, inline, text)
                continue
            before = bound["predecessors"].get(path, _sha(bound["terminal_files"][path]) if path in bound["terminal_files"] else None)
            if before is None:
                if path not in bound["predecessors"]:
                    raise ValueError("unbound_new_file")
                specs["/" + path] = {"content": text, "new_file": True}
            elif _sha(text) != before:
                specs["/" + path] = {"content": text, "before_sha256": before}
        build = bound["build_contract"]
        builds = [] if not build else [{"command": build["exact_original_build_command"], "working_directory": build["working_directory"],
                    "expected_binary_path": build["expected_binary_path"], "require_fresh_executable_receipt": True,
                    "after_materialization_and_source_edits": True, "before_test": True}]
        records[name] = {"files": specs, "command": command, "working_directory": bound["working_directory"],
                         "full_text": full, "build_contract": copy.deepcopy(build), "build_steps": builds,
                         "environment_binding": copy.deepcopy(bound["environment_binding"]),
                         "build_commands": [x["command"] for x in builds] if all(x["working_directory"] == bound["working_directory"] for x in builds) else None,
                         "after_sha256": {"/" + p: _sha(t) for p, t in full.items() if not inline or p != inline["path"]},
                         "requires_fresh_checkpoint_clone": True}
    result = {"version": "validation-material-plan.v1", "case_id": bound["case_id"], "test_id": bound["test_id"],
              "checkpoint": bound["checkpoint"], "arms": records, "candidate": copy.deepcopy(candidate),
              "candidate_status": "not_submitted" if candidate is None else candidate["status"],
              "material_integrity_sha256": seal, "public_input_receipt": bound["public_input_receipt"],
              "inventory_receipt": bound["inventory_receipt"], "fixed_q_receipt": copy.deepcopy(fixed_q_receipt),
              "frozen_output_receipt": copy.deepcopy(frozen_output_receipt), "executed": False,
              "semantic_classification": None, "syntax_repaired": False}
    result["plan_sha256"] = _digest(result)
    return result
