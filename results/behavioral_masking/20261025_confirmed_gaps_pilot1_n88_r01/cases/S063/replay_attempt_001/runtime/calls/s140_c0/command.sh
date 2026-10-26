cd /app && python - <<'PYEOF'
path = 'pwnlib/tubes/mux.py'
s = open(path).read()
marker = '_MAX_CHANNEL_ID = 65535\n'
insert = '_MAX_CHANNEL_ID = 65535\n\n__all__ = ["TubeMultiplexer", "MuxChannel"]\n'
assert marker in s
s = s.replace(marker, insert, 1)
open(path,'w').write(s)
print("added __all__")
PYEOF
head -45 pwnlib/tubes/mux.py