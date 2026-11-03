"""Real-parser checks for the five pre-slice pilot interventions."""
import hashlib
from eviweave.anchors import parse_source
from eviweave.pre_slice import (source_index, query_origins, origin_conflict,
                                helper_anchors, case_ranges, covered, template_key)


def test_explicit_types_and_local_constructions_bind_members():
    raw = b'class Response: pass\nclass Logger: pass\ndef check(r: Response):\n    log = Logger()\n    r.close()\n    log.close()\n'
    index = source_index('.py', raw)
    closes = [call for call in index['calls'] if call['name'] == 'close']
    assert [call['identity'] for call in closes] == [('type', 'Response'), ('type', 'Logger')]
    assert not origin_conflict(closes[0]['identity'], {('type', 'Response')})
    assert origin_conflict(closes[1]['identity'], {('type', 'Response')})


def test_dynamic_construction_is_not_guessed_from_capitalization():
    raw = b'from library import Factory\nr = Factory()\nr.close()\n'
    call = next(call for call in source_index('.py', raw)['calls'] if call['name'] == 'close')
    assert call['identity'] is None
    assert not origin_conflict(call['identity'], {('type', 'Response')})


def test_rebound_import_does_not_keep_namespace_identity():
    raw = b'import library as lib\nlib.close()\nlib = dynamic()\nlib.close()\n'
    calls = [call for call in source_index('.py', raw)['calls'] if call['name'] == 'close']
    assert calls[0]['identity'] == ('module', 'library')
    assert calls[1]['identity'] is None


def test_go_helper_edges_reach_concrete_calls_and_case_inputs():
    raw = (b'package p\nimport "testing"\n'
           b'func expectCode(t *testing.T, code string) { vm.Run(code) }\n'
           b'func TestX(t *testing.T) { expectCode(t, `first`); expectCode(t, `second`) }\n')
    index = source_index('.go', raw)
    anchors = helper_anchors(index, {'Run'})
    assert [raw[a:b] for a, b in anchors] == [b'expectCode(t, `first`)', b'expectCode(t, `second`)']
    assert index['episodes'] == anchors
    start = raw.index(b'func TestX')
    ranges, count = case_ranges(start, len(raw) - 1, [anchors[0]], index['episodes'])
    assert count == 2
    assert covered(*anchors[0], ranges)
    assert not covered(*anchors[1], ranges)
    assert covered(start, start + len(b'func TestX'), ranges)


def test_same_file_binding_handles_go_receiver_types():
    raw = b'package p\ntype Client struct{}\nfunc (c *Client) Close() { c.Flush() }\n'
    call = next(c for c in source_index('.go', raw)['calls'] if c['name'] == 'Flush')
    assert call['identity'] == ('type', 'Client')


def test_js_case_scopes_keep_common_setup_but_not_unselected_test():
    raw = b'const fixture = 1; test("a", () => send(fixture)); test("b", () => other(fixture));'
    index = source_index('.ts', raw)
    anchor = next((c['start'], c['end']) for c in index['calls'] if c['name'] == 'send')
    ranges, count = case_ranges(0, len(raw), [anchor], index['episodes'])
    assert count == 2
    assert covered(0, len(b'const fixture = 1;'), ranges)
    assert covered(*anchor, ranges)
    second = next((c['start'], c['end']) for c in index['calls'] if c['name'] == 'other')
    assert not covered(*second, ranges)


def test_template_identity_includes_full_file_version_and_path():
    first, second = (hashlib.sha256(raw).hexdigest() for raw in (b'one', b'two'))
    assert template_key('/app/test.py', first, [[0, 3]]) == template_key('test.py', first, [[0, 3]])
    assert template_key('test.py', first, [[0, 3]]) != template_key('test.py', second, [[0, 3]])
    assert template_key('test.py', first, [[0, 3]]) != template_key('other.py', first, [[0, 3]])


def test_source_syntax_failure_is_a_recorded_unknown():
    assert source_index('.py', b'def broken(')['status'] == 'source_parse_error'


def test_go_table_input_and_consumer_are_kept_together():
    raw = (b'package p\nimport "testing"\nfunc TestX(t *testing.T) { '
           b'cases := []struct{code string; want int}{ {`first`,1}, {`second`,2} }; '
           b'for _, tc := range cases { t.Run(tc.code, func(t *testing.T){ run(tc.code) }) } }')
    index = source_index('.go', raw)
    table, = index['tables']
    first, second = table['rows']
    start = raw.index(b'func TestX')
    ranges, _ = case_ranges(start, len(raw), [first], index['episodes'], index['tables'])
    assert covered(*first, ranges)
    assert not covered(*second, ranges)
    consumer = next((c['start'], c['end']) for c in index['calls'] if c['name'] == 'run')
    assert covered(*consumer, ranges)
    ranges, _ = case_ranges(start, len(raw), [consumer], index['episodes'], index['tables'])
    assert covered(*first, ranges) and covered(*second, ranges)


def test_query_origins_expand_modified_receiver_members():
    raw = b'class Response:\n    def close(self):\n        self.flush()\n    def flush(self): pass\n'
    source = {'id': 'one', 'path': 'api.py', 'kind': 'final_workspace', 'raw': raw,
              'parsed': parse_source('api.py', raw)}
    index = source_index('.py', raw)
    origins = query_origins('', {'api.py': {3}}, [source], [source], {'one': index})
    assert origins['close'] == {('type', 'Response')}
    assert origins['flush'] == {('type', 'Response')}
