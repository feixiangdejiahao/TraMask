cd /app && timeout 10 python - <<'EOF'
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m=s.mux()
r.close()
import time; time.sleep(0.1)
print("closed", m.closed)
m.close()
print("close after death ok")
EOF