cd /app && cat > /tmp/test_debug3.py <<'PY'
from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer, MuxChannel
import time, threading, random, sys, traceback
context.log_level='error'
import pwnlib.tubes.mux as muxmod

l=listen(0); r=remote('localhost', l.lport); l.wait_for_connection()
m1=TubeMultiplexer(l, high_water_mark=4096, low_water_mark=1024)
m2=TubeMultiplexer(r, high_water_mark=4096, low_water_mark=1024)
N=4
c1s=[]; c2s=[]
for i in range(N):
    c=m1.open_channel(channel_id=i+1); p=m2.accept_channel(timeout=5)
    c.settimeout(60); p.settimeout(60)
    c1s.append(c); c2s.append(p)

def sender(idx):
    random.seed(idx)
    for j in range(100):
        c1s[idx].send(bytes([idx])*(random.randint(1,500)))

def receiver(idx):
    random.seed(idx)
    for j in range(100):
        expected = bytes([idx])*(random.randint(1,500))
        got = c2s[idx].recvn(len(expected), timeout=8)
        if got != expected:
            print('MISMATCH', idx, j, len(got), len(expected))
            print('m2 closed?', m2._closed)
            print('--- m2 reader stack ---')
            traceback.print_stack(sys._current_frames()[m2._reader_thread.ident])
            print('--- m1 reader stack ---')
            traceback.print_stack(sys._current_frames()[m1._reader_thread.ident])
            return

threads=[]
for i in range(N):
    t=threading.Thread(target=sender,args=(i,)); t.start(); threads.append(t)
    t=threading.Thread(target=receiver,args=(i,)); t.start(); threads.append(t)
for t in threads:
    t.join(30)
print('done')
m1.close(); m2.close()
PY
timeout 40 python /tmp/test_debug3.py 2>&1 | head -60