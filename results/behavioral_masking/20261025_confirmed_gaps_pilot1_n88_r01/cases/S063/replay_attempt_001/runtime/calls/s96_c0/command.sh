cd /app && timeout 20 python - <<'EOF'
import time, threading
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(); m2=s.mux()
c1=m1.open_channel(1, timeout=1); c2=m2.accept_channel(timeout=1)
res={}
def recver():
    try:
        c1.recv(timeout=10)
        res['r']='data'
    except EOFError:
        res['r']='EOFError'
    except Exception as e:
        res['r']=type(e).__name__
t=threading.Thread(target=recver); t.start()
time.sleep(0.2)
m1.close()
t.join(2)
print("blocked recv unblocked:", res)
m2.close()
EOF