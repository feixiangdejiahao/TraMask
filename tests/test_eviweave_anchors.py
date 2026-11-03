import subprocess

from eviweave.anchors import changed_lines, focused_names, parse_source, rank_units, target_names
import pytest


def source(path, code, identity='H:1'):
    raw = code.encode()
    return {'id': identity, 'path': path, 'raw': raw, 'parsed': parse_source(path, raw)}


@pytest.mark.parametrize(('path', 'code', 'name'), [
    ('x.py', 'def check():\n    y = x.send(1)\n    assert x.closed\n', 'send'),
    ('x.go', 'package p\nfunc check() { x.Send(1) }', 'Send'),
    ('x.rs', 'fn check() { x.send(1); }', 'send'),
    ('x.ts', 'test("sample", () => { x.send(1); expect(x.closed).toBe(true) })', 'send'),
    ('x.js', 'function check() { x.send(1) }', 'send'),
])
def test_real_parsers_return_concrete_call_span(path, code, name):
    item = source(path, code)
    assert not item['parsed']['parse_errors']
    rows = rank_units([item], [name], mode='calls')
    assert len(rows) == 1
    (start, end), = rows[0]['anchors']
    assert item['raw'][start:end].decode() == f'x.{name}(1)'


def test_state_and_embedded_language_use_the_same_broad_rule():
    item = source('x.go', 'package p\nfunc check() { run(`{x: a = 50} := {x: undefined}`); x.Closed = true }')
    assert not rank_units([item], ['Closed', 'undefined'], mode='calls')
    row, = rank_units([item], ['Closed', 'undefined'], mode='uses')
    assert row['matched']['uses'] == ['Closed']
    assert row['matched']['literals'] == ['undefined']


def test_matching_is_spelling_not_type_resolution():
    item = source('x.py', 'def check():\n    a.send(1)\n    b.send(2)\n    alias(3)\n')
    row, = rank_units([item], ['send'], mode='calls')
    assert row['matched']['calls'] == ['send']
    assert [item['raw'][start:end] for start, end in row['anchors']] == [b'a.send(1)', b'b.send(2)']
    assert rank_units([item], ['actual_api'], mode='calls') == []


def test_generic_arguments_and_dynamic_callees_are_not_api_names():
    item = source('x.rs', 'fn check() { x.send::<Value>(1); factories[0](2); }')
    assert len(rank_units([item], ['send'], mode='calls')) == 1
    assert rank_units([item], ['Value', 'factories'], mode='calls') == []
    python = source('x.py', 'getattr(x, "send")(1)\n')
    assert rank_units([python], ['send'], mode='calls') == []


def test_constructor_is_a_concrete_call_seed():
    item = source('x.ts', 'const x = new Response("body");')
    row, = rank_units([item], ['Response'], mode='calls')
    (start, end), = row['anchors']
    assert item['raw'][start:end] == b'new Response("body")'


def test_targets_are_public_syntax_not_comments_or_prose():
    code = 'def send(x):\n    # secret_donor\n    return x.closed\n'
    patch = 'diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -3 +3 @@\n-    return False\n+    return x.closed\n'
    item = source('x.py', code)
    names = target_names('Support `send()` with the desired semantics.', patch,
                         [('x.py', item['raw'], item['parsed'])])
    assert names == ['closed', 'send', 'x']
    assert changed_lines(patch) == {'x.py': {2, 3}}


def test_syntax_error_remains_a_research_outcome():
    result = parse_source('x.py', b'def check(:\n    x.send(1)\n')
    assert result['parse_errors']
    assert result['units'] == []


def test_nested_helper_keeps_enclosing_function_and_both_source_contexts():
    item = source('x.py', 'def check():\n    def chunks():\n        yield b"x"\n    x.send(chunks())\n')
    duplicate = {**item, 'id': 'H:2'}
    rows = rank_units([item, duplicate], ['send'], mode='calls')
    assert {row['source'] for row in rows} == {'H:1', 'H:2'}
    assert all(row['name'] == 'check' and row['first_line'] == 1 and row['last_line'] == 4 for row in rows)


def test_different_imports_do_not_merge_equal_function_text():
    first = source('first.py', 'from first_api import send\ndef check():\n    send(1)\n', 'H:1')
    second = source('second.py', 'from second_api import send\ndef check():\n    send(1)\n', 'H:2')
    rows = rank_units([first, second], ['send'], mode='calls')
    assert len(rows) == 2
    assert {row['source'] for row in rows} == {'H:1', 'H:2'}


def test_each_field_read_and_literal_carrier_remains_a_seed():
    item = source('x.py', 'def check():\n    a.closed\n    b.closed\n    run("closed")\n    run("closed")\n')
    row, = rank_units([item], ['closed'], mode='uses')
    assert len(row['anchors']) == 4


def test_multifile_patch_does_not_assign_next_header_to_previous_file():
    patch = ('diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-a\n+b\n'
             'diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n@@ -4 +4 @@\n-c\n+d\n')
    assert changed_lines(patch) == {'a.py': {1}, 'b.py': {3, 4}}


def test_real_git_patch_paths_increment_and_deleted_function_boundary(tmp_path):
    def git(*args):
        return subprocess.run(['git', '-C', str(tmp_path), *args], check=True, capture_output=True).stdout

    git('init', '-q')
    initial = {'with space.py': 'def first():\n    return 1\n', '中文.py': 'def second():\n    return 1\n',
               'counter.js': 'let counter = 0;\n', 'deletion.py': 'def f():\n    keep()\n    removed()\n'}
    for path, text in initial.items():
        (tmp_path / path).write_text(text)
    git('add', '.')
    git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'base')
    (tmp_path / 'with space.py').write_text('def first():\n    return 2\n')
    (tmp_path / '中文.py').write_text('def second():\n    return 2\n')
    (tmp_path / 'counter.js').write_text('let counter = 0;\n++ counter;\n')
    (tmp_path / 'deletion.py').write_text('def f():\n    keep()\n\ndef g():\n    other()\n')
    patch = git('diff', '--no-color').decode()
    changed = changed_lines(patch)
    assert set(changed) == set(initial)
    assert 2 in changed['counter.js']
    final = []
    for path in initial:
        raw = (tmp_path / path).read_bytes()
        final.append((path, raw, parse_source(path, raw)))
    assert {'first', 'second', 'f'} <= set(focused_names('', changed, final, []))


def test_javascript_each_and_modifiers_form_separate_test_units():
    item = source('x.test.ts', "describe('s',()=>{test.each([1])('a',()=>x.send()); "
                  "test.each([2])('b',()=>y.send()); it.only('c',()=>z.send())});")
    rows = rank_units([item], ['send'], mode='calls')
    assert len(rows) == 3
    contents = [item['raw'][row['start']:row['end']] for row in rows]
    assert all(text.count(b'.send()') == 1 for text in contents)
