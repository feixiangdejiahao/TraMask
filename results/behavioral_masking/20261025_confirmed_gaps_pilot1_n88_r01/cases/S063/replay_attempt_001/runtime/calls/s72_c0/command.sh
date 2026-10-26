cd /app && cat > /tmp/test_symopen.py <<'PYEOF'
import socket, time
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l = listen(0); r = remote('localhost', l.lport); s = l.wait_for_connection()
m1 = r.mux(); m2 = s.mux()
a = m1.open_channel(5, timeout=1)
b = m2.open_channel(5, timeout=1)
print("both opened", a.channel_id, b.channel_id)
a.send(b'hi')
print("b recv", b.recv(timeout=1))
m1.close(); m2.close()
PYEOF
timeout 15 python /tmp/test_symopen.py