"""Comparison must consume real slice versions, bindings and material links."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from eviweave.artifacts import read_json, write_json
from eviweave.blobs import BlobStore
from eviweave.behavior_clusters import read_candidate_materials
from eviweave.comparison import BehaviorComparison, compare_slices, load_slice_comparison
from scripts.comparison_audit import partition_records
from eviweave.evidence import SourceGraph
from eviweave.slice_behavior import indexes, read_behavior_graph
from eviweave.slicing import slice_targets
from eviweave.trajectory import Trajectory
from test_eviweave_joint_pipeline import run_pipeline


def comparison_for(texts, path='test.py'):
    sources, views = {}, []
    for i, text in enumerate(texts):
        source = str(i)
        graph = SourceGraph({'id': source, 'path': path, 'raw': text.encode()})
        behavior = indexes(graph)[0]
        sources[source] = graph, behavior
        views.append({'id': i, 'source': source, 'nodes': set(range(len(graph.nodes))),
                      'anchors': {(source, op['id']) for op in behavior.operations if op['name'] == 'send'}})
    return BehaviorComparison(sources, views)


@pytest.mark.parametrize('path,texts', [
    ('test.py', ['a=[]\nsend(a,a)\n', 'b=[]\nc=[]\nsend(b,c)\n']),
    ('test.ts', ['const a=[];send(a,a);', 'const b=[];const c=[];send(b,c);']),
    ('test.js', ['const a=[];send(a,a);', 'const b=[];const c=[];send(b,c);']),
    ('test.go', ['package p\nfunc f(){a:=[]int{};send(a,a)}', 'package p\nfunc f(){b:=[]int{};c:=[]int{};send(b,c)}']),
    ('test.rs', ['fn f(){let a=vec![];send(a,a);}', 'fn f(){let b=vec![];let c=vec![];send(b,c);}']),
])
def test_shared_entry_runs_alignment_differences_and_partitioning(path, texts):
    comparison = comparison_for(texts, path)
    roots = [(r['view'], *r['key']) for r in comparison.records if r['interface'] == ('call', 'send')]
    result = comparison.align(*roots)
    assert {row['role'] for row in result['ports']} == {'positional:0', 'positional:1'}
    assert ('lexical_topology',) in result['difference']['addresses']
    partition = comparison.partition(modes=('ports', 'relations'))
    members = {row for rows in partition['memberships']['ports'].values() for row in rows}
    assert set(roots) <= members
    assert partition['cluster_pairs']['original']['ports']


def test_multiple_source_projections_keep_one_context_and_all_members():
    comparison = comparison_for(['a=make()\nsend(a)\n', 'b=make()\nsend(b)\n'])
    comparison.views[1]['id'] = 0
    comparison = BehaviorComparison(comparison.sources, comparison.views)
    partition = comparison.partition()
    assert {r['view'] for r in comparison.records} == {0}
    members = {row for rows in partition['memberships']['ports'].values() for row in rows}
    assert {source for _, source, _ in members} == {'0', '1'}


def test_class_queries_keep_the_original_member_read_to_call_bridge():
    comparison=comparison_for(['obj=Box()\nvalue=obj.send\nconsume(value)\n',
                               'obj=Box()\nvalue=obj.send(1)\nconsume(value)\n'])
    direct=comparison.partition()
    audited=partition_records(comparison.index,comparison.records,comparison.views,modes=('ports',))
    assert direct['cluster_pairs']['original']['ports']==audited['cluster_pairs']['lifted']['ports']
    assert direct['memberships']==audited['memberships']


def test_actual_slicing_connects_comparison_and_preserves_deleted_input_output(tmp_path):
    command = '''cat >test_gone.py <<'PY'
from impl import send
def test_first():
    value=[]
    send(value,value)
def test_second():
    first=[]
    second=[]
    send(first,second)
test_first()
test_second()
print('candidate-observation')
PY
python3 -B test_gone.py
rm test_gone.py
'''
    _, slices, _ = run_pipeline(tmp_path, {'impl.py': 'def send(a,b): return None\n'}, command, 'Preserve `send()` behavior.')
    destination = tmp_path / 'comparison'
    summary = compare_slices(slices, destination)
    assert summary['occurrences'] and summary['difference_profiles']
    pairs = read_behavior_graph(destination / 'cluster_pairs.json.gz')['original']['ports']
    assert pairs
    packet = read_candidate_materials(destination, pairs[0])
    assert any(d['text'] is not None and 'candidate-observation' in d['text'] for d in packet['candidate_materials'])
    assert read_behavior_graph(destination / 'difference_profiles.json.gz')
    comparison, _, _ = load_slice_comparison(slices)
    roots = [(r['view'], *r['key']) for r in comparison.records if r['anchor'] and r['interface'] == ('call', 'send')]
    assert roots
    left = roots[0]
    right = next(row for row in roots if row != left)
    result = comparison.align(left, right)
    assert result['ports']
    output = tmp_path / 'aligned.json'
    process = subprocess.run([sys.executable, '-m', 'eviweave', 'align', '--directory', str(slices),
                              '--left', *map(str, left), '--right', *map(str, right), '--out', str(output)],
                             check=True, capture_output=True, text=True,
                             env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'src')})
    assert read_json(output) == json.loads(json.dumps(result))
    assert 'changed_relations' in process.stdout
    alternate = tmp_path / 'relations'
    compare_slices(slices, alternate, modes=('relations',))
    pair = read_behavior_graph(alternate/'cluster_pairs.json.gz')['original']['relations'][0]
    assert read_candidate_materials(alternate,pair,partition='relations')['candidate_materials']
    pool = read_behavior_graph(destination/'candidate_materials.json.gz')
    assert pool['executions']
    assert len(pool['view_executions']) >= len(pool['executions'])
    assert all(link['relation'] not in {'observed_input','observed_output'}
               for links in pool['views'].values() for link in links)


@pytest.mark.parametrize('raw', [b'# coding: latin-1\n# caf\xe9\ndef test_send():\n    a=[1]\n    send(a,a)\n',
                               b'\xef\xbb\xbfdef test_send():\n    a=[1]\n    send(a,a)\n'])
def test_physical_encoding_version_and_utf8_coordinates_remain_separate(tmp_path, raw):
    collected=tmp_path/'collected';collected.mkdir()
    store=BlobStore(collected/'blobs');store.create()
    digest=store.put(raw)
    snapshot={'files':[{'kind':'file','path':'/app/test_send.py','sha256':digest}]}
    trajectory=Trajectory(collected);trajectory.start(snapshot);trajectory.finish(snapshot)
    write_json(collected/'snapshots/initial.json',snapshot)
    write_json(collected/'snapshots/submission.json',snapshot)
    write_json(collected/'manifest.json',{'replay':str(collected),'trajectory':str(collected/'trajectory.json'),
               'submission_state_validated':True,'source_versions':[{'path':'/app/test_send.py','sha256':digest}],
               'unobserved_source_candidates':[]})
    write_json(collected/'plan.json',{'action_ids':['s1']})
    call=collected/'runtime/calls/s1';call.mkdir(parents=True)
    (call/'command.sh').write_text('python3 test_send.py')
    (call/'output.bin').write_bytes(b'')
    write_json(call/'archived_expected.json',{})
    (collected/'inputs').mkdir()
    (collected/'inputs/instruction.md').write_text('Preserve `send()` behavior.')
    (collected/'inputs/model.patch').write_text('')
    slices=tmp_path/'slices';slice_targets(collected/'manifest.json',slices)
    comparison,_,_=load_slice_comparison(slices)
    assert any(r['anchor'] and r['interface']==('call','send') for r in comparison.records)


def test_source_input_retains_material_context_without_becoming_execution(tmp_path):
    source='def test_send():\n value=[]\n send(value,value)\n'
    _,slices,_=run_pipeline(tmp_path,{'test_input.py':source},'cat test_input.py\n','Preserve `send()` behavior.')
    destination=tmp_path/'comparison'
    summary=compare_slices(slices,destination)
    assert summary['material_only_views']
    assert summary['candidate_materials']
    assert not summary['occurrences']
    materials=read_behavior_graph(destination/'candidate_materials.json.gz')
    assert materials['view_executions']


def test_parse_failure_is_research_data_not_a_dropped_source():
    comparison = comparison_for(['def broken(:\n send(\n'])
    assert comparison.sources['0'][0].issues
    assert not comparison.records
    assert not comparison.partition()['memberships']['ports']
