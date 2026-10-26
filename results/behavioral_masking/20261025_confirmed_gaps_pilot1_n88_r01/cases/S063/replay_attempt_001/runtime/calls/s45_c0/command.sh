cd /app && python - <<'EOF'
import socket, time, threading
ls = socket.socket(); ls.bind(('127.0.0.1',0)); ls.listen(1)
port = ls.getsockname()[1]
c = socket.create_connection(('127.0.0.1', port))
s, _ = ls.accept()
result = {}
def recv_thread():
    try:
        d = c.recv(100)
        result['r'] = ('data', d)
    except Exception as e:
        result['r'] = ('exc', type(e).__name__, str(e))
th = threading.Thread(target=recv_thread); th.start()
time.sleep(0.2)
c.shutdown(socket.SHUT_RD)
th.join(1)
print("after SHUT_RD on blocked recv:", result)
# reset
result.clear()
def recv_thread2():
    try:
        d = c.recv(100)
        result['r'] = ('data', d)
    except Exception as e:
        result['r'] = ('exc', type(e).__name__, str(e))
th2 = threading.Thread(target=recv_thread2); th2.start()
time.sleep(0.2)
c.shutdown(socket.SHUT_WR)
th2.join(1)
print("after SHUT_WR on blocked recv:", result)
EOF