cd /app && python - <<'EOF'
from datetime import datetime
from dateutil import tz
from dateutil.rrule import *

# TZID not in inline, but in tzids mapping -> should use mapping
s = """BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART;TZID=Custom:19970902T090000
RRULE:FREQ=YEARLY;COUNT=2
END:VEVENT
END:VCALENDAR
"""
my_tz = tz.tzstr('EST5EDT')
rr = rrulestr(s, tzids={'Custom': my_tz})
print('tz:', repr(rr.dtstart.tzinfo))
assert rr.dtstart.tzinfo == my_tz

# Inline wins over mapping
s2 = """BEGIN:VCALENDAR
BEGIN:VTIMEZONE
TZID:Custom
BEGIN:STANDARD
DTSTART:19700101T000000
TZOFFSETFROM:-0400
TZOFFSETTO:-0400
TZNAME:Custom
END:STANDARD
END:VTIMEZONE
BEGIN:VEVENT
DTSTART;TZID=Custom:19970902T090000
RRULE:FREQ=YEARLY;COUNT=2
END:VEVENT
END:VCALENDAR
"""
fake = tz.tzstr('EST5EDT')
rr2 = rrulestr(s2, tzids={'Custom': fake})
print('inline tz:', repr(rr2.dtstart.tzinfo))
assert rr2.dtstart.tzinfo.tzname(rr2.dtstart) == 'Custom'
print("OK")
EOF