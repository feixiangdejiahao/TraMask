cd /app && python - <<'EOF'
from datetime import datetime
from dateutil import tz
from dateutil.rrule import *

NYC = tz.gettz('America/New_York')
BXL = tz.gettz('Europe/Brussels')
rs = rruleset()
rs.rrule(rrule(YEARLY, count=2, dtstart=datetime(1997,1,2,9,0,tzinfo=NYC)))
rs.rdate(datetime(1998,1,1,9,0,tzinfo=BXL))
ical = rs.to_ical()
print(ical)
print('VTIMEZONE count:', ical.count('BEGIN:VTIMEZONE'))
assert ical.count('BEGIN:VTIMEZONE') == 2
print("OK")
EOF