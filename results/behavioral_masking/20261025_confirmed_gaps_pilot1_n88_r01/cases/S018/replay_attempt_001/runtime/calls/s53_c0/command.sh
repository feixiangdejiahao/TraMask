cd /app && python - <<'EOF'
path = 'src/dateutil/rrule.py'
with open(path) as f:
    src = f.read()

# Add _repr_datetime helper after _datetime_to_ical_str
helper = r'''

def _repr_datetime(dt):
    """
    Return a Python expression that reconstructs *dt* using the ``datetime``
    class (as imported by ``from datetime import datetime``) and ``tz`` from
    :mod:`dateutil`.
    """
    if dt.tzinfo is None:
        return 'datetime({0}, {1}, {2}, {3}, {4}, {5})'.format(
            dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
    tzid = _tzid(dt)
    if tzid == 'UTC':
        tzexpr = 'tz.UTC'
    else:
        tzexpr = 'tz.gettz({0!r})'.format(tzid)
    return ('datetime({0}, {1}, {2}, {3}, {4}, {5}, tzinfo={6})'.format(
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, tzexpr))
'''

anchor = "def _dtstart_ical_str(dt):"
src = src.replace(anchor, helper + "\n\n" + anchor, 1)

# Update __repr__ to use _repr_datetime
old_repr = """        if self._until is not None:
            args.append('until=' + repr(self._until))
        if self._dtstart is not None:
            args.append('dtstart=' + repr(self._dtstart))"""
new_repr = """        if self._until is not None:
            args.append('until=' + _repr_datetime(self._until))
        if self._dtstart is not None:
            args.append('dtstart=' + _repr_datetime(self._dtstart))"""
assert old_repr in src
src = src.replace(old_repr, new_repr, 1)

with open(path, 'w') as f:
    f.write(src)
print("repr updated")
EOF
cd /app && python - <<'EOF'
from datetime import datetime
from dateutil import tz
from dateutil.rrule import rrule, YEARLY, MONTHLY, MO, TU
r1 = rrule(YEARLY, count=3, dtstart=datetime(1997, 9, 2, 9, 0), byweekday=(MO, TU))
print(repr(r1))
print(eval(repr(r1)) == r1)
r2 = rrule(YEARLY, count=3, dtstart=datetime(1997,9,2,9,0,tzinfo=tz.gettz('America/New_York')))
print(repr(r2))
print(eval(repr(r2)) == r2)
r3 = rrule(YEARLY, count=3, dtstart=datetime(1997,9,2,9,0,tzinfo=tz.UTC))
print(repr(r3))
print(eval(repr(r3)) == r3)
EOF