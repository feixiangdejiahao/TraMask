cd /app && timeout 15 python - <<'EOF'
from pwnlib.tubes.process import process
p = process(['/bin/cat'])
m = p.mux()
m.close()
print("process mux close ok")
EOF