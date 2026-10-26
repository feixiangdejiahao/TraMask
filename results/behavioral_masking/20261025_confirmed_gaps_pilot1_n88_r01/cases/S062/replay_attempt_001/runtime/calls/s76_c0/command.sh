cd /app && cat > /tmp/test_debug_conc.py <<'PY'
from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer
import time, threading, random
context.log_level='error'

l=listen(0); r=remote('localhost', l.lport); l.wait_for_connection()
m1=TubeMultiplexer(l, high_water_mark=4096, low_water_mark=1024)
m2=TubeMultiplexer(r, high_water_mark=4096, low_water_mark=1024)
N=4
c1s=[]; c2s=[]
for i in range(N):
    c=m1.open_channel(channel_id=i+1); p=m2.accept_channel(timeout=5)
    c.settimeout(30); p.settimeout(30)
    c1s.append(c); c2s.append(p)

slow=[]
def sender(idx):
    random.seed(idx)
    for j in range(100):
        c1s[idx].send(bytes([idx])*(random.randint(1,500)))

def receiver(idx):
    random.seed(idx)
    for j in range(100):
        expected = bytes([idx])*(random.randint(1,500))
        t0=time.time()
        got = c2s[idx].recvn(len(expected), timeout=15)
        dt=time.time()-t0
        if dt>1:
            slow.append((idx,j,dt,len(got),len(expected)))
        if got != expected:
            print('MISMATCH', idx, j, len(got), len(expected), 'dt', dt)
            return

threads=[]
for i in range(N):
    t=threading.Thread(target=sender,args=(i,)); t.start(); threads.append(t)
    t=threading.Thread(target=receiver,args=(i,)); t.start(); threads.append(t)
t0=time.time()
for t in threads:
    t.join(40)
print('total time', time.time()-t0)
print('slow reads (>1s):', slow[:20], 'count', len(slow))
for i in range(N):
    print('stats', i, c1s[i].stats['frames_sent'], c2s[i].stats['frames_received'])
m1.close(); m2.close()
PY
timeout 60 python /tmp/test_debug_conc.py