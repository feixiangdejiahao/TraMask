cd /app && timeout 30 python - <<'PY'
from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer
import time, threading, random
context.log_level='error'

l=listen(0); r=remote('localhost', l.lport); l.wait_for_connection()
m1=TubeMultiplexer(l, high_water_mark=4096, low_water_mark=1024)
m2=TubeMultiplexer(r, high_water_mark=4096, low_water_mark=1024)
c=m1.open_channel(); p=m2.accept_channel(timeout=5)
c.settimeout(30); p.settimeout(30)

errors=[]
def sender():
    try:
        random.seed(1)
        for j in range(1000):
            payload = b'x' * (random.randint(1,500))
            c.send(payload)
    except Exception as e:
        errors.append(('s', type(e).__name__, str(e)))
def receiver():
    try:
        random.seed(1)
        for j in range(1000):
            expected = b'x' * (random.randint(1,500))
            got = p.recvn(len(expected), timeout=10)
            if got != expected:
                errors.append(('r', 'mismatch', j, len(got), len(expected)))
                return
    except Exception as e:
        errors.append(('r', type(e).__name__, str(e)))

t1=threading.Thread(target=sender); t1.start()
t2=threading.Thread(target=receiver); t2.start()
t1.join(30); t2.join(30)
print('errors:', errors[:5] if errors else 'NONE')
print('alive', t1.is_alive(), t2.is_alive())
print('stats', c.stats, p.stats)
m1.close(); m2.close()
print('done')
PY