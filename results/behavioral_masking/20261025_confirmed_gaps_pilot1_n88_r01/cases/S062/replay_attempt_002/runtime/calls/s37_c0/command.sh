cd /app && timeout 10 python - <<'PY'
from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer
import time, socket
context.log_level='error'

l=listen(0); r=remote('localhost', l.lport); l.wait_for_connection()
m1=TubeMultiplexer(l); m2=TubeMultiplexer(r)
c=m1.open_channel(); p=m2.accept_channel(timeout=3)
print('r sock', r.sock)
l.close(); time.sleep(0.3)
print('r sock after l.close:', r.sock)
r.sock.settimeout(1.0)
try:
    print('direct recv:', r.sock.recv(1))
except socket.timeout:
    print('socket.timeout')
except Exception as e:
    print('err', type(e).__name__, e)
m2.close(); m1.close()
PY
echo "exit $?"