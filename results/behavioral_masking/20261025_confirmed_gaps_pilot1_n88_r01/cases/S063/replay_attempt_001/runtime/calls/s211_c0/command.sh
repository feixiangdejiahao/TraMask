cd /app && timeout 10 python - <<'EOF'
import time, threading
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(); m2=s.mux()
m1.open_channel(1, timeout=1)
time.sleep(0.1)
res={}
def acc():
    try:
        c=m2.accept_channel(timeout=1)
        res['r']='got %s' % (c.channel_id if c else None)
    except EOFError:
        res['r']='EOFError'
t=threading.Thread(target=acc); t.start()
time.sleep(0.1)
m2.close()
t.join(2)
print(res)
m1.close()
EOF