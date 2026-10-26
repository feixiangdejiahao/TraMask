cd /app && timeout 15 python - <<'EOF'
import time, threading
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(high_water_mark=10, low_water_mark=1); m2=s.mux(high_water_mark=10, low_water_mark=1)
c1=m1.open_channel(1, timeout=1); c2=m2.accept_channel(timeout=1)
c1.send(b'A'*100)
time.sleep(0.2)
res={}
def sender():
    try:
        c1.send(b'B')
        res['r']='sent'
    except EOFError:
        res['r']='EOFError'
t=threading.Thread(target=sender); t.start()
time.sleep(0.2)
c1.shutdown('send')
t.join(2)
print("shutdown send unblocks sender:", res)
m1.close(); m2.close()
EOF