cd /app && python - <<'PYEOF'
path = 'pwnlib/tubes/mux.py'
s = open(path).read()

# Add _MuxBuffer class after constants
marker = '''# How often the reader thread wakes up to check for a closed underlying tube.
_POLL_INTERVAL = 0.01
'''
insert = '''# How often the reader thread wakes up to check for a closed underlying tube.
_POLL_INTERVAL = 0.01


class _MuxBuffer(Buffer):
    """Buffer that notifies the channel when data is consumed."""

    def __init__(self, channel, *args, **kwargs):
        super(_MuxBuffer, self).__init__(*args, **kwargs)
        self._channel = channel

    def get(self, want=float("inf")):
        data = super(_MuxBuffer, self).get(want)
        self._channel._mux._maybe_resume(self._channel)
        return data
'''
assert marker in s
s = s.replace(marker, insert, 1)

# Import Buffer
s = s.replace("from pwnlib.tubes.tube import tube\n",
              "from pwnlib.tubes.buffer import Buffer\nfrom pwnlib.tubes.tube import tube\n")

# Replace buffer creation in MuxChannel init
old = '''        self._stats_lock = threading.Lock()

        self.buffer.set_watermarks(high=mux.high_water_mark,
                                   low=mux.low_water_mark)
'''
new = '''        self._stats_lock = threading.Lock()

        self.buffer = _MuxBuffer(self)
        self.buffer.set_watermarks(high=mux.high_water_mark,
                                   low=mux.low_water_mark)
'''
assert old in s
s = s.replace(old, new, 1)

open(path,'w').write(s)
print("MuxBuffer integrated")
PYEOF
python -c "import ast; ast.parse(open('/app/pwnlib/tubes/mux.py').read()); print('ok')"