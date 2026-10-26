python3 -I -c '
import hashlib,json,sys
data=open(sys.argv[1],'"'"'rb'"'"').read();actual=hashlib.sha256(data).hexdigest()
print(json.dumps({'"'"'path'"'"':sys.argv[1],'"'"'bytes'"'"':len(data),'"'"'sha256'"'"':actual}))
if actual!=sys.argv[2]:raise RuntimeError('"'"'docker_copy_bytes_changed'"'"')
' /tmp/tramask-21d643f5b484433aa0e9/implementation.patch 0d27a348aeae4444f5fb49dbf05c4027ed668b117dc8d3bf275ea99e9433a6cb