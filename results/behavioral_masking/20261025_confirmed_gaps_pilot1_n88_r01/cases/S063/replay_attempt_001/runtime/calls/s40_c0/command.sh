cd /app && python - <<'EOF'
import socket, time
ls = socket.socket()
ls.bind(('127.0.0.1', 0)); ls.listen(1)
port = ls.getsockname()[1]
c = socket.create_connection(('127.0.0.1', port))
s, _ = ls.accept()
c.close()
time.sleep(0.3)
s.settimeout(2)
try:
    d = s.recv(100)
    print("raw recv returned", d)
except Exception as e:
    print("raw recv exc", type(e).__name__, e)
EOF