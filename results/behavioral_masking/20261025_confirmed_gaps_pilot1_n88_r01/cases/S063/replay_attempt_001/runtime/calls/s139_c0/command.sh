cd /app && timeout 30 python - <<'EOF'
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(max_channels=100); m2=s.mux(max_channels=100)
ch1=[]; ch2=[]
for i in range(30):
    c=m1.open_channel(timeout=1)
    ch1.append(c)
    ch2.append(m2.accept_channel(timeout=1))
print("ids", [c.channel_id for c in ch1])
print("channels dict len", len(m1.channels), len(m2.channels))
# send on a few
for i in range(30):
    ch1[i].send(bytes([i])*10)
for i in range(30):
    assert ch2[i].recv(timeout=1) == bytes([i])*10, i
print("30 channels ok")
m1.close(); m2.close()
EOF