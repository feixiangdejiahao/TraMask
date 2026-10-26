cd /app && python - <<'EOF'
from pwnlib.tubes.tube import tube
t = tube()
m = t.mux()
print("mux ok", m)
EOF