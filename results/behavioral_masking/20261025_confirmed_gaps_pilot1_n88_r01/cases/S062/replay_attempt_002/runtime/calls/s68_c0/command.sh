cd /app && timeout 20 python - <<'PY'
from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer
import time
context.log_level = 'error'

l,r = listen(0), None
r = remote('localhost', l.lport); l.wait_for_connection()
m1=TubeMultiplexer(l); m2=TubeMultiplexer(r)
c=m1.open_channel(); p=m2.accept_channel(timeout=3)
c.send(b'hello')
c.send(b'world')
c.shutdown('send')
data = p.recvall(timeout=2)
print('recvall:', data)
assert data == b'helloworld'
m1.close(); m2.close()
print('recvall OK')
PY