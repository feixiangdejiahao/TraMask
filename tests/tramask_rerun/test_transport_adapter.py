"""Synthetic fixtures only; transport success never implies semantic validity."""
import copy
import hashlib
import json

import pytest

from tramask_rerun.transport_adapter import TransportAdapterError, canonicalize_paths, recover_json


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.fixture
def case():
    files = {"app/code.py": "def value():\n    return 1\n", "tmp/test.py": "result = value()\nassert result == 1\n"}
    proposal = {"status": "proposed", "original_command": "python /tmp/test.py",
                "target": {"source_path": "code.py", "anchor": "code.py::value"},
                "alternative": {"edits": [{"path": "/app/code.py", "old": "return 1", "new": "return 2"}]},
                "instrumentation": {
                    "common_edits": [{"path": "/tmp/test.py", "old": "assert result == 1\n", "new": "print(result)\nassert result == 1\n"}],
                    "p_edits": [{"path": "code.py", "old": "    return 1\n", "new": "    print(1)\n    return 1\n"}],
                    "q_edits": [{"path": "code.py", "old": "    return 2\n", "new": "    print(2)\n    return 2\n"}],
                    "helper_files": [{"path": "helpers/new_probe.py", "content": "print('code.py')\n"}]}}
    return files, proposal


def test_strict_json_and_exact_raw_receipt():
    raw = ' \n{"code":"brace } and quote \\\" and slash \\\\"}  \n'
    result = recover_json(raw)
    assert result["value"] == json.loads(raw)
    assert result["raw_text"] == result["recovered_text"] == raw
    assert result["receipt"]["status"] == "strict_json"
    assert result["receipt"]["raw_sha256"] == result["receipt"]["recovered_sha256"] == sha(raw)
    assert result["receipt"]["insertions"] == []


def test_nested_eof_closures_and_unicode_offsets_do_not_touch_code():
    code = 'print("引号 } ]")\n# \\ literal'
    full = json.dumps({"items": [{"code": code}]}, ensure_ascii=False)
    raw = full[:-3] + " \n"
    result = recover_json(raw)
    assert result["recovered_text"] == raw + "}]}"
    assert result["value"]["items"][0]["code"] == code
    assert result["receipt"]["insertions"] == [{"character_offset": len(raw),
        "utf8_byte_offset": len(raw.encode()), "text": "}]}", "sha256": sha("}]}")}]
    assert result["receipt"]["raw_sha256"] == sha(raw)
    assert result["receipt"]["status"] == "recovered_eof_containers"


@pytest.mark.parametrize("raw", [
    '{"x": "unterminated', '{"x": "escape\\', '{"x":', '{"x"', '{"x": 1,',
    '{"x": tru', '{"x": 1e', '{"x": [1}', '{"x": 1 "y": 2', '[1,,2',
    '```json\n{"x": 1}\n```', 'prefix {"x":1', '{"x":1} trailing', '',
])
def test_never_repair_strings_values_separators_or_extract_objects(raw):
    with pytest.raises(TransportAdapterError) as error:
        recover_json(raw)
    assert error.value.receipt["status"] == "rejected"
    assert error.value.receipt["raw_sha256"] == sha(raw)


@pytest.mark.parametrize("raw, reason", [
    ('{"x":1,"x":2}', "duplicate_json_key"),
    ('{"x":{"a":1,"a":2}', "duplicate_json_key"),
    ('{"a":1,"\\u0061":2}', "duplicate_json_key"),
    ('{"x":NaN}', "nonfinite_json_number"), ('{"x":Infinity', "nonfinite_json_number"),
    ('{"x":-Infinity}', "nonfinite_json_number"), ('{"x":1e999}', "nonfinite_json_number"),
])
def test_reject_duplicate_keys_and_all_nonfinite_forms(raw, reason):
    with pytest.raises(TransportAdapterError, match=reason):
        recover_json(raw)


def test_aliases_are_uniform_and_q_anchor_binds_q_not_p(case):
    files, proposal = case
    snapshot = copy.deepcopy((files, proposal))
    result = canonicalize_paths(proposal, files, ["/tmp/test.py"])
    canonical, receipt = result["proposal"], result["receipt"]
    assert canonical["target"]["source_path"] == "app/code.py"
    assert canonical["alternative"]["edits"][0]["path"] == "app/code.py"
    assert canonical["instrumentation"]["common_edits"][0]["path"] == "tmp/test.py"
    assert canonical["instrumentation"]["q_edits"][0]["path"] == "app/code.py"
    q = next(c for c in receipt["anchor_checks"] if c["stage"] == "q_edits_after_common")
    assert q["old_occurrences"] == 1
    assert q["file_sha256"] == sha(files["app/code.py"].replace("return 1", "return 2"))
    assert len(receipt["path_changes"]) == 5
    assert (files, proposal) == snapshot
    # Description, command, helper location and all source strings remain untouched.
    assert canonical["target"]["anchor"] == proposal["target"]["anchor"]
    assert canonical["original_command"] == proposal["original_command"]
    assert canonical["instrumentation"]["helper_files"] == proposal["instrumentation"]["helper_files"]
    assert receipt["new_helpers_not_relocated"] == [{"path": "helpers/new_probe.py", "location_validation": "deferred"}]
    for name in ("common_edits", "p_edits", "q_edits"):
        for old, new in zip(proposal["instrumentation"][name], canonical["instrumentation"][name]):
            assert (old["old"], old["new"]) == (new["old"], new["new"])
    assert receipt["semantic_validation"] == receipt["execution"] == "not_performed"


def test_common_anchor_must_exist_in_both_branches(case):
    files, proposal = case
    proposal["instrumentation"]["common_edits"] = [{"path": "code.py", "old": "return 1", "new": "print(1); return 1"}]
    proposal["instrumentation"]["p_edits"] = []
    with pytest.raises(TransportAdapterError, match="old_anchor_must_occur_exactly_once") as error:
        canonicalize_paths(proposal, files, ["tmp/test.py"])
    assert error.value.receipt["anchor_checks"][-1]["stage"] == "common_from_q"
    assert error.value.receipt["anchor_checks"][-1]["old_occurrences"] == 0


def test_q_and_p_checks_follow_common_insertion(case):
    files, proposal = case
    proposal["instrumentation"]["p_edits"] = [{"path": "/tmp/test.py", "old": "print(result)\n", "new": "print(result)\n# P\n"}]
    proposal["instrumentation"]["q_edits"] = [{"path": "/tmp/test.py", "old": "print(result)\n", "new": "print(result)\n# Q\n"}]
    result = canonicalize_paths(proposal, files)
    assert all(c["old_occurrences"] == 1 for c in result["receipt"]["anchor_checks"])


@pytest.mark.parametrize("content, count", [("return 1\nreturn 1", 2), ("return 3", 0)])
def test_even_canonical_path_requires_unique_anchor(content, count):
    proposal = {"alternative": {"edits": [{"path": "app/x", "old": "return 1", "new": "return 2"}]}}
    with pytest.raises(TransportAdapterError, match="old_anchor_must_occur_exactly_once") as error:
        canonicalize_paths(proposal, {"app/x": content})
    assert error.value.receipt["anchor_checks"][0]["old_occurrences"] == count


def test_overlapping_occurrences_and_overlapping_edit_spans_rejected():
    h = {"alternative": {"edits": [{"path": "a", "old": "aa", "new": "b"}]}}
    with pytest.raises(TransportAdapterError, match="old_anchor_must_occur_exactly_once"):
        canonicalize_paths(h, {"app/a": "aaa"})
    h["alternative"]["edits"] = [{"path": "a", "old": "abc", "new": "X"}, {"path": "a", "old": "bcd", "new": "Y"}]
    with pytest.raises(TransportAdapterError, match="overlapping_exact_edits"):
        canonicalize_paths(h, {"app/a": "abcd"})


def test_ambiguous_path_not_disambiguated_by_old_anchor():
    h = {"alternative": {"edits": [{"path": "app/a", "old": "only here", "new": "changed"}]}}
    with pytest.raises(TransportAdapterError, match="ambiguous_public_path_alias"):
        canonicalize_paths(h, {"app/a": "only here", "app/app/a": "elsewhere"})


@pytest.mark.parametrize("path", ["app/../x", "/etc/passwd", "app//x", "./app/x", "app/.git/config", "app/.env", "app\\x"])
def test_path_traversal_private_and_noncanonical_paths_rejected(path):
    with pytest.raises(TransportAdapterError):
        canonicalize_paths({"target": {"source_path": path}}, {"app/x": "safe"})


def test_unknown_file_not_invented_and_new_helper_not_used_as_public_file():
    h = {"instrumentation": {"helper_files": [{"path": "app/new.py", "content": "old"}],
        "p_edits": [{"path": "new.py", "old": "old", "new": "new"}]}}
    with pytest.raises(TransportAdapterError, match="path_not_in_public_files"):
        canonicalize_paths(h, {"app/x": "safe"})


def test_tests_can_supply_full_text_and_conflicting_snapshot_is_rejected(case):
    files, proposal = case
    result = canonicalize_paths(proposal, {"app/code.py": files["app/code.py"]}, {"tmp/test.py": files["tmp/test.py"]})
    assert result["receipt"]["test_paths"] == ["tmp/test.py"]
    with pytest.raises(TransportAdapterError, match="conflicting_public_file_content"):
        canonicalize_paths(proposal, files, {"tmp/test.py": "conflict"})


def test_does_not_fix_empty_alternative_noop_or_changed_probe_statements(case):
    files, proposal = case
    proposal["alternative"]["edits"] = []
    proposal["instrumentation"]["q_edits"] = []
    proposal["instrumentation"]["p_edits"][0]["new"] = "    return 999\n"
    result = canonicalize_paths(proposal, files)
    assert result["proposal"]["alternative"]["edits"] == []
    assert result["proposal"]["instrumentation"]["p_edits"][0]["new"] == "    return 999\n"
    proposal["alternative"]["edits"] = [{"path": "code.py", "old": "return 1", "new": "return 1"}]
    result = canonicalize_paths(proposal, files)
    assert result["proposal"]["alternative"]["edits"][0]["old"] == result["proposal"]["alternative"]["edits"][0]["new"]


def test_candidate_slots_and_nonpaths_preserved_without_semantic_certification():
    candidates = [{"rank": 1, "edits": [{"path": "/tmp/t", "old": "setup=0", "new": "setup=1"}]},
                  None, {"rank": 3, "status": "no_proposal"}, "malformed", {"rank": 5, "edits": []}]
    h = {"candidates": candidates}
    result = canonicalize_paths(h, {"tmp/t": "setup=0\n"}, ["tmp/t"])
    assert len(result["proposal"]["candidates"]) == 5
    assert result["proposal"]["candidates"][1:] == candidates[1:]
    assert result["proposal"]["candidates"][0]["edits"][0]["path"] == "tmp/t"
    assert h["candidates"][0]["edits"][0]["path"] == "/tmp/t"


def test_second_adapter_call_is_idempotent(case):
    files, h = case
    once = canonicalize_paths(h, files)
    twice = canonicalize_paths(once["proposal"], files)
    assert twice["proposal"] == once["proposal"]
    assert twice["receipt"]["path_changes"] == []
    assert twice["receipt"]["canonical_proposal_sha256"] == once["receipt"]["canonical_proposal_sha256"]
