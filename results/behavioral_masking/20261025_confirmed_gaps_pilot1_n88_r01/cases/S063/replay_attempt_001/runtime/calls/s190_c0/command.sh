cd /app && timeout 15 python - <<'EOF'
import time, threading
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(); m2=s.mux()
c1=m1.open_channel(1, timeout=1); c2=m2.accept_channel(timeout=1)
res={}
def recver():
    try:
        c1.recv(timeout=5)
        res['r']='data'
    except EOFError:
        res['r']='EOFError'
t=threading.Thread(target=recver); t.start()
time.sleep(0.2)
c1.close()
t.join(2)
print("channel close unblocks recv:", res)
m1.close(); m2.close()
EOF