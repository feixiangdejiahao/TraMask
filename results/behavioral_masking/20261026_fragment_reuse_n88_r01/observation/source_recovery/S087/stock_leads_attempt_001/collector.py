
import base64,hashlib,json,os,pathlib,subprocess
paths=['crates/wasmi/benches/wat/preserve-all-locals.wat', 'crates/wasmi/src/coredump.rs', 'crates/wasmi/tests/coredump.rs', 'crates/wasmi/tests/coredump_details.rs', 'crates/wasmi/tests/coredump_edge.rs', 'crates/wasmi/tests/coredump_reentrant.rs', 'crates/wasmi/tests/integration/func.rs', 'crates/wasmi/tests/parse_coredump.rs', 'crates/wasmi/Cargo.toml', 'crates/wasmi/tests/mod.rs', 'crates/wasmi/tests/integration/mod.rs']
base='e1f76e285b9ad68a952b7cf5297bbb7ab91e6028'
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
