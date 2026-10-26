cd /app && cat > /tmp/test_mux2.py <<'PY'
from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer, MuxChannel
import time, threading, traceback

context.log_level = 'debug'

def make_pair():
    l = listen(0)
    r = remote('localhost', l.lport)
    l.wait_for_connection()
    return l, r

l, r = make_pair()
print('made pair')
m1 = TubeMultiplexer(l)
m2 = TubeMultiplexer(r)
print('created muxes')
time.sleep(0.5)
print('channels', m1.channels, m2.channels, 'closed', m1._closed, m2._closed)
c1 = m1.open_channel()
print('opened', c1.channel_id)
c2 = m2.accept_channel(timeout=3)
print('accepted', c2.channel_id)
PY
python /tmp/test_mux2.py 2>&1 | head -60