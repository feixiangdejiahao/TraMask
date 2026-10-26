cd /app && timeout 20 python - <<'PY'
from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer
import time
context.log_level = 'error'

# ID reuse after close
l,r = listen(0), None
r = remote('localhost', l.lport); l.wait_for_connection()
m1=TubeMultiplexer(l); m2=TubeMultiplexer(r)
c=m1.open_channel(channel_id=5)
p=m2.accept_channel(timeout=3)
assert c.channel_id == 5
print('channels before close:', sorted(m1.channels), sorted(m2.channels))
c.close()
time.sleep(0.2)
print('channels after close:', sorted(m1.channels), sorted(m2.channels))
# remote should auto-close and confirm
# reopen same id
c2=m1.open_channel(channel_id=5)
p2=m2.accept_channel(timeout=3)
print('reopened id', c2.channel_id, p2.channel_id)
assert c2.channel_id == 5
m1.close(); m2.close()
print('ID reuse OK')

# auto-allocate after close reuses lowest
l,r = listen(0), None
r = remote('localhost', l.lport); l.wait_for_connection()
m1=TubeMultiplexer(l); m2=TubeMultiplexer(r)
c1=m1.open_channel(); p1=m2.accept_channel(timeout=3)
c2=m1.open_channel(); p2=m2.accept_channel(timeout=3)
print('ids', c1.channel_id, c2.channel_id)
c1.close(); time.sleep(0.2)
c3=m1.open_channel(); p3=m2.accept_channel(timeout=3)
print('reused id', c3.channel_id)
assert c3.channel_id == c1.channel_id
m1.close(); m2.close()
print('auto reuse OK')
PY