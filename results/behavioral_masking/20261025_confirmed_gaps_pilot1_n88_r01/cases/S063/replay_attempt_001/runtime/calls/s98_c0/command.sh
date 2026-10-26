cd /app && timeout 15 python - <<'EOF'
import time
from pwnlib.tubes.process import process
p = process(['python3', '/tmp/mux_peer.py'])
time.sleep(0.5)
print("poll", p.poll())
print("recv stderr?", )
try:
    print("stderr", p.recv(timeout=0.3))
except Exception as e:
    print("stderr exc", type(e).__name__, e)
EOF