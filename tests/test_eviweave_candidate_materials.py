"""Candidate packets must carry actual inputs, outputs and snapshot versions."""
import hashlib

from eviweave.evidence import SourceGraph
from eviweave.material_entries import MaterialConnections
from eviweave.behavior_clusters import candidate_materials


def file(source,path,text,action=None):
    row={'source':source,'path':path,'text':text,'kind':'file',
         'sha256':hashlib.sha256(text.encode()).hexdigest()}
    if action is not None:row['action_id']=action
    return row


def test_module_execution_carries_input_with_comments_without_a_native_match():
    code='from bandit.core import manager\ndef test_scan():\n    manager.run_tests()\n'
    graph=SourceGraph({'id':'test','path':'/app/tests/test_scan.py','raw':code.encode()})
    input_code="call(shell=True)  # nosec-begin\nnext_call()\n# nosec-end\n"
    materials=[file('package','/app/bandit/__init__.py',''),
               file('input','/tmp/input.py',input_code,'probe'),
               {'source':'output','kind':'output','text':'3 B602\n','action_id':'probe','origin':'original'}]
    actions=[{'id':'probe','command':'python -m bandit /tmp/input.py','expected':{'output':'3 B602\n'}}]
    index=MaterialConnections(materials,actions,root='/app')
    links=index.links([(graph,[[0,len(graph.raw)]])],actions=[])
    assert {'input','output'}<={index.documents[row['material']]['source'] for row in links}
    assert any(row['relation']=='package_execution_candidate' for row in links)
    assert index.documents[index.ids['input']]['text']==input_code
    assert index.documents[index.ids['output']]['origin']=='original'


def test_edit_path_connects_opaque_rust_fixture_and_its_own_snapshot_only():
    code="p='crates/jobs/collapse.rs'\ns=open(p).read()\nopen(p,'w').write(s)\n"
    graph=SourceGraph({'id':'edit','path':'<inline>.py','raw':code.encode()})
    fixture='#[test]\nfn collapse() { insta::assert_snapshot!(run(r#"<g class="n"/>"#)); }\n'
    snapshot='---\nsource: crates/jobs/collapse.rs\n---\n<g class="n"/>\n'
    index=MaterialConnections([file('fixture','/app/crates/jobs/collapse.rs',fixture),
                file('snapshot','/app/crates/jobs/snapshots/collapse.snap',snapshot),
                file('other','/app/crates/jobs/snapshots/other.snap','---\nsource: crates/jobs/other.rs\n---\nwrong\n')],[],root='/app')
    links=index.links([(graph,[[0,len(graph.raw)]])],actions=[])
    assert {index.documents[row['material']]['source'] for row in links}=={'fixture','snapshot'}
    assert next(row for row in links if row['material']==index.ids['snapshot'])['relation']=='snapshot_for_source'
    assert '<g class="n"/>' in index.documents[index.ids['fixture']]['text']


def test_static_path_keeps_all_versions_as_candidates_and_never_uses_an_unretained_literal():
    code="path='context.json'\nconsume(path)\nunrelated='other.json'\n"
    graph=SourceGraph({'id':'program','path':'/app/check.py','raw':code.encode()})
    index=MaterialConnections([file('old','/app/context.json','{"n":1}'),
                              file('new','/app/context.json','{"n":2}'),
                              file('other','/app/other.json','{}')],[],root='/app')
    end=code.index('unrelated=')
    links=index.links([(graph,[[0,end]])],actions=[])
    assert {index.documents[r['material']]['source'] for r in links}=={'old','new'}
    assert {r['relation'] for r in links}=={'literal_path_version_candidate'}


def test_cluster_candidate_only_reads_attachments_of_its_member_views():
    members={3:[(10,'source','op'),(11,'source','other')],4:[(12,'other_source','op')]}
    links={10:[{'material':'input','relation':'action_material','via':'a1'}],
           11:[{'material':'output','relation':'action_material','via':'a1'}],
           12:[{'material':'unrelated','relation':'action_material','via':'a2'}]}
    result=candidate_materials((3,3),members,links)
    assert set(result)=={'input','output'}
    assert result['input']==[{'view':10,'relation':'action_material','via':'a1'}]


def test_go_byte_string_remains_data_while_utf8_path_is_connected():
    code='package main\nfunc check() { consume("\\xff", "context.json") }\n'
    graph=SourceGraph({'id':'go','path':'/app/check.go','raw':code.encode()})
    index=MaterialConnections([file('input','/app/context.json','{"n":3}')],[],root='/app')
    links=index.links([(graph,[[0,len(graph.raw)]])],actions=[])
    assert {index.documents[r['material']]['source'] for r in links}=={'input'}
    assert b'"\\xff"' in graph.raw
