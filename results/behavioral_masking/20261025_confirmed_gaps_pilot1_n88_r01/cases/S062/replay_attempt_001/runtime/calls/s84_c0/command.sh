cd /app && cat > /tmp/test_debug9.py <<'PY'
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

orig_send_raw = MuxChannel.send_raw
def send_raw_log(self, data):
    t0=time.time()
    if self.channel_id==2:
        log('send ch2 START len%d paused=%s' % (len(data), self._flow_paused))
    try:
        res = orig_send_raw(self, data)
    except Exception as e:
        if self.channel_id==2:
            log('send ch2 EXC %s after %.3f' % (type(e).__name__, time.time()-t0))
        raise
    if self.channel_id==2:
        log('send ch2 END len%d after %.3f' % (len(data), time.time()-t0))
    return res
MuxChannel.send_raw = send_raw_log

orig_pause = TubeMultiplexer._handle_pause
def pause_log(self, cid):
    if cid==2:
        log('m1 PAUSE ch2')
    return orig_pause(self, cid)
TubeMultiplexer._handle_pause = pause_log

orig_resume = TubeMultiplexer._handle_resume
def resume_log(self, cid):
    if cid==2:
        log('m1 RESUME ch2')
    return orig_resume(self, cid)
TubeMultiplexer._handle_resume = resume_log

orig_write = TubeMultiplexer._write_frame
def write_log(self, ftype, cid, payload=b''):
    if cid==2 and ftype in (muxmod._PAUSE, muxmod._RESUME, muxmod._DATA):
        log('m2 WRITE type%d ch2 len%d' % (ftype, len(payload)))
    return orig_write(self, ftype, cid, payload)
TubeMultiplexer._write_frame = write_log

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
timeout 40 python /tmp/test_debug9.py
echo "=== ch2 last 40 ==="
grep "ch2\|SENDER 2\|MISMATCH 2" /tmp/mux_debug.log | tail -40