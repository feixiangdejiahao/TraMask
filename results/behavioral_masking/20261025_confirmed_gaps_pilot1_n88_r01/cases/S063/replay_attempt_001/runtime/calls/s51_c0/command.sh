cd /app && cat > /tmp/test_muxclose_debug.py <<'PYEOF'
import socket, time, threading
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
from pwnlib.tubes.mux import _MSG_MUX_CLOSE

l2 = listen(0); r2 = remote('localhost', l2.lport); srv2 = l2.wait_for_connection()
m3 = r2.mux(); m4 = srv2.mux()
e1 = m3.open_channel(1, timeout=1); e2 = m4.accept_channel(timeout=1)
print("m4 reader alive", m4._reader_thread.is_alive())
# monkeypatch dispatch on m4 to trace mux close
orig = m4._dispatch
def traced(cid, payload):
    if payload and payload[0] == _MSG_MUX_CLOSE:
        print("MUX CLOSE received on m4 channel", cid)
    return orig(cid, payload)
m4._dispatch = traced
print("closing m3")
m3.close()
time.sleep(0.5)
print("m3.closed", m3.closed, "m4.closed", m4.closed)
print("m4 reader alive after", m4._reader_thread.is_alive())
print("m3 reader alive after", m3._reader_thread.is_alive())
PYEOF
timeout 15 python /tmp/test_muxclose_debug.py