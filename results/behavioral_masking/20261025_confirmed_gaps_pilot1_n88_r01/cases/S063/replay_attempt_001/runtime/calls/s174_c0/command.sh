cd /app && timeout 10 python - <<'EOF'
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(); m2=s.mux()
c1=m1.open_channel(3, timeout=1)
c2=m2.accept_channel(timeout=1)
print("in channels", 3 in m2.channels, m2.channels[3] is c2)
m1.close(); m2.close()
EOF