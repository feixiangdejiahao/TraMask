cd /app && timeout 20 python - <<'EOF'
import time
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
fail=0
for i in range(20):
    l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
    m1=r.mux(); m2=s.mux()
    try:
        c1=m1.open_channel(i+1, timeout=0.02)
        c2=m2.accept_channel(timeout=0.02)
    except Exception as e:
        fail+=1
        print("fail", i, type(e).__name__)
    m1.close(); m2.close()
    r.close(); l.close()
print("failures", fail)
EOF