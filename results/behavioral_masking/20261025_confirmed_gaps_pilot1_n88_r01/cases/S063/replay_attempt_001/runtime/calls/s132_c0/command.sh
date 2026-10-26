cd /app && timeout 15 python - <<'EOF'
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(); m2=s.mux()
c1=m1.open_channel(1, timeout=1); c2=m2.accept_channel(timeout=1)
c1.sendline(b'abc')
print("c2 recvline:", c2.recvline(timeout=1))
print("stats", c1.stats, c2.stats)
m1.close(); m2.close()
EOF