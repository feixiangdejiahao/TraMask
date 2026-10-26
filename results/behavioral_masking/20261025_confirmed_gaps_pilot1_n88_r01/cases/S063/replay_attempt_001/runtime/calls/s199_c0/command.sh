cd /app && timeout 15 python - <<'EOF'
import time
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(high_water_mark=0, low_water_mark=0); m2=s.mux(high_water_mark=0, low_water_mark=0)
c1=m1.open_channel(1, timeout=1); c2=m2.accept_channel(timeout=1)
c1.settimeout(0.2)
c1.send(b'A')
time.sleep(0.1)
print("flow_paused", c2._flow_paused)
try:
    c1.send(b'B')
    print("no timeout (race)")
except TimeoutError:
    print("timeout ok")
print("recv:", c2.recv(timeout=1))
print("flow_paused after", c2._flow_paused)
m1.close(); m2.close()
EOF