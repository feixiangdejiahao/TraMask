cd /app && cat > /tmp/test_death3.py <<'PY'
from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer
import time
context.log_level = 'error'

l = listen(0)
r = remote('localhost', l.lport)
l.wait_for_connection()
m1 = TubeMultiplexer(l)
m2 = TubeMultiplexer(r)
c = m1.open_channel()
p = m2.accept_channel(timeout=3)
print('reader threads alive', m1._reader_thread.is_alive(), m2._reader_thread.is_alive())
l.close()
time.sleep(0.2)
print('m2 closed?', m2._closed)
print('r connected', r.connected())
try:
    print('direct recvn:', r.recvn(7, timeout=r.maximum))
except EOFError as e:
    print('direct recvn EOFError OK')
except Exception as e:
    print('direct recvn other', type(e).__name__, e)
m2.close()
PY
python /tmp/test_death3.py