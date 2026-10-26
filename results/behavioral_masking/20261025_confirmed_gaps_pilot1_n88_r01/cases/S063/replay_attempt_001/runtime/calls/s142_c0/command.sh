cd /app && timeout 15 python - <<'EOF'
import time
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(); m2=s.mux()
c1=m1.open_channel(5, timeout=1); c2=m2.accept_channel(timeout=1)
c1.close(); c2.close()
time.sleep(0.2)
d1=m1.open_channel(5, timeout=1)
d2=m2.accept_channel(timeout=1)
print("reopened", d1.channel_id, d2.channel_id)
d1.send(b'ok'); print(d2.recv(timeout=1))
m1.close(); m2.close()
EOF