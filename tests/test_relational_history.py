from anchor_retrieval.syntax import Source
from relational_gap.history import recover_history, namespace_go_validation, go_duplicate_declarations


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


def test_python_editor_containing_vitest_is_not_misparsed_as_typescript():
    data = trajectory("python3 - <<'PY'\nfrom pathlib import Path\np = Path('small.test.ts')\np.write_text('import {test} from \"vitest\"; test(\"x\", () => {});')\nPY")
    versions, _ = recover_history(data, 'typescript')
    assert len(versions) == 1
    assert versions[0].language == 'typescript'
    assert versions[0].written_path == 'small.test.ts'
    assert versions[0].code.startswith('import {test}')


def test_go_namespace_never_turns_blank_identifier_into_a_binding():
    source = Source('sample_test.go', '''package p
var _ = helper
func helper(x int) int { return x }
func TestSample(t *testing.T) { _, err := load(); _ = err; _, err = load() }
''', 'go', 'trajectory')
    result, names = namespace_go_validation(source, 'abc')
    assert '_' not in names
    assert 'var _ = helper_rh_abc' in result.code
    assert '_, err := load()' in result.code
    assert '_, err = load()' in result.code
    assert '__rh_' not in result.code


def test_unknown_old_source_edit_assertion_is_not_a_runtime_test():
    data = trajectory("python3 - <<'PY'\np = 'production.py'\ns = open(p).read()\nassert 'old' in s\ns = s.replace('old', 'new')\nopen(p, 'w').write(s)\nPY")
    versions, report = recover_history(data, 'python')
    assert not versions
    assert report['skipped']['source_edit_script_not_runtime_validation'] == 1


def test_go_duplicate_check_distinguishes_legal_scopes_and_discarded_names():
    source = Source('sample_test.go', '''package p
var _, _ = 1, 2
func init() {}
func init() {}
func (a A) Read() {}
func (b B) Read() {}
func TestOne(t *testing.T) {}
func TestOne(t *testing.T) {}
var a, b = 1, 2
const b = 3
''', 'go')
    assert go_duplicate_declarations(source) == ['TestOne', 'b']


def test_go_namespace_renames_all_names_of_multiple_declarations():
    source = Source('sample_test.go', 'package p\nvar a, b = 1, 2\n', 'go')
    result, names = namespace_go_validation(source, 'abc')
    assert names == ['a', 'b']
    assert 'var a_rh_abc, b_rh_abc = 1, 2' in result.code


def test_context_managed_source_editor_is_not_a_validation():
    data = trajectory("python - <<'PY'\npath = 'subject.py'\nwith open(path) as f:\n    old = f.read()\nassert 'old' in old\nnew = old.replace('old', 'new')\nwith open(path, 'w') as f:\n    f.write(new)\nprint('edited')\nPY")
    versions, report = recover_history(data, 'python')
    assert not versions
    assert report['skipped']['source_edit_script_not_runtime_validation'] == 1


def test_context_managed_edit_recovers_only_previously_known_bytes():
    data = trajectory(
        "cat > test_example.py <<'EOF'\ndef test_example(): assert 1\nEOF",
        "python - <<'PY'\npath = 'test_example.py'\nwith open(path) as f:\n    old = f.read()\nnew = old.replace('assert 1', 'assert 2')\nwith open(path, 'w') as f:\n    f.write(new)\nPY")
    versions, report = recover_history(data, 'python')
    assert len(versions) == 2
    assert versions[-1].code == 'def test_example(): assert 2\n'
    assert report['versions'][-1]['recovery'] == 'restricted_python_literal_file_edit'


def test_unknown_rebinding_does_not_reuse_stale_literal_file_contents():
    data = trajectory("python - <<'PY'\ns = 'def test_x(): assert 1'\ns = unknown()\nopen('test_x.py', 'w').write(s)\nPY")
    versions, _ = recover_history(data, 'python')
    assert not versions


def test_unexecuted_helper_write_is_not_itself_a_source_editor():
    data = trajectory("python - <<'PY'\np = 'generated.py'\ndef write_later():\n    open(p, 'w').write('x')\nassert 2 + 2 == 4\nPY")
    versions, _ = recover_history(data, 'python')
    assert len(versions) == 1
