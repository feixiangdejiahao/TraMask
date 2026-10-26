cd /app && cat > /tmp/test_concurrency.py <<'PY'
from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer
import time, threading, random
context.log_level = 'error'

def make_pair():
    l = listen(0)
    r = remote('localhost', l.lport)
    l.wait_for_connection()
    return l, r

l,r = make_pair()
m1 = TubeMultiplexer(l)
m2 = TubeMultiplexer(r)
N = 8
channels1 = []
channels2 = []
for i in range(N):
    c = m1.open_channel(channel_id=i+1)
    p = m2.accept_channel(timeout=3)
    assert c.channel_id == p.channel_id
    channels1.append(c)
    channels2.append(p)

errors = []
def sender(idx):
    try:
        ch = channels1[idx]
        for j in range(50):
            msg = b'%d:%d:' % (idx, j) + bytes([65 + idx]) * (j % 100)
            ch.send(msg)
    except Exception as e:
        errors.append(('sender', idx, type(e).__name__, str(e)))

def receiver(idx):
    try:
        ch = channels2[idx]
        for j in range(50):
            expected = b'%d:%d:' % (idx, j) + bytes([65 + idx]) * (j % 100)
            got = ch.recvn(len(expected), timeout=5)
            if got != expected:
                errors.append(('recv', idx, 'mismatch', got, expected))
    except Exception as e:
        errors.append(('receiver', idx, type(e).__name__, str(e)))

threads = []
for i in range(N):
    t1 = threading.Thread(target=sender, args=(i,)); t1.start(); threads.append(t1)
    t2 = threading.Thread(target=receiver, args=(i,)); t2.start(); threads.append(t2)
for t in threads:
    t.join(10)

print('errors:', errors[:5] if errors else 'NONE')
print('all threads done')
for i in range(N):
    print(i, channels1[i].stats, channels2[i].stats)
m1.close(); m2.close()
print('CONCURRENCY DONE')
PY
python /tmp/test_concurrency.py