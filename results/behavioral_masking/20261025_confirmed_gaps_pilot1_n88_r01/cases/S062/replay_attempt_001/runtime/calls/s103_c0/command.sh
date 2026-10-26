cd /app && timeout 60 python - <<'PY'
from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer, MuxChannel
from pwnlib.tubes.buffer import Buffer
from pwnlib.tubes.tube import tube
import time
context.log_level='error'

b=Buffer(); b.set_watermarks(high=100, low=50)
assert b.high_water==100 and b.low_water==50 and not b.over_high_water and b.under_low_water
b.add(b'A'*100); assert b.over_high_water and not b.under_low_water
b.get(50); assert not b.over_high_water and b.under_low_water
try: b.set_watermarks(high=1, low=2); assert False
except ValueError: pass

l=listen(0); r=remote('localhost', l.lport); l.wait_for_connection()
m1=l.mux(max_channels=64, high_water_mark=1000, low_water_mark=100)
m2=r.mux(max_channels=64, high_water_mark=1000, low_water_mark=100)
assert isinstance(m1, TubeMultiplexer) and isinstance(m2, TubeMultiplexer)
assert m1.high_water_mark==1000 and m1.low_water_mark==100

c=m1.open_channel(channel_id=7); p=m2.accept_channel(timeout=3)
assert m1.channels[7] is c and m2.channels[7] is p
assert isinstance(c, tube) and isinstance(c, MuxChannel)
assert c.channel_id==7 and p.channel_id==7
assert c.stats=={'bytes_sent':0,'bytes_received':0,'frames_sent':0,'frames_received':0}

c.send(b'hello'); c.send(b'world')
assert p.recvn(5)==b'hello'; assert p.recvn(5)==b'world'
assert c.stats['frames_sent']==2 and c.stats['bytes_sent']==10
assert p.stats['frames_received']==2 and p.stats['bytes_received']==10

c.shutdown('send')
try: c.send(b'x'); assert False
except EOFError: pass
p.send(b'back'); assert c.recvn(4)==b'back'

c.close()
try: c.send(b'x'); assert False
except EOFError: pass
try: p.recv(timeout=2); assert False
except EOFError: pass
try: p.send(b'x'); assert False
except EOFError: pass
assert not c.connected() and not p.connected()

c2=m1.open_channel(channel_id=7); p2=m2.accept_channel(timeout=3)
assert c2.channel_id==7

m1.close(); m2.close()
assert m1.close() is None

l=listen(0); r=remote('localhost', l.lport); l.wait_for_connection()
for bad in [None, 0, 65536, 1.5, True]:
    try: TubeMultiplexer(l, max_channels=bad); assert False
    except ValueError: pass
try: TubeMultiplexer(l, low_water_mark=10, high_water_mark=5); assert False
except ValueError: pass
m=TubeMultiplexer(r)
try: m.open_channel(channel_id=True); assert False
except TypeError: pass
try: m.open_channel(channel_id=0); assert False
except ValueError: pass
m.close(); l.close()
print("FINAL SMOKE TEST PASSED")
PY