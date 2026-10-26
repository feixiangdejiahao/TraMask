cd /app && cat > /tmp/test_max1.py <<'PYEOF'
import socket
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(max_channels=1); m2=s.mux(max_channels=1)
c=m1.open_channel(1, timeout=1)
print("opened", c.channel_id)
for fn in [lambda: m1.open_channel(1, timeout=1), lambda: m1.open_channel(2, timeout=1), lambda: m1.open_channel(timeout=1)]:
    try:
        fn(); print("ERROR")
    except ValueError:
        print("ValueError ok")
m1.close(); m2.close()
PYEOF
timeout 10 python /tmp/test_max1.py