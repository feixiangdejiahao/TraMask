cd /app && python - <<'EOF'
from datetime import datetime
from dateutil import tz
from dateutil.rrule import *

NYC = tz.gettz('America/New_York')
r = rrule(YEARLY, count=3, dtstart=datetime(1997,9,2,9,0,tzinfo=NYC))
ical = r.to_ical()
print("--- to_ical ---")
print(ical)
print("--- parse back ---")
r2 = rrulestr(ical)
print(list(r))
print(list(r2))
assert list(r) == list(r2)

# rruleset to_ical round trip
rs = rruleset()
rs.rrule(rrule(YEARLY, count=2, dtstart=datetime(1997,9,2,9,0,tzinfo=NYC)))
rs.rdate(datetime(1998,1,1,9,0,tzinfo=NYC))
ical2 = rs.to_ical()
print("--- rruleset to_ical ---")
print(ical2)
rs2 = rrulestr(ical2)
assert list(rs) == list(rs2), (list(rs), list(rs2))

# UTC to_ical has no VTIMEZONE
r3 = rrule(YEARLY, count=3, dtstart=datetime(1997,9,2,9,0,tzinfo=tz.UTC))
assert 'BEGIN:VTIMEZONE' not in r3.to_ical()
print("OK")
EOF