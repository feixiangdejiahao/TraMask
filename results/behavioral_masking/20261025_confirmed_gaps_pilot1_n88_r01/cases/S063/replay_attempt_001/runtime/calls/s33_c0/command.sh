cd /app && python - <<'EOF'
from pwnlib.tubes.tube import tube
from pwnlib.timeout import Timeout
t = tube()
try:
    t.recvn(4, timeout=Timeout.forever)
except Exception as e:
    print("recvn forever err:", type(e).__name__, e)
try:
    t.recvn(4, timeout=Timeout.maximum)
except Exception as e:
    print("recvn maximum err:", type(e).__name__, e)
EOF