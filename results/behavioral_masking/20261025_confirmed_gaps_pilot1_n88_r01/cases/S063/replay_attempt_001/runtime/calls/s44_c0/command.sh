cd /app && cat > /tmp/test_eof_nomux.py <<'PYEOF'
import socket, time
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l = listen(0); r = remote('localhost', l.lport); s = l.wait_for_connection()
m = s.mux()
time.sleep(0.2)
r.close()
time.sleep(0.5)
print("m.closed", m.closed, "reader alive", m._reader_thread.is_alive())
PYEOF
timeout 10 python /tmp/test_eof_nomux.py