cd /app && python - <<'EOF'
from datetime import datetime
from dateutil import tz
from dateutil.rrule import *
from dateutil.tz import tzical

NYC = tz.gettz('America/New_York')
r = rrule(YEARLY, count=3, dtstart=datetime(1997,9,2,9,0,tzinfo=NYC))
ical = r.to_ical()
print(repr(ical[:200]))
try:
    t = tzical(ical)
    print('keys:', t.keys())
    for k in t.keys():
        print(k, repr(t.get(k)))
except Exception as e:
    print('tzical failed:', type(e).__name__, e)

# Direct rrulestr parse and inspect tzinfo
r2 = rrulestr(ical)
print('parsed dtstart tzinfo:', repr(r2.dtstart.tzinfo))
print('parsed rdate:', r2.rdates if hasattr(r2,'rdates') else None)
EOF