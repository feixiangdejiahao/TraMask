"""Real syntax and small execution examples for the research slicing model."""
from eviweave.evidence import SourceGraph


def test_deep_javascript_chain_uses_iterative_syntax_walks():
    from eviweave.anchors import parse_source
    from eviweave.test_units import discover
    from eviweave.pre_slice import source_index
    code="const seed = {step(){return this;}};\nconst value = seed"+'.step()'*1400+";\nit('deep',()=>{expect(value).toBe(seed);});\n"
    raw=code.encode();units=discover('deep.test.ts',raw)
    assert units['status']=='parsed' and units['units'][0]['name']=='deep'
    parsed=parse_source('deep.test.ts',raw)
    assert not parsed['parse_errors']
    index=source_index('.ts',raw)
    assert index['calls']
    graph=SourceGraph({'id':'deep','path':'deep.test.ts','raw':raw})
    a=raw.index(b'toBe(seed)');criterion=graph.criterion(a,a+len(b'toBe(seed)'))
    view=graph.slice(criterion['node'])
    assert any(b'const value' in raw[a:b] for a,b in view['ranges'])


def sliced(code, needle, path='test.py', **flags):
    raw = code.encode()
    graph = SourceGraph({'id':'source','path':path,'raw':raw})
    a = raw.index(needle.encode())
    criterion = graph.criterion(a,a+len(needle.encode()))
    result = graph.slice(criterion['node'],**flags)
    text = '\n'.join(raw[a:b].decode() for a,b in result['ranges'])
    return graph,result,text


def test_object_binding_guard_observation_and_interference():
    code = '''def check(flag, expected):
    broker = Broker()
    q = Queue()
    noise = Logger()
    if flag:
        broker.bind(q)
    broker.send(3)
    q.clear()
    assert q.empty() == expected
    noise.flush()
'''
    graph,result,text = sliced(code,'broker.send(3)')
    for part in ['broker = Broker()', 'q = Queue()', 'if flag:', 'broker.bind(q)',
                 'q.clear()', 'assert q.empty() == expected']:
        assert part in text
    assert 'noise' not in text
    assert result['observations']
    _,_,without_state = sliced(code,'broker.send(3)',state=False)
    assert 'q.clear()' not in without_state


def test_expected_computation_and_call_contexts():
    code = '''def expected(x):
    return x + 1
def one(a):
    r = run(a)
    assert r == expected(a)
def other():
    z = expected(999)
    print(z)
'''
    graph,result,text = sliced(code,'run(a)')
    assert 'return x + 1' in text
    assert 'expected(999)' not in text
    assert result['bindings'] and all(kind=='direct' for _,_,kind in result['bindings'])


def test_class_attribute_binding_does_not_use_other_class_definition():
    code = '''class A:
    ENABLED = {1, 2}
    def check(self):
        result = run(self.ENABLED)
        assert result
class B:
    ENABLED = {7, 8}
'''
    _,_,text = sliced(code,'run(self.ENABLED)')
    assert 'ENABLED = {1, 2}' in text
    assert '{7, 8}' not in text


def test_import_alias_and_namespace_state_order():
    code = '''import datetime as dt_mod
def check(value):
    ns = dict(vars(dt_mod))
    ns.update(extra)
    r = eval(value, ns)
    assert r is not None
'''
    _,_,text = sliced(code,'eval(value, ns)')
    assert 'import datetime as dt_mod' in text
    assert 'ns = dict(vars(dt_mod))' in text and 'ns.update(extra)' in text


def test_exception_observation_is_connected_to_throwing_call():
    code = '''def check():
    r = Response()
    try:
        r.consume()
    except Error:
        assert r.closed
'''
    _,result,text = sliced(code,'r.consume()')
    assert 'except Error:' in text
    assert 'assert r.closed' in text
    assert result['observations']


def test_callback_body_is_not_included_just_by_registration_text_span():
    code = '''test('one', () => { const r = run(1); expect(r).toBe(2) });
test('two', () => { const z = unrelated(999); expect(z).toBe(999) });'''
    _,_,text = sliced(code,'run(1)','test.ts')
    assert 'expect(r).toBe(2)' in text
    assert 'unrelated(999)' not in text and 'expect(z)' not in text


def test_callback_contract_assertion_and_return_are_restored():
    code = '''def check():
    def factory(value):
        assert value == 7
        return Success('ok')
    result = Failure(7).lash(factory)
    assert result == Success('ok')
'''
    _,_,text = sliced(code,'Failure(7).lash(factory)')
    assert 'assert value == 7' in text
    assert "return Success('ok')" in text


def test_go_table_and_opaque_program_input():
    code = '''package p
import "testing"
func expectRun(t *testing.T, code string, want int) { got := run(code); if got != want { t.Fatal(got) } }
func TestX(t *testing.T) { expectRun(t, `a := 1; out = a`, 1); expectRun(t, `out = 2`, 2) }
'''
    _,_,text = sliced(code,'expectRun(t, `a := 1; out = a`, 1)','test_test.go')
    assert '`a := 1; out = a`' in text
    assert 'got := run(code)' in text
    assert '`out = 2`' not in text


def test_loop_dependencies_and_rust_macro_observation():
    code = '''#[test]
fn check() {
    let mut r = Client::new();
    for i in 0..3 { r.send(i); }
    assert_eq!(r.closed(), true);
}
'''
    _,result,text = sliced(code,'r.send(i)','test.rs')
    assert 'for i in 0..3' in text
    assert 'assert_eq!' in text
    assert result['observations']


def test_syntax_error_is_an_explicit_research_issue():
    graph = SourceGraph({'id':'bad','path':'test.py','raw':b'def broken('})
    assert graph.nodes == [] and graph.issues == [{'kind':'source_parse_error','source':'bad'}]


def test_formal_parameters_are_not_confused_with_callback_definitions():
    code = 'def helper(x):\n    return x + 1\ndef run(value):\n    return helper(value)\n'
    graph,_,_ = sliced(code,'helper(value)')
    run_scope=next(s['id'] for s in graph.scopes if s['name']=='run')
    call=next(n for n in graph.nodes if any(name=='helper' for name,_,_ in n['calls']))
    assert run_scope not in graph.callees[call['id']]


def test_generator_body_connects_to_its_consuming_call():
    code='''def check(body):
    def chunks():
        for i in range(0,len(body),3):
            yield body[i:i+3]
    response = Response(stream=chunks())
    list(response.consume())
    assert response.closed
'''
    _,_,text=sliced(code,'response.consume()')
    assert 'yield body[i:i+3]' in text and 'for i in range' in text


def test_signature_without_body_is_a_declaration_not_recursive_parsing():
    raw=b'package p\nfunc external(x int) int\n'
    graph=SourceGraph({'id':'one','path':'test.go','raw':raw})
    assert any(n['kind']=='declaration' for n in graph.nodes)


def test_go_function_value_is_resolved_at_its_call_site():
    code='''package p
func TestX() {
    run := func(x int) int { return produce(x) }
    got := run(7)
    assert(got == 8)
}
'''
    _,result,text=sliced(code,'run(7)','test.go')
    assert 'return produce(x)' in text
    assert 'assert(got == 8)' in text
    assert any(kind=='direct' for _,_,kind in result['bindings'])


def test_callback_keeps_registration_and_outer_assignment_binding():
    code='''describe('suite', () => {
    let runner;
    beforeEach(() => { runner = new Runner({bail:true}); });
    it('case', () => { runner.run(); expect(runner.done).toBe(true); });
    it('other', () => { unrelated(999); });
});'''
    _,_,text=sliced(code,'runner.run()','test.js')
    assert "it('case'" in text and "describe('suite'" in text
    assert 'runner = new Runner({bail:true})' in text
    assert 'unrelated(999)' not in text


def test_parameterized_input_decorator_is_part_of_function_dependencies():
    code='''@pytest.mark.parametrize('value,expected', [(7,8)])
def check(value, expected):
    result = run(value)
    assert result == expected
'''
    _,_,text=sliced(code,'run(value)')
    assert "@pytest.mark.parametrize('value,expected', [(7,8)])" in text
    _,_,text=sliced(code,"pytest.mark.parametrize('value,expected', [(7,8)])")
    assert 'run(value)' in text and 'assert result == expected' in text


def test_function_to_string_is_source_input_not_an_executed_callback():
    code='''const input = function example(dep) { forbidden(dep); }.toString();
const result = parse(input);
expect(result).toEqual(['dep']);'''
    graph,result,text=sliced(code,'parse(input)','test.js')
    assert 'function example(dep) { forbidden(dep); }.toString()' in text
    assert not result['bindings']
    assert any(n['source_values'] for n in graph.nodes)
    _,_,text=sliced(code,'function example(dep) { forbidden(dep); }.toString()','test.js')
    assert 'parse(input)' in text and 'expect(result)' in text
