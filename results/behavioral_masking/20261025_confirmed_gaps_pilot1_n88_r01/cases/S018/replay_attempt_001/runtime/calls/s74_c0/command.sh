cd /app && python - <<'EOF'
from datetime import datetime
from dateutil import tz
from dateutil.rrule import *

NYC = tz.gettz('America/New_York')
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
RRULE:FREQ=YEARLY;COUNT=3
END:VEVENT
END:VCALENDAR
"""
r3 = rrulestr(s)
r1 = rrule(YEARLY, count=3, dtstart=datetime(1997,9,2,9,0,tzinfo=NYC))
print('r1 == r3:', r1 == r3)
if r1 != r3:
    for attr in ['_freq','_interval','_dtstart','_until','_count','_wkst','_bysetpos','_bymonth','_byyearday','_byeaster','_bymonthday','_bynmonthday','_byweekno','_byweekday','_bynweekday','_byhour','_byminute','_bysecond']:
        a = getattr(r1, attr); b = getattr(r3, attr)
        if a != b:
            print('diff', attr, repr(a), repr(b))
EOF