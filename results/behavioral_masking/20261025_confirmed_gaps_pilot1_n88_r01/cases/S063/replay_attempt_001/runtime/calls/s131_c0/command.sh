cd /app && timeout 15 python - <<'EOF'
import socket, time
from pwnlib.tubes.sock import sock
s1, s2 = socket.socketpair()
t1 = sock(timeout=None); t2 = sock(timeout=None)
t1.sock = s1; t2.sock = s2
m1 = t1.mux(); m2 = t2.mux()
c1 = m1.open_channel(1, timeout=1)
c2 = m2.accept_channel(timeout=1)
c1.send(b'hi')
print("recv:", c2.recv(timeout=1))
m1.close(); m2.close()
EOF