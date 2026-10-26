cd /app && python - <<'PYEOF'
path = 'pwnlib/tubes/mux.py'
s = open(path).read()
old = '''    def _recv_data_chunk(self, timeout=tube.default):
        """Block until a chunk is available or the timeout elapses."""
        timeout = self._get_timeout_seconds(timeout)
'''
new = '''    def _recv_data_chunk(self, timeout=tube.default):
        """Block until a chunk is available or the timeout elapses."""
        if timeout is tube.default:
            timeout = self.timeout
        else:
            timeout = self._get_timeout_seconds(timeout)
'''
assert old in s
s = s.replace(old, new, 1)
open(path,'w').write(s)
print("patched timeout default")
PYEOF
timeout 15 python - <<'EOF'
import time
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(); m2=s.mux()
c1=m1.open_channel(1, timeout=1); c2=m2.accept_channel(timeout=1)
c2.settimeout(0.1)
t0=time.time()
print("recv no data:", c2.recv(), "elapsed", round(time.time()-t0,2))
m1.close(); m2.close()
EOF