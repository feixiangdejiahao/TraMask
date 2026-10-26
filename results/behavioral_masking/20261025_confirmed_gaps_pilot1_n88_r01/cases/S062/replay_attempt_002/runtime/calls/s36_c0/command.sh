cd /app && timeout 15 python - <<'PY'
from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer
import time, sys, traceback
context.log_level='error'

l=listen(0); r=remote('localhost', l.lport); l.wait_for_connection()
m1=TubeMultiplexer(l); m2=TubeMultiplexer(r)
c=m1.open_channel(); p=m2.accept_channel(timeout=3)
print('opened, reader alive', m2._reader_thread.is_alive())
l.close()
time.sleep(0.5)
print('m2 closed?', m2._closed, 'reader alive', m2._reader_thread.is_alive())
print('--- m2 reader stack ---')
for th in threading.enumerate():
    if th is m2._reader_thread:
        traceback.print_stack(sys._current_frames()[th.ident])
print('--- m1 reader stack ---')
for th in threading.enumerate():
    if th is m1._reader_thread:
        traceback.print_stack(sys._current_frames()[th.ident])
m2.close(); m1.close()
PY
echo done