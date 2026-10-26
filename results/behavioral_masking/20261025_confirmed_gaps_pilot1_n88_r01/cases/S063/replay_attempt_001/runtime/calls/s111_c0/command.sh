cd /app && timeout 10 python - <<'EOF'
import time
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
from pwnlib.tubes.tube import tube
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(); m2=s.mux()
c1=m1.open_channel(1, timeout=1); c2=m2.accept_channel(timeout=1)
c2.settimeout(0.1)
print("timeout property", c2.timeout)
print("get_timeout_seconds(default)", c2._get_timeout_seconds(tube.default))
print("get_timeout_seconds(0.2)", c2._get_timeout_seconds(0.2))
t0=time.time()
print("chunk:", c2._recv_data_chunk(0.2), "elapsed", round(time.time()-t0,2))
m1.close(); m2.close()
EOF