"""Execute independently instrumented toy modules, without Docker or models."""
import ast
import sys
import types

import pytest

from experimental.observed_write_runtime import Observer, build_plan, instrument_sources


LIBRARY = '''class Resource:
    def __init__(self):
        self.flag = False
    def advance(self, fail=False):
        if fail:
            raise ValueError("stop")
        self.finish()
    def finish(self):
        self.flag = True
'''


def execute(monkeypatch, library=LIBRARY, body=None, *, raw_library=False, optimize=-1):
    body = body or '''    item = Resource()
    item.advance()
    assert item.flag is True
'''
    sources = {'toy_resource.py':library,
        'toy_validation.py':'from toy_resource import Resource\ndef test_case():\n'+body}
    plan = build_plan(sources, assertion_paths=['toy_validation.py'])
    overlays = instrument_sources(sources, plan, runtime_module='_toy_observer')
    recorder = Observer()
    monkeypatch.setitem(sys.modules, '_toy_observer', types.SimpleNamespace(observer=recorder))
    modules = {}
    for path in ['toy_resource.py', 'toy_validation.py']:
        name = path[:-3]
        module = types.ModuleType(name)
        monkeypatch.setitem(sys.modules, name, module)
        code = sources[path] if raw_library and path=='toy_resource.py' else overlays.get(path,sources[path])
        exec(compile(code, path, 'exec', optimize=optimize), module.__dict__)
        modules[name] = module
    return modules['toy_validation'].test_case, recorder, plan, overlays, modules


def observations(recorder):
    return [row for row in recorder.events if row['kind']=='assertion_read']


@pytest.mark.parametrize('names', [('Resource','flag','item','advance','finish'),
                                  ('Ledger','settled','record','process','commit')])
def test_normal_and_exception_paths_reach_same_q_with_different_actual_writers(monkeypatch,names):
    body = '''    item = Resource()
    try:
        item.advance(FAIL)
    except ValueError:
        pass
    assert item.flag is True
'''
    library = LIBRARY
    for before, after in zip(('Resource','flag','item','advance','finish'),names):
        library, body = library.replace(before,after), body.replace(before,after)
    # Keep import construction generic while checking name independence.
    sources={'toy_resource.py':library,'toy_validation.py':
        f'from toy_resource import {names[0]}\nFAIL = False\ndef test_case():\n'+body}
    plan=build_plan(sources,assertion_paths=['toy_validation.py'])
    overlays=instrument_sources(sources,plan,runtime_module='_toy_observer')
    recorder=Observer()
    monkeypatch.setitem(sys.modules,'_toy_observer',types.SimpleNamespace(observer=recorder))
    modules={}
    for path,code in overlays.items():
        module=types.ModuleType(path[:-3]);monkeypatch.setitem(sys.modules,path[:-3],module)
        exec(compile(code,path,'exec'),module.__dict__);modules[path[:-3]]=module
    validation=modules['toy_validation']
    validation.test_case()
    validation.FAIL=True
    with pytest.raises(AssertionError):
        validation.test_case()
    a,b=observations(recorder)
    assert a['q_span']==b['q_span']
    assert a['allocation_span']==b['allocation_span']
    assert a['object_token']!=b['object_token']
    assert a['value']['value'] is True and b['value']['value'] is False
    assert a['last_observed_writer']!=b['last_observed_writer']
    assert a['last_observed_writer']['line']==9
    assert b['last_observed_writer']['line']==3
    assert all(row['status']=='observed_within_instrumented_code' for row in [a,b])
    assert all('phase' not in row for row in recorder.events)


def test_finally_executes_write_before_exception_reaches_q(monkeypatch):
    library=LIBRARY.replace('        if fail:\n            raise ValueError("stop")\n        self.finish()',
        '        try:\n            if fail:\n                raise ValueError("stop")\n        finally:\n            self.finish()')
    body='''    item = Resource()
    try:
        item.advance(True)
    except ValueError:
        pass
    assert item.flag is True
'''
    run,recorder,plan,_,_=execute(monkeypatch,library,body)
    run()
    row=observations(recorder)[0]
    assert row['value']['value'] is True
    expected=next(w for w in plan['writes'] if w['writer_span']['line']==11)
    assert row['last_observed_writer']==expected['writer_span']


def test_alias_reads_share_instance_but_other_instance_cannot_supply_writer(monkeypatch):
    body='''    first = Resource()
    second = Resource()
    alias = first
    alias.advance()
    assert first.flag is True
    assert alias.flag is True
    assert second.flag is False
'''
    run,recorder,_,_,_=execute(monkeypatch,body=body)
    run()
    a,b,c=observations(recorder)
    assert a['object_token']==b['object_token']!=c['object_token']
    assert a['last_observed_writer']==b['last_observed_writer']
    assert a['last_observed_writer']!=c['last_observed_writer']
    assert c['value']['value'] is False


def test_property_alias_reads_storage_without_an_extra_getter_call(monkeypatch):
    library=LIBRARY.replace('self.flag','self._stored')+'''
    @property
    def flag(self):
        return self._stored
'''
    run,recorder,_,_,modules=execute(monkeypatch,library)
    getter=modules['toy_resource'].Resource.flag.fget.__code__
    calls=[]
    def profile(frame,event,arg):
        if event=='call' and frame.f_code is getter:
            calls.append(frame.f_code)
    previous=sys.getprofile()
    sys.setprofile(profile)
    try:
        run()
    finally:
        sys.setprofile(previous)
    assert len(calls)==1
    row=observations(recorder)[0]
    assert row['observed_field']=='flag' and row['field']=='_stored'
    assert row['value']['value'] is True


def test_missing_write_is_unknown_even_when_direct_storage_value_exists(monkeypatch):
    library=LIBRARY.replace('self.flag = False', 'self.__dict__["flag"] = False')
    run,recorder,_,_,_=execute(monkeypatch,library,body='''    item = Resource()
    assert item.flag is False
''')
    run()
    row=observations(recorder)[0]
    assert row['value']['value'] is False
    assert row['status']=='unknown' and row['reason']=='no_observed_write'
    assert row['last_observed_writer'] is None


def test_uninstrumented_library_and_unobserved_mutation_are_explicitly_unknown(monkeypatch):
    run,recorder,_,_,_=execute(monkeypatch,raw_library=True)
    run()
    assert observations(recorder)[0]['status']=='unknown'
    run,recorder,_,_,_=execute(monkeypatch,body='''    item = Resource()
    item.__dict__["flag"] = True
    assert item.flag is True
''')
    run()
    row=observations(recorder)[0]
    assert row['reason']=='storage_changed_since_last_observed_write'


def test_failed_assignment_rhs_does_not_emit_a_successful_write(monkeypatch):
    library=LIBRARY.replace('self.flag = True','self.flag = int("invalid")')
    run,recorder,_,_,_=execute(monkeypatch,library,body='''    item = Resource()
    try:
        item.finish()
    except ValueError:
        pass
    assert item.flag is False
''')
    run()
    row=observations(recorder)[0]
    writes=[x for x in recorder.events if x['kind']=='write']
    assert len(writes)==1 and row['last_observed_writer']==writes[0]['writer_span']


def test_short_circuit_assertions_are_excluded_instead_of_claiming_unread_operands(monkeypatch):
    run,recorder,plan,_,_=execute(monkeypatch,body='''    item = Resource()
    assert True or item.flag
''')
    run()
    assert observations(recorder)==[]
    assert plan['queries']==[]
    assert plan['unsupported'][0]['reason']=='assertion_read_may_short_circuit_or_have_effects'


def test_original_assert_ast_and_future_import_are_preserved(monkeypatch):
    library='"""module doc"""\nfrom __future__ import annotations\n'+LIBRARY
    run,_,_,overlays,_=execute(monkeypatch,library)
    run()
    before=ast.parse('assert item.flag is True').body[0]
    after=next(n for n in ast.walk(ast.parse(overlays['toy_validation.py'])) if isinstance(n,ast.Assert))
    assert ast.dump(before)==ast.dump(after)
    tree=ast.parse(overlays['toy_resource.py'])
    assert tree.body[0].value.value=='module doc'
    assert tree.body[1].module=='__future__'


def test_optimized_away_assertion_does_not_claim_q_was_reached(monkeypatch):
    run,recorder,_,_,_=execute(monkeypatch,optimize=1)
    run()
    assert observations(recorder)==[]
    assert any(row['kind']=='write' for row in recorder.events)


def test_custom_dict_property_is_never_called_by_observer(monkeypatch):
    library=LIBRARY+'''
    @property
    def __dict__(self):
        raise RuntimeError("observer must not call this getter")
'''
    run,recorder,_,_,_=execute(monkeypatch,library)
    run()
    row=observations(recorder)[0]
    assert row['status']=='unknown' and row['reason']=='non_native_instance_dict'


def test_observation_does_not_keep_subject_instances_alive(monkeypatch):
    library='destroyed = []\n'+LIBRARY+'''
    def __del__(self):
        destroyed.append(True)
'''
    run,recorder,_,_,modules=execute(monkeypatch,library)
    run()
    assert len(observations(recorder))==1
    assert modules['toy_resource'].destroyed==[True]


@pytest.mark.parametrize('protected', [False, True])
def test_real_generator_exception_and_finally_change_observed_writer(monkeypatch,protected):
    operation=('        try:\n            yield from self.parts()\n        finally:\n            self.finish()'
               if protected else '        yield from self.parts()\n        self.finish()')
    library='''class Resource:
    def __init__(self):
        self.flag = False
    def advance(self):
OPERATION
    def parts(self):
        yield 1
        raise ValueError("consumer stops")
    def finish(self):
        self.flag = True
'''.replace('OPERATION',operation)
    run,recorder,_,_,_=execute(monkeypatch,library,body='''    item = Resource()
    try:
        list(item.advance())
    except ValueError:
        pass
    assert item.flag is True
''')
    if protected:
        run()
    else:
        with pytest.raises(AssertionError):
            run()
    row=observations(recorder)[0]
    assert row['value']['value'] is protected
    assert (row['last_observed_writer']['line']==3) is not protected


def test_selected_function_scope_does_not_instrument_unselected_assertions():
    sources={'toy_resource.py':LIBRARY,'toy_validation.py':'''from toy_resource import Resource
def chosen():
    item = Resource()
    assert item.flag is False
def other():
    item = Resource()
    assert item.flag is False
'''}
    plan=build_plan(sources,assertion_functions={'toy_validation.py':['chosen']})
    assert len(plan['queries'])==1 and len(plan['enumerated_assertions'])==1
    assert plan['queries'][0]['q_span']['line']==4
