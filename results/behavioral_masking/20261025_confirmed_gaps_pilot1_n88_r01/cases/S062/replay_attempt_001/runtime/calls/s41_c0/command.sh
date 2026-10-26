cd /app && timeout 12 python - <<'PY'
from pwn import *
import time, threading
context.log_level='error'

l=listen(0); r=remote('localhost', l.lport); l.wait_for_connection()
res_l=[]; res_r=[]
def rd(name, obj, res):
    try:
        res.append(obj.recvn(7, timeout=obj.maximum))
    except EOFError:
        res.append('EOF')
    except Exception as e:
        res.append(type(e).__name__)
tl=threading.Thread(target=rd, args=('l', l, res_l)); tl.daemon=True; tl.start()
tr=threading.Thread(target=rd, args=('r', r, res_r)); tr.daemon=True; tr.start()
time.sleep(0.3)
print('before close', tl.is_alive(), tr.is_alive())
l.close()
time.sleep(0.5)
print('after close', tl.is_alive(), tr.is_alive(), res_l, res_r)
r.close()
PY
echo "exit $?"