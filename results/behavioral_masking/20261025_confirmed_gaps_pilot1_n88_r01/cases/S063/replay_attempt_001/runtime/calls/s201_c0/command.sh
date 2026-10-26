cd /app && timeout 10 python - <<'EOF'
import time
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(); m2=s.mux()
c1=m1.open_channel(1, timeout=1); c2=m2.accept_channel(timeout=1)
c1.send(b'hello')
time.sleep(0.05)
print("recv1:", c2.recv(timeout=1))  # consumes into buffer/returns
c1.send(b'world')
time.sleep(0.05)
m2.close()  # close local mux
try:
    print("recv2:", c2.recv(timeout=0.2))
except EOFError:
    print("EOF ok")
m1.close()
EOF