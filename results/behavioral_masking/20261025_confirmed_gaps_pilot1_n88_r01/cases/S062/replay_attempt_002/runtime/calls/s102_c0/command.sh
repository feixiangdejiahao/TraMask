cd /app && timeout 60 python - <<'PY'
from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer, MuxChannel
from pwnlib.tubes.buffer import Buffer
from pwnlib.tubes.tube import tube
import time
context.log_level='error'

print("buffer")
b=Buffer(); b.set_watermarks(high=100, low=50)
assert b.high_water==100 and b.low_water==50 and not b.over_high_water and b.under_low_water
b.add(b'A'*100); assert b.over_high_water and not b.under_low_water
b.get(50); assert not b.over_high_water and b.under_low_water
try: b.set_watermarks(high=1, low=2); assert False
except ValueError: pass

print("mux method")
l=listen(0); r=remote('localhost', l.lport); l.wait_for_connection()
m1=l.mux(max_channels=64, high_water_mark=1000, low_water_mark=100)
m2=r.mux(max_channels=64, high_water_mark=1000, low_water_mark=100)
print("isinstance", isinstance(m1, TubeMultiplexer), isinstance(m2, TubeMultiplexer))
print("marks", m1.high_water_mark, m1.low_water_mark)
assert isinstance(m1, TubeMultiplexer) and isinstance(m2, TubeMultiplexer)
assert m1.high_water_mark==1000 and m1.low_water_mark==100

print("open")
c=m1.open_channel(channel_id=7); p=m2.accept_channel(timeout=3)
print("c", c, "p", p)
print("channels", list(m1.channels), list(m2.channels))
assert m1.channels[7] is c and m2.channels[7] is p
print("types", isinstance(c, tube), isinstance(c, MuxChannel), c.channel_id, p.channel_id)
assert isinstance(c, tube) and isinstance(c, MuxChannel)
assert c.channel_id==7 and p.channel_id==7
print("stats", c.stats)
assert c.stats=={'bytes_sent':0,'bytes_received':0,'frames_sent':0,'frames_received':0}

print("data")
c.send(b'hello'); c.send(b'world')
d=p.recv()
print("recv", d)
assert d==b'helloworld'
print("stats2", c.stats, p.stats)
assert c.stats['frames_sent']==2 and c.stats['bytes_sent']==10
assert p.stats['frames_received']==2 and p.stats['bytes_received']==10

print("half close")
c.shutdown('send')
try: c.send(b'x'); assert False
except EOFError: pass
p.send(b'back'); print("back recv", c.recv()); assert c.recv()==b'back'

print("full close")
c.close()
try: c.send(b'x'); assert False
except EOFError: pass
try: p.recv(timeout=2); assert False
except EOFError: pass
try: p.send(b'x'); assert False
except EOFError: pass
assert not c.connected() and not p.connected()

print("id reuse")
c2=m1.open_channel(channel_id=7); p2=m2.accept_channel(timeout=3)
assert c2.channel_id==7

m1.close(); m2.close()
assert m1.close() is None
print("ALL OK")
PY