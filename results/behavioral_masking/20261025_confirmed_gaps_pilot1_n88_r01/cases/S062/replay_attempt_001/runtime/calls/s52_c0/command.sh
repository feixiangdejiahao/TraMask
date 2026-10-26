cd /app && python - <<'PY'
from pwnlib.tubes.tube import tube
from pwnlib.tubes.mux import TubeMultiplexer
import pwnlib.tubes.tube as tube_mod
t = tube()
print(type(t), isinstance(t, tube))
print(tube_mod.tube is tube)
try:
    m = TubeMultiplexer(t)
    print('ok', m)
except Exception as e:
    print('err', type(e), e)
PY