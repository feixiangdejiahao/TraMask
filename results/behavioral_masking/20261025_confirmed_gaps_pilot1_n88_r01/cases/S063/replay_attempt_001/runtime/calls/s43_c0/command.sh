cd /app && cat > /tmp/test_stack2.py <<'PYEOF'
import socket, time, threading, sys, traceback
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote

l3 = listen(0); r3 = remote('localhost', l3.lport); srv3 = l3.wait_for_connection()
m4 = r3.mux(); m5 = srv3.mux()
time.sleep(0.2)
print("r3.sock before", r3.sock)
r3.close()
print("r3.sock after", r3.sock)
time.sleep(0.5)
print("m4.closed", m4.closed, "m5.closed", m5.closed)
print("m4 reader alive", m4._reader_thread.is_alive(), "m5 reader alive", m5._reader_thread.is_alive())
for ident, frame in list(sys._current_frames().items()):
    if ident in (m4._reader_thread.ident, m5._reader_thread.ident):
        print("=== stack for", ident, "===")
        traceback.print_stack(frame)
PYEOF
timeout 10 python /tmp/test_stack2.py