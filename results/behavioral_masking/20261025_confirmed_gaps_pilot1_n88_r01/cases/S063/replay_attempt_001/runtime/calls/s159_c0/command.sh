cd /app && timeout 10 python - <<'EOF'
from pwnlib.tubes.tube import tube
t = tube()
m = t.mux()
m.close()
print("close on base tube mux ok")
EOF