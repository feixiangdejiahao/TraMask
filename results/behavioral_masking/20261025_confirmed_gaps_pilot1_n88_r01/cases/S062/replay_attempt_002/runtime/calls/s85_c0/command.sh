cd /app && cat > /tmp/test_debug10.py <<'PY'
from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer, MuxChannel
import time, threading, random
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

start=time.time()
def tid(): return threading.current_thread().name
def log(msg):
    with open('/tmp/mux_debug.log','a') as f:
        f.write('%.3f %s %s\n' % (time.time()-start, tid(), msg))

orig_recv_raw = MuxChannel.recv_raw
def recv_raw_log(self, numb, *a):
    with self._cond:
        buflen = len(self._recv_buffer)
    if self.channel_id==2:
        log('ENTER recv_raw buf=%d' % buflen)
    t0=time.time()
    res = orig_recv_raw(self, numb, *a)
    if self.channel_id==2:
        log('EXIT recv_raw -> %s after %.3f' % ('None' if res is None else len(res), time.time()-t0))
    return res
MuxChannel.recv_raw = recv_raw_log

def sender(idx):
    threading.current_thread().name = 'sender-%d' % idx
    random.seed(idx)
    for j in range(100):
        c1s[idx].send(bytes([idx])*(random.randint(1,500)))
    log('SENDER %d done' % idx)

def receiver(idx):
    threading.current_thread().name = 'receiver-%d' % idx
    random.seed(idx)
    for j in range(100):
        expected = bytes([idx])*(random.randint(1,500))
        got = c2s[idx].recvn(len(expected), timeout=8)
        if got != expected:
            log('MISMATCH %d %d' % (idx, j))
            return
    log('RECEIVER %d done' % idx)

threads=[]
for i in range(N):
    t=threading.Thread(target=sender,args=(i,)); t.start(); threads.append(t)
    t=threading.Thread(target=receiver,args=(i,)); t.start(); threads.append(t)
for t in threads:
    t.join(30)
print('done')
m1.close(); m2.close()
PY
rm -f /tmp/mux_debug.log
timeout 40 python /tmp/test_debug10.py
echo "=== ch2 tail ==="
grep "ch2" /tmp/mux_debug.log | tail -20