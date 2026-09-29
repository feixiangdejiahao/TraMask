"""The presentation driver dispatches fixed input once and resumes honestly."""
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from relation_search.checkpoint import digest, read, write
from scripts import run_source_declarations_ablation as driver


def prepared(tmp_path, cases=('A','B')):
    output = tmp_path/'arm'
    frozen = tmp_path/'frozen'
    dispatch = frozen/'scripts/relation_search_semantics.py'
    provider = frozen/'relational_gap/provider.py'
    converter = tmp_path/'converter.py'
    for path in (dispatch,provider,converter):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('# Frozen input for a mocked subprocess; never executed.\n')
    protocol = dict(cases=list(cases),code_sha256={str(converter):digest(converter)},
                    frozen_driver=str(dispatch),frozen_driver_sha256=digest(dispatch),provider_sha256=digest(provider))
    write(output/'stage.json',protocol)
    records = []
    for case in cases:
        directory = output/case
        request = dict(system='fixed system',prompt='fixed prompt '+case,thinking='enabled')
        request['id'] = hashlib.sha256(request['prompt'].encode()).hexdigest()
        path = directory/'request.json'
        write(path,request)
        settings = dict(model='deepseek-v4-flash',temperature=0,max_tokens=16384,
                        stream=False,response_format={'type':'json_object'},thinking={'type':'enabled'})
        preview = {**settings,'messages':[dict(role='system',content=request['system']),dict(role='user',content=request['prompt'])]}
        write(directory/'wire_preview.json',preview)
        records.append(dict(case=case,candidate_id='candidate_'+case,request=str(path),request_sha256=digest(path),
            wire_preview_sha256=digest(directory/'wire_preview.json'),model_settings=settings,
            command=[str(frozen/'.venv/bin/python'),str(dispatch),'complete','--input',str(path),'--output',str(directory/'completion')]))
    write(output/'ready.json',dict(status='ready',prepared=len(cases),expected=len(cases),pending=[],records=records))
    return output, records


def completion(row, *, status='complete', wire=True, validation=True):
    directory = Path(row['request']).parent
    destination = directory/'completion'
    destination.mkdir(exist_ok=True)
    if wire:
        write(destination/'request.json',read(directory/'wire_preview.json'))
    manifest = dict(status=status,request_id=read(Path(row['request']))['id'],
                    request_sha256=digest(destination/'request.json') if wire else '0'*64,
                    external_model_calls=1,usage={'prompt_tokens':10,'completion_tokens':5})
    write(destination/'manifest.json',manifest)
    if validation:
        write(destination/'validation.json',{'revisions':[],'decisions':[]})
    return SimpleNamespace(returncode=0,stdout='recorded output',stderr='')


def test_dispatches_each_case_once_and_resumes_without_losing_returncode(tmp_path,monkeypatch):
    output, rows = prepared(tmp_path)
    calls = []
    def fake(command,**kwargs):
        row = next(row for row in rows if row['command']==command)
        calls.append(row['case'])
        return completion(row)
    monkeypatch.setattr(driver.subprocess,'run',fake)
    driver.run(output)
    before = read(output/'execution_results.json')
    assert calls==['A','B'] and all(row['driver_returncode']==0 for row in before)
    assert read(output/'execution_complete.json')['complete']==2
    driver.run(output)
    assert calls==['A','B']
    assert read(output/'execution_results.json')==before


@pytest.mark.parametrize('status',['prepared','dispatching','unknown_status',None])
def test_existing_unfinished_or_unknown_status_never_retries(tmp_path,monkeypatch,status):
    output, rows = prepared(tmp_path)
    completion(rows[0],status=status)
    monkeypatch.setattr(driver.subprocess,'run',lambda *a,**k:pytest.fail('must not dispatch'))
    with pytest.raises(ValueError):
        driver.run(output)
    assert not (output/'execution_complete.json').exists()


def test_complete_manifest_requires_wire_and_correct_wire_hash(tmp_path,monkeypatch):
    output, rows = prepared(tmp_path)
    completion(rows[0],wire=False)
    monkeypatch.setattr(driver.subprocess,'run',lambda *a,**k:pytest.fail('must not dispatch'))
    with pytest.raises(ValueError):
        driver.run(output)
    completion(rows[0])
    path = output/'A/completion/manifest.json'
    record = read(path)
    record['request_sha256']='0'*64
    write(path,record)
    with pytest.raises(ValueError):
        driver.run(output)


def test_fresh_incomplete_attempt_is_preserved_and_stops_further_dispatch(tmp_path,monkeypatch):
    output, rows = prepared(tmp_path)
    calls=[]
    def fake(command,**kwargs):
        row=next(row for row in rows if row['command']==command)
        calls.append(row['case'])
        return completion(row,status='prepared',validation=False)
    monkeypatch.setattr(driver.subprocess,'run',fake)
    with pytest.raises((ValueError,RuntimeError)):
        driver.run(output)
    assert calls==['A'] and (output/'A/completion/manifest.json').exists()
    assert read(output/'execution_results.json')[0]['status']=='prepared'
    assert not (output/'execution_complete.json').exists()


def test_preview_messages_are_checked_before_any_dispatch(tmp_path,monkeypatch):
    output, rows=prepared(tmp_path)
    request=read(output/'A/request.json')
    request['system']='unexpected system'
    write(output/'A/request.json',request)
    ready=read(output/'ready.json')
    ready['records'][0]['request_sha256']=digest(output/'A/request.json')
    write(output/'ready.json',ready)
    monkeypatch.setattr(driver.subprocess,'run',lambda *a,**k:pytest.fail('must not dispatch'))
    with pytest.raises(ValueError):
        driver.run(output)


def test_recorded_provider_error_is_terminal_without_retry(tmp_path,monkeypatch):
    output, rows=prepared(tmp_path)
    completion(rows[0],status='error',validation=False)
    calls=[]
    def fake(command,**kwargs):
        row=next(row for row in rows if row['command']==command)
        calls.append(row['case'])
        return completion(row)
    monkeypatch.setattr(driver.subprocess,'run',fake)
    driver.run(output)
    assert calls==['B']
    assert [row['status'] for row in read(output/'execution_results.json')]==['error','complete']
    assert read(output/'execution_complete.json')['complete']==1
