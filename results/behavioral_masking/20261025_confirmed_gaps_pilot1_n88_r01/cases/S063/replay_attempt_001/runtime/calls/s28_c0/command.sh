cd /app && cat > /tmp/test_mux_basic.py <<'PYEOF'
import socket, time, threading, traceback
from pwnlib.tubes.remote import remote
from pwnlib.tubes.mux import TubeMultiplexer, MuxChannel
from pwnlib.tubes.tube import tube

s1, s2 = socket.socketpair()
t1 = remote.fromsocket(s1)
t2 = remote.fromsocket(s2)
m1 = t1.mux(max_channels=10, high_water_mark=1024, low_water_mark=256)
m2 = t2.mux(max_channels=10, high_water_mark=1024, low_water_mark=256)

c1 = m1.open_channel(1, timeout=1)
print("opened c1 id", c1.channel_id, "stats", c1.stats)
c2 = m2.accept_channel(timeout=1)
print("accepted c2 id", c2.channel_id, "stats", c2.stats)

c1.send(b'hello')
print("c2.recv:", c2.recv())
print("c1 stats:", c1.stats)
print("c2 stats:", c2.stats)

# echo back
c2.send(b'world')
print("c1.recv:", c1.recv())

# close channel
c1.close()
time.sleep(0.1)
try:
    c2.recv(timeout=0.1)
    print("ERROR: c2.recv should EOF")
except EOFError as e:
    print("c2.recv EOF ok")
try:
    c2.send(b'x')
    print("ERROR: c2.send should EOF")
except EOFError:
    print("c2.send EOF ok")
try:
    c1.send(b'x')
    print("ERROR: c1.send should EOF")
except EOFError:
    print("c1.send EOF ok")
print("c2 connected:", c2.connected())

m1.close(); m2.close()
print("BASIC OK")
PYEOF
timeout 20 python /tmp/test_mux_basic.py