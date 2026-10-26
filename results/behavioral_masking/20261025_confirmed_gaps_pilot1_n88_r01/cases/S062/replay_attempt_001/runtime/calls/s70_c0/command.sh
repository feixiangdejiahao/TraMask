cd /app && grep -n "__all__\|from pwnlib.tubes" pwn/toplevel.py | head -30; echo ---; python - <<'PY'
import pwn
print('has TubeMultiplexer:', hasattr(pwn, 'TubeMultiplexer'))
print('has MuxChannel:', hasattr(pwn, 'MuxChannel'))
# check __all__
if hasattr(pwn, '__all__'):
    print('in __all__:', 'TubeMultiplexer' in pwn.__all__, 'MuxChannel' in pwn.__all__)
else:
    print('no pwn.__all__')
PY