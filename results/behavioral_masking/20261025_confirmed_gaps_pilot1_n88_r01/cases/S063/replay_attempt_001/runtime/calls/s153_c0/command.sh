cd /app && timeout 10 python - <<'EOF'
import time
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
r.close()
m = s.mux()
time.sleep(0.05)
print("closed", m.closed)
try:
    m.open_channel(1, timeout=0.1)
    print("ERROR")
except EOFError:
    print("EOFError ok")
m.close()
EOF