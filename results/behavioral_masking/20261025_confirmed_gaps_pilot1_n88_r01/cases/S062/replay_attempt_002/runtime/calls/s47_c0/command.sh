cd /app && cat > /tmp/test_misc.py <<'PY'
from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer, MuxChannel
import time
context.log_level = 'error'

# mux() method
l = listen(0); r = remote('localhost', l.lport); l.wait_for_connection()
m1 = l.mux(max_channels=10, high_water_mark=100, low_water_mark=10)
m2 = r.mux(max_channels=10, high_water_mark=100, low_water_mark=10)
assert isinstance(m1, TubeMultiplexer)
assert m1.max_channels == 10
print('mux() method OK')
c1 = m1.open_channel(); c2 = m2.accept_channel(timeout=3)
assert isinstance(c1, MuxChannel)
from pwnlib.tubes.tube import tube
assert isinstance(c1, tube)
print('MuxChannel subclass of tube OK')
m1.close(); m2.close()

# open_channel timeout with silent peer
p = process(['/bin/sleep', '3'])
try:
    m = TubeMultiplexer(p)
    t0 = time.time()
    try:
        m.open_channel(timeout=0.3)
        print('FAIL: no timeout')
    except TimeoutError:
        print('open_channel timeout OK in %.2fs' % (time.time()-t0))
    m.close()
except Exception as e:
    print('process test error', type(e).__name__, e)
try:
    p.close()
except Exception:
    pass

# open_channel on closed mux
l = listen(0); r = remote('localhost', l.lport); l.wait_for_connection()
m1 = TubeMultiplexer(l); m2 = TubeMultiplexer(r)
m1.close()
try:
    m1.open_channel()
    print('FAIL open after close')
except EOFError:
    print('open after close EOFError OK')
m2.close()

# stats frames_sent increments once per send call
l = listen(0); r = remote('localhost', l.lport); l.wait_for_connection()
m1 = TubeMultiplexer(l); m2 = TubeMultiplexer(r)
c1 = m1.open_channel(); c2 = m2.accept_channel(timeout=3)
c1.send(b'one')
c1.send(b'two'*100)
print('frames_sent:', c1.stats['frames_sent'], 'bytes:', c1.stats['bytes_sent'])
assert c1.stats['frames_sent'] == 2
d1 = c2.recv(); d2 = c2.recv()
print('frames_received:', c2.stats['frames_received'], 'bytes:', c2.stats['bytes_received'])
assert c2.stats['frames_received'] == 2
assert d1 == b'one' and d2 == b'two'*100
print('stats OK')
m1.close(); m2.close()
print('MISC DONE')
PY
python /tmp/test_misc.py