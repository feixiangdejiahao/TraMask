cd /app && python - <<'PY'
src = open('/tmp/test_final_smoke.py').read()
old = """c.close()
try: c.send(b'x'); assert False
except EOFError: pass
try: p.recv(timeout=2); assert False
except EOFError: pass
try: p.send(b'x'); assert False
except EOFError: pass
assert not c.connected() and not p.connected()
"""
new = """c.close()
try: c.send(b'x'); assert False
except EOFError: pass
try: p.recv(timeout=2); assert False
except EOFError: pass
# wait for the full-close CLOSE to propagate before checking peer send
for _ in range(200):
    if not p.connected():
        break
    time.sleep(0.01)
try: p.send(b'x'); assert False
except EOFError: pass
assert not c.connected() and not p.connected()
"""
assert old in src
src = src.replace(old, new)
open('/tmp/test_final_smoke.py','w').write(src)
print('fixed')
PY
timeout 60 python /tmp/test_final_smoke.py