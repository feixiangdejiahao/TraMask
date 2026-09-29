import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from audit_relation_campaign_v3 import verify_semantic_frontier
from evaluate_relational_gap import digest


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def fixture(tmp_path, *, offered=True, previous=False):
    directory=tmp_path/'case'/('round_001' if previous else 'round_000')/'semantic'
    history={name:{'id':name} for name in ['editable','unsupported']}
    identity={'corpus_sha256':'corpus','issue_sha256':'issue'}
    configuration={'semantic_policy':'impact','oracle_evidence':'baseline',
                   'semantic_budget':16,'semantic_frontier_policy':'persistent-source-semantic-frontier-v1'}
    ids=['editable'] if offered else []
    pending=[] if offered else ['editable']
    ranking=[{'id':name,'evidence':{'eligible':name=='editable'},'selected':name=='editable',
              'previously_selected':False} for name in history]
    write(directory/'semantic_frontier.json', {'policy':configuration['semantic_frontier_policy'],
          'source_identity':identity,'candidates':list(history.values()),'selected_ids':ids,'pending_ids':pending})
    write(directory/'semantic_selection.json', {'policy':configuration['semantic_frontier_policy'],
          'selected':[history['editable']], 'offered_ids':ids,
          'selected_but_unoffered_ids':[] if offered else ['editable'],
          'ranking':ranking,'budget':16,'catalogue_count':2,'eligible_count':1,
          'selected_count':1,'pending_count':len(pending)})
    previous_sha=None
    if previous:
        previous_path=directory.parent.parent/'round_000'/'semantic'/'semantic_frontier.json'
        write(previous_path,{'selected_ids':[]})
        previous_sha=digest(previous_path)
    stage={'previous_semantic_sha256':previous_sha,'previously_selected':[],
           'semantic_frontier_policy':configuration['semantic_frontier_policy'],
           'selection_policy':'impact','evidence_mode':'baseline'}
    result={'selected_ids':['editable'],'offered_ids':ids,'previous_selected':ids,
            'pending_semantic_count':len(pending),'semantic_frontier_policy':configuration['semantic_frontier_policy']}
    if offered:
        request={'system':'system','prompt':'prompt','offered':{'C0':{'candidate':history['editable']}}}
        write(directory/'requests/request_000.json',request)
        write(directory/'completions/request_000/request.json',{'model':'deepseek-v4-flash',
              'messages':[{'role':'system','content':'system'},{'role':'user','content':'prompt'}]})
    return directory,stage,configuration,history,{'editable'} if previous else set(),previous_sha,identity,result


def test_eligible_queue_does_not_require_uneditable_candidates_to_fill_budget(tmp_path):
    args=fixture(tmp_path)
    assert verify_semantic_frontier(*args)[0]


def test_unoffered_opportunity_stays_pending_and_not_previously_served(tmp_path):
    args=fixture(tmp_path,offered=False,previous=True)
    assert verify_semantic_frontier(*args)[0]


def test_unoffered_candidate_cannot_be_marked_served(tmp_path):
    args=fixture(tmp_path,offered=False)
    path=args[0]/'semantic_frontier.json';value=json.loads(path.read_text())
    value['selected_ids']=['editable'];write(path,value)
    assert not verify_semantic_frontier(*args)[0]


def test_provider_wire_must_match_the_prepared_prompt(tmp_path):
    args=fixture(tmp_path)
    path=args[0]/'completions/request_000/request.json';value=json.loads(path.read_text())
    value['messages'][1]['content']='different prompt';write(path,value)
    with pytest.raises(AssertionError,match='Provider wire'):
        verify_semantic_frontier(*args)
