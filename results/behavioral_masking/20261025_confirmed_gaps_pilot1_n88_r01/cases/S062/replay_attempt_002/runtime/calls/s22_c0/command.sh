cd /app && cat > /tmp/test_mux.py <<'PY'
from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer, MuxChannel
import time, threading

context.log_level = 'error'

def make_pair():
    l = listen(0)
    r = remote('localhost', l.lport)
    l.wait_for_connection()
    return l, r

# Basic channel open/close
l, r = make_pair()
m1 = TubeMultiplexer(l)
m2 = TubeMultiplexer(r)
c1 = m1.open_channel()
c2 = m2.accept_channel(timeout=3)
print('channel ids', c1.channel_id, c2.channel_id)
print('stats', c1.stats, c2.stats)
c1.send(b'hello world')
print('recv:', c2.recv())
print('stats after', c1.stats, c2.stats)
c1.close()
try:
    c1.send(b'x')
except EOFError:
    print('local send after close -> EOFError OK')
try:
    c2.recv()
except EOFError:
    print('remote recv after close -> EOFError OK')
try:
    c2.send(b'x')
except EOFError:
    print('remote send after close -> EOFError OK')
print('connected', c1.connected(), c2.connected())
m1.close(); m2.close()
print('basic OK')
PY
python /tmp/test_mux.py