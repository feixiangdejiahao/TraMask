cd /app && cat > /tmp/test_debug4.py <<'PY'
from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer, MuxChannel
import time, threading, random, sys, traceback
context.log_level='error'

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
            ch = c1s[idx]
            pch = c2s[idx]
            print('sender stats', ch.stats)
            print('receiver stats', pch.stats)
            print('sender _flow_paused', ch._flow_paused, 'send_eof', ch._send_eof, 'closed', ch._closed)
            print('receiver _flow_paused_notified', pch._flow_paused_notified, 'recv_eof', pch._recv_eof, 'closed', pch._closed)
            print('receiver _recv_buffer size', len(pch._recv_buffer), 'tube buffer size', len(pch.buffer))
            print('m1 channels', sorted(m1.channels))
            print('m2 channels', sorted(m2.channels))
            print('m1 _closing_ids', m1._closing_ids)
            print('m2 _closing_ids', m2._closing_ids)
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
timeout 40 python /tmp/test_debug4.py