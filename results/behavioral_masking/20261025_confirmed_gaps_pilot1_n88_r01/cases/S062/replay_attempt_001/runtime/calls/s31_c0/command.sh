cd /app && cat > /tmp/test_death.py <<'PY'
from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer
import time, threading
context.log_level = 'error'

l = listen(0)
r = remote('localhost', l.lport)
l.wait_for_connection()
print('l.sock closed?', getattr(l,'sock',None))
m1 = TubeMultiplexer(l)
m2 = TubeMultiplexer(r)
c = m1.open_channel()
p = m2.accept_channel(timeout=3)
print('opened')
# check reader threads
print('m2 reader alive', m2._reader_thread.is_alive())
# close underlying directly
l.close()
time.sleep(0.5)
print('after l.close: m2._closed =', m2._closed)
print('reader alive', m2._reader_thread.is_alive())
print('p connected', p.connected())
try:
    print('recv result:', p.recv(timeout=1))
except EOFError as e:
    print('EOFError OK')
except Exception as e:
    print('other', type(e).__name__, e)
m2.close()
PY
python /tmp/test_death.py