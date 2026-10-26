cd /app && python - <<'PY'
path = 'pwnlib/tubes/__init__.py'
src = open(path).read()
src = src.replace("from pwnlib.tubes import ssh\nfrom pwnlib.tubes import tube\n",
                  "from pwnlib.tubes import ssh\nfrom pwnlib.tubes import mux\nfrom pwnlib.tubes import tube\n")
src = src.replace("__all__ = ['tube', 'sock', 'remote', 'listen', 'process', 'serialtube', 'server', 'ssh']",
                  "__all__ = ['tube', 'sock', 'remote', 'listen', 'process', 'serialtube', 'server', 'ssh', 'mux']")
open(path, 'w').write(src)

path = 'pwn/toplevel.py'
src = open(path).read()
src = src.replace("from pwnlib.tubes.ssh import ssh\n", "from pwnlib.tubes.ssh import ssh\nfrom pwnlib.tubes.mux import TubeMultiplexer, MuxChannel\n")
open(path, 'w').write(src)
print('patched')
PY
python -c "import pwnlib.tubes.mux; print('import ok')"
python -c "import pwn; print('pwn ok', hasattr(pwn, 'TubeMultiplexer'))"