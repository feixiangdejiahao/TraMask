cd /app && python - <<'EOF'
from pwnlib.context import context
print('timeout default:', context.timeout)
from pwnlib.tubes.tube import tube
t = tube()
print('tube timeout:', t.timeout)
EOF