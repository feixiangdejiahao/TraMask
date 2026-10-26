cd /app && timeout 12 python - <<'PY'
from pwn import *
import time, threading, socket
context.log_level='error'

l=listen(0); r=remote('localhost', l.lport); l.wait_for_connection()
result=[]
def rd():
    try:
        result.append(r.recvn(7, timeout=r.maximum))
    except EOFError:
        result.append('EOF')
    except Exception as e:
        result.append(type(e).__name__)
t=threading.Thread(target=rd); t.daemon=True; t.start()
time.sleep(0.3)
print('thread alive before close', t.is_alive())
l.close()
time.sleep(0.5)
print('thread alive after close', t.is_alive(), 'result', result)
r.close()
PY
echo "exit $?"