"""Prepare exact P/Q/probe/candidate file maps; never execute subject commands.

Runtime writes always bind to the original checkpoint, not an intermediate Q or
instrumented file. Structural validity never establishes E7/noninterference.
"""
from __future__ import annotations

import copy
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path, PurePosixPath

from tramask_pilot.hypotheses import validate_hypothesis


VARIANTS = ("p_original", "q_original", "p_instrumented", "q_instrumented")
PRIVATE = {".git", ".aws", ".agents", ".codex", "hidden_tests", "reference_solutions", "evaluation_assets"}
FLAGS = ("preserves_target_operation", "preserves_target_input_values", "preserves_target_input_semantics",
         "preserves_original_observation", "preserves_original_assertions")
PROPOSED_KEYS = {"rank", "status", "factor", "location", "current_state", "proposed_state", "evidence_refs",
                 "contract_justification", "semantic_factor_count", "change_scope", "edits", "operation_groups", *FLAGS}


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _text(value, name, empty=False):
    if not isinstance(value, str) or "\0" in value or (not empty and not value):
        raise ValueError("invalid_" + name)
    return value


def _path(value):
    _text(value, "subject_path")
    path = PurePosixPath(value)
    if "\\" in value or str(path) != value or ".." in path.parts:
        raise ValueError("noncanonical_subject_path")
    relative = value[1:] if path.is_absolute() else value
    parts = PurePosixPath(relative).parts
    if len(parts) < 2 or parts[0] not in {"app", "tmp"}:
        raise ValueError("subject_path_outside_app_or_tmp")
    if any(p in PRIVATE or p == ".env" or p.startswith(".env.") for p in parts):
        raise ValueError("private_subject_path")
    return relative


def _files(source_files):
    if not isinstance(source_files, dict):
        raise ValueError("source_files_must_be_full_text_mapping")
    result = {}
    for path, text in source_files.items():
        key = _path(path)
        if key in result:
            raise ValueError("duplicate_normalized_source_path")
        result[key] = _text(text, "full_file_text", empty=True)
    _collisions(result)
    return result


def _collisions(paths):
    names = set(paths)
    if any(str(parent) in names for name in names for parent in PurePosixPath(name).parents):
        raise ValueError("file_directory_collision")


def _edits(edits):
    if not isinstance(edits, list):
        raise ValueError("edits_must_be_list")
    result = []
    for row in edits:
        if not isinstance(row, dict) or set(row) != {"path", "old", "new"}:
            raise ValueError("edit_requires_exact_path_old_new")
        old, new = _text(row["old"], "old"), _text(row["new"], "new", empty=True)
        if old == new:
            raise ValueError("no_op_edit")
        result.append({"path": _path(row["path"]), "old": old, "new": new})
    return result


def _apply(files, edits):
    result, planned = dict(files), {}
    for row in _edits(edits):
        name = row["path"]
        if name not in files:
            raise ValueError("exact_edit_missing_source: " + name)
        base, old = files[name], row["old"]
        start = base.find(old)
        if start < 0 or base.find(old, start + 1) >= 0:
            raise ValueError("old_anchor_must_occur_exactly_once: " + name)
        planned.setdefault(name, []).append((start, start + len(old), row["new"]))
    for name, spans in planned.items():
        spans.sort()
        if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
            raise ValueError("overlapping_exact_edits: " + name)
        text = files[name]
        for start, end, replacement in reversed(spans):
            text = text[:start] + replacement + text[end:]
        result[name] = text
    return result


def _hypothesis(value):
    result = copy.deepcopy(value)
    if not isinstance(result, dict) or result.get("status") != "proposed":
        raise ValueError("proposed_hypothesis_required")
    result["target"]["source_path"] = _path(result["target"]["source_path"])
    result["alternative"]["edits"] = _edits(result["alternative"]["edits"])
    probe = result["instrumentation"]
    for key in ("common_edits", "p_edits", "q_edits"):
        probe[key] = _edits(probe[key])
    for helper in probe["helper_files"]:
        helper["path"] = _path(helper["path"])
    return result


def _prepare(source_files, hypothesis, test_paths=()):
    base, h = _files(source_files), _hypothesis(hypothesis)
    tests = {_path(p) for p in test_paths}
    validate_hypothesis(h, source_paths=set(base) - tests, test_paths=tests)
    q = _apply(base, h["alternative"]["edits"])
    probe = h["instrumentation"]
    helpers = {row["path"]: row["content"] for row in probe["helper_files"]}
    if helpers.keys() & base.keys():
        raise ValueError("probe_helper_already_in_checkpoint_inputs")
    _collisions(base.keys() | helpers.keys())
    maps = {"p_original": base, "q_original": q}
    for variant, initial in (("p", base), ("q", q)):
        common = _apply(initial, probe["common_edits"])
        common.update(helpers)
        maps[variant + "_instrumented"] = _apply(common, probe[variant + "_edits"])
    return base, h, maps, set(helpers)


def _origins(base, origins):
    supplied = {} if origins is None else {_path(k): v for k, v in origins.items()}
    if set(supplied) - set(base):
        raise ValueError("origin_for_unknown_source")
    hashes, new_files = {}, set()
    for path, text in base.items():
        origin = supplied.get(path, {})
        if not isinstance(origin, dict):
            raise ValueError("source_origin_requires_metadata")
        if origin.get("kind", "checkpoint") not in {"checkpoint", "regular_file", "historical_test_capsule"}:
            raise ValueError("source_origin_not_regular_file")
        claimed = origin.get("sha256", origin.get("before_sha256", _sha(text)))
        if claimed != _sha(text):
            raise ValueError("source_origin_hash_mismatch")
        is_new = origin.get("new_file", False)
        if type(is_new) is not bool:
            raise ValueError("source_new_file_must_be_boolean")
        if is_new:
            if origin.get("kind") != "historical_test_capsule" or "sha256" not in origin:
                raise ValueError("new_source_requires_explicit_historical_capsule_receipt")
            new_files.add(path)
        elif origin.get("kind") == "historical_test_capsule":
            raise ValueError("historical_capsule_requires_explicit_new_file")
        hashes["/" + path] = None if is_new else _sha(text)
    return hashes, new_files


def _save(base, h, maps, helpers, out, origins, extra=None):
    hashes, capsules = _origins(base, origins)
    hashes.update({"/" + path: None for path in helpers})
    production = {e["path"] for e in h["alternative"]["edits"]} | {h["target"]["source_path"]}
    if production & capsules:
        raise ValueError("historical_capsule_must_not_supply_production_source")
    records = {}
    for name in VARIANTS:
        full, specs = maps[name], {}
        for path, content in full.items():
            if path in helpers or path in capsules:
                specs["/" + path] = {"content": content, "new_file": True}
            elif content != base[path]:
                specs["/" + path] = {"content": content, "before_sha256": hashes["/" + path]}
        records[name] = {"full_text": full, "files": specs,
                         "command": h["instrumentation"]["command"] if name.endswith("_instrumented") else h["original_command"],
                         "command_review_required": True,
                         "after_sha256": {"/" + p: _sha(t) for p, t in full.items()}}
    result = {"variants": records, "checkpoint_before_hashes": hashes,
              "explicit_new_probe_helpers": sorted("/" + p for p in helpers),
              "explicit_new_historical_capsules": sorted("/" + p for p in capsules),
              "executed": False, "E7": None, "semantic_review": "pending_semantic_review",
              "instrumentation_noninterference": "pending_execution_and_review", **(extra or {})}
    output = Path(out).absolute()
    if ".." in output.parts or any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError("symlink_or_noncanonical_output_path")
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()
    with (output / "manifest.json").open("x") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return result


def stage_hypothesis(source_files, hypothesis, out, *, source_origins=None, test_paths=()):
    """Four full-text maps and absolute runtime specs, no source/content recovery.

    By default P has no writes. Optional source_origins[path] may explicitly name
    {kind:'historical_test_capsule', new_file:True, sha256:...}; only that caller-
    supplied capsule is added to original P. All other source bytes are treated
    as checkpoint bytes, and the runtime verifies their predecessor hashes.
    """
    base, h, maps, helpers = _prepare(source_files, hypothesis, test_paths)
    return _save(base, h, maps, helpers, out, source_origins)


def _hunks(base, changed):
    return [(a, b, changed[c:d]) for tag, a, b, c, d in
            SequenceMatcher(None, base, changed, autojunk=False).get_opcodes() if tag != "equal"]


def _merge(base, probe, candidate):
    """Conservative three-way merge with exact reconstruction of both branches."""
    insertions, changes = _hunks(base, probe), _hunks(base, candidate)
    if any(start != end for start, end, _ in insertions):
        raise ValueError("probe_is_not_verifiable_insertion_only")
    for position, _, _ in insertions:
        if any(start < position < end or start == end == position for start, end, _ in changes):
            raise ValueError("candidate_probe_merge_conflict")
    combined = [(s, e, t, "candidate") for s, e, t in changes]
    combined += [(s, e, t, "probe") for s, e, t in insertions]
    def rebuild(parts):
        text = base
        for start, end, replacement, _ in sorted(parts, key=lambda x: (x[0], x[1]), reverse=True):
            text = text[:start] + replacement + text[end:]
        return text
    if rebuild([p for p in combined if p[3] == "probe"]) != probe or rebuild(
            [p for p in combined if p[3] == "candidate"]) != candidate:
        raise ValueError("three_way_branch_reconstruction_failed")
    merged = rebuild(combined)
    return merged, {"base_sha256": _sha(base), "probe_sha256": _sha(probe),
                    "candidate_sha256": _sha(candidate), "merged_sha256": _sha(merged),
                    "preserved_probe_insertions": len(insertions), "candidate_changed_spans": len(changes),
                    "branch_reconstruction_verified": True}


def stage_candidate(source_files, hypothesis, candidate, out, allowed_test_paths, *, source_origins=None):
    """Apply candidate independently to original tests, then merge fixed probes.

    The response validator must be used separately before staging a model slot.
    This function still preflights exact anchors, test allowlist, fixed Q, probe
    preservation and collisions. It cannot certify context legality or E7.
    """
    tests = {_path(path) for path in allowed_test_paths}
    base, h, original_maps, helpers = _prepare(source_files, hypothesis, tests)
    edits = _edits(candidate.get("edits"))
    if candidate.get("status", "proposed") != "proposed" or not edits:
        raise ValueError("candidate_requires_proposed_nonempty_edits")
    if any(e["path"] not in tests for e in edits):
        raise ValueError("candidate_outside_test_allowlist")
    changed = _apply(base, edits)
    paths = {e["path"] for e in edits}
    maps, merges = {}, {}
    for variant in VARIANTS:
        full = dict(original_maps[variant])
        for path in paths:
            if variant.endswith("_instrumented"):
                full[path], detail = _merge(base[path], full[path], changed[path])
                merges.setdefault(variant, {})[path] = detail
            else:
                if full[path] != base[path]:
                    raise ValueError("Q_changes_candidate_test_source")
                full[path] = changed[path]
        maps[variant] = full
    production = set(base) - tests
    for variant in VARIANTS:
        if any(maps[variant][p] != original_maps[variant][p] for p in production):
            raise ValueError("candidate_changed_fixed_production_or_probe")
    return _save(base, h, maps, helpers, out, source_origins,
                 {"candidate_rank": candidate.get("rank"), "three_way_merges": merges,
                  "fixed_Q_preserved": True, "candidate_edits": edits})


def _json_response(value):
    if isinstance(value, str):
        def unique(pairs):
            result = {}
            for key, item in pairs:
                if key in result:
                    raise ValueError("duplicate_json_key")
                result[key] = item
            return result
        def finite(value):
            raise ValueError("nonfinite_json_value")
        return json.loads(value, object_pairs_hook=unique, parse_constant=finite)
    return value


def _candidate(row, context):
    if set(row) != PROPOSED_KEYS:
        raise ValueError("proposed_candidate_keys_mismatch")
    for field in ("factor", "location", "current_state", "proposed_state", "contract_justification"):
        _text(row[field], field)
    refs = row["evidence_refs"]
    if not isinstance(refs, list) or not refs or any(not isinstance(r, str) or r not in context.get("available_evidence_refs", []) for r in refs):
        raise ValueError("invalid_or_unavailable_evidence_refs")
    for flag in FLAGS:
        if type(row[flag]) is not bool:
            raise ValueError("preservation_flags_must_be_boolean")
    if not row["preserves_original_assertions"]:
        raise ValueError("original_assertion_preservation_claim_required")
    scope = row["change_scope"]
    if scope not in {"context_only", "test_body_or_assertions"}:
        raise ValueError("unknown_change_scope")
    if context.get("edit_policy") == "context_only" and scope != "context_only":
        raise ValueError("context_only_policy_violation")
    count = row["semantic_factor_count"]
    if type(count) is not int or count < 0:
        raise ValueError("invalid_semantic_factor_count")
    if scope == "context_only" and (count not in {1, 2} or not all(row[f] for f in FLAGS)):
        raise ValueError("context_only_requires_one_or_two_factors_and_preservation_claims")
    edits = _edits(row["edits"])
    allowed = {_path(p) for p in context.get("editable_paths", [])}
    if not edits or any(e["path"] not in allowed for e in edits):
        raise ValueError("edit_outside_exact_test_allowlist")
    groups = row["operation_groups"]
    if not isinstance(groups, list) or not groups:
        raise ValueError("operation_groups_required")
    factors, operation_ids, assignments = set(), set(), []
    for group in groups:
        if not isinstance(group, dict) or set(group) != {"factor", "operations"}:
            raise ValueError("invalid_operation_group")
        factor = _text(group["factor"], "operation_factor")
        if factor in factors:
            raise ValueError("duplicate_operation_factor")
        factors.add(factor)
        if not isinstance(group["operations"], list) or not group["operations"]:
            raise ValueError("empty_operation_group")
        for op in group["operations"]:
            if not isinstance(op, dict) or set(op) != {"id", "description", "edit_indices"}:
                raise ValueError("invalid_atomic_operation")
            op_id = _text(op["id"], "operation_id")
            _text(op["description"], "operation_description")
            if op_id in operation_ids:
                raise ValueError("duplicate_operation_id")
            operation_ids.add(op_id)
            indices = op["edit_indices"]
            if not isinstance(indices, list) or not indices or any(type(i) is not int or not 0 <= i < len(edits) for i in indices):
                raise ValueError("invalid_operation_edit_indices")
            assignments.extend(indices)
    if sorted(assignments) != list(range(len(edits))):
        raise ValueError("every_edit_must_belong_to_exactly_one_operation")
    if len(operation_ids) > min(8, context.get("max_atomic_setup_operations", 8)):
        raise ValueError("atomic_operation_budget_exceeded")
    if scope == "context_only" and (len(factors) != count or count > min(2, context.get("max_semantic_factors", 2))):
        raise ValueError("semantic_factor_group_count_mismatch")
    if "source_files" in context:
        _apply(_files(context["source_files"]), edits)
    return {**row, "edits": edits}


def validate_candidate_response(response, validation_context):
    """Return exactly five registered slots; malformed slots never disappear.

    Only JSON parsing is performed, with no extraction or format/semantic repair.
    Claims about new observations or preservation are not evidence of E7. Actual
    unique anchors are always verified during staging; the caller may also pass
    source_files in validation_context to verify them at response validation.
    """
    errors, parsed = [], None
    try:
        parsed = _json_response(response)
        if not isinstance(parsed, dict) or set(parsed) != {"original_command", "candidates"}:
            raise ValueError("response_top_level_keys_mismatch")
        if validation_context.get("candidate_slots", 5) != 5:
            raise ValueError("registered_candidate_slots_must_be_five")
        if parsed["original_command"] != validation_context.get("original_command") or not isinstance(parsed["original_command"], str):
            raise ValueError("original_command_changed")
        if not isinstance(parsed["candidates"], list) or len(parsed["candidates"]) != 5:
            raise ValueError("response_requires_exactly_five_slots")
    except (ValueError, TypeError) as error:
        errors.append(str(error))
    candidates = parsed.get("candidates", []) if isinstance(parsed, dict) else []
    candidates = candidates if isinstance(candidates, list) else []
    slots, fingerprints, seen_one_factor = [], set(), False
    for index in range(5):
        raw = candidates[index] if index < len(candidates) else None
        slot = {"rank": index + 1, "submitted_rank": raw.get("rank") if isinstance(raw, dict) else None,
                "status": "invalid", "structural_valid": False, "candidate": raw,
                "errors": list(errors), "E7": None, "semantic_review": "pending_semantic_review"}
        if not errors:
            try:
                if not isinstance(raw, dict) or type(raw.get("rank")) is not int or raw["rank"] != index + 1:
                    raise ValueError("slot_rank_must_match_registered_position")
                if raw.get("status") == "no_proposal":
                    if set(raw) != {"rank", "status", "reason"}:
                        raise ValueError("no_proposal_keys_mismatch")
                    _text(raw["reason"], "no_proposal_reason")
                    slot.update(status="no_proposal", structural_valid=True, semantic_review="not_applicable")
                elif raw.get("status") == "proposed":
                    normalized = _candidate(raw, validation_context)
                    if normalized["change_scope"] == "context_only" and normalized["semantic_factor_count"] == 2 and not seen_one_factor:
                        raise ValueError("two_factor_candidate_requires_prior_one_factor_slot")
                    fingerprint = json.dumps(sorted(normalized["edits"], key=lambda e: (e["path"], e["old"], e["new"])), sort_keys=True)
                    if fingerprint in fingerprints:
                        raise ValueError("duplicate_candidate_edits")
                    fingerprints.add(fingerprint)
                    seen_one_factor |= normalized["change_scope"] == "context_only" and normalized["semantic_factor_count"] == 1
                    slot.update(status="proposed", structural_valid=True, normalized_candidate=normalized,
                                anchor_validation="verified" if "source_files" in validation_context else "deferred_to_staging")
                else:
                    raise ValueError("unknown_candidate_slot_status")
            except (ValueError, TypeError, KeyError) as error:
                slot["errors"].append(str(error))
        slots.append(slot)
    return {"n_registered_slots": 5, "slots": slots, "response_errors": errors,
            "unregistered_entries": candidates[5:], "syntax_repaired": False,
            "n_invalid": sum(s["status"] == "invalid" for s in slots),
            "n_no_proposal": sum(s["status"] == "no_proposal" for s in slots),
            "n_structurally_proposed": sum(s["status"] == "proposed" for s in slots),
            "E7": None, "semantic_review": "pending_semantic_review"}
