cd /app && timeout 30 python - <<'EOF'
import threading
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(); m2=s.mux()
c1=m1.open_channel(1, timeout=1); c2=m2.accept_channel(timeout=1)
N=20; SIZE=100
def sender(idx):
    for i in range(N):
        c1.send(("%d:%d:"%(idx,i)).encode().ljust(SIZE,b'x'))
ts=[threading.Thread(target=sender, args=(i,)) for i in range(4)]
for t in ts: t.start()
for t in ts: t.join()
received=[]
while len(received) < N*4:
    received.append(c2.recvn(SIZE, timeout=2))
print("received", len(received))
# verify all frames unique by prefix
prefixes = set(r[:5] for r in received)
print("unique", len(prefixes))
assert len(prefixes)==N*4
print("same-channel concurrent send ok")
m1.close(); m2.close()
EOF