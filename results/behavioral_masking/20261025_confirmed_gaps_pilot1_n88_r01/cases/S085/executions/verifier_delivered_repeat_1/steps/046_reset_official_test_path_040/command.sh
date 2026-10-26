python3 -I -c '
import json,os,shutil,subprocess,sys
path=sys.argv[1];git=['"'"'git'"'"','"'"'-c'"'"','"'"'safe.directory=/app'"'"','"'"'-C'"'"','"'"'/app'"'"','"'"'--literal-pathspecs'"'"']
r=subprocess.run(git+['"'"'ls-tree'"'"','"'"'-z'"'"','"'"'HEAD'"'"','"'"'--'"'"',path],capture_output=True)
sys.stdout.buffer.write(r.stdout);sys.stderr.buffer.write(r.stderr)
print(json.dumps({'"'"'operation'"'"':'"'"'ls-tree'"'"','"'"'path'"'"':path,'"'"'returncode'"'"':r.returncode}),flush=True)
if r.returncode:sys.exit(r.returncode)
if r.stdout:
    r=subprocess.run(git+['"'"'checkout'"'"','"'"'-q'"'"','"'"'HEAD'"'"','"'"'--'"'"',path])
    print(json.dumps({'"'"'operation'"'"':'"'"'checkout'"'"','"'"'path'"'"':path,'"'"'returncode'"'"':r.returncode}),flush=True)
    sys.exit(r.returncode)
target='"'"'/app/'"'"'+path
parent=os.path.dirname(target)
while parent!='"'"'/app'"'"':
    if os.path.islink(parent):raise RuntimeError('"'"'symlink_parent_of_reset_path'"'"')
    parent=os.path.dirname(parent)
if os.path.islink(target) or os.path.isfile(target):os.unlink(target)
elif os.path.isdir(target):shutil.rmtree(target)
elif os.path.lexists(target):raise RuntimeError('"'"'unsupported_reset_path_kind'"'"')
print(json.dumps({'"'"'operation'"'"':'"'"'remove_absent_HEAD_preimage'"'"','"'"'path'"'"':path,'"'"'returncode'"'"':0}),flush=True)
' test/config/fixtures/shard-rebalance/node_modules/.vite/vitest/da39a3ee5e6b4b0d3255bfef95601890afd80709/results.json