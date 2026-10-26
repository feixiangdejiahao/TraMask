cd /app && cat > /tmp/test_debug2.py <<'PY'
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

log_lock = threading.Lock()
def log(msg):
    with log_lock:
        with open('/tmp/mux_debug.log','a') as f:
            f.write('%.3f %s\n' % (time.time(), msg))

orig_send_raw = MuxChannel.send_raw
def send_raw_log(self, data):
    t0=time.time()
    try:
        return orig_send_raw(self, data)
    finally:
        dt=time.time()-t0
        if dt>0.3:
            log('send_raw ch%d took %.3f' % (self.channel_id, dt))
MuxChannel.send_raw = send_raw_log

orig_handle_data = TubeMultiplexer._handle_data
def handle_data_log(self, channel_id, payload):
    t0=time.time()
    orig_handle_data(self, channel_id, payload)
    dt=time.time()-t0
    if dt>0.3:
        log('handle_data ch%d took %.3f' % (channel_id, dt))
TubeMultiplexer._handle_data = handle_data_log

orig_recv_raw = MuxChannel.recv_raw
def recv_raw_log(self, numb, *a):
    t0=time.time()
    try:
        return orig_recv_raw(self, numb, *a)
    finally:
        dt=time.time()-t0
        if dt>0.3:
            log('recv_raw ch%d took %.3f' % (self.channel_id, dt))
MuxChannel.recv_raw = recv_raw_log

def sender(idx):
    random.seed(idx)
    for j in range(100):
        c1s[idx].send(bytes([idx])*(random.randint(1,500)))

def receiver(idx):
    random.seed(idx)
    for j in range(100):
        expected = bytes([idx])*(random.randint(1,500))
        got = c2s[idx].recvn(len(expected), timeout=20)
        if got != expected:
            log('MISMATCH %d %d %d %d' % (idx, j, len(got), len(expected)))
            return

threads=[]
for i in range(N):
    t=threading.Thread(target=sender,args=(i,)); t.start(); threads.append(t)
    t=threading.Thread(target=receiver,args=(i,)); t.start(); threads.append(t)
for t in threads:
    t.join(40)
print('done')
m1.close(); m2.close()
PY
rm -f /tmp/mux_debug.log
timeout 60 python /tmp/test_debug2.py
echo "=== log ==="
sort -u /tmp/mux_debug.log | head -50