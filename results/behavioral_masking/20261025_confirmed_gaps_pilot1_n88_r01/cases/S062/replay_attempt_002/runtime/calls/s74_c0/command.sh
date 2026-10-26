cd /app && cat > /tmp/test_stress2.py <<'PY'
from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer
import time, threading, random
context.log_level = 'error'

l=listen(0); r=remote('localhost', l.lport); l.wait_for_connection()
m1=TubeMultiplexer(l, high_water_mark=4096, low_water_mark=1024)
m2=TubeMultiplexer(r, high_water_mark=4096, low_water_mark=1024)

N=4
c1s=[]; c2s=[]
for i in range(N):
    c=m1.open_channel(channel_id=i+1)
    p=m2.accept_channel(timeout=5)
    c.settimeout(30)
    p.settimeout(30)
    c1s.append(c); c2s.append(p)

errors=[]
def sender(idx):
    try:
        ch=c1s[idx]
        random.seed(idx)
        for j in range(100):
            payload = bytes([idx]) * (random.randint(1,500))
            ch.send(payload)
    except Exception as e:
        errors.append(('s', idx, type(e).__name__, str(e)))

def receiver(idx):
    try:
        ch=c2s[idx]
        random.seed(idx)
        for j in range(100):
            expected = bytes([idx]) * (random.randint(1,500))
            got = ch.recvn(len(expected), timeout=15)
            if got != expected:
                errors.append(('r', idx, 'mismatch', j, len(got), len(expected)))
                return
    except Exception as e:
        errors.append(('r', idx, type(e).__name__, str(e)))

threads=[]
for i in range(N):
    t=threading.Thread(target=sender,args=(i,)); t.start(); threads.append(t)
    t=threading.Thread(target=receiver,args=(i,)); t.start(); threads.append(t)
for t in threads:
    t.join(40)
print('errors:', errors[:10] if errors else 'NONE')
print('threads alive:', sum(t.is_alive() for t in threads))
for i in range(N):
    print('stats', i, c1s[i].stats['frames_sent'], c1s[i].stats['bytes_sent'], c2s[i].stats['frames_received'], c2s[i].stats['bytes_received'])
m1.close(); m2.close()
print('DONE')
PY
timeout 60 python /tmp/test_stress2.py