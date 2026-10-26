cd /app && timeout 15 python - <<'EOF'
import threading, time
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(); m2=s.mux()
res={}
def accepter():
    c=m2.accept_channel(timeout=3)
    res['id']=c.channel_id if c else None
t=threading.Thread(target=accepter); t.start()
time.sleep(0.2)
c1=m1.open_channel(7, timeout=1)
t.join(2)
print("accepted id", res)
m1.close(); m2.close()
EOF