cd /app && timeout 15 python -u - <<'EOF'
import time
from pwnlib.tubes.process import process
p = process(['python3', '/tmp/mux_peer_exit.py'])
m = p.mux()
try:
    c = m.open_channel(1, timeout=2)
except Exception as e:
    print("open exc", type(e).__name__, e)
time.sleep(0.5)
print("poll", p.poll())
if p.proc and p.proc.stderr:
    data = p.proc.stderr.read()
    print("stderr:", data[:2000])
m.close()
EOF