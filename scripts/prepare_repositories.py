"""Materialize only candidate workspaces, never evaluator assets."""
import json, subprocess, tarfile, io
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def run(*args, **kw):
    return subprocess.run(args, check=True, capture_output=True, **kw)
def main():
    records=[]
    for c in json.loads((ROOT/'data/cases.json').read_text()):
        dest=ROOT/'data/cases'/c['id']; repo=dest/'repository'
        if repo.exists(): continue
        run('docker','image','inspect',c['image'])
        name=run('docker','create','--network','none','--entrypoint','sleep',c['image'],'infinity').stdout.decode().strip()
        try:
            run('docker','start',name)
            run('docker','exec',name,'git','-C','/app','config','--global','--add','safe.directory','/app')
            head=run('docker','exec',name,'git','-C','/app','rev-parse','HEAD').stdout.decode().strip()
            if head != c['base_commit']: raise RuntimeError(f"{c['id']}: base mismatch {head}")
            run('docker','cp',str(dest/'model.patch'),name+':/candidate.patch')
            run('docker','exec',name,'git','-C','/app','apply','--whitespace=nowarn','/candidate.patch')
            # Copy versioned files and patch additions; retain developer tests, omit Git metadata.
            names=run('docker','exec',name,'git','-C','/app','ls-files','--cached','--others','--exclude-standard','-z').stdout
            archive=run('docker','exec','-i',name,'tar','-C','/app','--null','--ignore-failed-read','-T','-','-cf','-',input=names).stdout
            repo.mkdir()
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar: tar.extractall(repo,filter='data')
            records.append({'case':c['id'],'base_commit':head,'image':json.loads(run('docker','image','inspect',c['image']).stdout)[0]['Id'],'mode':'base image + submitted candidate patch'})
            print(c['id'], 'materialized',flush=True)
        finally: run('docker','rm','-f',name)
    (ROOT/'results/repositories.json').write_text(json.dumps(records,indent=2))
if __name__=='__main__': main()
