cd /app && cat > /tmp/test_concurrent.py <<'PYEOF'
import socket, time, threading, random
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote

l = listen(0); r = remote('localhost', l.lport); srv = l.wait_for_connection()
m1 = r.mux(high_water_mark=1<<20, low_water_mark=1<<18)
m2 = srv.mux(high_water_mark=1<<20, low_water_mark=1<<18)

NCH = 8
NSEND = 50
SIZE = 1000

channels1 = [m1.open_channel(i+1, timeout=2) for i in range(NCH)]
channels2 = [m2.accept_channel(timeout=2) for _ in range(NCH)]
print("opened", len(channels2))

errors = []
lock = threading.Lock()

def sender(idx):
    try:
        ch = channels1[idx]
        for j in range(NSEND):
            payload = ("%d:%d:" % (idx, j)).encode().ljust(SIZE, b'x')
            ch.send(payload)
    except Exception as e:
        with lock:
            errors.append(("sender", idx, type(e).__name__, str(e)))

def receiver(idx):
    try:
        ch = channels2[idx]
        for j in range(NSEND):
            data = ch.recvn(SIZE, timeout=5)
            prefix = ("%d:%d:" % (idx, j)).encode()
            if not data.startswith(prefix):
                with lock:
                    errors.append(("badprefix", idx, j, data[:20]))
    except Exception as e:
        with lock:
            errors.append(("receiver", idx, type(e).__name__, str(e)))

threads = []
for i in range(NCH):
    t = threading.Thread(target=sender, args=(i,)); t.start(); threads.append(t)
    t = threading.Thread(target=receiver, args=(i,)); t.start(); threads.append(t)
for t in threads:
    t.join(30)
print("alive", [t.is_alive() for t in threads])
print("errors", errors[:10])
if not errors:
    print("CONCURRENT OK")
# stats
for i in range(NCH):
    s1 = channels1[i].stats; s2 = channels2[i].stats
    assert s1['bytes_sent'] == s2['bytes_received'] == NSEND*SIZE, (i, s1, s2)
    assert s1['frames_sent'] == s2['frames_received'] == NSEND, (i, s1, s2)
print("stats all consistent")

m1.close(); m2.close()
PYEOF
timeout 60 python /tmp/test_concurrent.py