cd /app && cat > /tmp/test_stack.py <<'PYEOF'
import socket, time, threading, sys, traceback
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote

l3 = listen(0); r3 = remote('localhost', l3.lport); srv3 = l3.wait_for_connection()
m4 = r3.mux(); m5 = srv3.mux()
time.sleep(0.2)
r3.close()
time.sleep(0.5)
print("closed", m5.closed)
for ident, frame in list(sys._current_frames().items()):
    if ident == m5._reader_thread.ident:
        print("=== reader stack ===")
        traceback.print_stack(frame)
PYEOF
timeout 10 python /tmp/test_stack.py