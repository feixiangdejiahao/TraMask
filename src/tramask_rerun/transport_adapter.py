"""Auditable, in-memory transport recovery; no semantic repair or file writes.

Callers retain the original response and its original validation outcome. Neither
successful function certifies a hypothesis, instrumentation, command, or E label.
Every method must use the same policy before its normal schema/semantic checks.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import PurePosixPath


POLICY = "strict_json_eof_closures_and_unique_public_paths_v1"
PRIVATE = {".git", ".aws", ".agents", ".codex", "hidden_tests", "reference_solutions", "evaluation_assets"}


class TransportAdapterError(ValueError):
    """Rejected recovery, with a machine-readable reason and partial receipt."""

    def __init__(self, code, receipt=None):
        super().__init__(code)
        self.code = code
        self.receipt = copy.deepcopy(receipt or {})
        self.receipt.update(status="rejected", error=code)


def _sha(text):
    try:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    except UnicodeEncodeError as error:
        raise TransportAdapterError("invalid_unicode") from error


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise TransportAdapterError("duplicate_json_key")
        result[key] = value
    return result


def _constant(_):
    raise TransportAdapterError("nonfinite_json_number")


def _finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise TransportAdapterError("nonfinite_json_number")
    return result


def _loads(text):
    return json.loads(text, object_pairs_hook=_object, parse_constant=_constant, parse_float=_finite_float)


def _json_sha(value):
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise TransportAdapterError("not_finite_json_data") from error
    return _sha(encoded)


def recover_json(text):
    """Return ``value``, unchanged ``raw_text``, ``recovered_text`` and receipt.

    Strict parsing comes first. The only recovery is appending the uniquely
    determined closing containers at EOF. A second strict parse must succeed.
    Duplicate keys, nonfinite numbers, open strings, mismatched brackets, and
    missing keys/values/separators are rejected, never rewritten or extracted.
    Offsets in receipts are zero-based Unicode-character and UTF-8-byte offsets.
    """
    if not isinstance(text, str):
        raise TransportAdapterError("json_text_required")
    receipt = {"policy": POLICY, "raw_sha256": _sha(text), "raw_characters": len(text),
               "raw_bytes": len(text.encode("utf-8")), "insertions": [], "semantic_validation": "not_performed"}
    try:
        try:
            value = _loads(text)
            strict = True
        except json.JSONDecodeError as error:
            receipt["original_parse_error"] = {"character_offset": error.pos, "line": error.lineno,
                                                "column": error.colno, "message": error.msg}
            stack, in_string, escaped = [], False, False
            for char in text:
                if in_string:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == '"':
                        in_string = False
                elif char == '"':
                    in_string = True
                elif char in "[{":
                    stack.append("]" if char == "[" else "}")
                elif char in "]}":
                    if not stack or char != stack.pop():
                        raise TransportAdapterError("mismatched_json_containers")
            if in_string:
                raise TransportAdapterError("unterminated_json_string")
            if not stack:
                raise TransportAdapterError("not_eof_container_closure_only")
            suffix = "".join(reversed(stack))
            try:
                value = _loads(text + suffix)
            except json.JSONDecodeError as invalid:
                raise TransportAdapterError("not_eof_container_closure_only") from invalid
            receipt["insertions"] = [{"character_offset": len(text), "utf8_byte_offset": receipt["raw_bytes"],
                                      "text": suffix, "sha256": _sha(suffix)}]
            strict = False
        recovered = text + (receipt["insertions"][0]["text"] if receipt["insertions"] else "")
        receipt.update(status="strict_json" if strict else "recovered_eof_containers", strict_json=strict,
                       recovered_sha256=_sha(recovered), value_sha256=_json_sha(value))
        return {"value": value, "raw_text": text, "recovered_text": recovered, "receipt": receipt}
    except TransportAdapterError as error:
        raise TransportAdapterError(error.code, receipt) from error
    except (ValueError, RecursionError) as error:
        raise TransportAdapterError("invalid_json_data", receipt) from error


def _safe_path(value):
    if not isinstance(value, str) or not value or "\0" in value or "\\" in value:
        raise TransportAdapterError("invalid_public_path")
    path = PurePosixPath(value)
    if str(path) != value or ".." in path.parts or value in {".", "/"}:
        raise TransportAdapterError("noncanonical_public_path")
    if any(p in PRIVATE or p == ".env" or p.startswith(".env.") for p in path.parts):
        raise TransportAdapterError("private_path_not_allowed")
    if path.is_absolute() and (len(path.parts) < 3 or path.parts[1] not in {"app", "tmp"}):
        raise TransportAdapterError("absolute_path_outside_app_or_tmp")
    return value


def _public_files(source_files, test_paths):
    if not isinstance(source_files, dict):
        raise TransportAdapterError("full_source_files_required")
    result = {}
    maps = [source_files] + ([test_paths] if isinstance(test_paths, dict) else [])
    for mapping in maps:
        for key, content in mapping.items():
            _safe_path(key)
            if key.startswith("/") or key.split("/")[0] not in {"app", "tmp"} or "/" not in key:
                raise TransportAdapterError("public_file_key_requires_app_or_tmp_root")
            if not isinstance(content, str):
                raise TransportAdapterError("full_file_text_required")
            _sha(content)
            if key in result and result[key] != content:
                raise TransportAdapterError("conflicting_public_file_content")
            result[key] = content
    return result


def _resolve(value, files):
    _safe_path(value)
    matches = {name for name in files if value in {name, "/" + name}
               or (name.startswith("app/") and value == name[4:])}
    if not matches:
        raise TransportAdapterError("path_not_in_public_files")
    if len(matches) != 1:
        raise TransportAdapterError("ambiguous_public_path_alias")
    return next(iter(matches))


def _apply_for_anchor_checks(files, edits, stage, checks):
    """Pure string simulation to bind q/common anchors to their actual stage."""
    output, planned = dict(files), {}
    for index, edit in enumerate(edits):
        path, old = edit["path"], edit["old"]
        content = files[path]
        start, count = content.find(old), 0
        cursor = start
        while cursor >= 0:
            count += 1
            cursor = content.find(old, cursor + 1)
        checks.append({"stage": stage, "edit_index": index, "path": path, "file_sha256": _sha(content),
                       "old_sha256": _sha(old), "old_occurrences": count,
                       "character_offset": start if start >= 0 else None})
        if count != 1:
            raise TransportAdapterError("old_anchor_must_occur_exactly_once")
        planned.setdefault(path, []).append((start, start + len(old), edit["new"]))
    for path, spans in planned.items():
        spans.sort()
        if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
            raise TransportAdapterError("overlapping_exact_edits")
        content = files[path]
        for start, end, new in reversed(spans):
            content = content[:start] + new + content[end:]
        output[path] = content
    return output


def canonicalize_paths(proposal, source_files, test_paths=()):
    """Return a copy as ``proposal`` plus a receipt; never modify caller data.

    ``source_files`` maps public canonical app/... or tmp/... keys to full text.
    ``test_paths`` is an iterable of those paths, or a full-text test mapping to
    merge (conflicting contents are rejected). All alias candidates count before
    anchor checking: an anchor cannot break a path ambiguity. Existing edits are
    checked even when their path was already canonical. Q is checked against P;
    common against both P/Q; p/q against the respective common result. Candidate
    edits, when present, are checked independently against the original files.

    New helper paths and all non-path strings remain exactly as supplied. Helper
    locations are explicitly deferred to the normal staging/schema checks. Empty
    alternatives, no-op replacements and changed original probe statements are
    NOT repaired or certified; the downstream validator must still reject them.
    """
    if not isinstance(proposal, dict):
        raise TransportAdapterError("proposal_object_required")
    receipt = {"policy": POLICY, "input_proposal_sha256": _json_sha(proposal), "path_changes": [],
               "path_bindings": [], "anchor_checks": [], "new_helpers_not_relocated": [],
               "semantic_validation": "not_performed", "execution": "not_performed"}
    try:
        files = _public_files(source_files, test_paths)
        if isinstance(test_paths, str):
            raise TransportAdapterError("test_paths_must_be_collection")
        tests = sorted({_resolve(name, files) for name in test_paths})
        receipt.update(public_file_sha256={name: _sha(content) for name, content in sorted(files.items())},
                       test_paths=tests)
        canonical = copy.deepcopy(proposal)

        def path(value, pointer):
            name = _resolve(value, files)
            binding = {"pointer": pointer, "original": value, "canonical": name, "source_sha256": _sha(files[name])}
            receipt["path_bindings"].append(binding)
            if value != name:
                receipt["path_changes"].append(dict(binding))
            return name

        def edits(value, pointer):
            if not isinstance(value, list):
                raise TransportAdapterError("edits_must_be_list")
            for index, edit in enumerate(value):
                if (not isinstance(edit, dict) or set(edit) != {"path", "old", "new"}
                        or not isinstance(edit["old"], str) or not edit["old"] or not isinstance(edit["new"], str)):
                    raise TransportAdapterError("exact_path_old_new_edit_required")
                edit["path"] = path(edit["path"], f"{pointer}/{index}/path")
            return value

        if "target" in canonical:
            target = canonical["target"]
            if not isinstance(target, dict):
                raise TransportAdapterError("target_must_be_object")
            if "source_path" in target:
                target["source_path"] = path(target["source_path"], "/target/source_path")
        q = files
        if "alternative" in canonical:
            section = canonical["alternative"]
            if not isinstance(section, dict):
                raise TransportAdapterError("alternative_must_be_object")
            if "edits" in section:
                rows = edits(section["edits"], "/alternative/edits")
                q = _apply_for_anchor_checks(files, rows, "alternative_from_p", receipt["anchor_checks"])
        if "instrumentation" in canonical:
            probe = canonical["instrumentation"]
            if not isinstance(probe, dict):
                raise TransportAdapterError("instrumentation_must_be_object")
            common = edits(probe["common_edits"], "/instrumentation/common_edits") if "common_edits" in probe else []
            for branch, initial in (("p", files), ("q", q)):
                current = _apply_for_anchor_checks(initial, common, "common_from_" + branch, receipt["anchor_checks"])
                key = branch + "_edits"
                if key in probe:
                    rows = edits(probe[key], "/instrumentation/" + key)
                    _apply_for_anchor_checks(current, rows, key + "_after_common", receipt["anchor_checks"])
            for helper in probe.get("helper_files", []):
                if not isinstance(helper, dict) or "path" not in helper:
                    raise TransportAdapterError("invalid_helper_metadata")
                _safe_path(helper["path"])
                receipt["new_helpers_not_relocated"].append({"path": helper["path"], "location_validation": "deferred"})
        if "candidates" in canonical:
            if not isinstance(canonical["candidates"], list):
                raise TransportAdapterError("candidates_must_be_list")
            for index, candidate in enumerate(canonical["candidates"]):
                # Malformed/no-proposal slots remain present for the normal validator.
                if isinstance(candidate, dict) and "edits" in candidate:
                    rows = edits(candidate["edits"], f"/candidates/{index}/edits")
                    _apply_for_anchor_checks(files, rows, f"candidate_{index}_from_checkpoint", receipt["anchor_checks"])
        receipt.update(status="paths_canonicalized" if receipt["path_changes"] else "paths_unchanged",
                       canonical_proposal_sha256=_json_sha(canonical))
        return {"proposal": canonical, "receipt": receipt}
    except TransportAdapterError as error:
        raise TransportAdapterError(error.code, receipt) from error
    except (TypeError, KeyError, RecursionError) as error:
        raise TransportAdapterError("invalid_adapter_input_shape", receipt) from error
