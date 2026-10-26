cd /app && cat > /tmp/test_halfclose.py <<'PYEOF'
import socket, time, threading
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote

l = listen(0); r = remote('localhost', l.lport); srv = l.wait_for_connection()
m1 = r.mux(); m2 = srv.mux()
c1 = m1.open_channel(1, timeout=1); c2 = m2.accept_channel(timeout=1)

print("initial connected", c1.connected(), c1.connected('send'), c1.connected('recv'))
c1.shutdown('send')
print("after shutdown send c1:", c1.connected('send'), c1.connected('recv'), c1.connected())
# c1 send should raise EOFError
try:
    c1.send(b'x')
    print("ERROR c1 send after shutdown")
except EOFError:
    print("c1 send EOF ok")
# c1 can still recv
c2.send(b'hello')
print("c1 recv after shutdown:", c1.recv())

# remote c2 recv should EOF after c1 shutdown('send')
try:
    c2.recv(timeout=0.5)
    print("ERROR c2 recv expected EOF")
except EOFError:
    print("c2 recv EOF ok")
# c2 can still send
c2.send(b'world')
print("c1 recv2:", c1.recv())
# c2 connected('recv') should be False (remote send side closed), send True
print("c2 connected recv/send:", c2.connected('recv'), c2.connected('send'))

# Closing one channel doesn't affect another
d1 = m1.open_channel(2, timeout=1); d2 = m2.accept_channel(timeout=1)
c1.close()
time.sleep(0.1)
try:
    c1.recv(timeout=0.1)
    print("ERROR c1 recv after close")
except EOFError:
    print("c1 recv EOF ok")
d1.send(b'still alive')
print("d2 got:", d2.recv())
print("d1 connected:", d1.connected(), "d2 connected:", d2.connected())

# Underlying death propagates EOF to all channels
l2 = listen(0); r2 = remote('localhost', l2.lport); srv2 = l2.wait_for_connection()
m3 = r2.mux(); m4 = srv2.mux()
e1 = m3.open_channel(1, timeout=1); e2 = m4.accept_channel(timeout=1)
r2.close()  # kill underlying from client side; but m3 reader may block...
# Instead use m3.close() which closes underlying and sends mux close to m4
m3.close()
time.sleep(0.2)
print("m4.closed after m3.close", m4.closed)
try:
    e2.recv(timeout=0.2)
    print("ERROR e2 recv expected EOF")
except EOFError:
    print("e2 recv EOF ok")
try:
    e2.send(b'x')
    print("ERROR e2 send expected EOF")
except EOFError:
    print("e2 send EOF ok")

m1.close(); m2.close(); m4.close()
print("HALFCLOSE OK")
PYEOF
timeout 30 python /tmp/test_halfclose.py