"""The prepared overlay runs with the existing phase runner in local subprocesses."""
import json
from pathlib import Path
import shlex
import shutil
import sys

from relation_search.checkpoint import digest, read, write
from scripts.prepare_observed_write_overlay import prepare_group
from scripts.relational_phase_runner import execute_plan
from test_observed_write_runtime import LIBRARY


def test_overlay_executes_original_control_and_exception_variant_with_real_traces(tmp_path):
    source=tmp_path/'source'
    code='''from toy_resource import Resource
def test_case():
    item = Resource()
    try:
        item.advance(FAIL)
    except ValueError:
        pass
    assert item.flag is True
'''
    original=code.replace('FAIL','False')
    generated=code.replace('FAIL','True')
    write(source/'corpus.json',{'sources':{'toy_resource.py':{'code':LIBRARY},
                                         'test_case.py':{'code':original}}})
    artifact=tmp_path/'original_artifact'
    artifact.mkdir()
    phases,mounts=[],[]
    for role,text in [('control',original),('generated',generated)]:
        snapshot=artifact/(role+'.snapshot')
        snapshot.write_text(text)
        staged='.relational_phase_inputs/'+role+'.snapshot'
        mounts.append(dict(source=str(snapshot),target=staged,sha256=digest(snapshot)))
        phases.append(dict(role=role,timeout=15,report={'format':'pytest-junit','path':'junit.xml'},
            command='env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 '+shlex.quote(sys.executable)+
            ' -m pytest -q -c /dev/null --rootdir=. --confcutdir=. -p no:cacheprovider test_case.py'+
            ' --junitxml="$COMBINATION_REPORT_DIR/junit.xml"',
            files=[dict(target='test_case.py',staged=staged,sha256=digest(snapshot))]))
    runner=Path(__file__).resolve().parents[1]/'scripts/relational_phase_runner.py'
    mounts.append(dict(source=str(runner),target='.relational_phase_inputs/runner.py',sha256=digest(runner)))
    item=dict(path='test_case.py',test_name='test_case',id='test_case')
    manifest=artifact/'manifest.json'
    write(manifest,dict(case='toy',original_input=str(source),phases=phases,mounts=mounts,
                       controls=[item],obligations=[item]))
    overlay=tmp_path/'overlay'
    counts=prepare_group(manifest,overlay)
    assert [row['instrumented_q'] for row in counts]==[1,1]
    repository=tmp_path/'repository'
    repository.mkdir()
    (repository/'toy_resource.py').write_text(LIBRARY)
    for mount in read(overlay/'manifest.json')['mounts']:
        destination=repository/mount['target']
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(mount['source'],destination)
    logs=tmp_path/'logs'
    outcomes=execute_plan(read(overlay/'phase_plan.json'),repository=repository,logs=logs)
    assert [row['returncode'] for row in outcomes]==[0,1]
    observations=[]
    for role in ['control','generated']:
        events=[json.loads(line) for line in (logs/role/'observed_writes.jsonl').read_text().splitlines()]
        q=[row for row in events if row['kind']=='assertion_read']
        assert len(q)==1 and q[0]['status']=='observed_within_instrumented_code'
        assert all('phase' not in row for row in events)
        observations.append(q[0])
    assert observations[0]['value']['value'] is True
    assert observations[1]['value']['value'] is False
    assert observations[0]['last_observed_writer']['line']==9
    assert observations[1]['last_observed_writer']['line']==3
