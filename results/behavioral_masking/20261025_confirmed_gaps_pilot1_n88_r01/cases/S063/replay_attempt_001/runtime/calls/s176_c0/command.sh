cd /app && timeout 10 python - <<'EOF'
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m=r.mux()
try:
    m.open_channel(1, timeout=0.05)
except TimeoutError:
    pass
print("channels after timeout", m.channels)
# Now open again with a real peer
m2=s.mux()
c=m.open_channel(1, timeout=1)
print("reopened", c.channel_id)
m.close(); m2.close()
EOF