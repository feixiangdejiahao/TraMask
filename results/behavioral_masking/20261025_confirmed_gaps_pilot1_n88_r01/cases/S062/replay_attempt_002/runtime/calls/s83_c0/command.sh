cd /app && cat > /tmp/test_debug8.py <<'PY'
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
def log(msg):
    with open('/tmp/mux_debug.log','a') as f:
        f.write('%.3f %s\n' % (time.time()-start, msg))

orig_recvn = MuxChannel.recvn
def recvn_log(self, numb, timeout=None):
    with self._cond:
        blen = len(self.buffer)
        rlen = len(self._recv_buffer)
    if self.channel_id == 2:
        log('recvn ch2 ENTER n=%d buf=%d rbuf=%d timeout=%s' % (numb, blen, rlen, timeout))
    t0=time.time()
    try:
        res = orig_recvn(self, numb, timeout)
    except Exception as e:
        if self.channel_id==2:
            log('recvn ch2 EXC %s after %.3f' % (type(e).__name__, time.time()-t0))
        raise
    if self.channel_id==2:
        log('recvn ch2 EXIT n=%d got=%d dt=%.3f' % (numb, len(res), time.time()-t0))
    return res
MuxChannel.recvn = recvn_log

orig_fill = MuxChannel._fillbuffer
def fill_log(self, timeout=None):
    if self.channel_id == 2:
        log('fill ch2 ENTER timeout=%s buf=%d rbuf=%d stop=%s' % (timeout, len(self.buffer), len(self._recv_buffer), self._stop))
    t0=time.time()
    try:
        res = orig_fill(self, timeout)
    except Exception as e:
        if self.channel_id==2:
            log('fill ch2 EXC %s after %.3f' % (type(e).__name__, time.time()-t0))
        raise
    if self.channel_id==2:
        log('fill ch2 EXIT -> %r dt=%.3f' % (None if res is None else len(res), time.time()-t0))
    return res
MuxChannel._fillbuffer = fill_log

def sender(idx):
    random.seed(idx)
    for j in range(100):
        c1s[idx].send(bytes([idx])*(random.randint(1,500)))
    log('SENDER %d done' % idx)

def receiver(idx):
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
timeout 40 python /tmp/test_debug8.py
echo "=== ch2 tail ==="
grep "ch2" /tmp/mux_debug.log | tail -30