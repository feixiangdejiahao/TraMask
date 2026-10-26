cd /app && timeout 12 python - <<'PY'
from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer
import time, socket
context.log_level='error'

l=listen(0); r=remote('localhost', l.lport); l.wait_for_connection()
print('l peer', l.sock.getpeername(), 'r local', r.sock.getsockname())
print('r peer', r.sock.getpeername(), 'l local', l.sock.getsockname())
m1=TubeMultiplexer(l); m2=TubeMultiplexer(r)
c=m1.open_channel(); p=m2.accept_channel(timeout=3)
# Close the listen accepted socket directly via socket.close, bypassing listen.close
sock = l.sock
sock.close()
time.sleep(0.5)
print('m2 closed?', m2._closed)
r.sock.settimeout(1.0)
try:
    print('r.sock.recv:', r.sock.recv(1))
except socket.timeout:
    print('timeout - EOF not detected')
except Exception as e:
    print('err', type(e).__name__, e)
m2.close()
PY
echo "exit $?"