cd /app && timeout 20 python - <<'EOF'
import time, threading
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(high_water_mark=100, low_water_mark=10)
m2=s.mux(high_water_mark=100, low_water_mark=10)
c1=m1.open_channel(1, timeout=1); c2=m2.accept_channel(timeout=1)
c1.send(b'A'*200)  # triggers pause on c2
time.sleep(0.2)
result={}
def sender():
    try:
        c1.send(b'B'*10)
        result['r']='sent'
    except EOFError:
        result['r']='EOFError'
    except Exception as e:
        result['r']=type(e).__name__
th=threading.Thread(target=sender); th.start()
time.sleep(0.2)
print("sender blocked?", th.is_alive())
c1.close()  # should unblock sender with EOFError
th.join(2)
print("after close result:", result, "alive", th.is_alive())
m1.close(); m2.close()
EOF