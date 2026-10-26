cd /app && python - <<'EOF'
from datetime import datetime
from dateutil import tz
from dateutil.rrule import *

# tzstr
for spec in ['EST5EDT', 'UTC+04', 'AEST-10AEDT']:
    t = tz.tzstr(spec)
    r = rrule(YEARLY, count=3, dtstart=datetime(1997,9,2,9,0,tzinfo=t))
    s = str(r)
    print(spec, '->', s)
    try:
        rr = rrulestr(s)
        print('   list eq:', list(r) == list(rr), 'tz:', rr.dtstart.tzinfo)
    except Exception as e:
        print('   roundtrip fail:', type(e).__name__, e)

# tzutc
r = rrule(YEARLY, count=3, dtstart=datetime(1997,9,2,9,0,tzinfo=tz.UTC))
print('tzutc str:', str(r))
rr = rrulestr(str(r))
print('tzutc roundtrip:', list(r) == list(rr), rr.dtstart.tzinfo)

# datetime.timezone.utc
import datetime as dtm
r2 = rrule(YEARLY, count=3, dtstart=datetime(1997,9,2,9,0,tzinfo=dtm.timezone.utc))
print('timezone.utc str:', str(r2))
rr2 = rrulestr(str(r2))
print('timezone.utc roundtrip:', list(r2) == list(rr2), rr2.dtstart.tzinfo)
EOF