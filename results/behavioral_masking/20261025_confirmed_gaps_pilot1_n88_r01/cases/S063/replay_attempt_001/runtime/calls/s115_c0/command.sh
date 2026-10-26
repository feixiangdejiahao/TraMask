cd /app && timeout 15 python - <<'EOF'
import time
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(); m2=s.mux()
c1=m1.open_channel(1, timeout=1); c2=m2.accept_channel(timeout=1)
print("before", list(m2.channels.keys()))
c1.close()
time.sleep(0.2)
print("after", list(m2.channels.keys()))
m1.close(); m2.close()
EOF