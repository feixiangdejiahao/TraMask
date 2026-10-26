cd /app && cat > /tmp/test_mux_ids.py <<'PYEOF'
import socket, time, threading
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote

l = listen(0); r = remote('localhost', l.lport); srv = l.wait_for_connection()
m1 = r.mux(max_channels=5)
m2 = srv.mux(max_channels=5)

# auto ids
a = m1.open_channel(timeout=1)
b = m1.open_channel(timeout=1)
c = m1.open_channel(timeout=1)
print("auto ids", a.channel_id, b.channel_id, c.channel_id)

# non-int
for bad in [1.0, "1", True, None if False else 2.0]:
    try:
        m1.open_channel(bad, timeout=1)
        print("ERROR no TypeError", bad)
    except TypeError:
        print("TypeError ok", bad)
    except Exception as e:
        print("wrong exc", bad, type(e).__name__)

# out of range / duplicate / capacity
try:
    m1.open_channel(0, timeout=1)
    print("ERROR id 0")
except ValueError:
    print("ValueError id0 ok")
try:
    m1.open_channel(65536, timeout=1)
    print("ERROR id 65536")
except ValueError:
    print("ValueError id65536 ok")
try:
    m1.open_channel(a.channel_id, timeout=1)
    print("ERROR dup")
except ValueError:
    print("ValueError dup ok")
# capacity: max_channels=5, already 3 open, id 5 should work? capacity 5. open id 6 (> max) ValueError
try:
    m1.open_channel(6, timeout=1)
    print("ERROR id 6 > max")
except ValueError:
    print("ValueError id6 ok")
# open id 4 and 5 -> 5 total
d = m1.open_channel(4, timeout=1)
e = m1.open_channel(5, timeout=1)
try:
    m1.open_channel(timeout=1)
    print("ERROR capacity auto")
except ValueError:
    print("ValueError capacity auto ok")

# accept on m2 should have 5 pending channels
for i in range(5):
    ch = m2.accept_channel(timeout=1)
    print("accepted", i, ch.channel_id if ch else None)
extra = m2.accept_channel(timeout=0.2)
print("accept timeout returns", extra)

# open timeout when no remote accepts? actually remote auto-acks, so no timeout.
# Create a mux whose peer isn't a mux -> open times out
l2 = listen(0); r2 = remote('localhost', l2.lport); srv2 = l2.wait_for_connection()
m3 = r2.mux()
t0 = time.time()
try:
    m3.open_channel(1, timeout=0.2)
    print("ERROR no timeout")
except TimeoutError:
    print("TimeoutError open ok", round(time.time()-t0,2))
except Exception as e:
    print("wrong exc open", type(e).__name__, e)
m3.close(); r2.close(); l2.close()

# close unblocks accept
l3 = listen(0); r3 = remote('localhost', l3.lport); srv3 = l3.wait_for_connection()
m4 = r3.mux(); m5 = srv3.mux()
result = {}
def acc():
    try:
        m5.accept_channel(timeout=10)
        result['r'] = 'no exc'
    except EOFError:
        result['r'] = 'EOFError'
    except Exception as e:
        result['r'] = type(e).__name__
th = threading.Thread(target=acc); th.start()
time.sleep(0.2)
m4.close()
th.join(2)
print("close unblocks accept:", result.get('r'))

m1.close(); m2.close()
r.close(); l.close()
print("IDS OK")
PYEOF
timeout 30 python /tmp/test_mux_ids.py