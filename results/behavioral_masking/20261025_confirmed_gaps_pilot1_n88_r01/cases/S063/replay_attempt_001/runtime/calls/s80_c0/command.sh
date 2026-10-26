cd /app && python - <<'PYEOF'
path = 'pwnlib/tubes/tube.py'
s = open(path).read()
old = '''        All keyword arguments are forwarded to the
        :class:`TubeMultiplexer` constructor.

        Examples:

            >>> t = tube()
            >>> m = t.mux()
            >>> isinstance(m, TubeMultiplexer)  # doctest: +SKIP
            True
        \"\"\"
'''
new = '''        All keyword arguments are forwarded to the
        :class:`TubeMultiplexer` constructor.
        \"\"\"
'''
assert old in s
s = s.replace(old, new, 1)
open(path,'w').write(s)
print("mux doctest simplified")
PYEOF
grep -n -A8 "def mux" pwnlib/tubes/tube.py