"""Source-grounded edits preserve original checks and executable syntax."""
import json
import shutil
import subprocess

import pytest

from eviweave.anchors import _parser
from eviweave.behavior import BehaviorIndex
from eviweave.evidence import SourceGraph
from eviweave.local_edits import LocalEditIndex, apply_edits


def source(code):
    graph = SourceGraph({'id': 'public', 'path': 'example.ts', 'raw': code.encode()})
    assert not graph.issues
    return graph, BehaviorIndex(graph)


def span(code, needle):
    start = code.encode().index(needle.encode())
    return [start, start+len(needle.encode())]


def test_same_receiver_setup_deletion_and_argument_omission_enumerate_joint_plan():
    code = '''function donor(box) { box.register({ a: make(), b: make() }); box.start(); }
function base() { const box = create(); box.register({ a: make(), b: make(), c: make() }); box.start({ limit: 2 }); expect(count).toBe(2); }
'''
    graph, behavior = source(code)
    plans = LocalEditIndex({'public': (graph, behavior)}).deletion_plans('public', span(code, 'box.start({ limit: 2 })'))
    assert len(plans['recipes']) == 2
    assert plans['total_candidates'] == 3
    rendered = [apply_edits(graph.raw, c['edits']).decode() for c in plans['candidates']]
    assert any('box.register({ a: make(), b: make() }); box.start()' in text for text in rendered)
    assert all(text.count('expect(count).toBe(2)') == 1 for text in rendered)
    assert all(not _parser('.ts').parse(text.encode()).root_node.has_error for text in rendered)


@pytest.mark.parametrize('donor,expected', [
    ('{ b: 2, c: 3 }', '{ b: 2, c: 3 }'),
    ('{ a: 1, c: 3 }', '{ a: 1, c: 3 }'),
    ('{ a: 1, b: 2 }', '{ a: 1, b: 2 }'),
    ('{}', '{}'),
])
def test_object_deletion_keeps_separators_valid(donor, expected):
    code = f'function donor(x) {{ x.register({donor}); }}\nfunction base() {{ const x=create(); x.register({{ a: 1, b: 2, c: 3 }}); x.start(); }}'
    graph, behavior = source(code)
    plans = LocalEditIndex({'public': (graph, behavior)}).deletion_plans('public', span(code, 'x.start()'))
    assert plans['total_candidates'] == 1
    changed = apply_edits(graph.raw, plans['candidates'][0]['edits'])
    assert b'x.register('+expected.encode()+b')' in changed
    assert not _parser('.ts').parse(changed).root_node.has_error


def test_rebound_receiver_does_not_transfer_unrelated_setup():
    code = 'function donor(x) { x.register({ a: 1 }); } function base() { let x=create(); x.register({ a: 1, b: 2 }); x=create(); x.start(); }'
    graph, behavior = source(code)
    plans = LocalEditIndex({'public': (graph, behavior)}).deletion_plans('public', span(code, 'x.start()'))
    assert plans['total_candidates'] == 0


def test_closed_primitive_objects_produce_separate_literals_in_same_scope_only():
    code = '''const primitive = { n: 3 };
const open = { n: external };
const nested = { n: { x: 1 } };
function other() { const value={flag: true}; }
function base() { const before={flag: true}; const after={flag: true}; expect(compare(before,after)).toBe(true); }
'''
    graph, behavior = source(code)
    entry = span(code, 'const before={flag: true}')
    pair = span(code[entry[0]:], 'flag: true')
    pair = [v+entry[0] for v in pair]
    plans = LocalEditIndex({'public': (graph, behavior)}).fresh_object_plans('public', pair)
    chosen = next(c for c in plans['candidates'] if c['edits'][0]['replacement'] == '{ n: 3 }')
    changed = apply_edits(graph.raw, chosen['edits']).decode()
    assert 'function other() { const value={flag: true}; }' in changed
    assert 'const before={flag: { n: 3 }}; const after={flag: { n: 3 }}' in changed
    assert 'expect(compare(before,after)).toBe(true)' in changed
    assert not any(c['edits'][0]['replacement'] in {'{ n: external }', '{ n: { x: 1 } }'} for c in plans['candidates'])
    executable = shutil.which('node')
    if executable is None:
        pytest.skip('Node runtime unavailable for allocation-identity check')
    result = subprocess.run([executable, '-e', 'const before={flag:{n:3}}; const after={flag:{n:3}}; console.log(JSON.stringify([before.flag!==after.flag,before.flag.n===after.flag.n]));'],
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == [True, True]


def test_deletion_that_would_remove_an_original_check_is_not_emitted():
    code = 'function donor(x) { x.register({ a: 1 }); } function base() { const x=create(); x.register({ a: 1, b: expect(2).toBe(2) }); x.start(); }'
    graph, behavior = source(code)
    plans = LocalEditIndex({'public': (graph, behavior)}).deletion_plans('public', span(code, 'x.start()'))
    assert plans['total_candidates'] == 0


def test_edit_application_requires_original_version_and_disjoint_ranges():
    edit = {'range': [1, 2], 'before': 'b', 'replacement': 'x'}
    assert apply_edits(b'abc', [edit]) == b'axc'
    with pytest.raises(ValueError, match='source version'):
        apply_edits(b'adc', [edit])
    with pytest.raises(ValueError, match='Overlapping'):
        apply_edits(b'abc', [edit, edit])


def test_explicit_projection_retains_imports_and_complete_original_target():
    from scripts.pilot_alignment_edits import project_named_test
    code = b'''import {it, expect} from "vitest";
import {compare} from "../src";
const unrelated = invalidSetup();
describe("suite", () => {
it("target", () => { const a={x:1}; expect(compare(a,a)).toBe(true); });
});
'''
    projected, record = project_named_test(code, 'check.test.ts', 'suite > target')
    assert b'import {compare} from "../src";' in projected
    assert b'it("target", () => { const a={x:1}; expect(compare(a,a)).toBe(true); })' in projected
    assert b'invalidSetup' not in projected
    assert record['entire_target_registration_retained']
    assert record['unresolved_free_names'] == []


@pytest.mark.parametrize('setup,body,message', [
    ('const shared=setup();', 'expect(shared).toBe(1)', 'free names'),
    ('beforeEach(() => reset());', 'expect(1).toBe(1)', 'fixture hooks'),
])
def test_projection_rejects_missing_setup_or_hooks(setup, body, message):
    from scripts.pilot_alignment_edits import project_named_test
    code = f'describe("suite", () => {{ {setup} it("target", () => {{ {body}; }}); }});'.encode()
    with pytest.raises(ValueError, match=message):
        project_named_test(code, 'check.test.ts', 'suite > target')
