python3 -I -c '
import hashlib,json,sys
data=open(sys.argv[1],'"'"'rb'"'"').read();actual=hashlib.sha256(data).hexdigest()
print(json.dumps({'"'"'path'"'"':sys.argv[1],'"'"'bytes'"'"':len(data),'"'"'sha256'"'"':actual}))
if actual!=sys.argv[2]:raise RuntimeError('"'"'docker_copy_bytes_changed'"'"')
' /tmp/tramask-f90052dda2f547bd9954/test.patch d29c3c01914689b8d561a10fa4d7651ab81a828daae8eae95f04aee0daa91d2a