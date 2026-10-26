cd /app && python /tmp/test_mux.py >/dev/null 2>&1 && echo "basic OK" ; python /tmp/test_mux_full.py >/dev/null 2>&1 && echo "full OK"; python /tmp/test_flow.py >/dev/null 2>&1 && echo "flow OK"; python /tmp/test_concurrency.py >/dev/null 2>&1 && echo "concurrency OK"; python /tmp/test_edge.py >/dev/null 2>&1 && echo "edge (recvall omitted)"; timeout 30 python - <<'PY'
from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer
import time
context.log_level='error'
l,r = None, None
l=listen(0); r=remote('localhost', l.lport); l.wait_for_connection()
m1=TubeMultiplexer(l); m2=TubeMultiplexer(r)
c=m1.open_channel(); p=m2.accept_channel(timeout=3)
c.send(b'hello'); c.send(b'world'); c.shutdown('send')
data=p.recvall(timeout=2)
assert data==b'helloworld'
m1.close(); m2.close()
print("recvall OK")
PY