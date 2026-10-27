
import base64,hashlib,json,os,pathlib,subprocess
paths=['tests/test_typeddicts.py', 'tests/test_unions.py', 'tests/typeddicts.py', 'tests/conftest.py', 'conftest.py', 'pyproject.toml']
base='6bc4708fb9b2ac52d9a18997e923da6a58916102'
root=pathlib.Path('/app');out={'files':{},'test_bodies_executed':False}
env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null','GIT_OPTIONAL_LOCKS':'0'}
def git(*args):
 p=subprocess.run(['git','-c','safe.directory=/app','-c','core.fsmonitor=false','-C','/app',*args],env=env,capture_output=True)
 return {'returncode':p.returncode,'stdout':p.stdout.decode(errors='replace'),'stderr':p.stderr.decode(errors='replace')}
out['head']=git('rev-parse','HEAD');out['tracked_status']=git('status','--short');out['base_diff']=git('diff',base,'HEAD','--',*paths)
for path in paths:
 p=root/path
 if p.is_symlink():out['files'][path]={'status':'symlink_not_followed'};continue
 if not p.exists():out['files'][path]={'status':'missing'};continue
 raw=p.read_bytes();out['files'][path]={'status':'read','bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'content_base64':base64.b64encode(raw).decode(),'diff_from_base':git('diff',base,'HEAD','--',path)}
print(json.dumps(out))
