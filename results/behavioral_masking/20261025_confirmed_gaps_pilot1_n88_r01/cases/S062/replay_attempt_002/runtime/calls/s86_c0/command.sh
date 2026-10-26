cd /app && cat > /tmp/test_debug11.py <<'PY'
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
    which = 'm1' if self._mux is m1 else 'm2'
    log('ENTER recv_raw %s cid%d buf=%d' % (which, self.channel_id, buflen))
    t0=time.time()
    res = orig_recv_raw(self, numb, *a)
    log('EXIT recv_raw %s cid%d -> %s after %.3f' % (which, self.channel_id, 'None' if res is None else len(res), time.time()-t0))
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
            log('MISMATCH %d %d' % (idx, j))
            return
    log('RECEIVER %d done' % idx)

for attempt in range(3):
    threads=[]
    for i in range(N):
        t=threading.Thread(target=sender,args=(i,)); t.start(); threads.append(t)
        t=threading.Thread(target=receiver,args=(i,)); t.start(); threads.append(t)
    for t in threads:
        t.join(30)
    if any(open('/tmp/mux_debug.log').read().count('MISMATCH') for _ in [0]):
        break
print('done attempt')
m1.close(); m2.close()
PY
for i in 1 2 3; do
  rm -f /tmp/mux_debug.log
  timeout 40 python /tmp/test_debug11.py >/dev/null 2>&1
  if grep -q MISMATCH /tmp/mux_debug.log; then echo "FAILURE on run $i"; break; fi
  echo "run $i ok"
done
echo "=== recv_raw logs ==="
grep "recv_raw" /tmp/mux_debug.log | tail -30