cd /app && timeout 10 python - <<'EOF'
import time
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(); m2=s.mux()
m1.open_channel(1, timeout=1); m1.open_channel(2, timeout=1)
time.sleep(0.1)
print("timeout0 accept:", m2.accept_channel(timeout=0))
print("first:", m2.accept_channel(timeout=1).channel_id)
print("second:", m2.accept_channel(timeout=1).channel_id)
m1.close(); m2.close()
EOF