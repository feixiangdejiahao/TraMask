python3 -I -c '
import hashlib,json,sys
data=open(sys.argv[1],'"'"'rb'"'"').read();actual=hashlib.sha256(data).hexdigest()
print(json.dumps({'"'"'path'"'"':sys.argv[1],'"'"'bytes'"'"':len(data),'"'"'sha256'"'"':actual}))
if actual!=sys.argv[2]:raise RuntimeError('"'"'docker_copy_bytes_changed'"'"')
' /app/packages/core/test/prompts/async-autocomplete.test.ts 93fef575a63c958fc596b3fd1167366021cdf28f3f09dfebc715b97c1e67a8b0