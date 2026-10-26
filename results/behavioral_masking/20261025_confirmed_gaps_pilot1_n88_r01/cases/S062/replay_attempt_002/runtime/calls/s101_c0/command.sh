cd /app && timeout 20 python - <<'PY'
from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer
context.log_level='error'
l=listen(0); r=remote('localhost', l.lport); l.wait_for_connection()
m1=TubeMultiplexer(l); m2=TubeMultiplexer(r)
c=m1.open_channel(channel_id=7)
print('c id', c.channel_id, 'm1.channels', list(m1.channels))
p=m2.accept_channel(timeout=3)
print('p', p, 'p id', getattr(p,'channel_id',None), 'm2.channels', list(m2.channels))
print('m1[7] is c', m1.channels.get(7) is c)
print('m2[7] is p', m2.channels.get(7) is p)
m1.close(); m2.close()
PY