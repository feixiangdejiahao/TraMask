cd /app && cat > /tmp/test_flow.py <<'PY'
from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer
import time, threading
context.log_level = 'error'

def make_pair():
    l = listen(0)
    r = remote('localhost', l.lport)
    l.wait_for_connection()
    return l, r

l,r = make_pair()
m1 = TubeMultiplexer(l, high_water_mark=1000, low_water_mark=100)
m2 = TubeMultiplexer(r, high_water_mark=1000, low_water_mark=100)
c1 = m1.open_channel()
c2 = m2.accept_channel(timeout=3)
c1.settimeout(0.3)

# Send until flow control kicks in
sent = 0
try:
    for i in range(100000):
        c1.send(b'x'*100)
        sent += 100
except TimeoutError:
    print('TimeoutError after sending', sent, 'bytes -> flow control OK')
except Exception as e:
    print('FAIL wrong exception', type(e).__name__, e)
else:
    print('FAIL: never blocked')

# Drain receiver; should trigger resume
time.sleep(0.1)
received = 0
try:
    while True:
        d = c2.recv(timeout=0.1)
        if not d:
            break
        received += len(d)
except EOFError:
    pass
print('received', received, 'bytes')

# Now sender should be unblocked
try:
    c1.send(b'resume-test')
    print('send after drain OK')
except TimeoutError:
    print('FAIL still paused')
except Exception as e:
    print('FAIL', type(e).__name__, e)

# Verify remote received it
print('peer got:', c2.recv())
m1.close(); m2.close()

# ---- flow control independent per channel ----
print("== independent flow ==")
l,r = make_pair()
m1 = TubeMultiplexer(l, high_water_mark=1000, low_water_mark=100)
m2 = TubeMultiplexer(r, high_water_mark=1000, low_water_mark=100)
c1 = m1.open_channel(); p1 = m2.accept_channel(timeout=3)
c2 = m1.open_channel(); p2 = m2.accept_channel(timeout=3)
c1.settimeout(0.3)
c2.settimeout(0.3)

# Fill channel 1's buffer to trigger pause
try:
    for i in range(100000):
        c1.send(b'x'*100)
except TimeoutError:
    print('c1 paused OK')
except Exception as e:
    print('FAIL c1', e)

# Channel 2 should still be able to send
p2.send(b'hello on c2')
print('c2 send while c1 paused OK')
print('c2 peer recv:', c2.recv(timeout=1))

# Channel 1 still blocked
try:
    c1.send(b'y'*100)
    print('FAIL c1 should still be paused')
except TimeoutError:
    print('c1 still paused OK')

# Drain channel 1 -> resumes
d = p1.recv(4096)
c1.send(b'after resume')
print('c1 resumed OK:', p1.recv())
m1.close(); m2.close()
print('FLOW TESTS DONE')
PY
python /tmp/test_flow.py