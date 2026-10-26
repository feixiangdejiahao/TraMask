cd /app && timeout 10 python - <<'EOF'
import time
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(); m2=s.mux()
m1.open_channel(1, timeout=1)
time.sleep(0.1)
# m2 has channel queued but not accepted
print("m2 channels", len(m2.channels))
m2.close()
time.sleep(0.05)
ch = list(m2.channels.values())
print("channels after close", len(ch))
m1.close()
EOF