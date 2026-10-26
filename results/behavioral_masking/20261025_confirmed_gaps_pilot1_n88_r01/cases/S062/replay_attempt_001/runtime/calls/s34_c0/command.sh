cd /app && timeout 10 python - <<'PY'
from pwn import *
import time
context.log_level='error'
l=listen(0); r=remote('localhost', l.lport); l.wait_for_connection()
l.close(); time.sleep(0.2)
print('before recv')
try:
    print('recv max:', r.recv(timeout=r.maximum))
except EOFError as e:
    print('EOFError')
except Exception as e:
    print('other', type(e).__name__, e)
r.close()
PY
echo "exit: $?"