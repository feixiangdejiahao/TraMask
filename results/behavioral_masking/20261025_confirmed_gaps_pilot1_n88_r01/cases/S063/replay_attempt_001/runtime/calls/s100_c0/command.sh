cd /app && cat > /tmp/mux_peer.py <<'PYEOF'
import sys, os, select
from pwnlib.tubes.tube import tube

DBG = open('/tmp/peer_debug.log', 'a')
def dbg(*a):
    DBG.write(' '.join(map(str,a)) + '\n'); DBG.flush()

class StdioTube(tube):
    def __init__(self):
        super().__init__(timeout=None)
    def recv_raw(self, numb):
        r, _, _ = select.select([sys.stdin], [], [], self.timeout)
        if not r:
            return None
        data = os.read(sys.stdin.fileno(), numb)
        if not data:
            raise EOFError
        return data
    def send_raw(self, data):
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
    def can_recv_raw(self, timeout):
        r, _, _ = select.select([sys.stdin], [], [], timeout)
        return bool(r)
    def connected_raw(self, direction):
        return True

dbg('child starting')
t = StdioTube()
m = t.mux(max_channels=8)
dbg('mux created')
c = m.accept_channel(timeout=5)
dbg('accepted', c.channel_id if c else None)
if c is None:
    dbg('no channel accepted')
    sys.exit(2)
data = c.recv(timeout=2)
dbg('got data', data)
c.send(b'echo:' + data)
c.close()
m.close()
dbg('done')
PYEOF
rm -f /tmp/peer_debug.log
cat > /tmp/test_process_mux.py <<'PYEOF'
import time
from pwnlib.tubes.process import process
p = process(['python3', '/tmp/mux_peer.py'])
m = p.mux(max_channels=8)
c = m.open_channel(1, timeout=2)
print("opened", c.channel_id)
c.send(b'hello')
print("reply:", c.recv(timeout=3))
time.sleep(0.2)
try:
    c.recv(timeout=0.2)
    print("ERROR expected EOF")
except EOFError:
    print("channel EOF after peer close ok")
m.close()
print("PROCESS MUX OK")
PYEOF
cd /app && timeout 20 python /tmp/test_process_mux.py
echo "=== peer debug ==="; cat /tmp/peer_debug.log