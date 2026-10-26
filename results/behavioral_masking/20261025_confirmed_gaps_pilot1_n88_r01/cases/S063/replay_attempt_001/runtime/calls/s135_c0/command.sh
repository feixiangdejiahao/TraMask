cd /app && timeout 15 python -u - <<'EOF'
import time
from pwnlib.tubes.process import process
p = process(['python3', '/tmp/mux_peer_exit.py'])
print("started", flush=True)
m = p.mux()
print("mux created", flush=True)
try:
    c = m.open_channel(1, timeout=2)
    print("opened", c.channel_id, flush=True)
except Exception as e:
    print("open exc", type(e).__name__, e, flush=True)
time.sleep(1.0)
print("m.closed", m.closed, flush=True)
m.close()
print("done", flush=True)
EOF