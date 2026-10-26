"""Runner adaptation and evidence checks without Docker or provider calls."""
import json
import os
import subprocess

import pytest

from tramask_rerun import cache_qualification as cache


def test_only_cache_prefix_is_added_and_original_command_bytes_survive():
    original = "cd /app && timeout 150 go test -run 'TestGraph|TestExecutor' . ./internal/graph/ -v 2>&1 | head -50"
    effective = cache.cache_bypass_command(original)
    assert effective == cache.PREFIX + original
    assert effective[len(cache.PREFIX):] == original
    assert effective.count("-count=1") == 1
    assert "go clean" not in effective and "GOCACHE=" not in effective


@pytest.mark.parametrize("existing", ["-mod=vendor", "-race -tags=testing", ""])
def test_preexisting_goflags_are_preserved_exactly(existing):
    command = cache.cache_bypass_command("printf '%s' \"$GOFLAGS\"")
    result = subprocess.run(["/bin/sh", "-c", command], env={**os.environ, "GOFLAGS": existing}, capture_output=True, check=True)
    assert result.stdout.decode() == existing + " -count=1"


def test_unset_environment_preserves_persistent_go_config_without_real_go_call():
    command = "go() { printf '%s' '-mod=readonly'; };\n" + cache.cache_bypass_command("printf '%s' \"$GOFLAGS\"")
    environment = {key: value for key, value in os.environ.items() if key != "GOFLAGS"}
    result = subprocess.run(["/bin/sh", "-c", command], env=environment, capture_output=True, check=True)
    assert result.stdout == b"-mod=readonly -count=1"


@pytest.mark.parametrize("original", ["GOFLAGS=-race go test ./...", "export GOFLAGS=-race; go test ./...", "go test -count=5 ./..."])
def test_ambiguous_original_flag_overrides_are_not_silently_rewritten(original):
    with pytest.raises(ValueError):
        cache.cache_bypass_command(original)


def test_exit_zero_alone_cached_results_and_no_tests_do_not_qualify():
    for output in ("", "ok\texample/pkg\t(cached)\n", "ok\texample/pkg\t0.001s [no tests to run]\n", "FAIL\texample/pkg [build failed]\n"):
        result = cache.runner_observations({"stdout": output, "returncode": 0})
        assert not result["uncached_test_execution_reported"]
    result = cache.runner_observations({"stdout": "=== RUN TestX\n--- PASS: TestX (0.00s)\nPASS\nok\texample/pkg\t0.002s\n"})
    assert result["uncached_test_execution_reported"] and not result["cached_output_present"]


def test_existing_output_file_cannot_be_overwritten(tmp_path):
    target = tmp_path / "summary.json"
    cache._write_new(target, {"original": True})
    before = target.read_bytes()
    with pytest.raises(FileExistsError):
        cache._write_new(target, {"replacement": True})
    assert target.read_bytes() == before


def test_outcome_signature_ignores_scheduler_line_order_not_assertion_status():
    a = "--- PASS: TestA (0.00s)\n--- PASS: TestB (0.00s)\nok example/pkg 0.01s\n"
    b = "--- PASS: TestB (0.02s)\n--- PASS: TestA (0.01s)\nok example/pkg 0.03s\n"
    assert cache.runner_observations({"stdout": a})["outcome_signature"] == cache.runner_observations({"stdout": b})["outcome_signature"]
    changed = cache.runner_observations({"stdout": b.replace("PASS: TestA", "FAIL: TestA")})
    assert changed["outcome_signature"] != cache.runner_observations({"stdout": a})["outcome_signature"]
