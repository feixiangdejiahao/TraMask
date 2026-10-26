cd /app && timeout 10 python - <<'EOF'
import time
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m=r.mux()
time.sleep(0.05)
print("before", m._reader_thread.is_alive())
m.close()
time.sleep(0.1)
print("after", m._reader_thread.is_alive())
EOF