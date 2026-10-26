"""Source summaries only; these fixtures are never executed as subject code."""
import pytest

from anchor_retrieval.index import Index
from anchor_retrieval.syntax import Source
from experimental.observation_address_effects import summarize_method


def setup(code,language='python',path=None):
    path=path or {'python':'subject.py','go':'subject.go','typescript':'subject.ts'}[language]
    index=Index([Source(path,code,language)],'')
    def summary(name):
        unit=next(u for u in index.units.values() if u.name==name)
        return summarize_method(index,unit.id)
    return index,summary


def test_python_key_formal_and_owner_identity_match_read_write():
    _,get=setup('''class Box:
    def read(self, key):
        return self.items[key]
    def write(self, key, value):
        self.items[key] = value
''')
    read,write=get('read'),get('write')
    assert read['owner_key']==write['owner_key']
    assert read['reads'][0]['field']=='items'
    assert write['writes'][0]['key']==dict(kind='formal',name='key',parameter_index=1,argument_index=0)
    assert not read['complete_effect_summary']
    assert not write['writes'][0]['final_store_proved']


@pytest.mark.parametrize('receiver,key,field',[('self','key','items'),('me','token','entries')])
def test_identifier_renaming_does_not_change_structure(receiver,key,field):
    _,get=setup(f'class Box:\n def read({receiver},{key}): return {receiver}.{field}[{key}]\n def write({receiver},{key},value): {receiver}.{field}[{key}]=value\n')
    assert get('read')['reads'][0]['key']['name']==key
    assert get('write')['writes'][0]['field']==field


def test_reaching_local_return_definition_excludes_overwritten_read():
    _,get=setup('''class Box:
 def read(self,key):
  value=self.items[key]
  value=0
  return value
 def linked(self,key):
  token=key
  value=self.items[token]
  alias=value
  return alias
''')
    assert get('read')['reads']==[]
    assert get('linked')['reads'][0]['key']['name']=='key'


def test_literal_keys_and_plain_fields_are_distinguished():
    _,get=setup('''class Box:
 def read(self): return self.items['fixed']
 def write(self,value): self.items['fixed']=value
 def plain(self): return self.items
''')
    assert get('read')['reads'][0]['key']['value']=='fixed'
    assert get('plain')['reads'][0]['key'] is None
    assert len(get('read')['reads'])==1


def test_unknown_index_does_not_degrade_to_plain_field_match():
    _,get=setup('''class Box:
 def read(self,key): return self.items[transform(key)]
 def write(self,key,value): self.items[transform(key)]=value
''')
    assert not get('read')['reads']
    assert not get('write')['writes']


@pytest.mark.parametrize('statement',['key=other','self=other','key+=1','for key in values:\n   pass'])
def test_receiver_or_key_formal_rebinding_is_unknown(statement):
    _,get=setup('class Box:\n def write(self,key,value):\n  '+statement+'\n  self.items[key]=value\n')
    result=get('write')
    assert result['status']=='unknown'
    assert not result['writes']
    assert result['unknowns'][0]['reason']=='receiver_or_formal_rebound'


def test_guarded_store_is_retained_without_solving_guard():
    _,get=setup('''class Box:
 def write(self,key,value):
  if key not in self.items:
   self.items[key]=value
 def read(self,key):
  if enabled:
   return self.items[key]
  return None
''')
    effect=get('write')['writes'][0]
    assert effect['guards'][0]['kind']=='if_statement'
    assert effect['guards'][0]['feasibility']=='unproved'
    assert get('read')['reads'][0]['guards']


def test_loop_effect_may_exist_even_when_iteration_count_unknown():
    _,get=setup('''class Box:
 def write(self,key,value):
  for ignored in repetitions:
   self.items[key]=value
''')
    assert get('write')['writes'][0]['guards'][0]['kind']=='for_statement'


def test_conditional_local_alias_is_not_guessed():
    _,get=setup('''class Box:
 def read(self,key):
  value=0
  if enabled:
   value=self.items[key]
  return value
''')
    assert not get('read')['reads']
    assert get('read')['unknowns']


def test_nested_scope_effect_is_not_confused_with_method_effect():
    _,get=setup('''class Box:
 def write(self,key,value):
  def later():
   self.items[key]=value
  return later
''')
    assert get('write')['status']=='unknown'
    assert not get('write')['writes']


def test_go_receiver_type_declaration_and_argument_indexes():
    _,get=setup('''package p
type Box struct { items map[string]int }
func (b *Box) Read(key string) int { value := b.items[key]; return value }
func (b *Box) Write(key string, value int) { b.items[key] = value }
''','go')
    read,write=get('Read'),get('Write')
    assert read['status']==write['status']=='source_summary'
    assert read['owner_key']==write['owner_key']
    assert read['owner_span']['start_line']==2
    assert write['writes'][0]['key']['parameter_index']==0
    assert read['reads'][0]['key']['argument_index']==0


def test_typescript_this_receiver_and_local_result():
    _,get=setup('''class Box {
 read(key:string) { const value=this.items[key]; return value; }
 write(key:string,value:number) { this.items[key]=value; }
}''','typescript')
    assert get('read')['receiver_name']=='this'
    assert get('read')['reads'][0]['field']=='items'
    assert get('write')['writes'][0]['key']['parameter_index']==0


def test_distinct_classes_with_same_field_and_method_name_never_share_owner():
    index=Index([Source('one.py','class Box:\n def read(self,k): return self.items[k]\n','python'),
                 Source('two.py','class Box:\n def read(self,k): return self.items[k]\n','python')],'')
    summaries=[summarize_method(index,u.id) for u in index.units.values()]
    assert summaries[0]['owner_key']!=summaries[1]['owner_key']


def test_go_methods_in_different_files_share_exact_type_declaration():
    index=Index([Source('a.go','package p\ntype Box struct { items map[string]int }\nfunc(b *Box) Read(k string) int{return b.items[k]}','go'),
                 Source('b.go','package p\nfunc(b *Box) Write(k string,v int){b.items[k]=v}','go')],'')
    a,b=[summarize_method(index,u.id) for u in index.units.values()]
    assert a['owner_key']==b['owner_key']


def test_source_refs_are_exact_utf8_spans():
    code='class Box:\n def read(self): return self.items["猫"]\n'
    _,get=setup(code);effect=get('read')['reads'][0]
    assert code.encode()[effect['span']['start_byte']:effect['span']['end_byte']].decode()=='self.items["猫"]'
    assert code.encode()[effect['key_span']['start_byte']:effect['key_span']['end_byte']].decode()=='"猫"'


def test_store_before_return_is_not_claimed_final_and_two_overwrites_retained():
    _,get=setup('''class Box:
 def write(self,k,v):
  self.items[k]=v
  self.items[k]=0
''')
    result=get('write')
    assert len(result['writes'])==2
    assert not any(e['final_store_proved'] for e in result['writes'])


def test_go_formal_address_escape_invalidates_formal_key_summary():
    _,get=setup('package p\ntype Box struct{items map[string]int}\nfunc(b *Box) Write(k string,v int){ change(&k); b.items[k]=v }','go')
    assert get('Write')['status']=='unknown'


def test_decorated_python_method_does_not_invent_instance_binding():
    _,get=setup('class Box:\n @staticmethod\n def read(self,k): return self.items[k]\n')
    assert get('read')['status']=='unknown'


def test_go_range_rebinding_a_formal_is_unknown():
    _,get=setup('package p\ntype Box struct{items map[string]int}\nfunc(b *Box) Write(k string,v int){ for k = range keys { b.items[k]=v } }','go')
    assert get('Write')['status']=='unknown'


@pytest.mark.parametrize('statement',[
    'try:\n   raise ValueError()\n  except ValueError as key:\n   return self.items[key]',
    'alias=key\n  import other as alias\n  return self.items[alias]',
    'alias=key\n  del alias\n  return self.items[alias]',
    'with resource as key:\n   return self.items[key]',
])
def test_exception_import_delete_or_with_bindings_do_not_inherit_formal_key(statement):
    _,get=setup('class Box:\n def read(self,key):\n  '+statement+'\n')
    result=get('read')
    assert result['status']=='unknown'
    assert not result['reads']


def test_typescript_catch_parameter_is_not_original_formal():
    _,get=setup('class Box { read(key:string) { try { throw Error(); } catch(key) { return this.items[key]; } } }','typescript')
    assert get('read')['status']=='unknown'


def test_literal_key_alias_keeps_definition_and_address_use_refs_distinct():
    code='class Box:\n def read(self):\n  key="fixed"\n  alias=key\n  return self.items[alias]\n'
    _,get=setup(code);effect=get('read')['reads'][0]
    value=effect['key']['value_span'];use=effect['key_span']
    assert code.encode()[value['start_byte']:value['end_byte']].decode()==effect['key']['text']=='"fixed"'
    assert code.encode()[use['start_byte']:use['end_byte']].decode()=='alias'
    assert value['start_byte']<use['start_byte']
