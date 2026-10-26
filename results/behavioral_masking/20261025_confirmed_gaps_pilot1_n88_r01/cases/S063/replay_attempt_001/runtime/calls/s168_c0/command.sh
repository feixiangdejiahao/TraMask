cd /app && timeout 10 python - <<'EOF'
import threading
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m=r.mux()
ts=[threading.Thread(target=m.close) for _ in range(5)]
for t in ts: t.start()
for t in ts: t.join()
print("concurrent close ok")
EOF