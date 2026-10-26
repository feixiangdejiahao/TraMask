cd /app && cat > /tmp/test_api.py <<'PYEOF'
import socket, time, threading
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote

l = listen(0); r = remote('localhost', l.lport); srv = l.wait_for_connection()
m1 = r.mux(); m2 = srv.mux()
c1 = m1.open_channel(1, timeout=1); c2 = m2.accept_channel(timeout=1)

c1.send(b'hello\nworld\n')
print("recvline:", c2.recvline())
print("recvuntil:", c2.recvuntil(b'ld\n'))
c1.send(b'12345')
print("recvn:", c2.recvn(3))
print("rest:", c2.recv())

# unrecv
c1.send(b'abcdef')
print("first:", c2.recv(2))
print("can_recv:", c2.can_recv(0.1))
c2.unrecv(b'XY')
print("after unrecv recv:", c2.recv())
print("can_recv now:", c2.can_recv(0.1))

# recv timeout returns b''
c1.send(b'data')
print("recv timeout empty:", c2.recv(timeout=0.01))
print("data now:", c2.recv())

# recvall: close send side remotely via shutdown, then recvall local
c1.shutdown('send')
try:
    print("recvall:", c2.recvall(timeout=1))
except Exception as e:
    print("recvall exc", type(e).__name__, e)

# setters
m1.high_water_mark = 2048
m1.low_water_mark = 512
print("new watermarks", m1.high_water_mark, m1.low_water_mark)
try:
    m1.low_water_mark = 3000
    print("ERROR setter low>high")
except ValueError:
    print("setter ValueError ok")

m1.close(); m2.close()
print("API OK")
PYEOF
timeout 30 python /tmp/test_api.py