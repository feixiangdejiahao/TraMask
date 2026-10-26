cd /app && timeout 15 python - <<'EOF'
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m=r.mux()
m.close(); m.close()
print("double close ok")
m.close()
print("triple close ok")
EOF