import hashlib
import json
import os
from pathlib import Path
import shutil

import pytest

from scripts.relational_phase_runner import execute_plan


def phase(root, role, code, command, timeout=20):
    staged = Path('.inputs') / role / 'toy_test.go'
    (root / staged).parent.mkdir(parents=True, exist_ok=True)
    (root / staged).write_text(code)
    return {'role': role, 'command': command, 'timeout': timeout,
            'files': [{'target': 'toy_test.go', 'staged': str(staged),
                       'sha256': hashlib.sha256(code.encode()).hexdigest()}]}


@pytest.mark.skipif(shutil.which('go') is None, reason='Go compiler required')
def test_original_control_compiles_before_invalid_generated_source(tmp_path):
    root = tmp_path/'repo'; root.mkdir()
    logs = tmp_path/'logs'
    command = 'GO111MODULE=off go test -count=1 -json ./ > "$COMBINATION_REPORT_DIR/go.jsonl"'
    control = phase(root, 'control', 'package toy\nimport "testing"\nfunc TestControl(t *testing.T) {}\n', command, 120)
    generated = phase(root, 'generated', 'package toy\nimport "testing"\nfunc TestGenerated(t *testing.T) { x:= &struct{}{}; _ = x+1 }\n', command, 120)
    results = execute_plan({'phases': [control, generated]}, root, logs)
    assert results[0]['returncode'] == 0
    assert results[1]['returncode'] != 0
    assert '"Action":"pass"' in (logs/'control/go.jsonl').read_text()
    assert (logs/'generated/result.json').exists()
    assert json.loads((logs/'control/context.json').read_text())['source_files'] == control['files']


def test_later_timeout_preserves_control_result_and_source_context(tmp_path):
    root = tmp_path/'repo'; root.mkdir(); logs = tmp_path/'logs'
    (root/'toy_test.go').write_text('candidate-before-mount')
    control = phase(root, 'control', 'whole-original', 'test "$(cat toy_test.go)" = whole-original; echo pass')
    generated = phase(root, 'generated', 'generated-only', 'test "$(cat toy_test.go)" = generated-only; sleep 30', .1)
    results = execute_plan({'phases': [control, generated]}, root, logs)
    assert results[0]['returncode'] == 0 and not results[0]['timed_out']
    assert results[1]['timed_out']
    assert (logs/'control/stdout.txt').read_text().strip() == 'pass'
    assert json.loads((logs/'control/context.json').read_text())['role'] == 'control'


def test_phase_source_hash_cannot_change(tmp_path):
    root = tmp_path/'repo'; root.mkdir()
    entry = phase(root, 'control', 'original', 'true')
    (root/entry['files'][0]['staged']).write_text('changed')
    with pytest.raises(ValueError, match='Frozen phase source'):
        execute_plan({'phases': [entry]}, root, tmp_path/'logs')
