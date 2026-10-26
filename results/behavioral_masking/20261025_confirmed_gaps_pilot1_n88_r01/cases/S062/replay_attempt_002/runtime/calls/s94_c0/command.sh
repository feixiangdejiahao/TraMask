cd /app && timeout 30 python - <<'PY'
from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer
import time, threading
context.log_level='error'

l=listen(0); r=remote('localhost', l.lport); l.wait_for_connection()
m1=TubeMultiplexer(l); m2=TubeMultiplexer(r)
c=m1.open_channel(); p=m2.accept_channel(timeout=3)

print('can_recv before:', p.can_recv(timeout=0.1))
c.send(b'hello\n')
print('can_recv after:', p.can_recv(timeout=1))
print('recvuntil:', p.recvuntil(b'\n'))

# recvline with a fresh line
c.send(b'world\n')
print('recvline:', p.recvline())

# wait_for_close
c2=m1.open_channel(); p2=m2.accept_channel(timeout=3)
def closer():
    time.sleep(0.2); c2.close()
t=threading.Thread(target=closer); t.daemon=True; t.start()
t0=time.time()
p2.wait_for_close(timeout=2)
print('wait_for_close took %.2f' % (time.time()-t0), 'connected:', p2.connected())

m1.close(); m2.close()
print('API TESTS OK')
PY