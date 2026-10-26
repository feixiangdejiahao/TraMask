cd /app && cat > /tmp/mux_peer_exit.py <<'PYEOF'
import sys, os, select
from pwnlib.tubes.tube import tube
class StdioTube(tube):
    def recv_raw(self, numb):
        r,_,_ = select.select([sys.stdin], [], [], self.timeout)
        if not r: return None
        data = os.read(sys.stdin.fileno(), numb)
        if not data: raise EOFError
        return data
    def send_raw(self, data): sys.stdout.buffer.write(data); sys.stdout.buffer.flush()
    def can_recv_raw(self, timeout):
        r,_,_ = select.select([sys.stdin], [], [], timeout); return bool(r)
    def connected_raw(self, direction): return True
t = StdioTube()
m = t.mux()
c = m.accept_channel(timeout=5)
print("peer accepted", flush=True)
sys.stdout.buffer.flush()
# just exit without closing
EOF
timeout 20 python - <<'EOF'
import time
from pwnlib.tubes.process import process
p = process(['python3', '/tmp/mux_peer_exit.py'])
m = p.mux()
c = m.open_channel(1, timeout=2)
print("opened")
time.sleep(0.3)  # child exits after accepting
time.sleep(0.3)
print("m.closed", m.closed)
try:
    c.recv(timeout=0.2)
    print("ERROR no EOF")
except EOFError:
    print("channel EOF on underlying death ok")
m.close()
EOF