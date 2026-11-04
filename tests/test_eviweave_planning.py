from eviweave.evidence import SourceGraph
from eviweave.planning import interface_features,related_order,check_plan,text_features
from eviweave.planning import changed_declaration_names,select_validation_centers
import subprocess


def test_interfaces_keep_setup_and_observation_without_claiming_object_identity():
    code=b'''def test_response(body):
    r = Response(stream=stream(body))
    parts = list(r.iter_multipart())
    assert r.is_closed
'''
    graph=SourceGraph({'id':'historical','path':'test_response.py','raw':code})
    features=interface_features(graph,[n['id'] for n in graph.nodes])
    assert {'Response','stream','list','iter_multipart'} <= set(features['calls'])
    assert 'stream' in features['keys'] and 'is_closed' in features['fields']
    assert 'r' in features['observations']
    assert 'must_alias' not in features


def test_connections_keep_unmatched_materials_in_the_workset():
    def row(identity,code,path,boundary):
        graph=SourceGraph({'id':identity,'path':path,'raw':code.encode()})
        features=interface_features(graph,list(range(len(graph.nodes))))
        features['paths']=[]
        return {'id':identity,'kind':'program','path':path,'boundary':boundary,'text':code,'features':features}
    records=[row('base','def test_x():\n    x = run(1)\n','test_a.py',['test','x']),
             row('donor','def test_y():\n    x = run(2)\n    assert x.closed\n','test_b.py',['test','y']),
             {'id':'unmatched','kind':'material','text':'a remote contract',
              'features':{'calls':[],'fields':[],'names':[],'observations':[],**text_features('a remote contract')}}]
    order,reasons=related_order(records,['base'],'run')
    assert order[0]=='base' and set(order)=={'base','donor','unmatched'}
    assert 'operation:base' in reasons['donor']


def test_plan_checks_exact_evidence_and_rejects_a_cyclic_order():
    plan={'base':'b','sources':['s'],'checks':[{'basis':[{'source':'issue','quote':'must close'}]}],
          'order':[['consume','observe'],['observe','consume']]}
    result=check_plan(plan,[{'id':'b','text':'r.consume()'},{'id':'s','text':'r.closed'}],
                      'The response must close.','')
    assert result['has_check_basis'] and not result['order_acyclic']
    assert not result['unknown_source_ids']
    plan['checks'][0]['basis'][0]['quote']='invented rule'
    assert not check_plan(plan,[{'id':'b','text':''},{'id':'s','text':''}],'must close','')['has_check_basis']


def test_changed_declaration_uses_real_git_lines_and_owner(tmp_path):
    def git(*args):
        return subprocess.run(['git','-C',str(tmp_path),*args],capture_output=True,check=True).stdout.decode()
    git('init','-q')
    source=tmp_path/'service.py'
    source.write_text('class Service:\n    def run(self, value):\n        return value\n')
    git('add','service.py')
    git('-c','user.name=Research','-c','user.email=research@local','commit','-qm','base')
    source.write_text('class Service:\n    def run(self, value):\n        return value + 1\n')
    names=changed_declaration_names(git('diff'),[('service.py',source.read_bytes())])
    assert {'Service','run'} <= names


def test_changed_validation_beats_an_unrelated_lexical_leader():
    records=[]
    for identity,path,code in [('old','test_other.py','def test_other():\n    assert unrelated(1)\n'),
                               ('current','test_service.py','def test_service():\n    assert Service().run(1) == 2\n')]:
        graph=SourceGraph({'id':identity,'path':path,'raw':code.encode()})
        features=interface_features(graph,list(range(len(graph.nodes))))
        records.append({'id':identity,'path':path,'source':identity,'boundary':['test',identity],'features':features})
    assert select_validation_centers(records,['old','current'],{'test_service.py'}, {'Service','run'},limit=1)==['current']
