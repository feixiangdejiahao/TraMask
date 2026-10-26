cd /app && timeout 15 python - <<'PY'
from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer
import time, threading, sys
context.log_level='error'

l = listen(0); r = remote('localhost', l.lport); l.wait_for_connection()
m1 = TubeMultiplexer(l); m2 = TubeMultiplexer(r)
c1 = m1.open_channel(); c2 = m2.accept_channel(timeout=3)
c1.send(b'one')
c1.send(b'two'*100)
print('sent')
d1 = c2.recv(timeout=2)
print('d1', d1)
d2 = c2.recv(timeout=2)
print('d2', d2)
print('closing...')
m1.close()
print('m1 closed')
m2.close()
print('m2 closed')
PY
echo "exit $?"