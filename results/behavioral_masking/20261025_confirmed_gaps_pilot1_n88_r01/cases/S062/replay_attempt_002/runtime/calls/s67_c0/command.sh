cd /app && cat > /tmp/test_edge.py <<'PY'
from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer
import time, threading
context.log_level = 'error'

def make_pair():
    l = listen(0); r = remote('localhost', l.lport); l.wait_for_connection()
    return l, r

# Remote accept blocked, local closes -> remote accept EOFError
print("== remote accept blocked on close ==")
l,r = make_pair(); m1=TubeMultiplexer(l); m2=TubeMultiplexer(r)
res=[]
def acc():
    try:
        res.append(m2.accept_channel())
    except EOFError:
        res.append('EOF')
    except Exception as e:
        res.append(type(e).__name__)
t=threading.Thread(target=acc); t.daemon=True; t.start()
time.sleep(0.2)
m1.close()
t.join(3)
print('result', res)
assert res == ['EOF'], res
m2.close()

# Sender blocked by flow control, remote closes -> sender EOFError
print("== sender blocked, remote closes ==")
l,r = make_pair()
m1=TubeMultiplexer(l, high_water_mark=1000, low_water_mark=100)
m2=TubeMultiplexer(r, high_water_mark=1000, low_water_mark=100)
c=m1.open_channel(); p=m2.accept_channel(timeout=3)
c.settimeout(1.0)
try:
    for i in range(100000):
        c.send(b'x'*100)
except TimeoutError:
    print('c paused')
except Exception as e:
    print('unexpected', e)
res=[]
def snd():
    try:
        c.send(b'blocked')
    except EOFError:
        res.append('EOF')
    except Exception as e:
        res.append(type(e).__name__)
t=threading.Thread(target=snd); t.daemon=True; t.start()
time.sleep(0.2)
m2.close()  # closes remote underlying, should wake sender with EOF
t.join(3)
print('sender result', res)
assert res == ['EOF'], res
m1.close()

# Open blocked waiting for ack, remote closes -> EOFError
print("== open blocked, remote closes ==")
l,r = make_pair()
m1=TubeMultiplexer(l); m2=TubeMultiplexer(r)
res=[]
def op():
    try:
        res.append(m1.open_channel(timeout=None))
    except EOFError:
        res.append('EOF')
    except Exception as e:
        res.append(type(e).__name__)
t=threading.Thread(target=op); t.daemon=True; t.start()
# ensure OPEN sent before close
time.sleep(0.3)
m2.close()
t.join(3)
print('open result', res)
assert res == ['EOF'], res
m1.close()

# recvall after half-close
print("== recvall after half-close ==")
l,r = make_pair(); m1=TubeMultiplexer(l); m2=TubeMultiplexer(r)
c=m1.open_channel(); p=m2.accept_channel(timeout=3)
c.send(b'hello')
c.send(b'world')
c.shutdown('send')
data = p.recvall(timeout=2)
print('recvall:', data)
assert data == b'helloworld'
m1.close(); m2.close()
print('EDGE TESTS DONE')
PY
timeout 40 python /tmp/test_edge.py