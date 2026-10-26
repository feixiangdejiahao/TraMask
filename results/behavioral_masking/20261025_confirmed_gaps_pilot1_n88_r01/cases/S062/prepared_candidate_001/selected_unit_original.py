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

