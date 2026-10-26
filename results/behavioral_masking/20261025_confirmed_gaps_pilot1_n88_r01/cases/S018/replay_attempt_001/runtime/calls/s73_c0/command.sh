cd /app && python - <<'EOF'
from datetime import datetime
from dateutil import tz
from dateutil.rrule import *
from dateutil.tz import tzical
from io import StringIO

# eq with tz-aware
NYC = tz.gettz('America/New_York')
r1 = rrule(YEARLY, count=3, dtstart=datetime(1997,9,2,9,0,tzinfo=NYC))
r2 = rrule(YEARLY, count=3, dtstart=datetime(1997,9,2,9,0,tzinfo=NYC))
assert r1 == r2 and hash(r1) == hash(r2)

# eq with different but same-instant tzinfo
s = """BEGIN:VCALENDAR
BEGIN:VTIMEZONE
TZID:America/New_York
BEGIN:STANDARD
DTSTART:19700101T000000
TZOFFSETFROM:-0400
TZOFFSETTO:-0400
TZNAME:EDT
END:STANDARD
END:VTIMEZONE
BEGIN:VEVENT
DTSTART;TZID=America/New_York:19970902T090000
RRULE:FREQ=YEARLY;COUNT=2
END:VEVENT
END:VCALENDAR
"""
r3 = rrulestr(s)
print('r3 tz:', repr(r3.dtstart.tzinfo))
print('r1 == r3:', r1 == r3)

# multi VEVENT - first only
s2 = """BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART:19970101T000000
RRULE:FREQ=YEARLY;COUNT=2
END:VEVENT
BEGIN:VEVENT
DTSTART:19980101T000000
RRULE:FREQ=YEARLY;COUNT=2
END:VEVENT
END:VCALENDAR
"""
rr = rrulestr(s2)
print('multi-vevent:', list(rr))
assert list(rr) == [datetime(1997,1,1), datetime(1998,1,1)]

# VCALENDAR forceset
rs = rrulestr(s2, forceset=True)
assert isinstance(rs, rruleset)

print("OK")
EOF