"""Structural admission only: accepted oracle values need not be correct."""
import pytest

from prototypes.assertion_operand_guard import valid_assertion


@pytest.mark.parametrize("old, observed, new", [
    ("assert result == 0, report", "result", "assert result != 0, report"),
    ("assert 'x' in names", "names", "assert 'y' in names"),
    ("assert value == expected", "value", "assert value == {'items': [1, None, -2]}"),
    ("assert values == (1, 2)", "values", "assert values == (3, 4)"),
    ("assert x == expected[0]", "x", "assert (x) != expected[0]"),
    ("assert read() == 1, read()", "read()", "assert read() == 2, read()"),
    ("assert result is None", "result", "assert result == 300"),
    ("assert result is not None", "result", "assert result != 'ready'"),
    ("assert result == 300", "result", "assert result is None"),
])
def test_python_supported_expected_revisions(old, observed, new):
    assert valid_assertion(new, old, observed, "python")


@pytest.mark.parametrize("new", [
    "assert True or read() == 1", "assert read() == 1 or True",
    "assert read() == items.pop()", "assert read() == read()",
    "assert read() == [read()]", "assert 2 == read()",
    "assert (read(), read())[0] == 2", "assert read() == 2, 'new message'",
    "assert read() is 2", "assert read() in [1, 2]",
    "assert read() == 1 == 2", "assert read() == object.attribute",
    "assert read() == set()",
    "assert read() == wanted", "assert read() == [item for item in rows]",
    "assert read() == (item := 2)", "assert read() == 2\nclear()",
])
def test_python_cannot_skip_move_duplicate_or_add_operations(new):
    assert not valid_assertion(new, "assert read() == 1", "read()", "python")


@pytest.mark.parametrize("old", ["assert x == consume()", "assert x == expected.property", "assert x == set()"])
def test_unknown_existing_expected_operation_cannot_be_removed(old):
    assert valid_assertion(old, old, "x", "python")
    assert not valid_assertion("assert x == 1", old, "x", "python")


def test_structural_admission_does_not_prove_oracle_strength():
    # x != None admits many more values than x == 3 for ordinary ints/None.
    # This guard checks operation boundaries, not the intended issue contract.
    assert valid_assertion("assert x != None", "assert x == 3", "x", "python")


@pytest.mark.parametrize('value', ["'ready'", '300', '[1]', '(1, 2)', '{}'])
def test_new_identity_literal_is_not_a_value_oracle(value):
    assert not valid_assertion('assert value is '+value, 'assert value is None', 'value', 'python')
    assert not valid_assertion('assert value is not '+value, 'assert value is None', 'value', 'python')


def test_existing_object_reference_can_keep_identity_without_copying_its_value():
    assert valid_assertion('assert value is expected', 'assert value is expected', 'value', 'python')
    assert not valid_assertion('assert value is [1]', 'assert value is expected', 'value', 'python')


@pytest.mark.parametrize("old, observed, new", [
    ("expect(parse(schema, input)).toStrictEqual(input)", "parse(schema, input)",
     "expect(parse(schema, input)).toStrictEqual({value: 1, children: [{value: 1, children: []}]})"),
    ("expect(read(), 'message').not.toEqual(input)", "read()",
     "expect(read(), 'message').not.toEqual([1, -2, null, true])"),
    ("expect(read()).toBe(expected)", "read()", "expect(read()).toBe('雪  花')"),
])
def test_typescript_fixes_expect_call_matcher_and_message(old, observed, new):
    assert valid_assertion(new, old, observed, "typescript")


@pytest.mark.parametrize("new", [
    "expect(true || read()).toBe(true)", "expect(read()).toBe(reset())",
    "expect(read()).toBe(read())", "expect(read()).toBe({value: read()})",
    "expect(read()).toEqual(1)", "expect(read()).not.toBe(1)",
    "expect(read()).resolves.toBe(1)", "expect(read(), 'new message').toBe(1)",
    "expect((reset(), read())).toBe(1)", "expect([read(), read()]).toBe(1)",
    "expect(read()).toBe({...input})", "expect(read()).toBe({get x() { return reset(); }})",
    "expect(read()).toBe({[key()]: 1})", "expect(read()).toBe(`${reset()}`)",
    "expect(read()).toBe(2); reset()", "expect(read()).toBe(other)",
    "expect(read()).toBe(new Box())", "expect(read()).toBe(input.value)",
])
def test_typescript_rejects_changed_observer_and_effectful_expectations(new):
    assert not valid_assertion(new, "expect(read()).toBe(1)", "read()", "typescript")


def test_typescript_preserves_existing_message_contents_not_just_whitespace():
    old = "expect(read(), 'a b').toEqual(input)"
    assert not valid_assertion("expect(read(), 'ab').toEqual([1])", old, "read()", "typescript")
    assert not valid_assertion("expect(read()).toBe(2)", "expect(read()).toBe(reset())", "read()", "typescript")


@pytest.mark.parametrize("old, observed, new", [
    ('if got != want { t.Errorf("wrong %s", got) }', "got",
     'if got != "new value" { t.Errorf("wrong %s", got) }'),
    ('if want == got { t.Fatal("wrong") }', "got", 'if -2 == got { t.Fatal("wrong") }'),
    ("require.Equal(t, int64(103), result.Value)", "result.Value",
     "require.Equal(t, int64(5004), result.Value)"),
    ('assert.Equal(t, want, result, "msg", detail)', "result",
     'assert.Equal(t, true, result, "msg", detail)'),
])
def test_go_preserves_api_actual_operand_and_failure_body(old, observed, new):
    assert valid_assertion(new, old, observed, "go")


@pytest.mark.parametrize("new", [
    'if got == "x" { t.Errorf("wrong %s", got) }',
    'if "x" != got { t.Errorf("wrong %s", got) }',
    'if got != "x" { t.Errorf("other %s", got) }',
    'if got != reset() { t.Errorf("wrong %s", got) }',
    'if got != got { t.Errorf("wrong %s", got) }',
    'if x := reset(); got != "x" { t.Errorf("wrong %s", got) }',
    'if got != "x" { t.Errorf("wrong %s", got) } else { reset() }',
    'if true || got != "x" { t.Errorf("wrong %s", got) }',
])
def test_go_guard_only_allows_expected_operand_change(new):
    old = 'if got != want { t.Errorf("wrong %s", got) }'
    assert not valid_assertion(new, old, "got", "go")


@pytest.mark.parametrize("new", [
    "require.NotEqual(t, int64(2), result.Value)",
    "require.Equal(t, reset(), result.Value)",
    "require.Equal(t, int64(reset()), result.Value)",
    "require.Equal(t, int32(2), result.Value)",
    "require.Equal(t, result.Value, result.Value)",
    "require.Equal(t, int64(2), result.Value, reset())",
    "require.Equal(t, int64(2), result.Other)",
])
def test_go_call_cannot_change_actual_api_or_add_calls(new):
    assert not valid_assertion(new, "require.Equal(t, int64(1), result.Value)", "result.Value", "go")


def test_go_cannot_introduce_or_remove_a_conversion_shaped_call():
    assert not valid_assertion("require.Equal(t, int64(2), x)", "require.Equal(t, 1, x)", "x", "go")
    assert not valid_assertion("require.Equal(t, 2, x)", "require.Equal(t, int64(1), x)", "x", "go")


@pytest.mark.parametrize("code, old, observed, language", [
    ("assert x", "assert x", "x", "python"),
    ("assert x == x", "assert x == x", "x", "python"),
    ("assert x == 1", "assert x == 1", "", "python"),
    ("assert x == 1", "assert x == 1", "x", "unknown"),
    ("assert x == 1", "assert x == 1", "x; clear()", "python"),
    ("expect(x).toEqual(1)", "expect(x).toEqual(1)", "x; clear()", "typescript"),
    ("require.Equal(t, 1, x)", "require.Equal(t, 1, x)", "x\nvar y = reset()", "go"),
    (None, "assert x == 1", "x", "python"),
    ("assert x == '\ud800'", "assert x == 1", "x", "python"),
])
def test_unsupported_or_malformed_forms_are_rejected(code, old, observed, language):
    assert not valid_assertion(code, old, observed, language)


# A frozen structural compatibility snapshot of all 17 cached revisions follows.
# Values are deliberately not labelled semantically correct: some old hypotheses
# were wrong. Keeping these examples only demonstrates admission of the existing
# observation-preserving edit forms, independent of experiment artifact paths.

CACHED_REVISIONS = [('oracle_0670f8742497a26ac96bd0ad',
  'python',
  [('assert k.modifiers == ("alt", "ctrl")', 'k.modifiers', 'assert k.modifiers == ("ctrl",)')]),
 ('oracle_b120d29823b07f6c10e4992b',
  'python',
  [('assert k_repeat.is_press is False', 'k_repeat.is_press', 'assert k_repeat.is_press is True'),
   ('assert k_repeat.is_repeat is True', 'k_repeat.is_repeat', 'assert k_repeat.is_repeat is False')]),
 ('oracle_632f942f01535264a24e9da1',
  'python',
  [('assert k.phase == "press"', 'k.phase', 'assert k.phase == "repeat"'),
   ('assert k.is_press is True', 'k.is_press', 'assert k.is_press is False'),
   ('assert k.is_repeat is False', 'k.is_repeat', 'assert k.is_repeat is True')]),
 ('oracle_5e8638e34368b31cdee3fee3',
  'python',
  [('assert k.modifiers == ("alt", "ctrl", "shift")',
    'k.modifiers',
    'assert k.modifiers == ("alt", "shift")'),
   ('assert k.ctrl is True', 'k.ctrl', 'assert k.ctrl is False')]),
 ('oracle_bc2766f58bcbb050a2645e16',
  'python',
  [('assert k.modifiers == ("alt", "ctrl")', 'k.modifiers', 'assert k.modifiers == ("alt", "shift")')]),
 ('oracle_cb90facfc55b15f010e47913',
  'python',
  [('assert logs.count("test_2_extra") == 2',
    'logs.count("test_2_extra")',
    'assert logs.count("test_2_extra") == 1')]),
 ('oracle_ab5730c8d2b8f1be16db6100',
  'python',
  [('assert k.modifiers == ("alt", "ctrl", "shift")',
    'k.modifiers',
    'assert k.modifiers == ("alt", "ctrl")')]),
 ('oracle_4be3957f8a93b8d277a32f8e',
  'python',
  [('assert event.key == "a"', 'event.key', 'assert event.key == "end"')]),
 ('oracle_cf76f67365867f0da6f4aa17',
  'python',
  [('assert "ctrl+plus" in k.aliases', 'k.aliases', 'assert "alt+ctrl+plus" in k.aliases')]),
 ('oracle_6abdbbd7911f88769a4e2ea9',
  'python',
  [('assert r.exit_code == 0, r.output', 'r.exit_code', 'assert r.exit_code != 0, r.output'),
   ('assert Database(p)["t"].rows[0]["name"] == "X"',
    'Database(p)["t"].rows[0]["name"]',
    'assert Database(p)["t"].rows[0]["name"] == "one"')]),
 ('oracle_e8d18e7c76530e50646ba77f',
  'python',
  [('assert r.exit_code == 0, r.output', 'r.exit_code', 'assert r.exit_code != 0, r.output'),
   ('assert r.exit_code != 0', 'r.exit_code', 'assert r.exit_code == 0'),
   ('assert list(Database(p)["t"].rows)[0]["name"] == "X"',
    'list(Database(p)["t"].rows)[0]["name"]',
    'assert list(Database(p)["t"].rows)[0]["name"] == "two"')]),
 ('oracle_f14ccf47ae05af75897c1047',
  'python',
  [('assert r.exit_code == 0, r.output', 'r.exit_code', 'assert r.exit_code != 0, r.output'),
   ('assert r.exit_code != 0', 'r.exit_code', 'assert r.exit_code == 0')]),
 ('oracle_bc29d4c79067c2735def0f46',
  'python',
  [('assert r.exit_code == 0, r.output', 'r.exit_code', 'assert r.exit_code != 0, r.output'),
   ('assert r.exit_code != 0', 'r.exit_code', 'assert r.exit_code == 0'),
   ('assert Database(p)["t"].rows[0]["name"] == "X"',
    'Database(p)["t"].rows[0]["name"]',
    'assert Database(p)["t"].rows[0]["name"] == "two"')]),
 ('oracle_b3ad1954abd9e3ff05dc18d0',
  'python',
  [('assert r.exit_code == 0, r.output', 'r.exit_code', 'assert r.exit_code != 0, r.output'),
   ('assert list(Database(p)["t"].rows)[0]["name"] == "X"',
    'list(Database(p)["t"].rows)[0]["name"]',
    'assert list(Database(p)["t"].rows)[0]["name"] == "one"')]),
 ('oracle_f8d47b6544fb9f8e8130e95e',
  'go',
  [('if got != want {\n\t\tt.Errorf("Output.Truncate() with default preserve = %q, want %q", got, want)\n\t}',
    'got',
    'if got != "\\x1b[1mfoo\\x1b[0m\\x1b[1mbar\\x1b[0m" {\n'
    '\tt.Errorf("Output.Truncate() with default preserve = %q, want %q", got, want)\n'
    '}')]),
 ('oracle_66628a829ffed4a2e7a01eae',
  'go',
  [('require.Equal(t, int64(103), r.(*tengo.Int).Value)',
    'r.(*tengo.Int).Value',
    'require.Equal(t, int64(5004), r.(*tengo.Int).Value)')]),
 ('oracle_ebb135944d952ba191c86d90',
  'typescript',
  [('expect(parse(TreeSchema, input)).toStrictEqual(input)',
    'parse(TreeSchema, input)',
    'expect(parse(TreeSchema, input)).toStrictEqual({ value: 1, children: [{ value: 1, children: [] }, { '
    'value: 1, children: [{ value: 1, children: [] }] }] })')])]

@pytest.mark.parametrize("identifier, language, edits", CACHED_REVISIONS, ids=[r[0] for r in CACHED_REVISIONS])
def test_all_17_cached_revisions_keep_their_structural_edit_forms(identifier, language, edits):
    for old, observed, new in edits:
        assert valid_assertion(new, old, observed, language), (identifier, old, new)
