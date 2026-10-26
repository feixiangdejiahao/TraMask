cd /app && timeout 15 python - <<'EOF'
import threading, time
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(); m2=s.mux()
for i in range(5):
    m1.open_channel(i+1, timeout=1)
time.sleep(0.1)
got=[]; lock=threading.Lock()
def acc():
    c=m2.accept_channel(timeout=2)
    with lock: got.append(c.channel_id if c else None)
ts=[threading.Thread(target=acc) for _ in range(5)]
for t in ts: t.start()
for t in ts: t.join()
print("got", sorted(got))
assert sorted(got)==[1,2,3,4,5]
print("concurrent accept ok")
m1.close(); m2.close()
EOF