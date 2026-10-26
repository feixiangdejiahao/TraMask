cd /app && timeout 15 python - <<'EOF'
import time, threading
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux()
res={}
def opener():
    try:
        m1.open_channel(timeout=5)
        res['r']='opened'
    except EOFError:
        res['r']='EOFError'
    except Exception as e:
        res['r']=type(e).__name__
t=threading.Thread(target=opener); t.start()
time.sleep(0.2)
m1.close()
t.join(2)
print(res, t.is_alive())
EOF