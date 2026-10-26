cd /app && timeout 15 python - <<'EOF'
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(max_channels=65535); m2=s.mux(max_channels=65535)
c1=m1.open_channel(65535, timeout=1)
c2=m2.accept_channel(timeout=1)
print("ids", c1.channel_id, c2.channel_id)
c1.send(b'x'); print(c2.recv(timeout=1))
m1.close(); m2.close()
EOF