cd /app && timeout 10 python - <<'PY'
from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer
import time
context.log_level='error'

l=listen(0); r=remote('localhost', l.lport); l.wait_for_connection()
print('accepter alive before mux', l._accepter.is_alive())
m1=TubeMultiplexer(l); m2=TubeMultiplexer(r)
c=m1.open_channel(); p=m2.accept_channel(timeout=3)
print('accepter alive after mux', l._accepter.is_alive())
m1.close()
time.sleep(0.3)
print('l.sock after m1.close:', getattr(l,'sock',None))
print('accepter alive after close', l._accepter.is_alive())
m2.close()
PY
echo "exit $?"