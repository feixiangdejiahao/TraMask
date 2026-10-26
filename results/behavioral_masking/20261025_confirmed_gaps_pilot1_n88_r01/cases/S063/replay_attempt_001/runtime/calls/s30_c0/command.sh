cd /app && cat > /tmp/test_sock.py <<'PYEOF'
import socket, time, threading
from pwnlib.tubes.sock import sock
from pwnlib.timeout import Timeout
s1, s2 = socket.socketpair()
t1 = sock(timeout=None); t2 = sock(timeout=None)
t1.sock = s1; t2.sock = s2
print("t1 timeout", t1.timeout, "sock timeout", s1.gettimeout())
def rdr():
    try:
        print("reading...")
        data = t1.recvn(8, timeout=Timeout.forever)
        print("got", data)
    except Exception as e:
        print("reader exception", type(e).__name__, e)
threading.Thread(target=rdr, daemon=True).start()
time.sleep(0.3)
t2.send(b'12345678')
time.sleep(0.5)
PYEOF
timeout 10 python /tmp/test_sock.py