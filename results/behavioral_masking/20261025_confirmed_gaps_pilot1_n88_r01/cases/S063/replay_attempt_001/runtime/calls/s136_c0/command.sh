cd /app && cat > /tmp/mux_peer_exit.py <<'PYEOF'
import sys, os, select, traceback
try:
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
    with open('/tmp/peer_exit.log','w') as f:
        f.write('accepted %r\n' % (c,))
except Exception:
    with open('/tmp/peer_exit.log','w') as f:
        traceback.print_exc(file=f)
EOF
rm -f /tmp/peer_exit.log
timeout 15 python -u - <<'EOF'
import time
from pwnlib.tubes.process import process
p = process(['python3', '/tmp/mux_peer_exit.py'])
m = p.mux()
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