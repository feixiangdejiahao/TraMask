cd /app && cat > /tmp/test_recvall.py <<'PYEOF'
import socket, time, threading
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote

l = listen(0); r = remote('localhost', l.lport); srv = l.wait_for_connection()
m1 = r.mux(); m2 = srv.mux()
c1 = m1.open_channel(1, timeout=1); c2 = m2.accept_channel(timeout=1)
c1.send(b'hello')
c1.shutdown('send')
print("c2 recv_eof", c2._recv_eof)
time.sleep(0.2)
print("c2 recv_eof after", c2._recv_eof)
print("recvall:", c2.recvall(timeout=1))
m1.close(); m2.close()
PYEOF
timeout 10 python /tmp/test_recvall.py