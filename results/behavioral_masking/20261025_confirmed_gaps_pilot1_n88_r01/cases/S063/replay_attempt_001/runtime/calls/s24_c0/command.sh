cd /app && python - <<'PYEOF'
path = 'pwnlib/tubes/tube.py'
s = open(path).read()
marker = """    # The minimal interface to be implemented by a child
    @abc.abstractmethod
    def recv_raw(self, numb):
"""
insert = """    def mux(self, **kwargs):
        \"\"\"mux(**kwargs) -> TubeMultiplexer

        Wrap this tube in a :class:`pwnlib.tubes.mux.TubeMultiplexer`,
        allowing multiple independent logical channels over a single
        underlying tube.

        All keyword arguments are forwarded to the
        :class:`TubeMultiplexer` constructor.

        Examples:

            >>> t = tube()
            >>> m = t.mux()
            >>> isinstance(m, TubeMultiplexer)  # doctest: +SKIP
            True
        \"\"\"
        from pwnlib.tubes.mux import TubeMultiplexer
        return TubeMultiplexer(self, **kwargs)

"""
assert marker in s
s = s.replace(marker, insert + marker, 1)
open(path, 'w').write(s)
print("patched tube")
PYEOF
grep -n "def mux" pwnlib/tubes/tube.py