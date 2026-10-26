cd /app && timeout 20 python - <<'EOF'
import time
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(); m2=s.mux()
c1=m1.open_channel(1, timeout=1); c2=m2.accept_channel(timeout=1)
c1.settimeout(0.2)
c2.buffer.set_watermarks(high=50, low=10)
c1.send(b'A'*100)
time.sleep(0.2)
print("flow_paused", c2._flow_paused, "total", c2._recv_size + len(c2.buffer))
try:
    c1.send(b'B')
    print("ERROR no timeout")
except TimeoutError:
    print("TimeoutError with buffer watermarks ok")
c2.recv()
print("after recv flow_paused", c2._flow_paused)
c1.send(b'C')
print("resumed ok")
m1.close(); m2.close()
EOF