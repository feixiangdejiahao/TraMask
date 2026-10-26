cd /app && timeout 15 python - <<'EOF'
import time
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost', l.lport, timeout=0.5); s=l.wait_for_connection()
m1=r.mux(); m2=s.mux()
c1=m1.open_channel(1, timeout=1); c2=m2.accept_channel(timeout=1)
c1.send(b'hi')
print("recv", c2.recv(timeout=1))
m1.close(); m2.close()
EOF