
import base64,hashlib,json,os,pathlib,subprocess
paths=['tests/test_result/test_result_bind.py', 'tests/test_result/test_result_equality.py', 'returns/interfaces/lashable.py', 'returns/result.py', 'setup.cfg', 'pyproject.toml']
base='41607fae1289de2787523c452d75212206b9c7c0'
r=pathlib.Path('/app');out={'files':{}}
env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null','GIT_OPTIONAL_LOCKS':'0'}
def git(*args):
 p=subprocess.run(['git','-c','safe.directory=/app','-c','core.fsmonitor=false','-C','/app',*args],env=env,capture_output=True)
 return {'returncode':p.returncode,'stdout':p.stdout.decode(errors='replace'),'stderr':p.stderr.decode(errors='replace')}
out['head']=git('rev-parse','HEAD');out['tracked_status']=git('status','--short');out['base_diff']=git('diff',base,'HEAD','--',*paths)
for path in paths:
 p=r/path
 if not p.exists():out['files'][path]={'status':'missing'};continue
 if p.is_symlink():out['files'][path]={'status':'symlink_not_followed'};continue
 raw=p.read_bytes();out['files'][path]={'status':'read','bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'content_base64':base64.b64encode(raw).decode(),'diff_from_base':git('diff',base,'HEAD','--',path)}
p=subprocess.run(['python3','-m','pytest','tests/test_result','--collect-only','-q','-o','addopts=','-p','no:cacheprovider'],cwd='/app',capture_output=True,timeout=60)
out['discovery_only']={'argv':['python3','-m','pytest','tests/test_result','--collect-only','-q','-o','addopts=','-p','no:cacheprovider'],'returncode':p.returncode,'stdout':p.stdout.decode(errors='replace'),'stderr':p.stderr.decode(errors='replace'),'test_bodies_executed':False}
print(json.dumps(out))
