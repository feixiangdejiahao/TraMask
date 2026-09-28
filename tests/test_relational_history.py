from anchor_retrieval.syntax import Source
from relational_gap.history import recover_history, namespace_go_validation


def trajectory(*commands):
    return {'steps': [{'step_id': n, 'tool_calls': [{'arguments': {'command': text}}]}
                      for n, text in enumerate(commands)]}


def test_append_retains_original_imports_and_tests_without_running_shell():
    data = trajectory("cat > sample_test.go <<'EOF'\npackage p\nfunc TestOne(t *testing.T) {}\nEOF",
                      "cat >> sample_test.go <<'EOF'\nfunc TestTwo(t *testing.T) {}\nEOF")
    versions, report = recover_history(data, 'go')
    assert len(versions) == 2
    assert 'package p' in versions[1].code
    assert 'TestOne' in versions[1].code and 'TestTwo' in versions[1].code
    assert report['versions'][1]['recovery'] == 'literal_heredoc_append'


def test_overwrites_preserve_both_historical_bodies():
    versions, _ = recover_history(trajectory(
        "cat > test_x.py <<'EOF'\ndef test_x(): assert 1\nEOF",
        "cat > test_x.py <<'EOF'\ndef test_x(): assert 2\nEOF"), 'python')
    assert len(versions) == 2
    assert versions[0].code != versions[1].code


def test_restricted_python_file_write_and_replace_are_recovered_statically():
    versions, _ = recover_history(trajectory(
        "python - <<'EOF'\nfrom pathlib import Path\np = Path('test_x.py')\np.write_text('def test_x(): assert 1\\n')\nEOF",
        "python - <<'EOF'\np = 'test_x.py'\ns = open(p).read()\ns = s.replace('assert 1', 'assert 2')\nopen(p, 'w').write(s)\nEOF"), 'python')
    files = [s for s in versions if s.written_path == 'test_x.py']
    assert len(files) == 2
    assert files[1].code == 'def test_x(): assert 2\n'


def test_unknown_reads_do_not_use_final_candidate_as_historical_source():
    versions, report = recover_history(trajectory(
        "cat >> unknown_test.go <<'EOF'\nfunc TestLater(t *testing.T) {}\nEOF"), 'go')
    assert not versions
    assert report['skipped']['append_without_recovered_base'] == 1


def test_go_namespace_preserves_strings_and_field_names():
    source = Source('sample_test.go', '''package p
func helper(x int) int { return x }
func TestSample(t *testing.T) { got := helper(1); _ = "helper"; _ = got; _ = x.helper }
''', 'go', 'trajectory')
    result, names = namespace_go_validation(source, 'abc')
    assert names == ['TestSample', 'helper']
    assert 'helper_rh_abc(1)' in result.code
    assert '"helper"' in result.code and 'x.helper' in result.code
    assert 'TestSample_rh_abc' in result.code
