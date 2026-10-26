cd /app && timeout 15 python - <<'EOF'
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(); m2=s.mux()
c1=m1.open_channel(1, timeout=1); c2=m2.accept_channel(timeout=1)
c1.shutdown('recv')
try:
    c1.recv(timeout=0.2)
    print("ERROR recv after shutdown recv")
except EOFError:
    print("c1 recv EOF ok")
print("c1 connected recv/send", c1.connected('recv'), c1.connected('send'))
c1.send(b'x')
print("c2 got", c2.recv(timeout=1))
m1.close(); m2.close()
EOF