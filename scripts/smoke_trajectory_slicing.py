#!/usr/bin/env python3
"""Real Docker/Git integration of collection, B/D and trajectory slicing."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from eviweave.artifacts import read_json,write_json
from eviweave.collection import collect_tests
from eviweave.history import history_records,read_context
from eviweave.replay.container import Container,open_container
from eviweave.slicing import TrajectorySlicer,slice_targets


def git(root,*args):return subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True).stdout


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True)
    fixture=out/'fixture';fixture.mkdir();(fixture/'.gitignore').write_text('__pycache__/\n*.pyc\n')
    old='def operation(x):\n    return x + 1\n';new='def operation(x):\n    return x + 2  # current\n'
    (fixture/'impl.py').write_text(old)
    git(fixture,'init','-q');git(fixture,'config','user.name','Research');git(fixture,'config','user.email','research@example.invalid')
    git(fixture,'add','.');git(fixture,'commit','-qm','base');base=git(fixture,'rev-parse','HEAD').decode().strip()
    retained='import unittest\nfrom impl import operation\nclass Check(unittest.TestCase):\n    def test_value(self):\n        self.assertEqual(operation(3), 5)\n'
    (fixture/'impl.py').write_text(new);(fixture/'test_retained.py').write_text(retained);(fixture/'state.json').write_text('{"value":4}')
    git(fixture,'add','.');patch=git(fixture,'diff','--cached','--binary',base);git(fixture,'reset','--hard',base)
    checkpoint=read_json(ROOT/'results/behavioral_masking/20261101_step_a_simplification_r02/live_collect/checkpoint.json')
    with open_container(checkpoint['image_id'],checkpoint['head'],out/'prepare') as runtime:
        # This is a disposable container, never the original checkpoint.
        runtime.control(['sh','-c','rm -rf /app && mkdir /app'])
        archive=io.BytesIO()
        def owner(info):
            info.uid=info.gid=0;info.uname=info.gname='root';return info
        with tarfile.open(fileobj=archive,mode='w') as bundle:bundle.add(fixture,arcname='.',filter=owner)
        Container.docker(['cp','-',runtime.name+':/app'],input_bytes=archive.getvalue());image=runtime.checkpoint()
    raw=out/'inputs';raw.mkdir();(raw/'instruction.md').write_text('Change `operation(x)` to add two. Preserve validation of prior and current states.\n')
    (raw/'model.patch').write_bytes(patch)
    (raw/'task.toml').write_text('[metadata]\nbase_commit_hash="'+base+'"\n[environment]\ndocker_image="'+image['image_id']+'"\n')
    transient='from impl import operation\nfrom pathlib import Path\nassert operation(3) == 4\nPath("/app/state.json").write_text(\'{"value":4}\')\nprint("old-pass")\n'
    commands=["cat >/tmp/eviweave-old-check.py <<'PY'\n"+transient+"PY\nPYTHONPATH=/app python3 /tmp/eviweave-old-check.py; rm /tmp/eviweave-old-check.py",
              "cat > /app/impl.py <<'PY'\n"+new+"PY\ncat >/app/test_retained.py <<'PY'\n"+retained+"PY\ncd /app && git add . && git commit -qm submitted",
              'cd /app && python3 -m unittest -v test_retained',
              "cd /app && printf 'from impl import operation\\nassert operation(4) == 6\\nprint(\"stdin-pass\")\\n' | PYTHONPATH=/app python3 -"]
    steps=[{'step_id':i,'tool_calls':[{'function_name':'bash','arguments':{'command':c}}],
            'observation':{'results':[{'content':json.dumps({'returncode':0,'output':''})}]}} for i,c in enumerate(commands)]
    write_json(raw/'trajectory.json',{'steps':steps})
    result=collect_tests({'id':'trajectory-smoke','image':image['image_id'],'base_commit':base},raw,out/'replay')
    assert result['state_validation_passed']
    assert not result['returncode_differences'] and not result['timeouts']
    observed_container=read_json(out/'replay/runtime/container.json')['name']
    with open_container(result['checkpoint']['image_id'],result['checkpoint']['head'],out/'check_checkpoint') as frozen:
        frozen.control(['test','!','-e','/tmp/'+observed_container])
    manifest_path=Path(result['step_a']['manifest']);manifest=read_json(manifest_path);slicer=TrajectorySlicer(manifest_path)
    source=next(m for m,v in slicer.trajectory.materials.items() if v['kind']=='file' and v['path']=='/tmp/eviweave-old-check.py' and
                v['sha256']==hashlib.sha256(transient.encode()).hexdigest())
    a=transient.encode().index(b'operation(3)');ref=str(slicer.trajectory.path)+'#/materials/'+source
    views=slicer.location(ref,a,a+len('operation(3)'));assert views
    text='\n'.join(slicer.cache[(f['path'],slicer.trajectory.materials[f['material']]['sha256'])].raw[a:b].decode()
                   for v in views if 'files' in v for f in v['files'] for a,b in f['ranges'])
    assert 'return x + 1' in text and 'return x + 2' not in text
    assert '/tmp/eviweave-old-check.py' not in slicer.trajectory.data['submitted']
    records=history_records(manifest_path)
    assert any(r['text']==transient for r in records)
    assert any('stdin-pass' in r['text'] and '#/materials/' in r['source'] for r in records)
    assert all(r['text'] in read_context(r['source']) for r in records)
    write_json(out/'old_execution_slice.json',views)
    batch=slice_targets(manifest_path,out/'slicing')
    assert batch['entry_groups'] and batch['retained_B_records']==len(records)
    summary={'submission_state_matches':True,'observed_actions':len(commands),'file_versions':len(manifest['source_versions']),
             'observer_scratch_excluded_from_checkpoint':True,
             'old_deleted_test_recovered':True,'old_implementation_used_for_old_execution':True,'stdin_program_indexed':True,
             'B_sources_read_back':len(records),'batch':batch,'new_llm_calls':0}
    write_json(out/'verification.json',summary)
    print({k:v for k,v in summary.items() if k!='batch'})


if __name__=='__main__':main()
