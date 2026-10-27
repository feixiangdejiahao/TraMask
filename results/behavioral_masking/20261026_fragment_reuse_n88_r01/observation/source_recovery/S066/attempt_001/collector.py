
import base64,hashlib,json,os,pathlib,subprocess
paths=['test/options/keywordCase.ts', 'test/behavesLikeSqlFormatter.ts', 'test/bigquery.test.ts', 'test/features/pipeSyntax.ts', 'package.json', '.babelrc', 'tsconfig.json']
base='954e5a474b9e3d45ca58f02a3a4eac8e1947acc5'
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
p=subprocess.run(['node','node_modules/jest/bin/jest.js','--listTests','--runInBand','--json','--coverage=false','--cache=false'],cwd='/app',capture_output=True,timeout=60)
out['discovery_only']={'argv':['node','node_modules/jest/bin/jest.js','--listTests','--runInBand','--json','--coverage=false','--cache=false'],'returncode':p.returncode,'stdout':p.stdout.decode(errors='replace'),'stderr':p.stderr.decode(errors='replace'),'test_bodies_executed':False}
print(json.dumps(out))
