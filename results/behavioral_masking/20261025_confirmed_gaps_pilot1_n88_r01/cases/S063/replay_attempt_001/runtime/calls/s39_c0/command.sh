cd /app && cat > /tmp/test_eof_detect.py <<'PYEOF'
import socket, time, threading
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
from pwnlib.timeout import Timeout

l3 = listen(0); r3 = remote('localhost', l3.lport); srv3 = l3.wait_for_connection()
m4 = r3.mux(); m5 = srv3.mux()
print("reader alive", m5._reader_thread.is_alive())
print("srv3 timeout", srv3.timeout, "sock timeout", getattr(srv3,'sock',None).gettimeout() if getattr(srv3,'sock',None) else None)
time.sleep(0.2)
print("closing r3")
r3.close()
time.sleep(0.5)
print("m5.closed", m5.closed, "reader alive", m5._reader_thread.is_alive())
try:
    x = srv3.recvn(4, timeout=Timeout.maximum)
    print("srv recvn got", x)
except EOFError:
    print("srv recvn EOFError")
except Exception as e:
    print("srv recvn exc", type(e).__name__, e)
PYEOF
timeout 20 python /tmp/test_eof_detect.py