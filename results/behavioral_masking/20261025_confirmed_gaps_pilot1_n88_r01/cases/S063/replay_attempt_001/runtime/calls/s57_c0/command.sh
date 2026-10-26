cd /app && python - <<'PYEOF'
# Update tubes/__init__.py
path = 'pwnlib/tubes/__init__.py'
s = open(path).read()
s = s.replace("""from pwnlib.tubes import mux
from pwnlib.tubes import process
""", """from pwnlib.tubes import mux
from pwnlib.tubes import process
""", 1)
# add class import after module imports
s = s.replace("""from pwnlib.tubes import ssh
from pwnlib.tubes import tube
""", """from pwnlib.tubes import ssh
from pwnlib.tubes import tube
from pwnlib.tubes.mux import MuxChannel, TubeMultiplexer
""", 1)
s = s.replace("""__all__ = [\u0027tube\u0027, \u0027sock\u0027, \u0027remote\u0027, \u0027listen\u0027, \u0027mux\u0027, \u0027process\u0027, \u0027serialtube\u0027, \u0027server\u0027, \u0027ssh\u0027]""",
"""__all__ = [\u0027tube\u0027, \u0027sock\u0027, \u0027remote\u0027, \u0027listen\u0027, \u0027mux\u0027, \u0027TubeMultiplexer\u0027, \u0027MuxChannel\u0027, \u0027process\u0027, \u0027serialtube\u0027, \u0027server\u0027, \u0027ssh\u0027]""")
open(path,'w').write(s)
print("init updated")
PYEOF
grep -n "mux\|TubeMultiplexer" pwnlib/tubes/__init__.py