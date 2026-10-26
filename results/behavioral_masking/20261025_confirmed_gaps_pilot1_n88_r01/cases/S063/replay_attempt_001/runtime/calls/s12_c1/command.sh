cd /app && python -c "from pwnlib import tubes; print(tubes.__file__)" && python - <<'EOF'
import pwnlib.tubes.tube as t
print(t.EOFError if hasattr(t,'EOFError') else 'no EOFError attr in tube')
from pwnlib.tubes import tube
print([x for x in dir(tube) if 'EOF' in x])
import pwnlib
print(pwnlib.__file__)
EOF