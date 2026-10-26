cd /app && timeout 10 python - <<'EOF'
import time
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(); m2=s.mux()
c1=m1.open_channel(1, timeout=1); c2=m2.accept_channel(timeout=1)
c1.send(b'0123456789')
time.sleep(0.05)
print(c2.recvn(3), c2.recvn(3), c2.recvn(4))
print("frames_received", c2.stats['frames_received'])
m1.close(); m2.close()
EOF