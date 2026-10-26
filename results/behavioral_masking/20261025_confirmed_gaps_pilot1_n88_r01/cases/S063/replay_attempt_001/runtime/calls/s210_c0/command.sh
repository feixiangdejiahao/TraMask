cd /app && timeout 10 python - <<'EOF'
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m=r.mux(max_channels=10)
try:
    m.open_channel(11, timeout=0.1)
    print("ERROR")
except ValueError:
    print("id>max ValueError ok")
m.close(); s.close()
EOF