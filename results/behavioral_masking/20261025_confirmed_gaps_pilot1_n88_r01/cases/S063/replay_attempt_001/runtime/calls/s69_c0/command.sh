cd /app && cat > /tmp/test_direct_close.py <<'PYEOF'
import socket, time
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote

# Case 1: no peer mux, close underlying directly on same side
l = listen(0); r = remote('localhost', l.lport); s = l.wait_for_connection()
m = r.mux()
time.sleep(0.15)
r.close()
time.sleep(0.3)
print("case1 m.closed", m.closed, "reader alive", m._reader_thread.is_alive())

# Case 2: peer mux, close underlying directly on client side
l2 = listen(0); r2 = remote('localhost', l2.lport); s2 = l2.wait_for_connection()
m_a = r2.mux(); m_b = s2.mux()
c1 = m_a.open_channel(1, timeout=1); c2 = m_b.accept_channel(timeout=1)
r2.close()
time.sleep(0.3)
print("case2 m_a.closed", m_a.closed, "m_b.closed", m_b.closed)
try:
    c2.recv(timeout=0.2)
    print("case2 c2 recv no EOF")
except EOFError:
    print("case2 c2 recv EOF ok")
m_a.close(); m_b.close()
PYEOF
timeout 20 python /tmp/test_direct_close.py