"""Synthetic execution-material guards; no subject programs are executed."""
import copy
import hashlib
import json

import pytest

from tramask_rerun.validation_material import load_validation_material, plan_validation


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def save(path, value):
    raw = json.dumps(value, ensure_ascii=False).encode()
    path.write_bytes(raw)
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


@pytest.fixture
def evidence(tmp_path):
    class Evidence:
        checkpoint = {"image_id": "sha256:" + "1" * 64, "head": "a" * 40}

        def __init__(self):
            self.native = {"app/code.py": "def value():\n    return 1\n", "tmp/test.py": "assert value() == 1\n"}
            self.authority = save(tmp_path / "authority.json", {"raw": "literal archived tests"})
            self.test = {"id": "original", "command": "python /tmp/test.py", "working_directory": "/app",
                         "test_paths": ["/tmp/test.py"], "files": {"tmp/test.py": self.native["tmp/test.py"]}}
            self.inventory = {"case_id": "H001", "checkpoint": self.checkpoint,
                              "inventory_complete_for_declared_recovery_scope": True, "validation_tests": [self.test]}
            self.public = {"case_id": "H001", "final_sources": {"app/code.py": self.native["app/code.py"]}}
            self.proof = {"checkpoint": self.checkpoint, "state_validation_passed": True}
            self.rebind()

        def rebind(self):
            rows, receipts = [], {}
            for path, text in self.test["files"].items():
                before = sha(self.native[path]) if path in self.native else None
                receipts[path] = {"sha256": sha(text), "terminal_sha256": before,
                                  "authority_receipt": self.authority, "version_action_id": "s1_c0"}
                rows.append({"path": "/" + path, "content_sha256": sha(text), "expected_terminal_sha256": before,
                             "status": "terminal" if before == sha(text) else "explicit_historical_test_version"})
            self.test["file_receipts"] = receipts
            self.test["materialization"] = {"kind": "explicit_historical_test_version" if any(r["status"] != "terminal" for r in rows) else "terminal",
                                           "files": rows, "production_overlay": False, "after_terminal_stateproof_only": True}
            files = dict(self.test["files"])
            public_test = {k: self.test[k] for k in ("id", "command", "working_directory")}
            if self.test.get("inline_test"):
                original = self.test["inline_test"]; body = original["content"]; command = self.test["command"]
                start = len(command[:command.index(body)].encode())
                path = "tmp/tramask_inline/" + sha(body) + ".py"
                files[path] = body
                public_test["inline_test"] = {"path": path, "text": body, "command_mapping": {
                    "original_command": command, "script_start_byte": start, "script_end_byte": start + len(body.encode())}}
            public_test["files"] = files
            self.public["validation_tests"] = [public_test]
            self.manifest = {"roots": ["/app", "/tmp"], "errors": [], "files": [
                {"path": "/" + p, "kind": "file", "sha256": sha(t)} for p, t in self.native.items()]}

        def load(self):
            self.proof["inventory"] = save(tmp_path / "manifest.json", self.manifest)
            exports = {"checkpoint": self.checkpoint, "status": "complete", "files": [
                {"path": "/" + p, "content": t, "status": "present", "sha256": sha(t)} for p, t in self.native.items()]}
            self.arguments = (save(tmp_path / "public.json", self.public), save(tmp_path / "inventory.json", self.inventory), "original")
            self.keywords = {"checkpoint_proof_receipt": save(tmp_path / "proof.json", self.proof),
                             "terminal_export_receipts": [save(tmp_path / "exports.json", exports)]}
            return load_validation_material(*self.arguments, **self.keywords)

        def inline(self, body="print('λ')", enclosure='"'):
            self.test.update(files={}, test_paths=[], command="# λ\npython -c " + enclosure + body + enclosure,
                             inline_test={"content": body, "sha256": sha(body), "language": "python"})
            self.rebind()

        def mixed(self):
            marker = "#[cfg(test)]\nmod tests {"
            self.prefix = "// λ\nfn value() -> u8 { 1 }\n"
            self.terminal_suffix = marker + "\n    assert_eq!(value(), 1);\n}\n"
            self.selected_suffix = marker + "\n    assert!(value() > 0);\n}\n"
            path = "app/code.rs"
            self.native = {path: self.prefix + self.terminal_suffix}
            self.public["final_sources"] = {path: self.native[path]}
            text = self.prefix + self.selected_suffix
            self.test.update(files={path: text}, test_paths=["/" + path], command="cargo test --lib")
            start = len(self.prefix.encode())
            self.test["protected_test_regions"] = [{"path": "/" + path, "region_kind": "cfg_test_module_suffix", "marker": marker,
                "selected_region_utf8_offsets": [start, len(text.encode())],
                "terminal_region_utf8_offsets": [start, len(self.native[path].encode())],
                "terminal_production_prefix_sha256": sha(self.prefix), "original_test_region_sha256": sha(self.selected_suffix),
                "terminal_test_region_sha256": sha(self.terminal_suffix)}]
            self.rebind()

    return Evidence()


def candidate(path="tmp/test.py", old="== 1", new="== 2"):
    return {"status": "proposed", "edits": [{"path": path, "old": old, "new": new}]}


def test_direct_native_plan_requires_no_q_and_is_deterministic_isolated(evidence):
    material = evidence.load(); original = copy.deepcopy(material); c = candidate(); c0 = copy.deepcopy(c)
    plan = plan_validation(material, c)
    assert plan == plan_validation(material, c)
    assert material == original and c == c0
    assert set(plan["arms"]) == {"p_original", "p_candidate"}
    assert plan["arms"]["p_original"]["files"] == {}
    assert plan["arms"]["p_candidate"]["files"]["/tmp/test.py"] == {
        "content": "assert value() == 2\n", "before_sha256": sha("assert value() == 1\n")}
    assert plan["semantic_classification"] is None and not plan["executed"] and not plan["syntax_repaired"]


def test_historical_file_versions_always_use_terminal_predecessor(evidence):
    evidence.test["files"]["tmp/test.py"] = "assert value() == 0\n"; evidence.rebind()
    p = plan_validation(evidence.load(), candidate(old="== 0"))
    for arm in p["arms"].values():
        assert arm["files"]["/tmp/test.py"]["before_sha256"] == sha(evidence.native["tmp/test.py"])
    assert p["arms"]["p_original"]["files"]["/tmp/test.py"]["content"].endswith("== 0\n")


def test_legacy_explicit_entry_kind_still_binds_each_predecessor(evidence):
    evidence.test["files"]["tmp/test.py"] = "assert value() == 0\n"; evidence.rebind()
    del evidence.test["materialization"]["files"][0]["status"]
    p = plan_validation(evidence.load())
    assert p["arms"]["p_original"]["files"]["/tmp/test.py"]["before_sha256"] == sha(evidence.native["tmp/test.py"])


def test_deleted_test_is_explicit_new_file_and_absence_requires_covered_root(evidence):
    del evidence.native["tmp/test.py"]; evidence.rebind()
    assert plan_validation(evidence.load())["arms"]["p_original"]["files"]["/tmp/test.py"]["new_file"] is True
    evidence.manifest["roots"] = ["/app"]
    with pytest.raises(ValueError, match="proven_absence"):
        evidence.load()


@pytest.mark.parametrize("mutation,error", [
    (lambda e: e.proof.update(state_validation_passed=False), "state_proof"),
    (lambda e: e.inventory.update(inventory_complete_for_declared_recovery_scope=False), "complete_qualified"),
    (lambda e: e.inventory.update(checkpoint={"image_id": "sha256:" + "2" * 64, "head": "b" * 40}), "checkpoint_mismatch"),
    (lambda e: e.test["materialization"]["files"][0].update(expected_terminal_sha256="0" * 64), "predecessor_receipts"),
    (lambda e: e.test["file_receipts"]["tmp/test.py"].update(sha256="0" * 64), "test_hash"),
    (lambda e: e.public["validation_tests"][0].update(command="python /tmp/other.py"), "public_test_mismatch"),
    (lambda e: e.public["validation_tests"].append(copy.deepcopy(e.public["validation_tests"][0])), "duplicate_public"),
])
def test_bad_binding_rejected_before_plans(evidence, mutation, error):
    mutation(evidence)
    with pytest.raises(ValueError, match=error):
        evidence.load()


def test_wrong_receipt_and_changed_authority_are_rejected(evidence, tmp_path):
    material = evidence.load()
    (tmp_path / "authority.json").write_text("changed")
    with pytest.raises(ValueError, match="receipt_hash"):
        plan_validation(material)
    with pytest.raises(ValueError, match="receipt_hash"):
        load_validation_material(*evidence.arguments, **evidence.keywords)


def test_material_seal_and_new_file_ancestor_collision(evidence):
    material = evidence.load(); material["command"] = "echo changed"
    with pytest.raises(ValueError, match="changed_after_binding"):
        plan_validation(material)
    body = evidence.test["files"].pop("tmp/test.py")
    del evidence.native["tmp/test.py"]; evidence.native["tmp/tests"] = "file"
    evidence.test.update(files={"tmp/tests/test.py": body}, test_paths=["/tmp/tests/test.py"])
    evidence.rebind()
    with pytest.raises(ValueError, match="non_directory_ancestor"):
        evidence.load()


def test_new_flags_and_unguarded_production_test_overlap_are_rejected(evidence):
    evidence.test["materialization"]["files"][0]["assert_absent_before_materialization"] = True
    with pytest.raises(ValueError, match="new_file_flag"):
        evidence.load()
    evidence.rebind(); evidence.public["final_sources"]["tmp/test.py"] = evidence.native["tmp/test.py"]
    with pytest.raises(ValueError, match="overlap_requires_region_guard"):
        evidence.load()


@pytest.mark.parametrize("edits,error", [
    ([{"path": "app/code.py", "old": "return 1", "new": "return 2"}], "outside_selected"),
    ([{"path": "tmp/test.py", "old": "value()", "new": "other()"},
      {"path": "tmp/test.py", "old": "value() == 1", "new": "value() == 2"}], "overlapping"),
    ([{"path": "tmp/../test.py", "old": "== 1", "new": "== 2"}], "noncanonical"),
])
def test_exact_edit_allowlist_and_overlap(evidence, edits, error):
    with pytest.raises(ValueError, match=error):
        plan_validation(evidence.load(), {"status": "proposed", "edits": edits})


def test_none_and_no_proposal_stay_unchanged(evidence):
    m = evidence.load()
    assert set(plan_validation(m)["arms"]) == {"p_original"}
    abstention = {"status": "no_proposal", "reason": "insufficient evidence"}
    p = plan_validation(m, abstention)
    assert p["candidate"] == abstention and set(p["arms"]) == {"p_original"}


def test_q_requires_frozen_output_but_stage1_planning_is_valid(evidence, tmp_path):
    m = evidence.load(); q = {"alternative": {"edits": [{"path": "app/code.py", "old": "return 1", "new": "return 9"}]}}
    bound = save(tmp_path / "q.json", q)
    with pytest.raises(ValueError, match="frozen_output"):
        plan_validation(m, fixed_q_receipt=bound)
    p = plan_validation(m, fixed_q_receipt=bound, frozen_output_receipt=bound)
    assert set(p["arms"]) == {"p_original", "q_original"}
    c = candidate(); frozen = save(tmp_path / "candidates.json", {"candidates": [c]})
    p = plan_validation(m, c, fixed_q_receipt=bound, frozen_output_receipt=frozen)
    assert "return 9" in p["arms"]["q_candidate"]["files"]["/app/code.py"]["content"]
    with pytest.raises(ValueError, match="not_in_frozen_output"):
        plan_validation(m, candidate(new="== 3"), fixed_q_receipt=bound, frozen_output_receipt=frozen)


def test_mixed_region_preserves_terminal_prefix_and_merges_q_by_guard(evidence, tmp_path):
    evidence.mixed(); m = evidence.load(); full = evidence.test["files"]["app/code.rs"]
    c = candidate("app/code.rs", full, full.replace("value() > 0", "value() > 2"))
    q = {"edits": [{"path": "app/code.rs", "old": full, "new": full.replace("{ 1 }", "{ 123 }", 1)}]}
    p = plan_validation(m, c, fixed_q_receipt=save(tmp_path / "q.json", q),
                        frozen_output_receipt=save(tmp_path / "candidate.json", c))
    for arm in p["arms"].values():
        assert arm["files"]["/app/code.rs"]["before_sha256"] == sha(evidence.native["app/code.rs"])
    assert p["arms"]["p_original"]["full_text"]["app/code.rs"] == full
    combined = p["arms"]["q_candidate"]["full_text"]["app/code.rs"]
    assert "{ 123 }" in combined and "value() > 2" in combined
    with pytest.raises(ValueError, match="production_prefix"):
        plan_validation(m, candidate("app/code.rs", "{ 1 }", "{ 2 }"))
    badq = save(tmp_path / "bad_q.json", {"edits": [{"path": "app/code.rs", "old": "value() > 0", "new": "value() > 2"}]})
    with pytest.raises(ValueError, match="protected_test_region"):
        plan_validation(m, fixed_q_receipt=badq, frozen_output_receipt=badq)


def test_mixed_region_bad_hash_or_utf8_range_is_rejected(evidence):
    evidence.mixed(); evidence.test["protected_test_regions"][0]["terminal_production_prefix_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="prefix_hash"):
        evidence.load()


def test_inline_utf8_replacement_preserves_exact_command_outside_bytes(evidence):
    evidence.inline(); m = evidence.load(); inline = m["inline"]; path = inline["path"]
    p = plan_validation(m, candidate(path, "λ", "unicode σ")); changed = p["arms"]["p_candidate"]
    start = inline["command_mapping"]["script_start_byte"]; end = inline["command_mapping"]["script_end_byte"]
    raw = evidence.test["command"].encode()
    assert changed["command"].encode() == raw[:start] + "print('unicode σ')".encode() + raw[end:]
    assert changed["files"] == {} and "/" + path not in changed["after_sha256"]


@pytest.mark.parametrize("replacement", ['print("x")', "print('$HOME')", "print('`id`')", "print('x')\\\n"])
def test_inline_double_quote_expansion_collisions_are_not_repaired(evidence, replacement):
    evidence.inline("print(1)"); m = evidence.load()
    with pytest.raises(ValueError, match="inline_double_quote"):
        plan_validation(m, candidate(m["inline"]["path"], "print(1)", replacement))


def test_inline_single_quote_and_quoted_heredoc_guards(evidence):
    evidence.inline("print(1)", "'"); m = evidence.load()
    with pytest.raises(ValueError, match="single_quote_collision"):
        plan_validation(m, candidate(m["inline"]["path"], "print(1)", "print('x')"))
    body = "print('λ')\n"; evidence.inline(body); evidence.test["command"] = "python - <<'PY'\n" + body + "PY\n"
    evidence.rebind(); m = evidence.load()
    p = plan_validation(m, candidate(m["inline"]["path"], body, 'print("x")\n'))
    assert p["arms"]["p_candidate"]["command"] == 'python - <<\'PY\'\nprint("x")\nPY\n'
    with pytest.raises(ValueError, match="delimiter_collision"):
        plan_validation(m, candidate(m["inline"]["path"], body, "PY\necho bad\n"))


def test_inline_existing_virtual_path_and_invalid_command_are_rejected(evidence):
    evidence.inline(); path = evidence.public["validation_tests"][0]["inline_test"]["path"]
    evidence.native[path] = "collision"; evidence.rebind()
    with pytest.raises(ValueError, match="virtual_path_collision"):
        evidence.load()
    del evidence.native[path]; evidence.test["command"] += '"'; evidence.rebind()
    with pytest.raises(ValueError, match="invalid_shell_quoting"):
        evidence.load()


def test_subject_language_syntax_is_preserved_without_repair(evidence):
    evidence.inline("print(1)"); m = evidence.load()
    p = plan_validation(m, candidate(m["inline"]["path"], "print(1)", "print("))
    assert p["arms"]["p_candidate"]["command"].endswith('"print("')
    assert p["syntax_repaired"] is False


def test_build_contract_is_carried_for_every_arm_without_binary_reuse(evidence, tmp_path):
    evidence.test["build_contract"] = {"required_before_execution": True,
        "exact_original_build_command": "go build -o /tmp/ytt ./cmd/ytt", "working_directory": "/app",
        "expected_binary_path": "/tmp/ytt", "policy": "rebuild each arm"}
    m = evidence.load(); c = candidate()
    q = save(tmp_path / "q.json", {"edits": [{"path": "app/code.py", "old": "return 1", "new": "return 9"}]})
    p = plan_validation(m, c, fixed_q_receipt=q, frozen_output_receipt=save(tmp_path / "frozen.json", c))
    assert len(p["arms"]) == 4
    for arm in p["arms"].values():
        assert arm["build_contract"] == evidence.test["build_contract"]
        assert arm["build_commands"] == ["go build -o /tmp/ytt ./cmd/ytt"]
        assert arm["build_steps"][0]["require_fresh_executable_receipt"]
        assert arm["build_steps"][0]["expected_binary_path"] == "/tmp/ytt"
