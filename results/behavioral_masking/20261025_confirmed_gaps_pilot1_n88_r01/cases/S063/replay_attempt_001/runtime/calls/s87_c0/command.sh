cd /app && timeout 15 python - <<'EOF'
import time
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(); m2=s.mux()
c1=m1.open_channel(1, timeout=1); c2=m2.accept_channel(timeout=1)
m1.close()
time.sleep(0.1)
for name, fn in [("c1.recv", lambda: c1.recv(timeout=0.2)), ("c1.send", lambda: c1.send(b'x'))]:
    try:
        fn(); print("ERROR", name)
    except EOFError:
        print(name, "EOF ok")
print("c1.connected", c1.connected())
m2.close()
EOF