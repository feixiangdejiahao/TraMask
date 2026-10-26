cd /app && timeout 30 python - <<'PY'
import doctest, pwnlib.tubes.tube as tube_mod
r = doctest.run_docstring_examples(tube_mod.tube.mux, tube_mod.__dict__, verbose=False, name='mux')
print('doctest done')
PY
echo "--- timing close detection ---"
cd /app && timeout 20 python - <<'PY'
from pwn import *
from pwnlib.tubes.mux import TubeMultiplexer
import time
context.log_level='error'
l=listen(0); r=remote('localhost', l.lport); l.wait_for_connection()
m1=TubeMultiplexer(l); m2=TubeMultiplexer(r)
c=m1.open_channel(); p=m2.accept_channel(timeout=3)
t0=time.time()
m1.close()
try:
    p.recv(timeout=5)
    print('no eof')
except EOFError:
    print('remote EOF after %.3fs' % (time.time()-t0))
m2.close()
PY