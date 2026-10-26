cd /app && timeout 20 python - <<'PY'
from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer, MuxChannel
import time
context.log_level='error'
# star import
exec("from pwnlib.tubes.mux import *")
print('star import ok:', 'TubeMultiplexer' in globals())
# empty frame
l=listen(0); r=remote('localhost', l.lport); l.wait_for_connection()
m1=TubeMultiplexer(l); m2=TubeMultiplexer(r)
c=m1.open_channel(); p=m2.accept_channel(timeout=3)
c.send(b'')
time.sleep(0.2)
print('sender stats after empty send:', c.stats)
print('receiver stats:', p.stats)
assert c.stats['frames_sent']==1
assert p.stats['frames_received']==1
# normal data after empty
c.send(b'abc')
print('recv after empty:', p.recvn(3, timeout=2))
m1.close(); m2.close()
print('empty frame OK')
PY