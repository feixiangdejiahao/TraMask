cd /app && timeout 15 python - <<'EOF'
from pwnlib.timeout import Timeout
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(); m2=s.mux()
c1=m1.open_channel(1, timeout=Timeout.default)
c2=m2.accept_channel(timeout=Timeout.default)
print("ok", c1.channel_id, c2.channel_id)
m1.close(); m2.close()
EOF