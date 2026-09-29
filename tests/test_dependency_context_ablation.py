import copy
import hashlib
import json

import pytest

from relation_search.checkpoint import write
from scripts.run_dependency_context_ablation import sample_requests, without_dependency_evidence


def request(identifier):
    prompt = dict(issue='Required behavior.', language='python', candidates=[dict(
        candidate='C0', modified_test='def test_value():\n    assert read(2) == 1',
        input_changes=[dict(before='1',after='2')], assertions=[dict(id='A0',code='assert read(2) == 1')],
        dependency_evidence=dict(rendered='SOURCE declaration and binding', status='ready'))])
    return dict(id=identifier, system='The same judgment task.',prompt=json.dumps(prompt),
        thinking='enabled',offered={'C0':{'candidate':{'id':identifier,'edits':['retained']}}},
        source_prepared='same/source',analysis_evidence={'C0':{'retained':'local source data'}})


def test_only_dependency_evidence_changes_and_local_execution_metadata_survives():
    original=request('source-candidate'); saved=copy.deepcopy(original)
    result=without_dependency_evidence(original)
    before=json.loads(original['prompt']); after=json.loads(result['prompt'])
    del before['candidates'][0]['dependency_evidence']
    assert before == after
    assert original == saved
    for key in ('system','thinking','offered','source_prepared','analysis_evidence'):
        assert result[key] == original[key]
    assert result['id'] == hashlib.sha256(result['prompt'].encode()).hexdigest()


def test_samples_depend_only_on_candidate_id_and_ignore_recovery_files(tmp_path):
    for index,identifier in enumerate(['gamma','alpha','beta']):
        write(tmp_path/f'request_{index:03d}.json',request(identifier))
    write(tmp_path/'request_000_split_00.json',request('do not resample repeated candidate'))
    rows=sample_requests(tmp_path,2)
    ids=[row['offered']['C0']['candidate']['id'] for _,row in rows]
    assert ids == sorted(['gamma','alpha','beta'],key=lambda x:hashlib.sha256(x.encode()).hexdigest())[:2]


def test_missing_intervention_field_is_not_an_ablation():
    original=request('id');payload=json.loads(original['prompt'])
    del payload['candidates'][0]['dependency_evidence'];original['prompt']=json.dumps(payload)
    with pytest.raises(ValueError,match='lacks dependency'):
        without_dependency_evidence(original)
