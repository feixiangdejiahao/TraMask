cd /app && cat > /tmp/test_remote_close.py <<'PYEOF'
import socket, time
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l = listen(0); r = remote('localhost', l.lport); s = l.wait_for_connection()
print("r.sock before", r.sock)
r.close()
print("r.sock after close:", r.sock)
s.settimeout(2)
try:
    d = s.sock.recv(100)
    print("server raw recv:", d)
except Exception as e:
    print("server recv exc", type(e).__name__, e)
PYEOF
timeout 10 python /tmp/test_remote_close.py