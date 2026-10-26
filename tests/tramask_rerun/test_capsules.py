import pytest
from tramask_rerun.capsules import recover_literal_capsule


def trajectory(commands):
    return {"steps": [{"step_id": i, "tool_calls": [{"function_name": "bash", "arguments": {"command": command}}],
                       "observation": {"results": [{"content": {"returncode": 0, "output": ""}}]}}
                      for i, command in enumerate(commands, 1)]}


def test_literal_append_replace_and_stop_before_cleanup():
    commands = ["cat > /tmp/test.py <<'EOF'\na=1\nEOF",
                "cat >> /tmp/test.py <<'EOF'\nassert a == 1\nEOF",
                "python3 - <<'PY'\np='/tmp/test.py'\ns=open(p).read()\nold='a=1'\nnew='a = 1'\ns=s.replace(old,new,1)\nopen(p,'w').write(s)\nPY\npython /tmp/test.py; rm /tmp/test.py"]
    result = recover_literal_capsule(trajectory(commands), "s3_c0", "python /tmp/test.py; rm /tmp/test.py", ["/tmp/test.py"])
    assert result["files"]["/tmp/test.py"]["content"] == "a = 1\nassert a == 1\n"
    assert len(result["literal_write_evidence"]) == 3


def test_relative_setup_paths_resolve_without_running_commands():
    command = "cd /tmp && mkdir example && cd example && cat > fixture.json <<'EOF'\n{}\nEOF\ncat > test.py <<'EOF'\nraise RuntimeError('data only')\nEOF\npython test.py"
    result = recover_literal_capsule(trajectory([command]), "s1_c0", "python test.py", ["/tmp/example/test.py", "/tmp/example/fixture.json"])
    assert set(result["files"]) == {"/tmp/example/test.py", "/tmp/example/fixture.json"}


def test_unknown_transformation_requires_evidence():
    commands = ["cat > /tmp/test.py <<'EOF'\na=1\nEOF",
                "python3 - <<'PY'\np='/tmp/test.py'\ns=open(p).read()\ns=s.upper()\nopen(p,'w').write(s)\nPY\npython /tmp/test.py"]
    with pytest.raises(ValueError, match="unsupported_capsule_transformation"):
        recover_literal_capsule(trajectory(commands), "s2_c0", "python /tmp/test.py", ["/tmp/test.py"])
