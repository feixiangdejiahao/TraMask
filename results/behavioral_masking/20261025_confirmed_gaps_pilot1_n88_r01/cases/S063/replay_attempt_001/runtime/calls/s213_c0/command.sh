cd /app && timeout 10 python - <<'EOF'
import time
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
from pwnlib.tubes.tube import tube
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(); m2=s.mux()
c1=m1.open_channel(1, timeout=1); c2=m2.accept_channel(timeout=1)
c2.settimeout(0.1)
t0=time.time()
print(c2.recv(timeout=tube.default), round(time.time()-t0,2))
m1.close(); m2.close()
EOF