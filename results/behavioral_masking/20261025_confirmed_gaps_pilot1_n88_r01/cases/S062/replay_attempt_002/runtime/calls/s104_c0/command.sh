cd /app && timeout 20 python - <<'PY'
from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer
import time
context.log_level='error'
l=listen(0); r=remote('localhost', l.lport); l.wait_for_connection()
m1=TubeMultiplexer(l); m2=TubeMultiplexer(r)
c=m1.open_channel(); p=m2.accept_channel(timeout=3)
c.send(b'hello'); c.send(b'world')
r1=p.recvn(5, timeout=3)
print('r1', repr(r1))
r2=p.recvn(5, timeout=3)
print('r2', repr(r2))
m1.close(); m2.close()
PY