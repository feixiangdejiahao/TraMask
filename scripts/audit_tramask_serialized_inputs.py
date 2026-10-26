"""Audit recorded model inputs, without dispatch, subject execution, or networking.

The request.json bytes are the audit subject. A passing source check means exact
agreement with named archived raw material, not an independent semantic judgment
about that material or a proof of the historical process that produced it.
Existing evidence and audit destinations are never overwritten.
"""
from __future__ import annotations

import argparse
import collections
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import types

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = ROOT / "results/behavioral_masking/20261023_tramask_evidence_n60_r01"
sys.path.insert(0, str(ROOT / "src"))
from tramask_pilot.corpus import calls as raw_calls


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode() if isinstance(value, str) else encoded(value)).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def receipt(path):
    path = Path(path).resolve()
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": sha(data)}


def walk(value, path=""):
    yield path, value
    if isinstance(value, dict):
        for key, item in value.items():
            yield from walk(item, path + "/" + str(key).replace("~", "~0").replace("/", "~1"))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from walk(item, path + "/" + str(i))


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        if isinstance(value, str):
            stream.write(value)
        else:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")


class Audit:
    def __init__(self, run):
        self.run = run.resolve()
        self.receipts = {}
        self.cases = {}
        self.packets = {}
        self.findings = []
        self.checks = collections.Counter()
        self.code = {}

    def check(self, rows, name, passed, **details):
        row = {"check": name, "passed": bool(passed), **details}
        rows.append(row)
        self.checks[(name, bool(passed))] += 1
        return bool(passed)

    def verify_receipt(self, bound):
        if not isinstance(bound, dict) or "path" not in bound or "sha256" not in bound:
            return {"passed": False, "reason": "not_a_local_file_receipt", "receipt": bound}
        path = Path(bound["path"])
        if not path.is_absolute():
            path = ROOT / path
        key = (str(path), bound["sha256"], bound.get("bytes"))
        if key not in self.receipts:
            if any(p in {".aws", ".codex", ".agents"} or p == ".env" or p.startswith(".env.") for p in path.parts):
                result = {"passed": False, "reason": "credential_or_private_path_not_read", "receipt": bound}
            elif not path.is_file():
                result = {"passed": False, "reason": "missing_file", "receipt": bound}
            else:
                actual = receipt(path)
                result = {"passed": actual["sha256"] == bound["sha256"] and ("bytes" not in bound or actual["bytes"] == bound["bytes"]),
                          "expected": bound, "actual": actual}
            self.receipts[key] = result
        return self.receipts[key]

    def composite_test(self, test, path, text, bound, history):
        """Verify terminal production prefix + exact historical test suffix."""
        region = next((r for r in test.get("protected_test_regions", []) if r["path"].lstrip("/") == path), None)
        if not region:
            return {"verified": False, "reason": "no_declared_composite_test_region"}
        historical = [(pointer, value) for pointer, value in walk(history)
                      if isinstance(value, str) and sha(value) == region.get("historical_original_module_sha256")]
        terminal = []
        for authority in bound.get("terminal_export_receipts", []):
            if not self.verify_receipt(authority)["passed"]:
                continue
            for row in read(authority["path"]).get("files", []):
                if row.get("path", "").lstrip("/") == path and isinstance(row.get("content"), str) and sha(row["content"]) == bound.get("terminal_sha256"):
                    terminal.append((authority, row["content"]))
        start, end = region["selected_region_utf8_offsets"]
        terminal_start, terminal_end = region["terminal_region_utf8_offsets"]
        raw = text.encode()
        marker = region["marker"].encode()
        historical_ok = any(value.encode().count(marker) == 1 and value.encode()[value.encode().index(marker):] == raw[start:end] for _, value in historical)
        terminal_ok = any(value.encode()[:terminal_start] == raw[:start] and sha(value.encode()[terminal_start:terminal_end]) == region["terminal_test_region_sha256"] for _, value in terminal)
        selected_ok = start == region["terminal_production_prefix_bytes"] and end == len(raw) and sha(raw[:start]) == region["terminal_production_prefix_sha256"] and sha(raw[start:end]) == region["original_test_region_sha256"]
        return {"verified": historical_ok and terminal_ok and selected_ok,
                "historical_test_suffix_exact": historical_ok, "terminal_production_prefix_exact": terminal_ok,
                "declared_region_hashes_and_full_coverage": selected_ok, "region": region,
                "historical_original_matching_pointers": [p for p, _ in historical][:8],
                "terminal_authorities": [r for r, _ in terminal],
                "scope": "Mechanical byte composition only. Legality of historical test materialization is a separate scientific qualification."}

    def case(self, case_id):
        if case_id in self.cases:
            return self.cases[case_id]
        directory = self.run / "runs" / case_id
        inputs = self.run / "inputs" / case_id
        raw = raw_calls(read(inputs / "trajectory.json"))
        actions = []
        for row in raw:
            output = (row.get("expected") or {}).get("output", "")
            if isinstance(output, str) and "\0" in output:
                output = "[Lossless JSON string encoding of raw output containing NUL]\n" + json.dumps(output, ensure_ascii=False)
            actions.append({"id": row["id"], "command": row["command"], "output": output,
                            "returncode": (row.get("expected") or {}).get("returncode")})
        result = {"case_id": case_id, "directory": directory, "inputs": inputs,
                  "issue": (inputs / "instruction.md").read_text(), "patch": (inputs / "model.patch").read_text(),
                  "actions": actions, "raw_actions": {r["id"]: r for r in raw}, "files": collections.defaultdict(list),
                  "tests": collections.defaultdict(list), "checks": [], "authority_documents": {},
                  "raw_receipts": [receipt(inputs / name) for name in ("instruction.md", "model.patch", "trajectory.json")]}
        self.cases[case_id] = result
        provenance = read(inputs / "provenance.json")
        for bound in provenance.get("input_receipts", []):
            self.check(result["checks"], "archived_input_receipt", self.verify_receipt(bound)["passed"], receipt=bound)
        for item in provenance.get("files", []):
            bound = item.get("receipt", {})
            self.check(result["checks"], "archived_input_receipt", self.verify_receipt(bound)["passed"], receipt=bound)
            original = item.get("source_receipt", {})
            if "path" in original:
                self.check(result["checks"], "original_raw_copy_equality", self.verify_receipt(original)["passed"] and original.get("sha256") == bound.get("sha256"),
                           receipt=original, classification="raw_archive_not_human_summary_even_if_parent_named_failure_analysis")
            elif "url" in original:
                self.check(result["checks"], "download_receipt_hash_binding", original.get("sha256") == bound.get("sha256") and original.get("bytes") == bound.get("bytes"),
                           receipt=original, limitation="Offline audit does not refetch or authenticate remote acquisition.")
        if provenance.get("source"):
            for name in ("instruction.md", "model.patch", "trajectory.json"):
                original = Path(provenance["source"]) / name
                self.check(result["checks"], "original_raw_copy_equality", original.is_file() and sha(original.read_bytes()) == sha((inputs / name).read_bytes()),
                           source_path=str(original), classification="raw_archive_not_human_summary_even_if_parent_named_failure_analysis")

        def add_export(path):
            if not path.exists():
                return
            doc = read(path)
            for row in doc.get("files", []):
                if row.get("status") != "present" or not isinstance(row.get("content"), str):
                    continue
                digest = sha(row["content"])
                self.check(result["checks"], "exported_file_content_hash", digest == row.get("sha256"), source_path=row["path"], authority=receipt(path))
                result["files"][(row["path"].lstrip("/"), digest)].append({"kind": "terminal_export", "authority": receipt(path), "checkpoint": doc.get("checkpoint")})

        add_export(directory / "terminal_sources/result.json")
        for qpath in sorted(directory.glob("qualified_validation_inventory*.json")):
            qualification = read(qpath)
            for bound in qualification.get("source_exports", []):
                self.check(result["checks"], "supplemental_source_export_receipt", self.verify_receipt(bound)["passed"], receipt=bound)
                add_export(Path(bound["path"]))
            for bound in qualification.get("input_receipts", []):
                self.check(result["checks"], "inventory_raw_input_receipt", self.verify_receipt(bound)["passed"], receipt=bound)
            for test in qualification.get("validation_tests", []):
                result["tests"][test["id"]].append({"test": test, "authority": receipt(qpath)})
                for path, text in test.get("files", {}).items():
                    bound = test.get("file_receipts", {}).get(path, {})
                    if bound:
                        self.check(result["checks"], "inventory_test_content_hash", sha(text) == bound.get("sha256"), test_id=test["id"], path=path)
                        authority = bound.get("authority_receipt")
                        if authority:
                            verified = self.verify_receipt(authority)["passed"]
                            self.check(result["checks"], "historical_test_authority_receipt", verified, receipt=authority)
                            if verified and authority["path"] not in result["authority_documents"]:
                                result["authority_documents"][authority["path"]] = read(authority["path"])
                            document = result["authority_documents"].get(authority["path"], {})
                            matches = [pointer for pointer, value in walk(document) if isinstance(value, str) and sha(value) == sha(text)]
                            composition = self.composite_test(test, path, text, bound, document) if not matches else None
                            self.check(result["checks"], "historical_authority_contains_exact_test_bytes", bool(matches), path=path,
                                       test_id=test["id"], authority=authority, matching_pointers=matches[:8],
                                       resolution=("verified_terminal_production_plus_historical_test_composition" if composition and composition["verified"] else None),
                                       composition=composition)
                            if composition:
                                self.check(result["checks"], "composed_test_bytes_bind_terminal_and_history", composition["verified"], path=path, test_id=test["id"], details=composition)
                        action_id = bound.get("version_action_id")
                        if action_id:
                            self.check(result["checks"], "historical_test_version_action_exists", action_id in result["raw_actions"], path=path, action_id=action_id)
                    result["files"][(path.lstrip("/"), sha(text))].append({"kind": "qualified_historical_or_terminal_test", "authority": receipt(qpath),
                        "test_id": test["id"], "file_receipt": bound})
        capsule_path = directory / "historical_test_capsule.json"
        if capsule_path.exists():
            capsule = read(capsule_path)
            for key in ("raw_trajectory_receipt", "terminal_export_receipt", "terminal_manifest_receipt", "trajectory", "selection", "qualification_receipt", "terminal_absence_receipt"):
                if key in capsule:
                    self.check(result["checks"], "capsule_authority_receipt", self.verify_receipt(capsule[key])["passed"], receipt=capsule[key])
            for path, row in capsule.get("files", {}).items():
                self.check(result["checks"], "capsule_file_hash", sha(row["content"]) == row["sha256"], path=path)
                direct = [a["id"] for a in actions if row["content"] in a["command"]]
                snapshots = [a["snapshot"] for a in capsule.get("authority_checks", []) if a.get("subject_path") == path and "snapshot" in a]
                snapshot_equal = any(self.verify_receipt(bound)["passed"] and sha(Path(bound["path"]).read_bytes()) == row["sha256"] for bound in snapshots)
                self.check(result["checks"], "capsule_bytes_in_raw_command_or_independent_archived_snapshot", bool(direct) or snapshot_equal,
                           path=path, raw_command_action_ids=direct, independent_snapshots=snapshots,
                           limitation="A snapshot match is archival evidence, not a fresh replay of intervening transformations.")
                if row.get("authority_receipt"):
                    self.check(result["checks"], "capsule_history_receipt", self.verify_receipt(row["authority_receipt"])["passed"], receipt=row["authority_receipt"])
                result["files"][(path.lstrip("/"), sha(row["content"]))].append({"kind": "historical_test_capsule", "authority": receipt(capsule_path),
                    "version_action_id": row.get("version_action_id"), "history_authority": row.get("authority_receipt")})
        return result

    def packet(self, case_id, path):
        packet = read(path)
        key = (case_id, sha(packet))
        if key in self.packets:
            return packet, self.packets[key]
        case = self.case(case_id)
        checks = []
        bindings = []
        self.check(checks, "public_packet_issue_equals_raw", packet.get("issue") == case["issue"])
        self.check(checks, "public_packet_patch_equals_raw", packet.get("final_patch") == case["patch"])
        self.check(checks, "public_packet_actions_equal_raw_projection", packet.get("actions") == case["actions"], raw_action_count=len(case["actions"]))
        for source, text in packet.get("final_sources", {}).items():
            origins = case["files"].get((source, sha(text)), [])
            self.check(checks, "public_packet_source_has_archived_authority", bool(origins), path=source, sha256=sha(text))
            bindings.append({"type": "source", "path": source, "sha256": sha(text), "origins": origins})
        tests = list(packet.get("validation_tests", []))
        if "selected_test" in packet and packet["selected_test"] not in tests:
            tests.append(packet["selected_test"])
        for test in tests:
            command_matches = [{"id": action["id"], "command_sha256": sha(action["command"]),
                                "start_character": action["command"].find(test["command"]),
                                "command_byte_sha256": sha(test["command"])}
                               for action in case["actions"] if test["command"] in action["command"]]
            self.check(checks, "public_test_command_exact_raw_tool_command_substring", bool(command_matches), test_id=test["id"], matches=command_matches)
            if test.get("id") == "original_validation":
                selection = read(case["directory"] / "selection.json")
                same = test.get("command") == selection.get("command") and test.get("working_directory") == selection.get("working_directory")
                self.check(checks, "public_test_metadata_equals_selection", same, test_id=test["id"], selection=receipt(case["directory"] / "selection.json"))
            else:
                authorities = case["tests"].get(test.get("id"), [])
                same = any(all(test.get(k) == row["test"].get(k) for k in ("command", "working_directory")) for row in authorities)
                self.check(checks, "public_test_metadata_equals_qualified_inventory", same, test_id=test.get("id"), inventory_authorities=[r["authority"] for r in authorities])
            for source, text in test.get("files", {}).items():
                origins = case["files"].get((source, sha(text)), [])
                inline = test.get("inline_test", {})
                inline_bound = False
                if inline.get("path") == source:
                    mapping = inline.get("command_mapping", {})
                    start, end = mapping.get("script_start_byte"), mapping.get("script_end_byte")
                    inline_bound = type(start) is int and type(end) is int and test["command"].encode()[start:end] == text.encode() and mapping.get("original_command") == test["command"]
                self.check(checks, "public_packet_test_has_archived_authority", bool(origins) or inline_bound, test_id=test.get("id"), path=source, sha256=sha(text), inline_command_bound=inline_bound)
                bindings.append({"type": "test", "test_id": test.get("id"), "path": source, "sha256": sha(text), "origins": origins, "inline_command_bound": inline_bound})
        result = {"case_id": case_id, "content_sha256": key[1], "example_public_input": receipt(path), "checks": checks, "file_bindings": bindings,
                  "raw_case_authority": case_id, "all_checks_passed": all(r["passed"] for r in checks)}
        self.packets[key] = result
        return packet, result

    def material(self, call_dir, packet, decoded, prepared):
        rows = []
        material = decoded["material"]
        fragments = []
        self.check(rows, "serialized_issue_equals_public_packet", material.get("issue") == packet["issue"])
        fragments.append({"pointer": "/material/issue", "sha256": sha(material.get("issue")), "bytes": len(material.get("issue", "").encode()), "authority": "raw instruction.md"})
        patch = material.get("final_patch")
        raw_patch = packet["final_patch"].encode()
        if isinstance(patch, str):
            self.check(rows, "serialized_patch_exact", patch == packet["final_patch"])
        else:
            self.check(rows, "patch_original_hash", patch.get("original_sha256") == sha(raw_patch) and patch.get("original_utf8_bytes") == len(raw_patch))
            for i, piece in enumerate(patch.get("pieces", [])):
                for part, prefix in (("file_header", "header"), ("hunk", "hunk")):
                    start, end = piece[prefix + "_start_byte"], piece[prefix + "_end_byte"]
                    self.check(rows, "serialized_patch_slice_exact", raw_patch[start:end] == piece[part].encode(), piece=i, part=part, start_byte=start, end_byte=end)
                    fragments.append({"pointer": f"/material/final_patch/pieces/{i}/{part}", "sha256": sha(piece[part]), "bytes": len(piece[part].encode()), "raw_start_byte": start, "raw_end_byte": end, "authority": "raw model.patch"})
        for source, pieces in material.get("local_sources", {}).items():
            original = packet.get("final_sources", {}).get(source)
            self.check(rows, "serialized_source_path_in_public_packet", original is not None, path=source)
            if original is None:
                continue
            raw = original.encode()
            for i, piece in enumerate(pieces):
                start, end = piece["start_byte"], piece["end_byte"]
                self.check(rows, "serialized_source_slice_exact", raw[start:end] == piece["text"].encode(), path=source, start_byte=start, end_byte=end)
                fragments.append({"pointer": f"/material/local_sources/{source}/{i}", "path": source, "sha256": sha(piece["text"]), "bytes": len(piece["text"].encode()), "original_sha256": sha(raw), "raw_start_byte": start, "raw_end_byte": end, "authority": "public_packet.final_sources; see packet file_bindings"})
        originals = {t["id"]: t for t in packet.get("validation_tests", [])}
        if "selected_test" in packet:
            originals[packet["selected_test"]["id"]] = packet["selected_test"]
        tests = list(material.get("validation_tests", [])) + ([material["selected_test"]] if "selected_test" in material else [])
        for test in tests:
            original = originals.get(test["id"])
            self.check(rows, "serialized_test_id_from_public_inventory", original is not None, test_id=test["id"])
            if original is None:
                continue
            self.check(rows, "serialized_test_metadata_exact", test["command"] == original["command"] and test["working_directory"] == original.get("working_directory", "/app"), test_id=test["id"])
            for source, text in test.get("files", {}).items():
                self.check(rows, "serialized_complete_test_file_exact", text == original.get("files", {}).get(source), test_id=test["id"], path=source)
                fragments.append({"pointer": f"/material/test:{test['id']}/files/{source}", "sha256": sha(text), "bytes": len(text.encode()) if isinstance(text, str) else None, "authority": "public_packet.validation_tests; see packet file_bindings"})
            for source, view in test.get("file_excerpts", {}).items():
                text = original["files"][source]
                self.check(rows, "test_excerpt_original_hash", view["original_sha256"] == sha(text) and view["original_utf8_bytes"] == len(text.encode()), path=source)
                for i, piece in enumerate(view["slices"]):
                    start, end = piece["start_byte"], piece["end_byte"]
                    self.check(rows, "serialized_test_slice_exact", text.encode()[start:end] == piece["text"].encode(), test_id=test["id"], path=source, start_byte=start, end_byte=end)
                    fragments.append({"pointer": f"/material/test:{test['id']}/file_excerpts/{source}/slices/{i}", "sha256": sha(piece["text"]), "bytes": len(piece["text"].encode()), "original_sha256": sha(text), "raw_start_byte": start, "raw_end_byte": end, "authority": "public_packet.validation_tests; see packet file_bindings"})
        action_map = collections.defaultdict(list)
        for i, event in enumerate(packet.get("actions", [])):
            core = {key: event[key] for key in ("command", "output")}
            action_map[sha(core)].append((i, event))
        action_receipts = {r.get("included_ref"): r for r in prepared.get("input_receipt", {}).get("sections", []) if r.get("section") == "actions" and r.get("included_ref")}
        policy = next((r for r in prepared.get("input_receipt", {}).get("sections", []) if r.get("section") == "actions_policy"), None)
        if not action_receipts and "reference_material_completion" in str(call_dir):
            first = read(call_dir.parent / "target_generation/prepared_request.json")
            action_receipts = {r.get("included_ref"): r for r in first["input_receipt"].get("sections", []) if r.get("section") == "actions" and r.get("included_ref")}
            policy = next((r for r in first["input_receipt"].get("sections", []) if r.get("section") == "actions_policy"), None)
        for i, event in enumerate(material.get("actions", [])):
            digest = sha({k: event[k] for k in ("command", "output")})
            matches = action_map.get(digest, [])
            self.check(rows, "serialized_action_exact_raw_tool_projection", event.get("ref") == "event:" + digest and bool(matches), ref=event.get("ref"))
            bound = action_receipts.get(event.get("ref"), {})
            self.check(rows, "serialized_action_index_receipt", any(index == bound.get("source_index") for index, _ in matches) and bound.get("source_sha256") == digest, ref=event.get("ref"))
            case_id = call_dir.relative_to(self.run / "runs").parts[0]
            original_actions = self.case(case_id)["raw_actions"]
            mapping_ok = all(original_actions[action["id"]].get("observation_mapping_unambiguous") is True
                             and "action was not executed" not in str((original_actions[action["id"]].get("expected") or {}).get("exception_info", ""))
                             for _, action in matches)
            self.check(rows, "serialized_action_has_actual_mapped_observation", bool(matches) and mapping_ok, ref=event.get("ref"))
            if policy:
                self.check(rows, "serialized_action_before_declared_cutoff", bound.get("source_index", 10**9) < policy["submission_cutoff_exclusive"], ref=event.get("ref"))
            fragments.append({"pointer": f"/material/actions/{i}", "sha256": digest, "bytes": len(encoded(event)), "source_action_ids": [e["id"] for _, e in matches], "source_indices": [index for index, _ in matches], "authority": "raw trajectory command/output only"})
        stage = prepared.get("validation_context", {}).get("stage")
        if stage == 2:
            planning_path = call_dir.parent / "stage_01/planning.json"
            planning = read(planning_path)
            target = {key: planning["target"][key] for key in ("behavior", "source_path", "anchor", "logical_effect", "public_observation") if key in planning["target"]}
            self.check(rows, "serialized_stage2_target_from_same_cell_planning", material.get("target") == target, authority=receipt(planning_path))
            self.check(rows, "serialized_stage2_selected_test_from_same_cell_planning", material["selected_test"]["id"] == planning.get("selected_test_id"), authority=receipt(planning_path))
        allowed = {"issue", "final_patch", "selected_test", "validation_tests", "local_sources", "actions"} | ({"target"} if stage == 2 else set())
        self.check(rows, "serialized_material_field_allowlist", set(material) <= allowed, unexpected_fields=sorted(set(material) - allowed))
        return {"checks": rows, "fragments": fragments, "all_checks_passed": all(r["passed"] for r in rows),
                "material_fields": sorted(material), "field_sha256": {k: sha(v) for k, v in material.items()},
                "history_count": len(material.get("actions", [])), "history_field_present": "actions" in material,
                "declared_action_policy": policy,
                "omission_receipts": [r for r in prepared.get("input_receipt", {}).get("sections", []) if "omitted" in r]}

    def scan(self, decoded, material_bound):
        pattern = re.compile(r"failure[ _-]analysis|hidden[ _/.-]*(?:verifier|tests?)|reference[ _/.-]*solution|gold[ _/-]*masker|other methods?.{0,8}outputs?|evaluation_assets", re.I)
        found = []
        for pointer, text in walk(decoded.get("material", {}), "/material"):
            if not isinstance(text, str):
                continue
            matches = sorted({m.group(0) for m in pattern.finditer(text)})
            if matches:
                found.append({"pointer": pointer, "terms": matches, "text_sha256": sha(text), "text_bytes": len(text.encode()),
                              "interpretation": "literal_flag_requires_source_context_review", "material_exact_source_bound": material_bound})
        return {"scope": "Decoded user material only. System prohibitions, schema instructions and archive directory names are excluded.",
                "literal_hits": found, "absence_of_hits_is_not_proof_of_no_leakage": True}


def load_builder(path, module_name):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(data):
    return sha(data)


def dump(value):
    return encoded(value).decode()


def dict_nodes(value):
    return (node for _, node in walk(value) if isinstance(node, dict))


def inspect_code(root, new):
    root, new = Path(root).resolve(), Path(new).resolve()
    selected = {
        "target_builder": new / "frozen_code/src/tramask_rerun/prompts.py",
        "target_schema": new / "frozen_code/src/tramask_pilot/hypotheses.py",
        "track_b_builder": new / "code_versions/track_b_dispatch_v04/src/tramask_rerun/prompts_inventory_v02.py",
        "test_codec": new / "code_versions/track_b_dispatch_v04/src/tramask_rerun/prompt_codec.py",
        "provider_adapter": new / "frozen_code/src/tramask_pilot/provider.py",
        "completion_builder_original_cohort": new / "code_versions/material_completion_v01/src/tramask_rerun/reference_completion.py",
        "completion_builder_reserved_cohort": new / "code_versions/reserved_reference_v02/src/tramask_rerun/reference_completion_reserved_v02.py",
    }
    documents = [(new / "protocol.json", read(new / "protocol.json"))]
    documents += [(p, read(p)) for p in sorted((new / "amendments").glob("*.json"))]
    result = {}
    for name, path in selected.items():
        if not path.is_file():
            result[name] = {"path": str(path), "status": "missing"}
            continue
        actual = receipt(path)
        declarations = []
        for record_path, record in documents:
            for node in dict_nodes(record):
                if node.get("sha256") == actual["sha256"] and node.get("bytes") == actual["bytes"] and "path" in node:
                    declarations.append({"record": receipt(record_path),
                                         "created_at": record.get("created_at"),
                                         "declared_code": node,
                                         "archived_bytes_match_declaration": True})
        result[name] = {"artifact": actual, "declarations": declarations,
                        "status": "archived_bytes_match_freeze_record" if declarations else "unbound_archive"}
    return {"files": result,
            "scope": "Hashes authenticate archived bytes against local freeze records; these records and their timestamps are not independently signed process attestations.",
            "dispatch_version_limit": "No per-call loaded-module hash record. Multiple Track B dispatchers share byte-identical prompt and codec implementations; exact pure-function reconstruction does not identify the original dispatcher process version."}


class ArchivedRequestRebuilder:
    def __init__(self, new):
        self.new = Path(new).resolve()
        self.modules = {}
        self._old_modules = {}
        self._prefix = "_tramask_readonly_prompt_audit"
        sys.dont_write_bytecode = True
        # Avoid importing provider, connection helpers, or any dispatcher. Only
        # these four archived pure modules are evaluated, with ordinary stdlib
        # imports and the optional test-view parser dependencies.
        self._set_module("tramask_pilot", types.ModuleType("tramask_pilot"))
        self._set_module(self._prefix, types.ModuleType(self._prefix))
        self._module("tramask_pilot.hypotheses", self.new / "frozen_code/src/tramask_pilot/hypotheses.py")
        self.target = self._module(self._prefix + ".prompts", self.new / "frozen_code/src/tramask_rerun/prompts.py")
        self.codec = self._module(self._prefix + ".prompt_codec", self.new / "code_versions/track_b_dispatch_v04/src/tramask_rerun/prompt_codec.py")
        self.track_b = self._module(self._prefix + ".prompts_inventory_v02", self.new / "code_versions/track_b_dispatch_v04/src/tramask_rerun/prompts_inventory_v02.py")

    def _set_module(self, name, module):
        self._old_modules.setdefault(name, sys.modules.get(name))
        sys.modules[name] = module

    def _module(self, name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        self._set_module(name, module)
        spec.loader.exec_module(module)
        self.modules[name] = receipt(path)
        return module

    def restore_modules(self):
        for name, previous in self._old_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous

    def rebuild(self, call_dir, packet=None, prepared=None):
        call_dir = Path(call_dir).resolve()
        prepared = prepared if prepared is not None else read(call_dir / "prepared_request.json")
        if call_dir.name == "target_generation":
            packet = packet if packet is not None else read(call_dir / "public_input.json")
            return self.target.build_target_request(packet)
        if "track_b" in call_dir.relative_to(self.new).parts:
            packet = packet if packet is not None else read(call_dir / "public_input.json")
            stage = int(call_dir.name[-2:])
            repeat = int(call_dir.parent.name[-2:])
            method = call_dir.parent.parent.name
            planning = read(call_dir.parent / "stage_01/planning.json") if stage == 2 else None
            evidence = None
            if stage == 2 and method in {"M3", "M4"}:
                qualification = read(call_dir.parent / "target_execution/qualification.json")
                bound = qualification["public_feedback"]
                if receipt(bound["path"]) != bound:
                    raise ValueError("feedback_receipt_mismatch")
                feedback = read(bound["path"])
                evidence = {k: feedback[k] for k in ("before_effects", "original_observations") if k in feedback}
            return self.track_b.build_end_to_end_request(packet, method, repeat, stage,
                                                       planning=planning, evidence=evidence)
        if call_dir.name != "reference_material_completion_v01":
            raise ValueError("unknown_actual_call_family")
        # Equivalent to reference_completion.prepare, but directly uses the
        # preserved initial packet and never imports that provider-aware module.
        original_path = call_dir.parent / "target_generation/prepared_request.json"
        original = read(original_path)
        packet = packet if packet is not None else read(call_dir.parent / "target_generation/public_input.json")
        payload = json.loads(original["prompt"])
        sources = copy.deepcopy(payload["material"].get("local_sources", {}))
        selection = read(call_dir.parent / "selection.json")
        changes = []
        for subject_path in selection["source_paths"]:
            path = subject_path.lstrip("/")
            text = packet["final_sources"].get(path)
            if text is None:
                changes.append({"path": path, "status": "original_selected_source_missing"})
                continue
            raw = text.encode()
            proposal = copy.deepcopy(sources)
            proposal[path] = [{"start_line": 1, "end_line": len(text.splitlines()),
                               "start_byte": 0, "end_byte": len(raw), "text": text}]
            candidate = copy.deepcopy(payload)
            candidate["material"]["local_sources"] = proposal
            candidate["available_evidence_refs"] = sorted(set(candidate["available_evidence_refs"]) | {"source:" + path})
            if len(original["system"].encode()) + len(dump(candidate).encode()) > 262144:
                changes.append({"path": path, "status": "complete_file_exceeds_remaining_cap_original_view_retained",
                                "original_sha256": digest(raw), "bytes": len(raw)})
                continue
            sources, payload = proposal, candidate
            changes.append({"path": path, "status": "complete_original_source_added",
                            "original_sha256": digest(raw), "bytes": len(raw)})
        prompt = dump(payload)
        request = {"id": call_dir.parent.name + "/pilot1/reference_material_completion/repeat_01",
                   "system": original["system"], "prompt": prompt, "max_tokens": original["max_tokens"],
                   "dispatchable": True, "status": "prepared",
                   "input_receipt": {"original_request": receipt(original_path),
                                     "full_source_changes": changes, "input_utf8_cap": 262144,
                                     "total_input_utf8_bytes": len(prompt.encode()) + len(original["system"].encode()),
                                     "system_unchanged": True, "old_proposal_or_behavioral_outcomes_in_input": False,
                                     "role": "P1 reference data construction, not method search or independent replicate"}}
        if not any(x["status"] == "complete_original_source_added" for x in changes):
            request.update(dispatchable=False, status="no_additional_material", prompt="")
        return request

    def audit(self, call_dir, packet=None, prepared=None):
        call_dir = Path(call_dir).resolve()
        prepared = prepared if prepared is not None else read(call_dir / "prepared_request.json")
        rebuilt = self.rebuild(call_dir, packet, prepared)
        fields = sorted(set(prepared) | set(rebuilt))
        differences = [key for key in fields if rebuilt.get(key) != prepared.get(key)]
        input_differences = [key for key in ("id", "system", "prompt", "max_tokens") if rebuilt.get(key) != prepared.get(key)]
        return {"path": str(call_dir), "status": "match" if not input_differences else "mismatch",
                "input_differing_fields": input_differences, "all_prepared_differing_fields": differences,
                "prepared_object_exact_match": rebuilt == prepared,
                "reconstructed_prompt_sha256": digest(rebuilt["prompt"].encode()),
                "actual_prompt_sha256": digest(prepared["prompt"].encode())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--output-name", default="serialized_input_provenance_audit_v01")
    args = parser.parse_args()
    run = args.run.resolve()
    out = run / args.output_name
    top = run / (args.output_name + ".json")
    if out.exists() or top.exists():
        raise FileExistsError("Refusing to overwrite an audit destination")
    audit = Audit(run)
    rebuilder = ArchivedRequestRebuilder(run)
    code_bindings = inspect_code(ROOT, run)
    ledger = read(run / "provider_budget.json")
    before_ledger = receipt(run / "provider_budget.json")
    manifests = sorted(run.glob("runs/**/provider/manifest.json"))
    calls, nonphysical, matched_keys, pairing, stage2 = [], [], [], collections.defaultdict(list), []
    frozen = run / "frozen_code/src/tramask_rerun/prompts.py"
    inventory = run / "code_versions/track_b_dispatch_v04/src/tramask_rerun/prompts_inventory_v02.py"
    builders = {"target": load_builder(frozen, "tramask_rerun._serialized_audit_frozen"),
                "track_b": load_builder(inventory, "tramask_rerun._serialized_audit_inventory")}
    for manifest_path in manifests:
        manifest = read(manifest_path)
        if manifest.get("external_model_calls") != 1:
            nonphysical.append({"manifest": receipt(manifest_path), "status": manifest.get("status"), "external_model_calls": manifest.get("external_model_calls")})
            continue
        call_dir = manifest_path.parent.parent
        relative = str(call_dir.relative_to(run))
        case_id = call_dir.relative_to(run / "runs").parts[0]
        prepared_path = call_dir / "prepared_request.json"
        prepared = read(prepared_path)
        request_path = manifest_path.parent / "request.json"
        request_bytes = request_path.read_bytes()
        request = json.loads(request_bytes)
        checks = []
        expected_payload = {"model": manifest["model"], "temperature": 0, "max_tokens": prepared["max_tokens"],
            "messages": [{"role": "system", "content": prepared["system"]}, {"role": "user", "content": prepared["prompt"]}],
            "response_format": {"type": "json_object"}, "stream": False, "thinking": {"type": "disabled"}}
        fingerprint = sha({"id": prepared["id"], "payload": request})
        key = sha(str(manifest_path.parent.resolve()))
        audit.check(checks, "provider_payload_equals_prepared_request", request == expected_payload)
        audit.check(checks, "recorded_request_is_canonical_wire_body_plus_newline", request_bytes == encoded(request) + b"\n")
        audit.check(checks, "manifest_request_sha256_recomputed", fingerprint == manifest.get("request_sha256"))
        audit.check(checks, "manifest_request_id_binding", prepared["id"] == manifest.get("request_id"))
        audit.check(checks, "budget_key_recomputed_from_physical_call_directory", key == manifest.get("budget_key"))
        entry = ledger["calls"].get(key, {})
        matched_keys.append(key)
        audit.check(checks, "ledger_entry_equals_manifest_budget", entry == manifest.get("budget"))
        audit.check(checks, "ledger_request_hash_matches_actual_payload", entry.get("request_sha256") == fingerprint)
        audit.check(checks, "ledger_call_settled", entry.get("status") == "settled")
        audit.check(checks, "ledger_reservation_matches_serialized_body", entry.get("input_token_upper_bound") == len(encoded(request)) + 1024 and entry.get("output_token_cap") == request["max_tokens"] and entry.get("reserved_tokens") == len(encoded(request)) + 1024 + request["max_tokens"])
        usage = manifest.get("usage") or {}
        audit.check(checks, "ledger_charge_matches_provider_usage", entry.get("charged_tokens") == max(usage.get("total_tokens", 0), usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)))
        result_path = call_dir / "result.json"
        if result_path.exists():
            result = read(result_path)
            for field in ("request", "public_input", "provider_manifest"):
                if field in result:
                    audit.check(checks, "result_artifact_receipt", audit.verify_receipt(result[field])["passed"], field=field, receipt=result[field])
        completion = "reference_material_completion" in relative
        packet_path = (call_dir.parent / "target_generation/public_input.json") if completion else call_dir / "public_input.json"
        packet, packet_audit = audit.packet(case_id, packet_path)
        raw_payload = json.loads(request["messages"][1]["content"])
        decoded = rebuilder.codec.decode_payload(raw_payload)
        audit.check(checks, "shared_test_codec_decoded", True, encoding=raw_payload.get("file_content_encoding", {}).get("version"), shared_files=len(raw_payload.get("shared_file_contents", {})), shared_chunks=len(raw_payload.get("shared_text_chunks", {})))
        material = audit.material(call_dir, packet, decoded, prepared)
        if completion:
            first = read(call_dir.parent / "target_generation/prepared_request.json")
            expected = json.loads(first["prompt"])
            selection = read(call_dir.parent / "selection.json")
            for source in selection["source_paths"]:
                source = source.lstrip("/")
                text = packet["final_sources"].get(source)
                if text is None:
                    continue
                candidate = copy.deepcopy(expected)
                candidate["material"]["local_sources"][source] = [{"start_line": 1, "end_line": len(text.splitlines()), "start_byte": 0, "end_byte": len(text.encode()), "text": text}]
                candidate["available_evidence_refs"] = sorted(set(candidate["available_evidence_refs"]) | {"source:" + source})
                if len(first["system"].encode()) + len(encoded(candidate)) <= 262144:
                    expected = candidate
            reconstruction = expected == raw_payload and first["system"] == prepared["system"]
            code_path = (run / "code_versions/reserved_reference_v02/src/tramask_rerun/reference_completion_reserved_v02.py"
                         if case_id.startswith("H") else run / "code_versions/material_completion_v01/src/tramask_rerun/reference_completion.py")
            if not code_path.exists():
                code_path = ROOT / "src/tramask_rerun/reference_completion.py"
            code = {"constructor": receipt(code_path), "version": "reference_material_completion", "method": "independent reimplementation of bounded complete-source replacement; no provider module imported"}
        else:
            context = prepared.get("validation_context", {})
            if context.get("track") == "B":
                stage = context["stage"]
                repeat = int(call_dir.parent.name.split("_")[-1])
                method = call_dir.parent.parent.name
                planning = read(call_dir.parent / "stage_01/planning.json") if stage == 2 else None
                rebuilt = builders["track_b"].build_end_to_end_request(packet, method, repeat, stage, planning=planning)
                code_path = inventory
                without_history = {k: v for k, v in decoded["material"].items() if k != "actions"}
                pair = {"call": relative, "case_id": case_id, "method": method, "repeat": repeat, "stage": stage,
                        "nonhistory_material_sha256": sha(without_history), "common_field_sha256": {k: sha(v) for k, v in without_history.items()},
                        "history_present": "actions" in decoded["material"], "history_count": len(decoded["material"].get("actions", [])),
                        "history_sha256": sha(decoded["material"].get("actions", [])), "input_utf8_cap": prepared["input_receipt"].get("input_utf8_cap"),
                        "prompt_tokens": usage.get("prompt_tokens"), "system_plus_prompt_bytes": len(prepared["system"].encode()) + len(prepared["prompt"].encode())}
                audit.check(checks, "track_b_history_visibility_matrix", pair["history_present"] == (method in {"M2", "M4"}), method=method, stage=stage)
                if stage == 1:
                    pairing[(case_id, repeat)].append(pair)
                else:
                    pair.update(selected_test_id=decoded["material"]["selected_test"]["id"], target=decoded["material"].get("target"), planning=receipt(call_dir.parent / "stage_01/planning.json"))
                    stage2.append(pair)
            else:
                rebuilt = builders["target"].build_target_request(packet)
                code_path = frozen
            reconstruction = all(rebuilt.get(k) == prepared.get(k) for k in ("id", "system", "prompt", "max_tokens"))
            code = {"constructor": receipt(code_path), "version": prepared["input_receipt"].get("version"), "method": "pure function called on actual stored public_input"}
        audit.check(checks, "frozen_constructor_reproduces_actual_model_input", reconstruction)
        full_rebuild = rebuilder.audit(call_dir, packet, prepared)
        audit.check(checks, "entire_prepared_object_reproduced_from_archived_code", full_rebuild["prepared_object_exact_match"], differing_fields=full_rebuild["all_prepared_differing_fields"])
        code["exact_prepared_reconstruction"] = full_rebuild
        dependency_names = ["target_schema", "provider_adapter"]
        if completion:
            dependency_names += ["target_builder", "completion_builder_reserved_cohort" if case_id.startswith("H") else "completion_builder_original_cohort"]
        elif prepared.get("validation_context", {}).get("track") == "B":
            dependency_names += ["track_b_builder", "test_codec"]
        else:
            dependency_names += ["target_builder"]
        code["dependency_bindings"] = {}
        for name in dependency_names:
            binding = code_bindings["files"][name]
            earlier = [d for d in binding.get("declarations", []) if d.get("created_at") and d["created_at"] < manifest["created_at"]]
            code["dependency_bindings"][name] = {"artifact": binding.get("artifact"), "earliest_freeze_record": min(earlier, key=lambda d: d["created_at"]) if earlier else None}
            audit.check(checks, "archived_code_hash_declared_before_call", bool(earlier), component=name)
        code["loaded_dispatcher_version"] = "not_independently_attested; constructor compatibility is verified"
        ir = prepared.get("input_receipt", {})
        audit.check(checks, "actual_input_within_declared_byte_cap", len(prepared["system"].encode()) + len(prepared["prompt"].encode()) <= ir["input_utf8_cap"])
        if "prompt_sha256" in ir:
            audit.check(checks, "input_receipt_prompt_hash", ir["prompt_sha256"] == sha(prepared["prompt"]))
            audit.check(checks, "input_receipt_system_hash", ir["system_sha256"] == sha(prepared["system"]))
            audit.check(checks, "input_receipt_material_hash", ir["material_sha256"] == sha(decoded["material"]))
        row = {"call": relative, "case_id": case_id, "request_id": prepared["id"], "created_at": manifest.get("created_at"),
               "provider_manifest": receipt(manifest_path), "request_file": receipt(request_path), "prepared_request": receipt(prepared_path),
               "public_input": receipt(packet_path), "public_packet_content_sha256": packet_audit["content_sha256"], "code": code,
               "provider_wire_utf8_bytes": len(encoded(request)), "system_utf8_bytes": len(prepared["system"].encode()), "prompt_utf8_bytes": len(prepared["prompt"].encode()),
               "provider_reported_usage": usage, "budget_key": key, "budget": entry, "checks": checks,
               "serialized_material": material, "prohibited_source_scan": audit.scan(decoded, material["all_checks_passed"] and packet_audit["all_checks_passed"]),
               "upstream_case_authorities_resolved": all(r["passed"] or r.get("resolution") for r in audit.case(case_id)["checks"]),
               "all_mechanical_checks_passed": all(r["passed"] for r in checks) and material["all_checks_passed"] and packet_audit["all_checks_passed"] and all(r["passed"] or r.get("resolution") for r in audit.case(case_id)["checks"])}
        calls.append(row)
    pairs = []
    for (case_id, repeat), rows in sorted(pairing.items()):
        fields = sorted({k for r in rows for k in r["common_field_sha256"]})
        unequal = {k: {r["method"]: r["common_field_sha256"].get(k) for r in rows} for k in fields
                   if len({r["common_field_sha256"].get(k) for r in rows}) > 1}
        pairs.append({"case_id": case_id, "repeat": repeat, "physical_stage1_methods": sorted(r["method"] for r in rows),
                      "all_four_present": len(rows) == 4, "strict_nonhistory_material_equal": not unequal,
                      "common_field_differences": unequal, "same_input_byte_cap": len({r["input_utf8_cap"] for r in rows}) == 1,
                      "trajectory_M2_M4_equal": len({r["history_sha256"] for r in rows if r["method"] in {"M2", "M4"}}) == 1,
                      "calls": rows})
    across_repeats = []
    for case_id in sorted({p["case_id"] for p in pairs}):
        rows = [r for pair in pairs if pair["case_id"] == case_id for r in pair["calls"]]
        across_repeats.append({"case_id": case_id, "physical_stage1_calls": len(rows),
                               "all_arms_and_repeats_common_material_equal": len({r["nonhistory_material_sha256"] for r in rows}) == 1,
                               "common_material_hashes": sorted({r["nonhistory_material_sha256"] for r in rows}),
                               "same_input_byte_cap": len({r["input_utf8_cap"] for r in rows}) == 1})
    summaries = [{"check": name, "passed_count": audit.checks[(name, True)], "failed_count": audit.checks[(name, False)]}
                 for name in sorted({n for n, _ in audit.checks})]
    for row in calls:
        for check in row["checks"] + row["serialized_material"]["checks"]:
            if not check["passed"]:
                audit.findings.append({"scope": row["call"], **check})
    for packet in audit.packets.values():
        for check in packet["checks"]:
            if not check["passed"]:
                audit.findings.append({"scope": "public_packet:" + packet["content_sha256"], **check})
    for case in audit.cases.values():
        for check in case["checks"]:
            if not check["passed"]:
                audit.findings.append({"scope": "case:" + case["case_id"], **check})
    for pair in pairs:
        if not pair["strict_nonhistory_material_equal"]:
            audit.findings.append({"scope": f"TrackB/{pair['case_id']}/repeat_{pair['repeat']}", "check": "stage1_nonhistory_material_equality", "passed": False, "differences": pair["common_field_differences"]})
    scan_hits = [{"call": row["call"], **hit} for row in calls for hit in row["prohibited_source_scan"]["literal_hits"]]
    charged = sum(r.get("charged_tokens", r["reserved_tokens"]) for r in ledger["calls"].values())
    usage_groups = collections.defaultdict(list)
    for row in calls:
        parts = Path(row["call"]).parts
        group = "/".join((parts[2], parts[3], parts[5])) if "track_b" in parts else parts[2]
        usage_groups[group].append(row)
    usage_summary = {}
    for group, rows in sorted(usage_groups.items()):
        tokens = [r["provider_reported_usage"].get("prompt_tokens", 0) for r in rows]
        wire_bytes = [r["provider_wire_utf8_bytes"] for r in rows]
        usage_summary[group] = {"physical_calls": len(rows), "prompt_tokens_total": sum(tokens),
            "prompt_tokens_min": min(tokens), "prompt_tokens_max": max(tokens),
            "completion_tokens_total": sum(r["provider_reported_usage"].get("completion_tokens", 0) for r in rows),
            "wire_bytes_min": min(wire_bytes), "wire_bytes_max": max(wire_bytes),
            "charged_tokens_total": sum(r["budget"]["charged_tokens"] for r in rows)}
    summary = {"version": "serialized-input-provenance-audit.v1", "created_at": datetime.now(timezone.utc).isoformat(),
               "audit_script": receipt(__file__), "run": str(run), "scope": "All physical calls in actual provider manifests, including P1 data construction and Track B generation; no executions or model dispatch.",
               "provider_manifest_count": len(manifests), "physical_call_count": len(calls), "nonphysical_manifest_count": len(nonphysical),
               "ledger_entries": len(ledger["calls"]), "ledger_total_charged_tokens": charged, "ledger_limit_tokens": ledger["limit_tokens"],
               "ledger_remaining_tokens": ledger["limit_tokens"] - charged,
               "ledger_physical_call_bijection": len(matched_keys) == len(set(matched_keys)) and set(matched_keys) == set(ledger["calls"]),
               "ledger_unchanged_during_audit": before_ledger == receipt(run / "provider_budget.json"), "provider_budget_receipt": before_ledger,
               "unique_public_packets": len(audit.packets), "cases_with_raw_authorities": len(audit.cases),
               "calls_passing_all_mechanical_checks": sum(row["all_mechanical_checks_passed"] for row in calls),
               "finding_count": len(audit.findings), "unresolved_finding_count": sum(not r.get("resolution") for r in audit.findings),
               "resolved_composite_full_file_lookup_failures": sum(bool(r.get("resolution")) for r in audit.findings),
               "literal_flag_count": len(scan_hits), "check_summary": summaries, "usage_by_call_family": usage_summary,
               "stage1_paired_blocks": len(pairs), "stage1_strict_nonhistory_equal_blocks": sum(p["strict_nonhistory_material_equal"] for p in pairs),
               "stage1_all_four_present_blocks": sum(p["all_four_present"] for p in pairs), "stage2_physical_calls": len(stage2),
               "stage1_case_equality_across_all_arms_and_repeats": across_repeats,
               "stage2_pairing_policy": "Targets and selected tests are selected independently in each method/repeat and may differ. Listed explicitly; no equality is imposed after selection.",
               "trajectory_contrast_interpretation": "M1/M3 exclude raw trajectory actions; all four arms still receive the same versioned original-test inventory, including historical test versions. The contrast is the additional selected raw tool-command/output events, not the absence of every form of historical information.",
               "limitations": [
                   "This is an offline audit of archived inputs. Hash agreement cannot establish that historical raw data or its original acquisition were authentic; remote objects were not fetched.",
                   "Terminal source bytes are bound to recorded export/checkpoint receipts, not re-extracted from Docker. Historical test reconstruction authorities are checked by hash and exact stored bytes; execution semantics and the correctness of reconstruction are not re-established here.",
                   "Literal prohibited-term searches are diagnostic. Ordinary source identifiers, raw original issue text, archive paths and system prohibitions are not leakage evidence. No universal semantic no-leakage claim follows from absence of a term.",
                   "Full constructor reproduction plus exact raw/material binding rules out unaccounted extra user material in these stored requests only; it does not prove operator exposure, gold timing, filesystem ACL isolation, or candidate-ranking independence.",
                   "Provider token counts are provider-reported, not independently tokenized. Byte upper bounds are distinct from token usage. Same byte ceilings do not imply identical actual input token counts.",
                   "The audit does not infer the scientific completeness of omitted/nonphysical calls and does not evaluate generated candidates or subject executions."
               ], "requirements": {"G04": "Actual-input branch audited; gold establishment timing, access isolation and ranking provenance require separate evidence.",
                    "G05": "See exact per-call serialized payload, raw-material authorities, fragments and retained failures. No unrestricted semantic leakage guarantee.",
                    "G08": "Actual usage, byte caps, omissions, arm visibility and strict stage1 common-material equality reported; comparable execution budgets require separate audit."}}
    out.mkdir()
    write_new(out / "code_bindings.json", code_bindings)
    write_new(out / "calls.json", calls)
    write_new(out / "public_packets.json", list(audit.packets.values()))
    case_records = [{k: v for k, v in case.items() if k in {"case_id", "checks", "raw_receipts"}} for case in audit.cases.values()]
    write_new(out / "case_authorities.json", case_records)
    write_new(out / "receipt_validation.json", list(audit.receipts.values()))
    write_new(out / "stage1_common_material_pairs.json", pairs)
    write_new(out / "stage1_common_material_across_repeats.json", across_repeats)
    write_new(out / "stage2_independent_selections.json", stage2)
    write_new(out / "nonphysical_manifests.json", nonphysical)
    write_new(out / "findings.json", audit.findings)
    write_new(out / "literal_source_flags.json", scan_hits)
    report = (
        "Actual serialized input provenance audit\n\n"
        f"Audited {len(calls)} physical provider calls from {len(manifests)} manifests. The other {len(nonphysical)} manifests did not dispatch. "
        f"The physical calls and settled ledger entries form a bijection; charged usage is {charged:,}/{ledger['limit_tokens']:,} tokens.\n\n"
        f"All {sum(r['all_mechanical_checks_passed'] for r in calls)}/{len(calls)} calls pass the recorded-payload/hash/ledger/material checks and the full archived-constructor reconstruction. "
        f"Public material is traced through {len(audit.packets)} distinct stored packets across {len(audit.cases)} cases. "
        "Checks cover raw issues, patch byte ranges, source/test bytes and slices, raw tool-command/output projections, same-cell stage2 planning, and source authorities. "
        "Prompt-code freeze hashes are dependencies of this audit, not substitutes for reading actual provider/request.json.\n\n"
        f"Track B has {len(pairs)} physical stage1 blocks; {sum(p['strict_nonhistory_material_equal'] for p in pairs)} have exact equality of every decoded nonhistory material field across M1/M2/M3/M4. "
        "M1/M3 exclude the actions field; M2/M4 include it. Stage2 target/test choices are independently generated and are listed separately. "
        "All four arms share versioned original tests, including historical test bytes, so the trajectory contrast means additional raw tool events rather than absence of every form of historical information. "
        "Byte caps, provider-reported token usage, omitted sections and raw excerpt offsets are included. Equal caps do not mean equal actual tokens.\n\n"
        f"Retained {len(audit.findings)} failed direct checks, of which {sum(bool(r.get('resolution')) for r in audit.findings)} have an explicit verified composition explanation and {sum(not r.get('resolution') for r in audit.findings)} remain unresolved. "
        "In HF002, some presented Rust modules combine the terminal production prefix with an exact historical test suffix; a whole module is consequently absent from the historical document. "
        "The failed full-file lookups remain in findings.json alongside independent prefix/suffix byte proofs. No source or prompt was changed.\n\n"
        f"The user-material literal screen found {len(scan_hits)} flags. This is not a semantic proof of no leakage. "
        "System prohibitions and raw-input archive parent names such as failure_analysis are excluded from the screen. "
        "The positive evidence is exact reconstruction and material binding, not absence of keywords. "
        "G04 gold timing, operator exposure, ACL isolation, ranking independence and historical dataset authenticity are outside what these recorded payloads can prove. "
        "No provider, Docker, network or subject execution was performed by this audit.\n"
    )
    write_new(out / "report.txt", report)
    summary["artifacts"] = [receipt(path) for path in sorted(out.iterdir())]
    write_new(top, summary)
    print(json.dumps({k: summary[k] for k in ("physical_call_count", "ledger_total_charged_tokens", "ledger_physical_call_bijection", "calls_passing_all_mechanical_checks", "finding_count", "literal_flag_count", "stage1_paired_blocks", "stage1_strict_nonhistory_equal_blocks")}, indent=2))


if __name__ == "__main__":
    main()
