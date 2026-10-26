cd /app && timeout 20 python - <<'EOF'
import threading
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(); m2=s.mux()
results=[]; lock=threading.Lock()
def open_some(base):
    for i in range(5):
        c=m1.open_channel(base+i, timeout=1)
        with lock: results.append(c.channel_id)
ts=[threading.Thread(target=open_some, args=(base,)) for base in (1,10,20)]
for t in ts: t.start()
for t in ts: t.join()
accepted=[m2.accept_channel(timeout=1).channel_id for _ in range(15)]
print("opened", sorted(results))
print("accepted", sorted(accepted))
assert sorted(results)==sorted(accepted)
print("concurrent open/accept ok")
m1.close(); m2.close()
EOF