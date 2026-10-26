cd /app && cat > /tmp/test_debug5.py <<'PY'
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

start = time.time()
def log(msg):
    with open('/tmp/mux_debug.log','a') as f:
        f.write('%.3f %s\n' % (time.time()-start, msg))

orig_handle_data = TubeMultiplexer._handle_data
def handle_data_log(self, channel_id, payload):
    log('READY data ch%d len%d' % (channel_id, len(payload)))
    orig_handle_data(self, channel_id, payload)
    log('DONE data ch%d' % channel_id)
TubeMultiplexer._handle_data = handle_data_log

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
timeout 40 python /tmp/test_debug5.py
echo "=== log around gaps ==="
python - <<'PY'
import re
prev=None
lines=open('/tmp/mux_debug.log').read().splitlines()
for line in lines:
    t=float(line.split()[0])
    if prev is not None and t-prev>1.0:
        print('GAP %.3f' % (t-prev), line)
    prev=t
# show first 40 and last 20
print('--- first 30 ---')
print('\n'.join(lines[:30]))
print('--- last 20 ---')
print('\n'.join(lines[-20:]))
print('total lines', len(lines))
PY