cd /app && timeout 30 python - <<'EOF'
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(high_water_mark=1<<20, low_water_mark=1<<18); m2=s.mux(high_water_mark=1<<20, low_water_mark=1<<18)
c1=m1.open_channel(1, timeout=1); c2=m2.accept_channel(timeout=1)
payload = b'x' * (5 * 1024 * 1024)
c1.send(payload)
data = c2.recvn(len(payload), timeout=10)
print("len", len(data), "match", data == payload)
m1.close(); m2.close()
EOF