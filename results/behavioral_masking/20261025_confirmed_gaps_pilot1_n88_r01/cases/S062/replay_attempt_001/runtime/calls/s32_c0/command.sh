cd /app && cat > /tmp/test_death2.py <<'PY'
from pwn import *
import time, socket
context.log_level = 'error'

l = listen(0)
r = remote('localhost', l.lport)
l.wait_for_connection()
print('l sock', l.sock)
l.close()
print('l closed, sock now', getattr(l,'sock',None))
time.sleep(0.2)
print('r connected', r.connected())
try:
    print('r recv:', r.recv(timeout=1))
except EOFError as e:
    print('EOFError OK')
except Exception as e:
    print('other', type(e).__name__, e)
r.close()
PY
python /tmp/test_death2.py