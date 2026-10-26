cd /app && timeout 20 python - <<'PY'
from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer
import time
context.log_level='error'
# Clean close propagation, no prior half-close
l=listen(0); r=remote('localhost', l.lport); l.wait_for_connection()
m1=TubeMultiplexer(l); m2=TubeMultiplexer(r)
c=m1.open_channel(); p=m2.accept_channel(timeout=3)
c.close()
# wait for close to propagate
for _ in range(50):
    if p.connected() is False:
        break
    time.sleep(0.01)
print('p connected after close:', p.connected())
try:
    p.send(b'x')
    print('FAIL: send did not raise')
except EOFError:
    print('peer send EOFError OK')
m1.close(); m2.close()
PY