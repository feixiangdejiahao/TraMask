cd /app && timeout 15 python -u - <<'EOF'
import time, sys
from pwnlib.tubes.process import process
print("A", flush=True)
p = process(['python3', '/tmp/mux_peer_exit2.py'])
print("B", flush=True)
m = p.mux()
print("C", flush=True)
try:
    c = m.open_channel(1, timeout=2)
    print("opened", flush=True)
except Exception as e:
    print("open exc", type(e).__name__, e, flush=True)
print("D", flush=True)
time.sleep(1.0)
print("m.closed", m.closed, flush=True)
m.close()
print("done", flush=True)
EOF