cd /app && cat > /tmp/test_flow.py <<'PYEOF'
import socket, time, threading
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote

l = listen(0); r = remote('localhost', l.lport); srv = l.wait_for_connection()
m1 = r.mux(high_water_mark=100, low_water_mark=10)
m2 = srv.mux(high_water_mark=100, low_water_mark=10)
c1 = m1.open_channel(1, timeout=1)
c2 = m2.accept_channel(timeout=1)
c1.settimeout(0.3)
c2.settimeout(0.3)

# Send a chunk that puts c2 over high watermark
c1.send(b'A' * 200)
# wait for pause to propagate
t0=time.time()
while not c2._flow_paused and time.time()-t0 < 1:
    time.sleep(0.01)
print("c2 flow_paused", c2._flow_paused, "recv_size", c2._recv_size)

# Now c1 send should block then TimeoutError
t0=time.time()
try:
    c1.send(b'B'*10)
    print("ERROR: expected TimeoutError")
except TimeoutError:
    print("TimeoutError ok after", round(time.time()-t0, 3))
except Exception as e:
    print("wrong exc", type(e).__name__, e)

# Now read on c2, should trigger resume
data = c2.recv()
print("received", len(data), "bytes; flow_paused now", c2._flow_paused, "recv_size", c2._recv_size)
t0=time.time()
while c2._flow_paused and time.time()-t0 < 1:
    time.sleep(0.01)
print("after drain flow_paused", c2._flow_paused)

# c1 should now send successfully
c1.send(b'C'*10)
print("c2 recv2:", c2.recv())
print("stats c1", c1.stats, "c2", c2.stats)

# Per-channel independence: open a second channel, pause it, verify other can still send
a1 = m1.open_channel(2, timeout=1); a2 = m2.accept_channel(timeout=1)
a1.settimeout(0.2); a2.settimeout(0.2)
b1 = m1.open_channel(3, timeout=1); b2 = m2.accept_channel(timeout=1)
b1.settimeout(0.2); b2.settimeout(0.2)
a1.send(b'X'*200)
time.sleep(0.2)
print("a2 flow_paused", a2._flow_paused)
# b1 should still send fine even though a is paused
b1.send(b'Y'*10)
print("b2 got", b2.recv())
# a1 should time out
try:
    a1.send(b'Z'*10)
    print("ERROR a1 expected timeout")
except TimeoutError:
    print("a1 independent TimeoutError ok")

m1.close(); m2.close()
print("FLOW OK")
PYEOF
timeout 30 python /tmp/test_flow.py