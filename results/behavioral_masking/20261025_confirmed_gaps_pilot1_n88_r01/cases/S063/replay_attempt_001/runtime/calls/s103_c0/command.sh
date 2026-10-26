cd /app && timeout 20 python - <<'EOF'
import time, threading
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux()
res={}
def opener():
    try:
        m1.open_channel(timeout=None)
        res['r']='opened'
    except EOFError:
        res['r']='EOFError'
    except Exception as e:
        res['r']=type(e).__name__
t=threading.Thread(target=opener); t.start()
time.sleep(0.2)
print("before close alive", t.is_alive())
m1.close()
t.join(2)
print("after close", res, "alive", t.is_alive())
EOF