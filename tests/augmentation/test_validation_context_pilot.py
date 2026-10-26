import json
from pathlib import Path

import pytest

from augmentation.validation_context_pilot import (
    harness, materialize_tests, public_file, serve_queries, validate_response,
)


def test_query_cannot_read_parent_secret_or_symlink(tmp_path):
    repo = tmp_path/"repo"
    repo.mkdir()
    (tmp_path/"secret.py").write_text("secret = 1")
    (repo/"leak.py").symlink_to(tmp_path/"secret.py")
    (repo/".env").write_text("TOKEN=hidden")
    for path in ("../secret.py", "leak.py", ".env", str(tmp_path/"secret.py")):
        with pytest.raises(ValueError):
            public_file(repo, path)


def test_source_only_arm_cannot_obtain_history(tmp_path):
    case = {"repository": str(tmp_path), "language": "go"}
    events = [{"step": 7, "agent_note": "private history", "command": "", "output": ""}]
    answers = serve_queries(case, {"validation_tests": []}, events,
                            [{"kind": "history", "step": 7}, {"kind": "history_search", "text": "private"}], history_allowed=False)
    assert all(a.get("error") == "history_unavailable_in_this_arm" for a in answers)
    assert all("answer" not in a for a in answers)


def test_program_connections_do_not_claim_execution(tmp_path):
    base = {"validation_tests": [
        {"id": "a", "path": "x_test.go", "line": 1, "code": "func TestA(t *testing.T) { apply(1) }"},
        {"id": "b", "path": "x_test.go", "line": 2, "code": "func TestB(t *testing.T) { apply(2) }"},
    ]}
    result = serve_queries({"repository": str(tmp_path), "language": "go"}, base, [],
                          [{"kind": "connections", "test_id": "a"}], history_allowed=False)[0]["answer"]
    assert result["tests"][0]["test_id"] == "b"
    assert "proof" in result["limit"]


def test_generated_test_cannot_overwrite_production(tmp_path):
    case = {"repository": str(tmp_path), "language": "go"}
    with pytest.raises(ValueError, match="not_a_test"):
        materialize_tests(case, {"tests": [{"path": "source.go", "mode": "new", "code": "package example"}]})


def test_generated_test_is_preserved_verbatim(tmp_path):
    case = {"repository": str(tmp_path), "language": "go"}
    code = 'package example\nimport "testing"\nfunc TestCCPilotCombination(t *testing.T) { t.Fatal("a real failure") }'
    files, names = materialize_tests(case, {"tests": [{"path": "cc_test.go", "mode": "new", "code": code}]})
    assert files["cc_test.go"] == code+"\n"
    assert names == ["TestCCPilotCombination"]


def test_workspace_script_resolves_vitest(tmp_path):
    package = tmp_path/"packages/core"
    package.mkdir(parents=True)
    (package/"package.json").write_text(json.dumps({"scripts": {"test:lib": "vitest"}}))
    result = harness({"repository": str(tmp_path), "language": "typescript"}, ["packages/core/src/cc.test.ts"])
    assert result["command"].startswith("cd packages/core && pnpm exec vitest run src/cc.test.ts")


def test_detection_survives_missing_generated_code():
    result = validate_response({"decision": "gap", "target": {"combination": "x"}, "tests": []})
    assert result["generation_missing"]
