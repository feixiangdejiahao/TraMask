"""A repeated citation may be recovered at any of its actual locations."""
import hashlib
import json

from eviweave.artifacts import write_json
from eviweave.blobs import BlobStore
from scripts import evaluate_trajectory_slicing_cohort as evaluation
import verify_pre_slice_five_pilot

compare_quote, summarize = evaluation.compare_quote, evaluation.summarize


def test_later_occurrence_of_a_repeated_citation_can_be_recovered():
    source = '# 中文\ndef first():\n    assert value == 7\ndef second():\n    assert value == 7\n'
    needle = 'assert value == 7'
    raw, target = source.encode(), needle.encode()
    second = raw.rindex(target)
    view = [('second.json', [[second, second + len(target)]])]
    info = {'path': '/app/test_sample.py', 'sha256': hashlib.sha256(raw).hexdigest()}
    results = compare_quote('M1', info, source, needle, view, view, False, {})
    assert len(results) == 2
    assert not results[0]['core_same_program_view']
    assert results[1]['core_same_program_view']
    assert results[1]['range'][0] == second


def test_failed_slicing_is_not_counted_as_an_unrecovered_citation():
    completed = {'id':'S1', 'references':1, 'worker_returncode':0, 'stage':'evaluated',
                 'quotes':[{'id':'Q1','old_native':True,'raw_retained':True,'source_aligned':True,
                            'same_program_view':True,'core_same_program_view':True,
                            'exact_occurrence_core_view':True,'core_union':True,'data_view':False,'material_entry_recovered':False,'analysis_recovered':True}]}
    failed = {'id':'S2', 'references':1, 'worker_returncode':1, 'stage':'slicing_unavailable',
              'quotes':[{'id':'Q2','old_native':True,'raw_retained':True,'source_aligned':True,
                         'same_program_view':None,'core_same_program_view':None,
                         'exact_occurrence_core_view':None,'core_union':None,'data_view':None,'material_entry_recovered':None,'analysis_recovered':None}]}
    summary = summarize([completed, failed]); totals = summary['totals']
    assert totals['raw_evaluated_references'] == 2 and totals['raw_retained'] == 2
    assert totals['slice_evaluated_references'] == 1 and totals['analysis_recovered'] == 1
    assert summary['cases_with_worker_errors'] == ['S2']
    assert summarize([failed])['totals']['slice_evaluated_references'] == 0
    assert summarize([failed])['totals']['analysis_recovered'] == 0


def test_static_view_retains_its_material_occurrence_in_evaluation(tmp_path, monkeypatch):
    code = 'def test_x():\n    assert x == 4\n'; needle = 'assert x == 4'
    inputs = tmp_path/'inputs'; inputs.mkdir()
    command = "cat > /tmp/test_x.py <<'EOF'\n" + code + 'EOF\n'
    write_json(inputs/'trajectory.json', {'steps':[{'step_id':1,'tool_calls':[
        {'function_name':'bash','arguments':{'command':command}}],
        'observation':{'results':[{'content':json.dumps({'returncode':0,'output':''})}]}}]})
    fr = tmp_path/'manual'
    write_json(fr/'public_workspace_v3/cases/S001/inventory.json', {'entries':[]})
    monkeypatch.setattr(verify_pre_slice_five_pilot,'FR',fr)
    gold=tmp_path/'quotes.json'
    write_json(gold,[{'case_id':'S001','id':'Q1','code':needle,'source_audit':{'cited_origin':'s1_c0'}},
                     {'case_id':'S001','id':'Q2','code':'raw-only-marker','source_audit':{'cited_origin':'s1_c0'}}])
    prior=tmp_path/'prior'
    start=code.encode().index(needle.encode())
    write_json(prior/'S001.json',{'quotes':[{'id':'Q1','native':True,
              'original_spans':[['H:s1_c0:0000',start,start+len(needle)]]},
              {'id':'Q2','native':False,'original_spans':[]}]})
    monkeypatch.setattr(evaluation,'GOLD',gold);monkeypatch.setattr(evaluation,'PRIOR',prior)

    run=tmp_path/'run'; case=run/'cases/S001'; replay=case/'replay'; tests=replay/'tests'
    store=BlobStore(tests/'blobs');store.create();digest=store.put(code.encode())
    graph=tests/'trajectory.json'
    write_json(graph,{'materials':{'M0':{'kind':'file','path':'/tmp/test_x.py','sha256':digest,'producer':None}},
                      'events':{},'edges':[]})
    write_json(tests/'manifest.json',{'replay':'..','trajectory':'trajectory.json','submission_state_validated':True})
    write_json(run/'protocol.json',{'collection_run':None})
    write_json(case/'worker_result.json',{'returncode':0})
    write_json(case/'slicing/summary.json',{})
    call=replay/'runtime/calls/s1_c0';call.mkdir(parents=True)
    (call/'command.sh').write_text(command)
    write_json(call/'archived_expected.json',{'output':'raw-only-marker'})
    command_source={'source':str(call/'command.sh'),'write':0}
    write_json(case/'slicing/targets.json',{'units':[{**command_source,'path':'/tmp/test_x.py'}],
                'records':[{'id':'R1','text':'raw-only-marker','source':str(call/'archived_expected.json')+'#/output'}]})
    write_json(case/'slicing/material_entries.json',{'actions':[{'action':'s1_c0','reasons':['validation_or_execution']}],
                                                   'records':['R1'],'files':[]})
    write_json(case/'slicing/views/0.json',{'source':str(graph)+'#/materials/M0','material':'M0',
               'static_slice':{'ranges':[[0,len(code.encode())]]}})
    write_json(case/'slicing/views/1.json',{'source':command_source,
               'static_slice':{'ranges':[[0,len(code.encode())]]}})
    quotes=evaluation.evaluate({'screen_id':'S001','input_directory':str(inputs)},case)['quotes'];quote=quotes[0]
    assert quote['core_same_program_view'] and quote['exact_occurrence_core_view']
    assert not quotes[1]['same_program_view'] and quotes[1]['material_entry_recovered'] and quotes[1]['analysis_recovered']
