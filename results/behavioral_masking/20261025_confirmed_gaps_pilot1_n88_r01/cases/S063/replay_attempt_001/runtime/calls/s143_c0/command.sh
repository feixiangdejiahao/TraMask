cd /app && timeout 10 python - <<'EOF'
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m1=r.mux(high_water_mark=1234, low_water_mark=567)
c1=m1.open_channel(1, timeout=1)
print("channel buffer watermarks", c1.buffer.high_water, c1.buffer.low_water)
m1.close()
EOF