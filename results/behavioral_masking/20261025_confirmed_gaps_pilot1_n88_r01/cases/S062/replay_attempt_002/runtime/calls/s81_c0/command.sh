cd /app && cat > /tmp/test_debug6.py <<'PY'
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

orig_recv_raw = MuxChannel.recv_raw
def recv_raw_log(self, numb, *a):
    with self._cond:
        buflen = len(self._recv_buffer)
    t0=time.time()
    try:
        res = orig_recv_raw(self, numb, *a)
    except Exception as e:
        log('recv_raw ch%d -> EXC %s (buf was %d, waited %.3f)' % (self.channel_id, type(e).__name__, buflen, time.time()-t0))
        raise
    dt=time.time()-t0
    if self.channel_id == 2:
        log('recv_raw ch%d (numb=%d buf=%d) -> %d in %.4f' % (self.channel_id, numb, buflen, 0 if res is None else len(res), dt))
    return res
MuxChannel.recv_raw = recv_raw_log

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
            log('MISMATCH %d %d len got=%d expected=%d' % (idx, j, len(got), len(expected)))
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
timeout 40 python /tmp/test_debug6.py
echo "=== ch2 recv_raw log (first 50) ==="
grep "recv_raw ch2\|MISMATCH 2" /tmp/mux_debug.log | head -50
echo "=== last 20 ==="
grep "recv_raw ch2\|MISMATCH 2" /tmp/mux_debug.log | tail -20