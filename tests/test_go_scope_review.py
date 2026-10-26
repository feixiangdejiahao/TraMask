import subprocess
import pytest
from prototypes.test_edit_analogy_v02.bindings import analyze_bindings

CODE='package sample\nfunc sibling() int { ret:=4; return ret }\nfunc target() int { return 0 }\n'

def edit(code,before,after,**kwargs):
 start=code.encode().index(before.encode())
 return analyze_bindings(code,'go',start,after,end_byte=start+len(before.encode()),path='target.go',**kwargs)

def test_sibling_local_never_becomes_target_binding():
 r=edit(CODE,'return 0','return ret',go_package_sources={})
 assert r['status']=='invalid'
 assert any(e['name']=='ret' and e['reason']=='undeclared_go_identifier' for e in r['errors'])
 assert r['bindings'][0]['binding_id'] is None

def test_assignment_target_requires_an_existing_binding():
 code='package sample\nfunc sibling(){ret:=4;_=ret}\nfunc target(){_=0}\n'
 r=edit(code,'_=0','ret=7',go_package_sources={})
 assert r['status']=='invalid'
 assert any(e['name']=='ret' for e in r['errors'])

def test_partial_package_is_unknown_not_proven_invalid():
 r=edit(CODE,'return 0','return ret')
 assert r['status']=='unknown' and not r['errors']

def test_peer_file_package_variable_is_visible_not_sibling_local():
 r=edit(CODE,'return 0','return ret',go_package_sources={'peer.go':'package sample\nvar ret=9\n'})
 assert r['status']=='compatible'
 assert r['bindings'][0]['reason']=='same_package_declaration'

def test_peer_file_local_cannot_supply_package_variable():
 r=edit(CODE,'return 0','return ret',go_package_sources={'peer.go':'package sample\nfunc third(){ret:=9;_=ret}\n'})
 assert r['status']=='invalid'

def test_same_file_package_variable_with_same_sibling_local_is_valid():
 r=edit(CODE+'var ret=9\n','return 0','return ret',go_package_sources={})
 assert r['status']=='compatible'

def test_go_assignment_to_parameter_is_valid():
 code='package sample\nfunc target(ret int){_=0}\n'
 assert edit(code,'_=0','ret=7',go_package_sources={})['status']=='compatible'

def test_named_result_assignment_is_valid():
 code='package sample\nfunc target()(ret int){return}\n'
 assert edit(code,'{return}','{ret=7;return}',go_package_sources={})['status']=='compatible'

def test_closure_can_capture_local():
 code='package sample\nfunc target()int{ret:=7; fn:=func()int{return 0}; _=ret;return fn()}\n'
 assert edit(code,'return 0','return ret',go_package_sources={})['status']=='compatible'

def test_peer_package_must_match():
 with pytest.raises(ValueError,match='one package'):
  edit(CODE,'return 0','return ret',go_package_sources={'peer.go':'package other\nvar ret=1\n'})

def test_named_type_conversion_not_rejected():
 code='package sample\ntype Count int\nfunc target()Count{return 0}\n'
 assert not edit(code,'return 0','return Count(1)',go_package_sources={})['errors']

def test_generic_function_type_parameter_not_rejected():
 code='package sample\nfunc target[T ~int](x T)T{return x}\n'
 assert not edit(code,'return x','return T(1)',go_package_sources={})['errors']

def test_compiler_confirms_single_file_counterexample_and_peer_positive(tmp_path):
 target=tmp_path/'target.go';target.write_text(CODE.replace('return 0','return ret'))
 p=subprocess.run(['go','tool','compile','-o',str(tmp_path/'toy.o'),str(target)],capture_output=True,text=True)
 assert p.returncode!=0 and 'undefined: ret' in p.stdout+p.stderr
 peer=tmp_path/'peer.go';peer.write_text('package sample\nvar ret=9\n')
 p=subprocess.run(['go','tool','compile','-o',str(tmp_path/'toy.o'),str(target),str(peer)],capture_output=True,text=True)
 assert p.returncode==0,p.stdout+p.stderr

def test_struct_field_key_not_rejected_as_unbound_value():
 code='package sample\ntype Box struct{Value int}\nfunc target()Box{return Box{}}\n'
 r=edit(code,'return Box{}','return Box{Value:1}',go_package_sources={})
 assert not r['errors']
 assert any(u['reason']=='composite_literal_key_kind_unknown' for u in r['unknowns'])

def test_dot_import_remains_unknown_without_export_data():
 code='package sample\nimport . "math"\nfunc target()float64{return 0}\n'
 r=edit(code,'return 0','return Pi',go_package_sources={})
 assert not r['errors']
 assert any(u['reason']=='dot_import_members_unresolved' for u in r['unknowns'])
