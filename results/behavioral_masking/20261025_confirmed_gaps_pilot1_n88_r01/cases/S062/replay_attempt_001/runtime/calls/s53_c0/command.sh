cd /app && timeout 30 python - <<'PY'
import doctest, pwnlib.tubes.tube as tube_mod
from pwnlib.tubes.mux import TubeMultiplexer
t = tube_mod.tube()
print('isinstance direct:', isinstance(t, tube_mod.tube))
import pwnlib.tubes.tube
print('module name', pwnlib.tubes.tube.__name__)
# run just the mux docstring
results = doctest.run_docstring_examples(tube_mod.tube.mux, tube_mod.__dict__, verbose=False, name='mux')
PY