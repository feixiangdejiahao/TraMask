import shutil
import subprocess
import pytest

from prototypes.test_action_and_oracle_transfer.go_slice_bindings import normalize_body

@pytest.mark.parametrize('body', [
    '{x := 1; _ = x}',
    '{x, y := 1, 2; _ = x}',
    '{x, y := 1, 2; _ = x; _ = y}',
    '{var (\nx = 1\ny = 2\n); _ = x}',
    '{x := 1; { x := 2; _ = x }; _ = x}',
    '{变量 := "值"; _ = 变量}',
])
def test_idempotence_and_syntax(body):
    normalized = normalize_body(body)
    assert normalize_body(normalized) == normalized
    from anchor_retrieval.syntax import Source
    assert not Source('slice.go', 'package x\nfunc f() '+normalized, 'go').root.has_error

@pytest.mark.skipif(shutil.which('go') is None, reason='Go unavailable')
def test_actual_compiler_preserves_initialization_order_shadowing_and_captures(tmp_path):
    body = '''{
    events := []int{}
    call := func(x int) (int, error) { events = append(events, x); return x, nil }
    x, err := call(1)
    {
        x, err := call(2)
        capture := func() int { return x }
        if capture() != 2 { t.Fatal("capture") }
    }
    var (
        y, otherErr = call(3)
        message string
    )
    if !reflect.DeepEqual(events, []int{1, 2, 3}) { t.Fatal(events) }
}'''
    text = 'package toy\nimport ("testing"; "reflect")\nfunc TestPrefix(t *testing.T) '+normalize_body(body)
    source = tmp_path / 'slice_test.go'
    source.write_text(text)
    result = subprocess.run(['go', 'test', str(source)], capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr

def test_invalid_input_stays_unchanged():
    body = '{ x := '
    assert normalize_body(body) == body
