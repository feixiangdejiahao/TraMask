cd /app && python - <<'PYEOF'
import re
path = 'pwnlib/tubes/buffer.py'
s = open(path).read()

# Add high/low water init
s = s.replace("""    def __init__(self, buffer_fill_size = None):
        self.data = [] # Buffer
        self.size = 0  # Length
        self.buffer_fill_size = buffer_fill_size
""", """    def __init__(self, buffer_fill_size = None):
        self.data = [] # Buffer
        self.size = 0  # Length
        self.buffer_fill_size = buffer_fill_size
        self.high_water = None
        self.low_water = None
""", 1)

# Add set_watermarks + properties after __contains__ (before index)
marker = """    def index(self, x):
"""
insert = """    def set_watermarks(self, high=None, low=None):
        \"\"\"
        Set the high and/or low water marks used for flow control.

        Arguments:
            high(int): High water mark.  The buffer is considered
                :attr:`over_high_water` when its size is greater than or
                equal to this value.
            low(int): Low water mark.  The buffer is considered
                :attr:`under_low_water` when its size is less than or
                equal to this value.

        Raises:
            ValueError: If both water marks are set and ``low > high``.
        \"\"\"
        if high is not None:
            self.high_water = high
        if low is not None:
            self.low_water = low
        if (self.high_water is not None and self.low_water is not None
                and self.low_water > self.high_water):
            raise ValueError("low_water_mark cannot exceed high_water_mark")

    @property
    def over_high_water(self):
        \"\"\"True if the buffer size is at or above the high water mark.\"\"\"
        if self.high_water is None:
            return False
        return self.size >= self.high_water

    @property
    def under_low_water(self):
        \"\"\"True if the buffer size is at or below the low water mark.\"\"\"
        if self.low_water is None:
            return False
        return self.size <= self.low_water

"""
assert marker in s
s = s.replace(marker, insert + marker, 1)

open(path, 'w').write(s)
print("patched")
PYEOF
nl -ba pwnlib/tubes/buffer.py | sed -n '30,100p'