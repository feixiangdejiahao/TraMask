import copy
import pytest

from tramask_rerun.prompt_codec import encode_payload, decode_payload


def test_roundtrip_preserves_versions_commands_and_nonascii():
    payload = {"material": {"validation_tests": [
        {"id": "v1-a", "command": "go test -run A", "files": {"app/t.go": "// 中文\nfunc A() {}"}},
        {"id": "v1-b", "command": "go test -run B", "files": {"app/t.go": "// 中文\nfunc A() {}"}},
        {"id": "v2", "command": "go test -run A", "files": {"app/t.go": "// 中文\nfunc A() { panic(1) }"}},
    ]}, "available_evidence_refs": ["test:v1-a", "test:v1-b", "test:v2"]}
    original = copy.deepcopy(payload)
    encoded = encode_payload(payload)
    assert payload == original
    assert len(encoded["shared_file_contents"]) == 1
    assert decode_payload(encoded) == original
    assert encoded["material"]["validation_tests"][2]["files"]["app/t.go"] == original["material"]["validation_tests"][2]["files"]["app/t.go"]
    key = next(iter(encoded["shared_file_contents"]))
    encoded["shared_file_contents"][key] += "altered"
    with pytest.raises(ValueError, match="hash mismatch"):
        decode_payload(encoded)


def test_unique_material_unchanged():
    payload = {"material": {"selected_test": {"files": {"app/t.py": "assert 1"}}}}
    assert encode_payload(payload) == payload
    assert decode_payload(payload) == payload


def test_distinct_versions_share_exact_blocks_without_dropping_definitions():
    import json
    common = "func shared() {\n" + "    preserved_statement()\n" * 60 + "}\n\n"
    first, second = common + "func first() {}\n", common + "func second() {}\n"
    payload = {"material": {"validation_tests": [
        {"id": "first", "files": {"app/t.go": first}},
        {"id": "second", "files": {"app/t.go": second}}]}}
    encoded = encode_payload(payload)
    assert len(json.dumps(encoded)) < len(json.dumps(payload))
    assert decode_payload(encoded) == payload
