cd /app && python - <<'PY'
import re
path = 'pwnlib/tubes/buffer.py'
src = open(path).read()
# Insert watermarks init in __init__
src = src.replace(
    "    def __init__(self, buffer_fill_size = None):\n        self.data = [] # Buffer\n        self.size = 0  # Length\n        self.buffer_fill_size = buffer_fill_size",
    "    def __init__(self, buffer_fill_size = None):\n        self.data = [] # Buffer\n        self.size = 0  # Length\n        self.buffer_fill_size = buffer_fill_size\n        self.high_water = None\n        self.low_water = None"
)
# Insert methods after get_fill_size
insert = '''
    def set_watermarks(self, high=None, low=None):
        """
        Sets the high and low water marks used for flow control.

        Arguments:
            high(int): High water mark, at which ``over_high_water`` becomes
                True.  ``None`` disables it.
            low(int): Low water mark, at which ``under_low_water`` becomes
                True.  ``None`` disables it.

        Raises:
            ValueError: If ``low > high``.
        """
        if low is not None and high is not None and low > high:
            raise ValueError("low_water mark cannot exceed high_water mark")

        if high is not None:
            self.high_water = high
        if low is not None:
            self.low_water = low

    @property
    def over_high_water(self):
        """
        True when the buffer size is at or above the high water mark.
        False when the high water mark is unset.
        """
        if self.high_water is None:
            return False
        return self.size >= self.high_water

    @property
    def under_low_water(self):
        """
        True when the buffer size is at or below the low water mark.
        False when the low water mark is unset.
        """
        if self.low_water is None:
            return False
        return self.size <= self.low_water

'''
# Insert before the final get_fill_size method's end (at the very end of file)
# Actually just append at end of class body - simplest: insert before last method's closing? We'll append after get_fill_size.
# The file ends with get_fill_size method. Let's append methods at end of class (dedent to 4 spaces).
# We'll insert before the end-of-file but within class by replacing the final method's return with return + new methods.
old = "        with context.local(buffer_size=size):\n            return context.buffer_size\n"
new = old + insert
assert old in src
src = src.replace(old, new, 1)
open(path, 'w').write(src)
print("done")
PY
nl -ba pwnlib/tubes/buffer.py | tail -60