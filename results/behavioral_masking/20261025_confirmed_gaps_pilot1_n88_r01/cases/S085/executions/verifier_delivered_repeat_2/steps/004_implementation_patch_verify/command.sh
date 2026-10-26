python3 -I -c '
import hashlib,json,sys
data=open(sys.argv[1],'"'"'rb'"'"').read();actual=hashlib.sha256(data).hexdigest()
print(json.dumps({'"'"'path'"'"':sys.argv[1],'"'"'bytes'"'"':len(data),'"'"'sha256'"'"':actual}))
if actual!=sys.argv[2]:raise RuntimeError('"'"'docker_copy_bytes_changed'"'"')
' /tmp/tramask-0ee1f0b8924b46268582/implementation.patch 6c919e0d07b254fb0aea08500a32ba4beba497e3cd345eae6d02f687e890ff7c