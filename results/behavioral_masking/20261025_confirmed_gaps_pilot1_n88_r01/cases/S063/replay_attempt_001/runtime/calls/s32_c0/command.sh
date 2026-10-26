cd /app && cat > /tmp/test_mux_basic.py <<'PYEOF'
import socket, time, threading
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote

l = listen(0)
r = remote('localhost', l.lport)
srv = l.wait_for_connection()
print("connected", srv)

m1 = r.mux(max_channels=10, high_water_mark=1024, low_water_mark=256)
m2 = srv.mux(max_channels=10, high_water_mark=1024, low_water_mark=256)

c1 = m1.open_channel(1, timeout=1)
print("opened c1 id", c1.channel_id, "stats", c1.stats)
c2 = m2.accept_channel(timeout=1)
print("accepted c2 id", c2.channel_id, "stats", c2.stats)

c1.send(b'hello')
print("c2.recv:", c2.recv())
print("c1 stats:", c1.stats)
print("c2 stats:", c2.stats)

c2.send(b'world')
print("c1.recv:", c1.recv())

c1.close()
time.sleep(0.1)
for name, fn in [("c2.recv", lambda: c2.recv(timeout=0.1)),
                 ("c2.send", lambda: c2.send(b'x')),
                 ("c1.send", lambda: c1.send(b'x'))]:
    try:
        fn()
        print("ERROR", name, "should EOF")
    except EOFError:
        print(name, "EOF ok")
print("c2 connected:", c2.connected())

m1.close(); m2.close()
print("BASIC OK")
PYEOF
timeout 20 python /tmp/test_mux_basic.py