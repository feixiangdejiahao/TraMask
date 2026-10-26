cd /app && timeout 10 python - <<'EOF'
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
l=listen(0); r=remote('localhost',l.lport); s=l.wait_for_connection()
m=r.mux(max_channels=3, high_water_mark=99, low_water_mark=11)
print(m.max_channels, m.high_water_mark, m.low_water_mark)
m.close(); s.close()
EOF