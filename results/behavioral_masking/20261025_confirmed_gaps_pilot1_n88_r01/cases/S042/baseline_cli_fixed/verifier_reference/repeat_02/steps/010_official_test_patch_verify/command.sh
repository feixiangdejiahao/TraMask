python3 -I -c '
import hashlib,json,sys
data=open(sys.argv[1],'"'"'rb'"'"').read();actual=hashlib.sha256(data).hexdigest()
print(json.dumps({'"'"'path'"'"':sys.argv[1],'"'"'bytes'"'"':len(data),'"'"'sha256'"'"':actual}))
if actual!=sys.argv[2]:raise RuntimeError('"'"'docker_copy_bytes_changed'"'"')
' /tmp/tramask-904c3b308a5a4fff9a50/test.patch a5702a062000b6c1e717e061bac7e5c1b8423b42ecbd7af34d19cdf596d03b3c