from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer, MuxChannel
from pwnlib.tubes.buffer import Buffer
import time, threading

context.log_level = 'error'

def make_pair():
    l = listen(0)
    r = remote('localhost', l.lport)
    l.wait_for_connection()
    return l, r

def close_pair(m1, m2):
    try: m1.close()
    except: pass
    try: m2.close()
    except: pass

# ---- Constructor validation ----
print("== constructor validation ==")
try: TubeMultiplexer(None)
except TypeError: print('TypeError None OK')
else: print('FAIL None')
try: TubeMultiplexer("abc")
except TypeError: print('TypeError str OK')
else: print('FAIL str')
l,r = make_pair()
try: TubeMultiplexer(l, max_channels=0)
except ValueError: print('ValueError max=0 OK')
else: print('FAIL max=0')
try: TubeMultiplexer(l, max_channels=65536)
except ValueError: print('ValueError max=65536 OK')
else: print('FAIL max=65536')
try: TubeMultiplexer(l, max_channels=1.5)
except ValueError: print('ValueError max=1.5 OK')
else: print('FAIL max=1.5')
try: TubeMultiplexer(l, low_water_mark=10, high_water_mark=5)
except ValueError: print('ValueError low>high OK')
else: print('FAIL low>high')
m = TubeMultiplexer(l)
print('props', m.max_channels, m.high_water_mark, m.low_water_mark)
r.close(); m.close()

# ---- Buffer ----
print("== Buffer ==")
b = Buffer()
b.set_watermarks(high=10, low=5)
b.add(b'A'*10)
assert b.over_high_water
assert not b.under_low_water
b.get(5)
assert not b.over_high_water
assert b.under_low_water
try: b.set_watermarks(high=1, low=2)
except ValueError: print('Buffer ValueError OK')
else: print('FAIL buffer low>high')
print('Buffer OK')

# ---- channel_id validation ----
print("== channel id validation ==")
l,r = make_pair()
m1,m2 = TubeMultiplexer(l), TubeMultiplexer(r)
for bad,exc in [(True,TypeError),(1.5,TypeError),('x',TypeError),(0,ValueError),(65536,ValueError)]:
    try:
        m1.open_channel(channel_id=bad)
        print('FAIL', bad)
    except exc:
        pass
    except Exception as e:
        print('FAIL wrong exc', bad, type(e).__name__)
print('id validation OK')
m1.close(); m2.close()

# ---- explicit id, duplicate ----
l,r = make_pair()
m1,m2 = TubeMultiplexer(l), TubeMultiplexer(r)
c = m1.open_channel(channel_id=7)
c2 = m2.accept_channel(timeout=3)
assert c.channel_id == 7 and c2.channel_id == 7
try: m1.open_channel(channel_id=7)
except ValueError: print('duplicate ValueError OK')
else: print('FAIL duplicate')
m1.close(); m2.close()

# ---- max_channels capacity ----
l,r = make_pair()
m1,m2 = TubeMultiplexer(l, max_channels=2), TubeMultiplexer(r, max_channels=2)
c1 = m1.open_channel(); a1 = m2.accept_channel(timeout=3)
c2 = m1.open_channel(); a2 = m2.accept_channel(timeout=3)
try: m1.open_channel()
except ValueError: print('capacity ValueError OK')
else: print('FAIL capacity')
m1.close(); m2.close()

# ---- half-close ----
print("== half close ==")
l,r = make_pair()
m1,m2 = TubeMultiplexer(l), TubeMultiplexer(r)
c = m1.open_channel(); p = m2.accept_channel(timeout=3)
c.send(b'before')
assert p.recv() == b'before'
c.shutdown('send')
try: c.send(b'x')
except EOFError: print('local send after shutdown -> EOF OK')
else: print('FAIL local send')
try: p.recv()
except EOFError: print('remote recv after peer shutdown -> EOF OK')
else: print('FAIL remote recv')
# remote can still send; local can still receive
p.send(b'after')
assert c.recv() == b'after'
print('connected states', c.connected('send'), c.connected('recv'), p.connected('send'), p.connected('recv'))
m1.close(); m2.close()

# ---- close one channel doesn't affect others ----
print("== independent channels ==")
l,r = make_pair()
m1,m2 = TubeMultiplexer(l), TubeMultiplexer(r)
c1 = m1.open_channel(); p1 = m2.accept_channel(timeout=3)
c2 = m1.open_channel(); p2 = m2.accept_channel(timeout=3)
c1.close()
try: c2.send(b'still alive')
except Exception as e: print('FAIL c2 send', e)
else: print('c2 send OK')
print('p2 recv:', p2.recv())
m1.close(); m2.close()

# ---- accept_channel timeout ----
print("== accept timeout ==")
l,r = make_pair()
m1,m2 = TubeMultiplexer(l), TubeMultiplexer(r)
t0=time.time()
res = m2.accept_channel(timeout=0.3)
assert res is None and 0.25 < time.time()-t0 < 2
print('accept timeout OK')
m1.close(); m2.close()

# ---- close unblocks accept ----
print("== close unblocks accept ==")
l,r = make_pair()
m1,m2 = TubeMultiplexer(l), TubeMultiplexer(r)
result = []
def acc():
    try:
        result.append(m2.accept_channel())
    except EOFError:
        result.append('EOF')
    except Exception as e:
        result.append(type(e).__name__)
t = threading.Thread(target=acc); t.daemon=True; t.start()
time.sleep(0.2)
m2.close()
t.join(2)
assert result == ['EOF'], result
print('close unblocks accept OK')
m1.close()

# ---- underlying death propagates ----
print("== underlying death ==")
l,r = make_pair()
m1,m2 = TubeMultiplexer(l), TubeMultiplexer(r)
c = m1.open_channel(); p = m2.accept_channel(timeout=3)
m1.close()  # closes underlying l
try:
    p.recv(timeout=3)
    print('FAIL recv after underlying death')
except EOFError:
    print('underlying death EOF OK')
m2.close()

print("\nALL FULL TESTS DONE")
