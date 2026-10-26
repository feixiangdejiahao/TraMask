"""Prepare auditable syntax-only repairs; never approve or execute a hypothesis."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re

from .corpus import RUN, read, receipt, write
from .evidence import selected_tree_files
from .hypotheses import validate_hypothesis, materialize_variants


def decode_code_layer(value):
    # One pass preserves an escaped backslash followed by n as literal code.
    mapping = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'"}
    return re.sub(r'''\\([ntr\\"'])''', lambda m: mapping[m[1]], value)


def prepare(case_id, *, source_name="target_hypothesis", destination_name="target_hypothesis_technical01"):
    case = RUN / "runs" / case_id
    original = case / source_name
    out = case / destination_name
    if out.exists():
        raise FileExistsError(out)
    manifest = read(original / "manifest.json")
    repairs = []
    value = manifest.get("parsed")
    if not isinstance(value, dict):
        raw = (original / "completion.txt").read_text()
        if manifest.get("finish_reason") != "stop":
            raise ValueError("incomplete_model_response_requires_manual_recovery")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as error:
            # The single missing final object delimiter is unambiguous only if
            # the decoder reaches the very end and the extra brace fully parses.
            if error.pos != len(raw):
                raise
            value = json.loads(raw + "}")
            repairs.append({"kind": "append_one_final_object_brace", "original_error": str(error)})
    value = copy.deepcopy(value)
    files = selected_tree_files(case)
    input_packet = read(original / "input.json")

    def path_fix(path):
        candidates = [path, path.lstrip("/"), "app/" + path]
        hits = list(dict.fromkeys(p for p in candidates if p in files))
        return hits[0] if len(hits) == 1 else path

    if value.get("status") == "proposed":
        target = value.get("target", {})
        if "source_path" in target:
            fixed = path_fix(target["source_path"])
            if fixed != target["source_path"]:
                repairs.append({"kind": "canonical_source_path", "old": target["source_path"], "new": fixed})
                target["source_path"] = fixed
        edit_groups = [("alternative", value.get("alternative", {}).get("edits", []))]
        probe = value.get("instrumentation", {})
        edit_groups += [(key, probe.get(key, [])) for key in ("common_edits", "p_edits", "q_edits")]
        for group, edits in edit_groups:
            for index, edit in enumerate(edits):
                fixed = path_fix(edit.get("path", ""))
                if fixed != edit.get("path"):
                    repairs.append({"kind": "canonical_edit_path", "group": group, "index": index,
                                    "old": edit.get("path"), "new": fixed})
                    edit["path"] = fixed
                old, new = edit.get("old"), edit.get("new")
                if isinstance(old, str) and isinstance(new, str) and "\\n" in old and "\n" not in old:
                    # This remains a proposed technical transformation: a human
                    # must review semantics and exact anchors before execution.
                    edit["old"], edit["new"] = decode_code_layer(old), decode_code_layer(new)
                    repairs.append({"kind": "decode_one_extra_code_escape_layer", "group": group, "index": index,
                                    "old_anchor_occurrences_in_delivered_file": files.get(fixed, "").count(edit["old"])})
        for index, helper in enumerate(probe.get("helper_files", [])):
            content = helper.get("content", "")
            if "\\n" in content and "\n" not in content:
                helper["content"] = decode_code_layer(content)
                repairs.append({"kind": "decode_helper_escape_layer", "index": index})
    out.mkdir(parents=True)
    write(out / "proposal.json", value)
    record = {"status": "pending_manual_technical_review", "original_manifest": receipt(original / "manifest.json"),
              "original_completion": receipt(original / "completion.txt"), "repairs": repairs,
              "no_execution_or_approval": True, "no_new_alternative_search": True,
              "source_receipts": input_packet.get("source_records")}
    try:
        normalized = validate_hypothesis(value, source_paths=input_packet["final_sources"],
            test_paths=input_packet["selected_test"]["files"], original_command=input_packet["selected_test"]["command"])
        write(out / "hypothesis.json", normalized)
        if normalized["status"] == "proposed":
            baseline = out / "public_tree"
            for name, content in files.items():
                path = baseline / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            staged = materialize_variants(baseline, out / "variants", normalized)
            write(out / "staging.json", staged)
        record["structural_status"] = "staged_pending_manual_review"
    except Exception as error:
        record.update(structural_status="requires_manual_repair", error_type=type(error).__name__, error=str(error))
    write(out / "construction.json", record)
    return {"id": case_id, "directory": str(out), "status": record["structural_status"], "error": record.get("error")}
