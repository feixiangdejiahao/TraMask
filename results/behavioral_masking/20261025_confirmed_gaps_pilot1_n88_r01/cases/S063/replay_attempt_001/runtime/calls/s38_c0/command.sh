cd /app && cat > /tmp/test_close_unblock.py <<'PYEOF'
import socket, time, threading
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote

l3 = listen(0); r3 = remote('localhost', l3.lport); srv3 = l3.wait_for_connection()
m4 = r3.mux(); m5 = srv3.mux()
print("m5 closed initial", m5.closed)
def acc():
    print("accept thread entering")
    try:
        x = m5.accept_channel(timeout=10)
        print("accept returned", x)
    except EOFError:
        print("accept EOFError")
    except Exception as e:
        print("accept exc", type(e).__name__, e)
th = threading.Thread(target=acc); th.start()
time.sleep(0.2)
print("closing m4")
m4.close()
for i in range(10):
    time.sleep(0.2)
    print("m5.closed", m5.closed, "alive", th.is_alive())
    if not th.is_alive():
        break
th.join(1)
print("done", m5.closed)
PYEOF
timeout 20 python /tmp/test_close_unblock.py