cd /app && python - <<'PY'
path = 'pwnlib/tubes/tube.py'
src = open(path).read()
old = '''    def connect_both(self, other):
        """connect_both(other)

        Connects the both ends of this tube object with another tube object."""

        self.connect_input(other)
        self.connect_output(other)

    def spawn_process(self, *args, **kwargs):
'''
new = '''    def connect_both(self, other):
        """connect_both(other)

        Connects the both ends of this tube object with another tube object."""

        self.connect_input(other)
        self.connect_output(other)

    def mux(self, **kwargs):
        """mux(**kwargs) -> TubeMultiplexer

        Wraps this tube in a :class:`pwnlib.tubes.mux.TubeMultiplexer`,
        allowing multiple independent logical channels to be multiplexed
        over this single tube.

        Arguments passed to this method are forwarded to the
        :class:`TubeMultiplexer` constructor.

        Examples:

            >>> from pwnlib.tubes.mux import TubeMultiplexer
            >>> t = tube()
            >>> isinstance(t.mux(), TubeMultiplexer)
            True
        """
        from pwnlib.tubes.mux import TubeMultiplexer
        return TubeMultiplexer(self, **kwargs)

    def spawn_process(self, *args, **kwargs):
'''
assert old in src
src = src.replace(old, new, 1)
open(path, 'w').write(src)
print('tube patched')
PY
python -m py_compile pwnlib/tubes/tube.py && echo OK