cd /app && rm -f /tmp/child_err.log && timeout 15 python -u - <<'EOF'
import time
from pwnlib.tubes.process import process
err = open('/tmp/child_err.log','w')
p = process(['python3', '/tmp/mux_peer_exit2.py'], stderr=err)
m = p.mux()
try:
    c = m.open_channel(1, timeout=2)
    print("opened")
except Exception as e:
    print("open exc", type(e).__name__, e)
time.sleep(0.5)
m.close()
err.close()
print("poll", p.poll())
EOF
echo "=== child err ==="; cat /tmp/child_err.log 2>/dev/null