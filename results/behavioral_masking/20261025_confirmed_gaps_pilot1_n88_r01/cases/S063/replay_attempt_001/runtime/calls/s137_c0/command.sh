cd /app && timeout 15 python -u - <<'EOF'
import time
from pwnlib.tubes.process import process
p = process(['python3', '/tmp/mux_peer_exit.py'])
print("started", flush=True)
m = p.mux()
print("mux created", flush=True)
try:
    c = m.open_channel(1, timeout=2)
    print("opened", flush=True)
except Exception as e:
    print("open exc", type(e).__name__, e, flush=True)
time.sleep(0.5)
m.close()
print("done", flush=True)
EOF
echo "=== child log ==="; cat /tmp/peer_exit.log 2>/dev/null || echo "(no log)"