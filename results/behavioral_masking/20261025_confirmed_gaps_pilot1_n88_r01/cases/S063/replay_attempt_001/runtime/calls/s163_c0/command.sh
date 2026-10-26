cd /app && timeout 20 python - <<'EOF'
import threading
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(max_channels=50); m2=s.mux(max_channels=50)
results=[]; lock=threading.Lock()
def auto():
    for _ in range(10):
        c=m1.open_channel(timeout=1)
        with lock: results.append(c.channel_id)
ts=[threading.Thread(target=auto) for _ in range(5)]
for t in ts: t.start()
for t in ts: t.join()
print("ids", sorted(results))
assert len(set(results))==50
print("auto unique under concurrency ok")
m1.close(); m2.close()
EOF