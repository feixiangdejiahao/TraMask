import copy
import json

from scripts.replay_uniform_second_gate import compatible


def request():
    return dict(candidate_sha256='program',system='judge',thinking='enabled',reasoning_effort='high',max_tokens=16384,
        prompt=json.dumps(dict(modified_test='fixed test',source_analysis='complete helpers')),
        check_ids=['P','Q0'],source_sha256={'source':'sha'},no_execution_outcomes=True,no_evaluation_labels=True)


def test_changed_complete_context_cannot_borrow_a_gate_answer():
    first=request();second=copy.deepcopy(first);wire=json.loads(second['prompt']);wire['source_analysis']='different helper';second['prompt']=json.dumps(wire)
    assert compatible(first,second)=='complete_source_payload_changed'


def test_only_declared_documentation_addition_can_differ():
    first=request();second=copy.deepcopy(first);wire=json.loads(second['prompt']);wire['api_contract_context']={'records':[]};second['prompt']=json.dumps(wire)
    assert compatible(first,second) is None
    second['source_sha256']['source']='changed'
    assert compatible(first,second)=='source_inventory_changed'
